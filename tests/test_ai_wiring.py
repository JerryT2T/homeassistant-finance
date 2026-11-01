"""AI categorisation wiring: only leftovers, within the cap, opt-in, no amount/IBAN/date."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from custom_components.finance_dashboard import ai_provider as ai
from custom_components.finance_dashboard.categorizer import TransactionCategorizer
from custom_components.finance_dashboard.manager._questions import QuestionsMixin
from custom_components.finance_dashboard.merchants import MerchantMemory
from tests.fakes import FakeStore

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "finance_dashboard"


def _tx(creditor, amount=-10.0, remit="", lid="", chain=None, day=20):
    return {
        "bookingDate": f"2026-10-{day:02d}",
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "creditorName": creditor,
        "debtorName": "",
        "remittanceInformationUnstructured": remit,
        "_ledger_id": lid or f"{creditor}{amount}{day}",
        "_transfer_chain_id": chain,
        "_status": "booked",
    }


class _Mgr(QuestionsMixin):
    def __init__(self, txs, accounts=None):
        self._memory = MerchantMemory(store=FakeStore())
        self._categorizer = TransactionCategorizer(memory=self._memory)
        self._transactions = txs
        self._transfer_overrides = {}
        self._accounts = accounts or []
        self._demo_mode = False
        self._credential_manager = None
        self._hass = MagicMock()
        self._hass.data = {}
        self._hass.services.has_service.side_effect = lambda d, s: d == "ai_task"
        self.derived = 0
        self._derive_from_ledger()

    def _derive_from_ledger(self, _o=None):
        self.derived += 1
        for t in self._transactions:
            t["category"], t["_owner_override"] = self._categorizer.resolve(t)


class _Env:
    """In-memory AI config + wizard state; records every prompt sent."""

    def __init__(self, opt_in=True, cap=100, answer="groceries", **cfg):
        self.cfg = ai.merge_config({"budget_cap": cap, **cfg})
        self.opt_in = opt_in
        self.answer = answer
        self.prompts: list[str] = []

    async def load_cfg(self, _hass):
        return ai.merge_config(self.cfg)

    async def save_cfg(self, _hass, cfg):
        self.cfg = ai.merge_config(cfg)

    async def granted(self, _hass, purpose):
        assert purpose == "categorize"
        return self.opt_in

    async def call_ha(self, _hass, _agent, prompt):
        self.prompts.append(prompt)
        return self.answer


def _run(mgr, env):
    with (
        patch.object(ai, "async_load_config", env.load_cfg),
        patch.object(ai, "async_save_config", env.save_cfg),
        patch.object(ai, "_call_ha", env.call_ha),
        patch("custom_components.finance_dashboard.ai_consent.async_granted", env.granted),
    ):
        return asyncio.run(mgr._async_ai_categorize())


def test_rules_and_memory_win_ai_only_for_leftovers() -> None:
    mgr = _Mgr([
        _tx("REWE Markt", -40),                 # keyword rule -> food
        _tx("Zorblax Quux", -30, lid="m"),      # unknown -> AI
        _tx("Taught Place", -20, lid="t"),      # user memory
    ])
    mgr._memory.learn_merchant("taught place", "leisure")
    mgr._derive_from_ledger()
    env = _Env()
    assert _run(mgr, env) == 1
    assert len(env.prompts) == 1 and "Zorblax Quux" in env.prompts[0]
    assert "REWE" not in env.prompts[0] and "Taught" not in env.prompts[0]
    rule = mgr._memory.known_merchants()["zorblax quux"]
    assert rule == {"category": "groceries", "source": "ai"} or rule["source"] == "ai"
    cats = {t["creditorName"]: t["category"] for t in mgr._transactions}
    assert cats["Zorblax Quux"] != "other" and cats["Taught Place"] == "leisure"
    assert env.cfg["cache"]["zorblax quux"] == rule["category"]


def test_user_answer_overrides_ai_entry() -> None:
    mgr = _Mgr([_tx("Zorblax Quux", -30, lid="m")])
    _run(mgr, _Env())
    mgr._memory.learn_merchant("zorblax quux", "leisure")
    assert mgr._memory.known_merchants()["zorblax quux"] == {"category": "leisure"}
    # and the AI never replaces a user rule
    assert mgr._memory.learn_ai_merchant("zorblax quux", "groceries") is False


def test_cap_respected_highest_impact_first() -> None:
    txs = [_tx("Zorblax Small", -5), _tx("Zorblax Big", -500), _tx("Zorblax Mid", -50)]
    mgr = _Mgr(txs)
    env = _Env(cap=2)
    assert _run(mgr, env) == 2
    assert len(env.prompts) == 2
    assert "Zorblax Big" in env.prompts[0] and "Zorblax Mid" in env.prompts[1]
    assert env.cfg["usage"]["calls"] == 2
    # a second pass in the same session makes no further call
    assert _run(mgr, env) == 0
    assert len(env.prompts) == 2


def test_opt_out_makes_zero_calls() -> None:
    mgr = _Mgr([_tx("Zorblax Quux", -30)])
    env = _Env(opt_in=False)
    assert _run(mgr, env) == 0
    assert env.prompts == [] and env.cfg["usage"]["calls"] == 0


def test_unusable_provider_makes_zero_calls() -> None:
    mgr = _Mgr([_tx("Zorblax Quux", -30)])
    env = _Env(provider="xai")  # keyed provider without a key
    assert _run(mgr, env) == 0
    assert env.prompts == []


def test_skips_income_chains_own_names_cache_and_invalid_answers() -> None:
    accounts = [{"name": "Jeremy Treder"}]
    mgr = _Mgr(
        [
            _tx("Jeremy Tim Treder", -300),           # own name
            _tx("Chainquux Inc", -80, chain="c1"),       # transfer chain
            _tx("Cachedquux Inc", -70),                  # in AI cache: learned, no call
            _tx("Refundquux Inc", +60),                  # income side
            _tx("Oddquux Inc", -20),                     # answer is not a category
        ],
        accounts,
    )
    env = _Env(answer="blorp", cache={"cachedquux": "groceries"})
    assert _run(mgr, env) == 1  # the cached merchant, without a call
    assert len(env.prompts) == 1 and "Oddquux Inc" in env.prompts[0]
    assert mgr._memory.known_merchants()["cachedquux"]["category"] == "groceries"
    assert "oddquux" not in mgr._memory.known_merchants()
    # a failed answer is not retried within the session
    assert _run(mgr, env) == 0 and len(env.prompts) == 1


def test_cached_answers_are_learned_even_when_the_budget_is_used_up() -> None:
    mgr = _Mgr([_tx("Cachedquux Inc", -70), _tx("Newquux Inc", -50)])
    env = _Env(cap=0, cache={"cachedquux": "groceries"})
    assert _run(mgr, env) == 1
    assert env.prompts == []
    assert mgr._memory.known_merchants()["cachedquux"]["category"] == "groceries"
    assert "newquux" not in mgr._memory.known_merchants()


def test_payload_has_no_amount_iban_or_date() -> None:
    mgr = _Mgr([
        _tx(
            "Zorblax Quux",
            -1234.56,
            remit="Rechnung 2026-10-20 DE89370400440532013000 EUR 1234,56 vom 20.10.2026",
        )
    ])
    env = _Env()
    _run(mgr, env)
    prompt = env.prompts[0]
    for needle in ("1234", "DE89", "2026", "20.10", "0532013000"):
        assert needle not in prompt
    assert "Zorblax Quux" in prompt


def test_schedule_is_background_and_single_flight() -> None:
    mgr = _Mgr([_tx("Zorblax Quux", -30)])
    task = MagicMock()
    task.done.return_value = False
    mgr._hass.async_create_background_task.side_effect = lambda coro, name: (coro.close(), task)[1]
    mgr.schedule_ai_categorization()
    mgr.schedule_ai_categorization()  # still running -> no second task
    assert mgr._hass.async_create_background_task.call_count == 1


def test_schedule_never_raises() -> None:
    mgr = _Mgr([])
    mgr._hass.async_create_background_task.side_effect = RuntimeError("boom")
    mgr.schedule_ai_categorization()


@pytest.mark.parametrize(
    ("rel", "expect"),
    [("manager/_persistence.py", 1), ("manager/_refresh.py", 1)],
)
def test_ai_pass_is_triggered_only_from_derive_and_import_paths(rel, expect) -> None:
    src = (PKG / rel).read_text(encoding="utf-8")
    assert src.count("schedule_ai_categorization()") == expect
    callers = []
    for path in PKG.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in (
                "schedule_ai_categorization",
                "_async_ai_categorize",
            ):
                callers.append(path.relative_to(PKG).as_posix())
    assert not any(c.startswith("api/") or c in ("home.py", "coordinator.py") for c in callers)
