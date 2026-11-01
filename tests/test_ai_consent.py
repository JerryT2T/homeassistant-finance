"""Per-purpose AI consent, sheet ideas and the trimmed options form (fakes, no HA core)."""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.finance_dashboard import ai_consent as consent
from custom_components.finance_dashboard import ai_provider as ai
from custom_components.finance_dashboard import plan_ideas


class _FakeStore:
    def __init__(self, data=None):
        self.data = data
        self.saves = 0

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = data
        self.saves += 1


def _hass():
    hass = MagicMock()
    hass.data = {}
    hass.services.has_service.side_effect = lambda d, s: d == "ai_task"

    async def run_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = run_job
    return hass


def _with_store(store, legacy=False):
    async def legacy_state(_hass):
        return {"ai_opt_in": legacy}

    return (
        patch.object(consent, "_store", lambda _h: store),
        patch("custom_components.finance_dashboard.setup_wizard.async_load_state", legacy_state),
    )


def _run(coro, *patches):
    async def go():
        return await coro

    for p in patches:
        p.start()
    try:
        return asyncio.run(go())
    finally:
        for p in patches:
            p.stop()


# -- consent store -------------------------------------------------------------


def test_default_is_denied_and_shape() -> None:
    store = _FakeStore()
    state = _run(consent.async_load(_hass()), *_with_store(store))
    assert set(state) == {"categorize", "sheet_analysis"}
    assert state["categorize"] == {
        "granted": False, "mode": "recurring", "granted_at": None, "used_at": None,
    }
    assert state["sheet_analysis"]["mode"] == "once"


def test_migrates_legacy_wizard_opt_in_into_categorize_only() -> None:
    store = _FakeStore()
    state = _run(consent.async_load(_hass()), *_with_store(store, legacy=True))
    assert state["categorize"]["granted"] is True and state["categorize"]["granted_at"]
    assert state["sheet_analysis"]["granted"] is False
    assert store.data["categorize"]["granted"] is True  # persisted: migration runs once


def test_existing_store_wins_over_legacy_flag() -> None:
    store = _FakeStore({"categorize": {"granted": False}})
    state = _run(consent.async_load(_hass()), *_with_store(store, legacy=True))
    assert state["categorize"]["granted"] is False


def test_set_and_revoke() -> None:
    store = _FakeStore()
    hass = _hass()
    patches = _with_store(store)

    async def go():
        await consent.async_set(hass, "categorize", True)
        first = await consent.async_granted(hass, "categorize")
        await consent.async_set(hass, "categorize", False)
        return first, await consent.async_granted(hass, "categorize")

    assert _run(go(), *patches) == (True, False)


def test_once_purpose_is_consumed_recurring_is_not() -> None:
    store = _FakeStore()
    hass = _hass()

    async def go():
        await consent.async_set(hass, "sheet_analysis", True)
        await consent.async_set(hass, "categorize", True)
        await consent.async_mark_used(hass, "sheet_analysis")
        await consent.async_mark_used(hass, "categorize")
        return await consent.async_load(hass)

    state = _run(go(), *_with_store(store))
    assert state["sheet_analysis"]["granted"] is False and state["sheet_analysis"]["used_at"]
    assert state["categorize"]["granted"] is True and state["categorize"]["used_at"]


def test_unknown_purpose_raises() -> None:
    hass = _hass()
    for call in (
        lambda: consent.async_granted(hass, "x"),
        lambda: consent.async_set(hass, "x", True),
        lambda: consent.async_mark_used(hass, "x"),
    ):
        with pytest.raises(ValueError):
            asyncio.run(call())


# -- categorize gating ---------------------------------------------------------


def test_questions_pass_gates_on_categorize_consent() -> None:
    from custom_components.finance_dashboard.manager import _questions

    src = open(_questions.__file__, encoding="utf-8").read()
    assert 'async_granted(self._hass, "categorize")' in src
    assert "ai_opt_in" not in src


# -- sheet ideas -----------------------------------------------------------------


def _tx(name, amount, day, cat="subscriptions"):
    return {
        "_status": "booked",
        "creditorName": name,
        "bookingDate": day,
        "category": cat,
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
    }


def _manager():
    txs = [_tx("Netflix International", -12.99, f"2026-0{m}-05") for m in (6, 7, 8, 9)]
    txs += [_tx("REWE Markt", -80, "2026-09-02", "groceries"), _tx("REWE Markt", -60, "2026-10-02", "groceries")]
    return SimpleNamespace(_transactions=txs, _credential_manager=None)


class _AiEnv:
    def __init__(self, answer="1: fixed\n2: reserve"):
        self.cfg = ai.merge_config({"budget_cap": 50})
        self.answer = answer
        self.prompts: list[str] = []

    async def load(self, _h):
        return ai.merge_config(self.cfg)

    async def save(self, _h, cfg):
        self.cfg = ai.merge_config(cfg)

    async def call_ha(self, _h, _agent, prompt):
        self.prompts.append(prompt)
        return self.answer


NAMES = ["Netflix", "Lebensmittel", "Zorblax Gizmo", "Quuxbar Abo"]


def _ideas(env, granted, store):
    hass = _hass()

    async def go():
        if granted:
            await consent.async_set(hass, "sheet_analysis", True)
        return await plan_ideas.async_sheet_ideas(hass, _manager(), b"xlsx", date(2026, 10, 20))

    patches = [
        *_with_store(store),
        patch.object(plan_ideas, "sheet_position_names", lambda _wb: list(NAMES)),
        patch.object(ai, "async_load_config", env.load),
        patch.object(ai, "async_save_config", env.save),
        patch.object(ai, "_call_ha", env.call_ha),
    ]
    return _run(go(), *patches), hass


def test_sheet_ideas_without_consent_makes_no_ai_call() -> None:
    env = _AiEnv()
    result, _ = _ideas(env, granted=False, store=_FakeStore())
    assert env.prompts == [] and env.cfg["usage"]["calls"] == 0
    assert result["needs_consent"] is True and result["ai_used"] is False
    by = {i["name"]: i for i in result["ideas"]}
    assert by["Netflix"]["matched"] == "series" and by["Netflix"]["kind"] == "fixed"
    assert by["Netflix"]["amount"] == 12.99  # plan sign: expense positive, from data
    assert by["Lebensmittel"]["matched"] == "category" and by["Lebensmittel"]["kind"] == "pot"
    assert by["Lebensmittel"]["amount"] == 70.0
    assert by["Zorblax Gizmo"]["matched"] is None and by["Quuxbar Abo"]["matched"] is None


def test_sheet_ideas_with_consent_sends_names_only_and_consumes() -> None:
    env = _AiEnv()
    store = _FakeStore()
    result, _hass_ = _ideas(env, granted=True, store=store)
    assert len(env.prompts) == 1
    prompt = env.prompts[0]
    assert "Zorblax Gizmo" in prompt and "Quuxbar Abo" in prompt
    assert "Netflix" not in prompt and "Lebensmittel" not in prompt  # locally matched stay local
    assert "12.99" not in prompt and "EUR" not in prompt and "70" not in prompt
    assert result["ai_used"] is True and result["needs_consent"] is False
    by = {i["name"]: i for i in result["ideas"]}
    assert by["Zorblax Gizmo"] == {
        "name": "Zorblax Gizmo", "matched": "ai", "series_id": None,
        "category": None, "amount": None, "kind": "fixed",
    }
    assert by["Quuxbar Abo"]["kind"] == "reserve" and by["Quuxbar Abo"]["amount"] is None
    assert store.data["sheet_analysis"]["granted"] is False  # one-time consent consumed
    assert env.cfg["usage"]["calls"] == 1


def test_sheet_ideas_failed_ai_call_keeps_consent() -> None:
    env = _AiEnv(answer="")
    store = _FakeStore()
    result, _ = _ideas(env, granted=True, store=store)
    assert result["ai_used"] is False
    assert all(i["matched"] is None for i in result["ideas"] if i["name"].startswith(("Z", "Q")))
    assert store.data["sheet_analysis"]["granted"] is True


def test_name_prompt_strips_numbers() -> None:
    prompt = ai.build_names_prompt([ai.sanitize("Miete 950,00 EUR DE89370400440532013000", 60)])
    assert "950" not in prompt and "DE89" not in prompt


# -- consent API payload -------------------------------------------------------


def test_purposes_view_is_bounded_and_keyed() -> None:
    from custom_components.finance_dashboard.api.ai_consent import VIEWS, purposes_view

    assert len(VIEWS) == 1
    view = purposes_view()
    assert set(view) == set(consent.PURPOSES)
    for meta in view.values():
        assert len(meta["pros"]) <= 3 and len(meta["risks"]) <= 3
        assert all(k.startswith("ai.purpose.") for k in meta["pros"] + meta["risks"])


# -- options flow --------------------------------------------------------------


@pytest.mark.asyncio
async def test_options_form_has_no_refresh_interval_or_dead_fields() -> None:
    from custom_components.finance_dashboard.config_flow import FinanceDashboardOptionsFlow

    flow = FinanceDashboardOptionsFlow(SimpleNamespace(options={}, data={}))
    result = await flow.async_step_init(None)
    keys = {str(k) for k in result["data_schema"].schema}
    assert keys == {
        "enable_total_balance_sensor", "demo_mode", "raw_retention_days", "show_household",
    }
