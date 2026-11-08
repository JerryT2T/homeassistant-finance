"""Owner sets, the one resolution chain, series/AI signals, settlement (no network)."""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.finance_dashboard import ai_provider as ai
from custom_components.finance_dashboard.const import OWNER_SHARED
from custom_components.finance_dashboard.household_settle import settlement_balances
from custom_components.finance_dashboard.household_summary import Classifier
from custom_components.finance_dashboard.manager import AssignmentError, FinanceDashboardManager
from custom_components.finance_dashboard.manager._ownership import OwnershipMixin
from custom_components.finance_dashboard.manager._questions import QuestionError
from custom_components.finance_dashboard.merchants import MerchantMemory
from custom_components.finance_dashboard.ownership import (
    apply_owner_set,
    account_kind,
    owner_set_label,
    resolve_owner_detail,
)
from custom_components.finance_dashboard.plan_match import resolve_owner
from tests.test_assignments import USERS, _mgr, _set


def _tx(kind="person_household", person="Anna", **extra):
    base = {
        "_account_type": "shared" if kind == "household" else "personal",
        "_account_person": "" if kind in ("household", "open") else person,
        "_account_household_use": kind == "person_household",
        "category": "leisure",
    }
    return {**base, **extra}


POS = SimpleNamespace(owner="Max")


# --- C1: owner sets ---------------------------------------------------------


def test_old_configs_keep_their_meaning() -> None:
    assert account_kind({"type": "shared"}) == "household"
    assert account_kind({"type": "personal", "person": "Anna"}) == "person"
    assert account_kind({"type": "personal", "person": ""}) == "open"
    assert account_kind({}) == "open"
    assert account_kind({"type": "personal", "person": "Anna", "household_use": True}) == (
        "person_household"
    )
    assert owner_set_label({"type": "personal", "person": "Anna", "household_use": True}) == {
        "owner": "Anna", "household": True,
    }


def test_apply_owner_set_rejects_other_combinations() -> None:
    acc = {"id": "x"}
    assert apply_owner_set(acc, "Anna", True)["household_use"] is True
    assert apply_owner_set(acc, "shared", False)["type"] == "shared"
    with pytest.raises(ValueError):
        apply_owner_set(acc, "shared", True)
    with pytest.raises(ValueError):
        apply_owner_set(acc, "", True)


def test_assignments_put_get_household_flag_and_changed() -> None:
    mgr = _mgr([{"name": "Anna", "ha_users": ["u1"]}, {"name": "Max", "ha_users": ["u2"]}])
    persons = [{"name": "Anna", "ha_users": ["u1"]}, {"name": "Max", "ha_users": ["u2"]}]
    key = FinanceDashboardManager.get_assignments(mgr, USERS)["accounts"][0]["key"]
    body = {"persons": persons, "accounts": [{"key": key, "owner": "Anna", "household": True}]}
    assert FinanceDashboardManager.async_set_assignments(mgr, body, USERS) is True
    acc = FinanceDashboardManager.get_assignments(mgr, USERS)["accounts"][0]
    assert (acc["owner"], acc["household"], acc["owner_kind"]) == ("Anna", True, "person_household")
    # the same again changes nothing -> no re-derive needed
    assert FinanceDashboardManager.async_set_assignments(mgr, body, USERS) is False
    # only the flag flips -> changed
    body["accounts"][0]["household"] = False
    assert FinanceDashboardManager.async_set_assignments(mgr, body, USERS) is True


@pytest.mark.parametrize(
    "item",
    [
        {"owner": "shared", "household": True},
        {"owner": "", "household": True},
        {"owner": "Anna", "household": "yes"},
    ],
)
def test_assignments_reject_forbidden_sets(item) -> None:
    mgr = _mgr()
    key = FinanceDashboardManager.get_assignments(mgr, USERS)["accounts"][0]["key"]
    body = {"persons": [{"name": "Anna", "ha_users": []}], "accounts": [{"key": key, **item}]}
    with pytest.raises(AssignmentError):
        FinanceDashboardManager.async_set_assignments(mgr, body, USERS)


# --- C2/C4: the chain -------------------------------------------------------


def test_chain_on_person_household_account() -> None:
    tx = _tx()
    assert resolve_owner_detail(tx) == ("Anna", "account", 50)
    assert resolve_owner_detail({**tx, "_ai_tendency": "personal"}) == ("Anna", "ai", 60)
    assert resolve_owner_detail({**tx, "_ai_tendency": "shared"}) == (OWNER_SHARED, "ai", 60)
    assert resolve_owner_detail({**tx, "category": "groceries"})[1:] == ("category", 70)
    assert resolve_owner_detail({**tx, "category": "groceries", "_ai_tendency": "personal"})[0] == (
        OWNER_SHARED
    )
    series = {**tx, "category": "groceries", "_series_owner": "Max"}
    assert resolve_owner_detail(series) == ("Max", "series", 85)
    assert resolve_owner_detail(series, POS) == ("Max", "plan", 90)
    ruled = {**series, "_owner_override": "shared"}
    assert resolve_owner_detail(ruled, POS) == (OWNER_SHARED, "merchant_rule", 95)
    booked = {**ruled, "_owner_scope": "booking"}
    assert resolve_owner_detail(booked, POS) == (OWNER_SHARED, "correction", 100)
    assert resolve_owner_detail(ruled, POS, correction="Anna") == ("Anna", "correction", 100)


def test_household_categories_are_configurable_through_the_stamp() -> None:
    tx = _tx(category="leisure", _household_categories=("leisure",))
    assert resolve_owner_detail(tx)[:2] == (OWNER_SHARED, "category")
    assert resolve_owner_detail(_tx(category="groceries", _household_categories=()))[1] == "account"


def test_person_and_household_accounts_ignore_the_household_signals() -> None:
    noisy = {"category": "groceries", "_series_owner": "Max", "_ai_tendency": "shared"}
    assert resolve_owner_detail(_tx("person", **noisy)) == ("Anna", "account", 100)
    assert resolve_owner_detail(_tx("household", **noisy)) == (OWNER_SHARED, "account", 100)
    assert resolve_owner_detail(_tx("open", **noisy)) == ("open", "account", 0)
    assert resolve_owner_detail(_tx("person"), POS) == ("Max", "plan", 90)


def test_resolve_owner_is_the_same_chain() -> None:
    tx = _tx(category="groceries")
    assert resolve_owner(tx, None) == resolve_owner_detail(tx)[0] == OWNER_SHARED
    assert resolve_owner(_tx("household"), POS) == "Max"


def test_classifier_detail_matches_classify() -> None:
    clf = Classifier(None, [], {"t1": "Max"}, ["Anna", "Max"])
    tx = _tx(transactionId="t1")
    assert clf.classify(tx, date(2026, 5, 1)) == ("Max", False)
    assert clf.classify_detail(tx, date(2026, 5, 1))[2:] == ("correction", 100)


# --- C3/D1: memory signals --------------------------------------------------


def _memory():
    return MerchantMemory(store=MagicMock())


def test_series_decision_covers_members_and_the_payee() -> None:
    mem = _memory()
    mem.learn_series_owner("s_abc", "shared", ["k1|L1"])
    tx = {"_account_key": "k1", "_ledger_id": "L1", "creditorName": "Other Name"}
    assert mem.series_owner(tx) == "shared"
    assert mem.series_owner({"_account_key": "k1", "_ledger_id": "L9", "creditorName": "x"}) is None
    from custom_components.finance_dashboard.recurring import series_id

    future = {"_ledger_id": "L2", "creditorName": "Netflix  ", "transactionAmount": {"amount": "-9"}}
    mem.learn_series_owner(series_id("Netflix", True), "Max")
    assert mem.series_owner(future) == "Max"
    assert mem.forget_series_owner("s_abc")
    assert mem.series_owner(tx) is None


def test_merchant_owner_keeps_category_and_ai_fills_owner_only_rules() -> None:
    mem = _memory()
    mem.set_merchant_owner("rewe", "shared")
    assert mem.known_merchants()["rewe"] == {"category": None, "owner": "shared"}
    assert mem.learn_ai_merchant("rewe", "groceries") is True
    assert mem.known_merchants()["rewe"]["owner"] == "shared"
    mem.set_merchant_owner("rewe", None)
    assert mem.known_merchants()["rewe"]["category"] == "groceries"
    mem.set_merchant_owner("zzz", "Anna")
    mem.set_merchant_owner("zzz", None)
    assert "zzz" not in mem.known_merchants()


def test_tendency_and_household_categories() -> None:
    mem = _memory()
    assert mem.learn_tendency("rewe", "shared") and not mem.learn_tendency("rewe", "shared")
    assert not mem.learn_tendency("rewe", "bogus")
    assert mem.tendency({"creditorName": "REWE"}) == "shared"
    assert "groceries" in mem.household_categories()
    mem.set_household_categories(["leisure"])
    assert mem.household_categories() == ("leisure",)
    mem.set_household_categories(None)
    assert "groceries" in mem.household_categories()


# --- D1: AI answer ----------------------------------------------------------


def test_prompt_and_parsing_carry_the_tendency_but_no_new_data() -> None:
    payload = ai.build_payload("REWE Markt", "Einkauf 12,50 EUR Anna Muster")
    assert set(payload) == {"merchant", "remittance"}
    prompt = ai.build_prompt(payload, ["groceries", "leisure"])
    assert "shared or personal" in prompt and "12,50" not in prompt
    assert ai.parse_tendency("groceries shared") == "shared"
    assert ai.parse_tendency("leisure, personal.") == "personal"
    assert ai.parse_tendency("groceries") is None
    assert ai.parse_category("groceries shared", ["groceries"]) == "groceries"


def _run_categorize(answer, **kw):
    cfg = ai.default_config()
    cfg["provider"] = "ha"
    saved = {}

    async def load(_h):
        return saved.get("cfg") or cfg

    async def save(_h, c):
        saved["cfg"] = c

    async def ask_raw(*_a, **_k):
        return answer, None

    import custom_components.finance_dashboard.ai_provider as mod

    orig = (mod.async_load_config, mod.async_save_config, mod._ask_raw)
    mod.async_load_config, mod.async_save_config, mod._ask_raw = load, save, ask_raw
    try:
        out = asyncio.run(
            mod.async_categorize_full(
                MagicMock(), credentials=None, opt_in=True, merchant_id="rewe",
                merchant="REWE", remittance="Einkauf", categories=["groceries", "leisure"],
                today=date(2026, 5, 1), **kw,
            )
        )
    finally:
        mod.async_load_config, mod.async_save_config, mod._ask_raw = orig
    return out, saved["cfg"]


def test_one_call_answers_category_and_tendency_and_caches_both() -> None:
    (cat, tend), cfg = _run_categorize("groceries shared")
    assert (cat, tend) == ("groceries", "shared")
    assert cfg["cache"]["rewe"] == "groceries" and cfg["tendency"]["rewe"] == "shared"
    assert cfg["usage"]["calls"] == 1
    assert ai.merge_config(cfg)["tendency"] == {"rewe": "shared"}


def test_category_without_tendency_still_counts() -> None:
    (cat, tend), cfg = _run_categorize("groceries")
    assert (cat, tend) == ("groceries", None) and "rewe" not in cfg["tendency"]


# --- D2: consent re-asked once ---------------------------------------------


def test_old_categorize_grant_is_void_until_asked_again() -> None:
    from custom_components.finance_dashboard import ai_consent as consent

    old = consent._entry({"granted": True, "granted_at": "2026-01-01T00:00:00"}, "categorize")
    assert old["granted"] is False and old["reconsent"] is True
    # persisted as stale, it stays stale (the flag survives a reload)
    again = consent._entry({**old}, "categorize")
    assert again["granted"] is False and again["reconsent"] is True
    fresh = consent._entry({"granted": True, "version": 2}, "categorize")
    assert fresh["granted"] is True and fresh["reconsent"] is False
    # other purposes did not widen
    assert consent._entry({"granted": True}, "contract_query")["granted"] is True


# --- E1/C3: manager methods -------------------------------------------------


class _Mgr(OwnershipMixin):
    def __init__(self):
        self._memory = MerchantMemory(store=MagicMock())
        self._memory.async_save = _async_noop
        self._demo_mode = False
        self._transactions = [
            {"_ledger_id": "L1", "creditorName": "REWE", "category": "other"},
            {"_ledger_id": "L2", "creditorName": "REWE", "category": "groceries"},
        ]
        self.persons = [{"name": "Anna"}]
        self._accounts = [{"person": "Anna"}]
        self.derived = 0

    def _valid_owners(self):
        return FinanceDashboardManager._valid_owners(self)

    async def async_apply_owner_change(self):
        self.derived += 1


async def _async_noop():
    return None


def test_owner_correction_for_any_category_per_booking_and_merchant() -> None:
    m = _Mgr()
    out = asyncio.run(m.async_correct_owner(ledger_id="L2", owner="shared", reach="booking"))
    assert out["owner"] == "shared" and m.derived == 1
    assert m._memory.booking_rule({"_ledger_id": "L2"}) == {"category": "groceries", "owner": "shared"}
    asyncio.run(m.async_correct_owner(ledger_id="L2", owner="Anna", reach="merchant"))
    assert m._memory.known_merchants()["rewe"]["owner"] == "Anna"
    asyncio.run(m.async_correct_owner(ledger_id="L2", owner=None, reach="booking"))
    assert "owner" not in m._memory.booking_rule({"_ledger_id": "L2"})
    for bad in (
        {"ledger_id": "nope", "owner": "shared", "reach": "booking"},
        {"ledger_id": "L1", "owner": "Mallory", "reach": "booking"},
        {"ledger_id": "L1", "owner": "shared", "reach": "everyone"},
    ):
        with pytest.raises(QuestionError):
            asyncio.run(m.async_correct_owner(**bad))


def test_series_and_household_category_validation() -> None:
    m = _Mgr()
    asyncio.run(m.async_set_series_owner(series_id="s_1", owner="shared", ledger_ids=["k|L1"]))
    assert m._memory.series_decisions()["s_1"]["owner"] == "shared"
    asyncio.run(m.async_set_series_owner(series_id="s_1", owner=None))
    assert m._memory.series_decisions() == {}
    with pytest.raises(QuestionError):
        asyncio.run(m.async_set_series_owner(series_id="s_1", owner="Mallory"))
    got = asyncio.run(m.async_set_household_categories(["groceries"]))
    assert got["categories"] == ["groceries"]
    with pytest.raises(QuestionError):
        asyncio.run(m.async_set_household_categories(["not_a_category"]))


def test_ai_review_pass_needs_consent_and_never_runs_without_it(monkeypatch) -> None:
    m = _Mgr()
    m._hass = MagicMock()

    async def denied(_h, _p):
        return False

    monkeypatch.setattr("custom_components.finance_dashboard.ai_consent.async_granted", denied)
    out = asyncio.run(m.async_ai_review_pass(["rewe"]))
    assert out["reason"] == "no_consent" and out["asked"] == 0


# --- F1: settlement ---------------------------------------------------------


def _booking(amount, kind, person="", category="leisure", tid="t", **extra):
    return {
        "transactionId": tid,
        "bookingDate": "2026-05-10",
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "creditorName": "Shop",
        "category": category,
        "_status": "booked",
        "_account_type": "shared" if kind == "household" else "personal",
        "_account_person": person,
        "_account_household_use": kind == "person_household",
        **extra,
    }


def test_settlement_both_directions() -> None:
    clf = Classifier(None, [], {"own": "Anna"}, ["Anna", "Max"])
    txs = [
        _booking(-40, "household", tid="own"),  # Anna's own spend from the joint account
        _booking(-10, "household", tid="joint"),  # household spend from the joint: nothing
        _booking(-25, "person", "Anna", tid="x", _owner_override="shared"),  # household from Anna
        _booking(-30, "person_household", "Max", category="groceries", tid="y"),  # category default
        _booking(-5, "person", "Max", tid="z"),  # personal from personal: nothing
        _booking(100, "household", tid="inc", category="income_work"),  # income ignored
    ]
    out = settlement_balances(txs, clf)
    assert out["Anna"] == {"owes_household": 40.0, "household_owes": 25.0, "net": 15.0}
    assert out["Max"] == {"owes_household": 0.0, "household_owes": 30.0, "net": -30.0}


def test_settlement_window_and_refund_netting() -> None:
    clf = Classifier(None, [], {"own": "Anna"}, ["Anna"])
    spend = _booking(-40, "household", tid="own")
    refund = _booking(15, "household", tid="own", _net_expense=True)
    assert settlement_balances([spend, refund], clf)["Anna"]["owes_household"] == 25.0
    assert settlement_balances([spend], clf, (date(2026, 6, 1), date(2026, 6, 30))) == {}
