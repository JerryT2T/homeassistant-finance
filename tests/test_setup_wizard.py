"""Setup wizard, payday, pots from history, exception notifications, non-admin gating.

All figures are invented.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.finance_dashboard import notify
from custom_components.finance_dashboard import setup_wizard as wiz
from custom_components.finance_dashboard.pots import Pot

TODAY = date(2026, 4, 20)


def _tx(amount, day, name="Shop", cat="food", owner="Anna", month=None, **extra):
    d = date(2026, month or 4, day).isoformat()
    t = {
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "bookingDate": d,
        "creditorName" if amount < 0 else "debtorName": name,
        "category": cat,
        "_status": "booked",
        "_account_person": owner,
        "_account_type": "shared" if owner == "shared" else "personal",
    }
    t.update(extra)
    return t


def _salary(month, day=27, amount=2500.0, owner="Anna", year=2026):
    t = _tx(amount, day, "Employer GmbH", "income", owner)
    t["bookingDate"] = date(year, month, day).isoformat()
    return t


# --- wizard state -----------------------------------------------------------


def test_state_resumes_at_first_pending_step_and_data_upgrades() -> None:
    state = wiz.default_state()
    assert wiz.current_step(state, {}) == "persons"
    hints = {"persons": True, "accounts": True}
    assert wiz.current_step(state, hints) == "payday"
    state = wiz.apply_update(state, {"step": "payday", "status": "skipped"})
    assert wiz.current_step(state, hints) == "region"


def test_complete_ends_resume() -> None:
    state = wiz.apply_update(wiz.default_state(), {"complete": True})
    assert wiz.current_step(state, {}) == "done"


@pytest.mark.parametrize(
    "body,code",
    [
        ({"step": "nope"}, "unknown_step"),
        ({"step": "persons", "status": "skipped"}, "not_skippable"),
        ({"step": "ai", "status": "weird"}, "invalid_status"),
        ({"ai_opt_in": "yes"}, "invalid_ai_opt_in"),
        ({"notifications": {"bogus": True}}, "unknown_notification_setting"),
        ({"notifications": {"large_debit": 1}}, "invalid_notifications"),
        ({"notifications": {"large_debit_factor": 0.5}}, "invalid_notifications"),
        ({"notifications": {"large_debit_threshold": -1}}, "invalid_notifications"),
    ],
)
def test_update_validation(body, code) -> None:
    with pytest.raises(wiz.SetupError) as err:
        wiz.apply_update(wiz.default_state(), body)
    assert err.value.code == code


def test_ai_is_toggle_only_and_plan_skippable() -> None:
    state = wiz.apply_update(wiz.default_state(), {"ai_opt_in": True, "step": "ai",
                                                   "status": "skipped"})
    assert state["ai_opt_in"] is True and state["steps"]["ai"] == "skipped"


# --- payday -----------------------------------------------------------------


def test_payday_suggestion_is_largest_recurring_credit_per_person() -> None:
    txs = [_salary(m) for m in (1, 2, 3)]
    txs += [_tx(50.0, 5, "Cashback Co", "income", "Anna", month=m) for m in (1, 2, 3)]
    out = wiz.suggest_paydays(txs, [{"name": "Anna"}, {"name": "Max"}])
    anna = next(x for x in out if x["person"] == "Anna")
    assert (anna["suggested_day"], anna["source"]) == (27, "employer gmbh") or anna[
        "suggested_day"
    ] == 27
    assert anna["amount"] == 2500.0
    assert next(x for x in out if x["person"] == "Max")["suggested_day"] is None


def test_paydays_validate_and_store_on_person() -> None:
    persons = [{"name": "Anna", "ha_users": []}]
    assert wiz.validate_paydays([{"person": "Anna", "day": 27}], persons) == {"Anna": 27}
    for bad in ([{"person": "Zed", "day": 3}], [{"person": "Anna", "day": 32}],
                [{"person": "Anna", "day": True}], "x"):
        with pytest.raises(wiz.SetupError):
            wiz.validate_paydays(bad, persons)
    stored = wiz.apply_paydays(persons, {"Anna": 27})
    assert wiz.person_payday(stored[0]) == 27
    assert wiz.person_payday({"payday": {"day": 5, "confirmed": False}}) is None


def test_payday_cycle_windows() -> None:
    assert wiz.payday_cycle(27, date(2026, 4, 20)) == (date(2026, 3, 27), date(2026, 4, 26))
    assert wiz.payday_cycle(27, date(2026, 4, 27)) == (date(2026, 4, 27), date(2026, 5, 26))
    assert wiz.payday_cycle(31, date(2026, 2, 28)) == (date(2026, 2, 28), date(2026, 3, 30))
    assert wiz.payday_cycle(5, date(2026, 1, 2)) == (date(2025, 12, 5), date(2026, 1, 4))


def test_assignments_keep_confirmed_payday() -> None:
    from custom_components.finance_dashboard.manager import FinanceDashboardManager

    entry = SimpleNamespace(data={
        "accounts": [], "persons": [{"name": "Anna", "ha_users": [],
                                     "payday": {"day": 27, "confirmed": True}}]})
    hass = MagicMock()
    hass.config_entries.async_update_entry.side_effect = lambda e, data: setattr(e, "data", data)
    from custom_components.finance_dashboard.budget_plan import BudgetPlan

    mgr = SimpleNamespace(_entry=entry, _hass=hass, _demo_mode=False, _accounts=[],
                          budget_plan=BudgetPlan(persons=[]))
    mgr.persons = FinanceDashboardManager.persons.fget(mgr)
    FinanceDashboardManager.async_set_assignments(
        mgr, {"persons": [{"name": "Anna", "ha_users": []}], "accounts": []}, [])
    assert entry.data["persons"][0]["payday"] == {"day": 27, "confirmed": True}


# --- pots from history ------------------------------------------------------


def test_pot_suggestions_median_rounded_excluding_fixed_other_transfers() -> None:
    txs = [_salary(m, day=1) for m in (1, 2, 3, 4)]
    # food per cycle (1st..end): Jan 200, Feb 233, Mar 400 -> median 233 -> 230
    txs += [_tx(-200, 10, month=1), _tx(-233, 10, month=2), _tx(-400, 10, month=3)]
    txs += [_tx(-900, 3, "Landlord", "housing", month=m) for m in (1, 2, 3)]
    txs += [_tx(-70, 4, "Misc", "other", month=m) for m in (1, 2, 3)]
    txs += [_tx(-70, 4, "Own acct", "transfers", month=m) for m in (1, 2, 3)]
    out = wiz.suggest_pots(txs, [], TODAY)
    assert [(s["owner"], s["category"], s["cycle_budget"], s["samples"]) for s in out] == [
        ("Anna", "food", 230.0, 3)
    ]


def test_pot_suggestions_need_two_samples_and_skip_existing() -> None:
    txs = [_salary(m, day=1) for m in (1, 2, 3, 4)]
    txs += [_tx(-100, 10, month=3)]
    assert wiz.suggest_pots(txs, [], TODAY) == []
    txs += [_tx(-100, 10, month=2)]
    assert len(wiz.suggest_pots(txs, [], TODAY)) == 1
    existing = [Pot(id="p", name="Food", owner="Anna", category_keys=["food"])]
    assert wiz.suggest_pots(txs, existing, TODAY) == []


def test_pot_acceptance_validation() -> None:
    assert wiz.validate_pot_acceptance(
        {"accept": [{"category": "food", "owner": "Anna", "cycle_budget": 230}]}
    )[0]["category_keys"] == ["food"]
    for bad in (None, {"accept": []}, {"accept": [{"x": 1}]}):
        with pytest.raises(wiz.SetupError):
            wiz.validate_pot_acceptance(bad)


# --- exceptions -------------------------------------------------------------

SET = {"large_debit": True, "large_debit_factor": 3.0, "large_debit_threshold": 500.0,
       "double_charge": True, "missing_salary": True}


def test_large_debit_relative_and_absolute() -> None:
    hist = [_tx(-20, d, "Cafe", month=3) for d in (1, 5, 9)]
    spike = _tx(-90, 18, "Cafe")
    found = notify.detect_large_debits(hist + [spike], TODAY, 3.0, 500.0)
    assert [e["kind"] for e in found] == ["large_debit"] and found[0]["amount"] == 90.0
    big = _tx(-600, 19, "Furniture")
    assert len(notify.detect_large_debits([big], TODAY, 3.0, 500.0)) == 1
    assert notify.detect_large_debits([big], TODAY, 3.0, 0) == []  # absolute rule off
    # no baseline and below threshold: silent; old transactions: silent
    assert notify.detect_large_debits([_tx(-90, 18, "New")], TODAY, 3.0, 500.0) == []
    assert notify.detect_large_debits([_tx(-600, 1, "Old")], TODAY, 3.0, 500.0) == []


def test_double_charge_within_three_days_only() -> None:
    twice = [_tx(-12.99, 17, "Stream"), _tx(-12.99, 19, "Stream")]
    assert [e["kind"] for e in notify.detect_double_charges(twice, TODAY)] == ["double_charge"]
    apart = [_tx(-12.99, 10, "Stream"), _tx(-12.99, 19, "Stream")]
    assert notify.detect_double_charges(apart, TODAY) == []


def test_missing_salary_after_grace_and_confirmed_payday() -> None:
    txs = [_salary(m, day=5, year=2026) for m in (1, 2, 3)]  # nothing in April
    persons = [{"name": "Anna"}]
    assert notify.detect_missing_salary(txs, persons, date(2026, 4, 8)) == []  # within grace
    found = notify.detect_missing_salary(txs, persons, date(2026, 4, 12))
    assert [e["kind"] for e in found] == ["missing_salary"] and found[0]["person"] == "Anna"
    assert "iban" not in str(found).lower()
    # a confirmed later payday moves the due date: not overdue yet
    later = [{"name": "Anna", "payday": {"day": 20, "confirmed": True}}]
    assert notify.detect_missing_salary(txs, later, date(2026, 4, 12)) == []
    # salary arrived
    txs.append(_salary(4, day=5))
    assert notify.detect_missing_salary(txs, persons, date(2026, 4, 12)) == []


def test_consent_exceptions() -> None:
    out = notify.consent_exceptions(
        [{"bank_id": "b", "title": "FakeBank", "consent_state": "expiring"},
         {"bank_id": "c", "consent_state": "ok"}], TODAY)
    assert [e["kind"] for e in out] == ["consent_expiring"]


def test_digest_text() -> None:
    txs = [_tx(-100, 18, cat="food"), _tx(-40, 10, cat="food")]
    d = notify.build_digest(txs, TODAY, {"status": "good", "remaining": 321.0, "questions_open": 2})
    assert d["questions_open"] == 2 and d["week"] == "2026-W17"
    assert "passt" in d["text"] and "Lebensmittel" in d["text"] and d["top_changes"][0]["category"] == "food"


def _hass_for_run():
    hass = MagicMock()
    hass.data = {}
    store = SimpleNamespace(saved=None)

    async def _load():
        return store.saved

    async def _save(data):
        store.saved = data

    hass.data["finance_dashboard"] = {
        "_setup_wizard_store": SimpleNamespace(async_load=_load, async_save=_save)}
    return hass, store


async def test_delivery_once_and_digest_once_per_week(monkeypatch) -> None:
    created = []
    monkeypatch.setattr(notify, "_persistent",
                        lambda h, i, t, m: created.append((i, m)))
    hass, _ = _hass_for_run()
    mgr = SimpleNamespace(
        demo_mode=False,
        _transactions=[_tx(-600, 19, "Furniture"), _tx(-30, 18, "Shop", owner="shared")],
        persons=[], get_bank_status=lambda: [], get_home=lambda **k: {"status": "good"})
    from datetime import datetime

    now = datetime(2026, 4, 20, 7, 0)
    await notify.async_after_refresh(hass, mgr, now)
    events = [c.args[0] for c in hass.bus.async_fire.call_args_list]
    assert events.count(notify.EVENT_EXCEPTION) == 1
    assert events.count(notify.EVENT_WEEKLY_DIGEST) == 1
    exc_payload = next(c.args[1] for c in hass.bus.async_fire.call_args_list
                       if c.args[0] == notify.EVENT_EXCEPTION)
    assert exc_payload["person"] == "Anna" and "iban" not in str(exc_payload).lower()
    # persistent text for a personal item carries neither merchant nor amount
    assert all("Furniture" not in m and "600" not in m for _, m in created)

    hass.bus.async_fire.reset_mock()
    await notify.async_after_refresh(hass, mgr, now)  # same day: nothing new
    assert hass.bus.async_fire.call_count == 0
    await notify.async_after_refresh(hass, mgr, datetime(2026, 4, 21, 7, 0))
    assert hass.bus.async_fire.call_count == 0  # same ISO week, exception deduped
    await notify.async_after_refresh(hass, mgr, datetime(2026, 4, 27, 7, 0))
    events = [c.args[0] for c in hass.bus.async_fire.call_args_list]
    assert events == [notify.EVENT_WEEKLY_DIGEST]


async def test_disabled_notifications_are_silent() -> None:
    hass, store = _hass_for_run()
    store.saved = {"notifications": {"enabled": False}}
    mgr = SimpleNamespace(demo_mode=False, _transactions=[_tx(-600, 19)], persons=[],
                          get_bank_status=lambda: [])
    from datetime import datetime

    await notify.async_after_refresh(hass, mgr, datetime(2026, 4, 20, 7, 0))
    assert hass.bus.async_fire.call_count == 0


# --- access / gating --------------------------------------------------------


class _Json:
    def json(self, data, status_code=200):
        return SimpleNamespace(_data=data, _status=status_code)


def _request(is_admin, user_id="u2", mgr=None, query=None, body=None):
    user = SimpleNamespace(id=user_id, name="Max", is_admin=is_admin)
    request = MagicMock()
    request.get.side_effect = lambda k, d=None: user if k == "hass_user" else d
    request.query = query or {}
    request.json = AsyncMock(return_value=body or {})
    hass = MagicMock()
    hass.data = {"finance_dashboard": {"entry": SimpleNamespace(entry_id="e"), "e": MagicMock()}}
    request.app = {"hass": hass}
    return request


def _patch_manager(monkeypatch, module, mgr):
    monkeypatch.setattr(module, "_get_manager", lambda hass: mgr)


@pytest.mark.parametrize("name,method", [
    ("FinanceDashboardSetupView", "get"), ("FinanceDashboardSetupView", "put"),
    ("FinanceDashboardPaydaySuggestionsView", "get"),
    ("FinanceDashboardPotSuggestionsView", "get"), ("FinanceDashboardPotSuggestionsView", "post"),
    ("FinanceDashboardTransferPlanView", "get"), ("FinanceDashboardBenchmarkView", "get"),
    ("FinanceDashboardTransferChainsView", "get"),
    ("FinanceDashboardAssignmentsView", "get"),
    ("FinanceDashboardPlanUploadView", "post"), ("FinanceDashboardPlanImportUrlView", "post"),
])
async def test_admin_only_endpoints_refuse_members(name, method, monkeypatch) -> None:
    from custom_components.finance_dashboard import api

    view = getattr(api, name)()
    view.json = _Json().json
    resp = await getattr(view, method)(_request(False))
    assert resp._status == 403


def _member_manager():
    accounts = [
        {"id": "a1", "type": "personal", "person": "Max"},
        {"id": "a2", "type": "personal", "person": "Anna"},
        {"id": "a3", "type": "shared"},
    ]
    return SimpleNamespace(
        _accounts=accounts,
        resolve_person=lambda u: "Max" if u and u.id == "u2" else None,
    )


async def test_member_sees_own_and_shared_balances_only(monkeypatch) -> None:
    from custom_components.finance_dashboard.api import data

    mgr = _member_manager()
    mgr.async_get_balance = AsyncMock(return_value={
        k: {"account_name": k, "iban_masked": "****1234", "balances": []} for k in ("a1", "a2", "a3")
    })
    mgr.get_balance_history = lambda key: []
    monkeypatch.setattr(data, "_get_manager", lambda hass: mgr)
    monkeypatch.setattr(data, "_account_keys_by_uid", lambda m: {})
    view = data.FinanceDashboardBalanceView()
    view.json = _Json().json
    resp = await view.get(_request(False))
    assert set(resp._data) == {"a1", "a3"}
    resp = await view.get(_request(True))
    assert set(resp._data) == {"a1", "a2", "a3"}


async def test_member_transactions_are_aggregate_only(monkeypatch) -> None:
    from custom_components.finance_dashboard.api import data

    mgr = SimpleNamespace(async_get_monthly_summary=AsyncMock(return_value={
        "categories": {"food": 10}, "total_income": 1, "total_expenses": 2,
        "transaction_count": 3}))
    monkeypatch.setattr(data, "_get_manager", lambda hass: mgr)
    view = data.FinanceDashboardTransactionsView()
    view.json = _Json().json
    resp = await view.get(_request(False))
    assert resp._status == 200 and resp._data["privacy"] == "aggregate_only"
    assert "transactions" not in resp._data


async def test_member_home_returns_own_person_view(monkeypatch) -> None:
    from custom_components.finance_dashboard.api import home

    calls = {}

    def _get_home(**kw):
        calls.update(kw)
        return {"view": kw["view"], "person": {"name": kw["person"]}}

    mgr = SimpleNamespace(resolve_person=lambda u: "Max", get_home=_get_home)
    monkeypatch.setattr(home, "_get_manager", lambda hass: mgr)
    view = home.FinanceDashboardHomeView()
    view.json = _Json().json
    resp = await view.get(_request(False, query={"view": "person", "horizon": "cycle"}))
    assert resp._status == 200 and calls["person"] == "Max"  # person comes from the login


async def test_admin_can_run_setup_endpoints(monkeypatch) -> None:
    from custom_components.finance_dashboard.api import setup

    hass_store = {}
    mgr = SimpleNamespace(persons=[{"name": "Anna"}], pots=[], _accounts=[], _transactions=[],
                          demo_mode=False)
    monkeypatch.setattr(setup, "_get_manager", lambda hass: mgr)

    async def _load(hass):
        return wiz._merge_state(hass_store.get("s"))

    async def _save(hass, state):
        hass_store["s"] = state

    monkeypatch.setattr(setup.wiz, "async_load_state", _load)
    monkeypatch.setattr(setup.wiz, "async_save_state", _save)
    from custom_components.finance_dashboard import ai_consent

    consents = {"categorize": False}

    async def _granted(hass, purpose):
        return consents[purpose]

    async def _set(hass, purpose, granted):
        consents[purpose] = granted
        return {}

    monkeypatch.setattr(ai_consent, "async_granted", _granted)
    monkeypatch.setattr(ai_consent, "async_set", _set)
    view = setup.FinanceDashboardSetupView()
    view.json = _Json().json
    resp = await view.get(_request(True))
    assert resp._status == 200 and resp._data["current_step"] == "accounts"
    resp = await view.put(_request(True, body={"step": "ai", "status": "skipped"}))
    assert resp._data["steps"]["ai"] == "skipped"
    resp = await view.put(_request(True, body={"step": "persons", "status": "skipped"}))
    assert resp._status == 400 and resp._data["error"] == "not_skippable"


def test_region_validation() -> None:
    from custom_components.finance_dashboard.api.setup import _region

    assert _region({"state": "rp", "postcode": "56179"}) == {
        "benchmark_state": "RP", "benchmark_postcode": "56179"}
    assert _region({"state": "DE-RP"})["benchmark_state"] == "DE-RP"
    assert _region({"state": "Rheinland"}) is None
    assert _region({"postcode": "5617"}) is None


async def test_invalid_region_rejects_before_any_write(monkeypatch) -> None:
    """A bad region must 400 without having stored paydays or wizard state."""
    from custom_components.finance_dashboard.api import setup

    updates, saved = [], []
    entry = SimpleNamespace(data={"persons": [{"name": "Anna"}]}, options={})
    mgr = SimpleNamespace(persons=[{"name": "Anna"}], pots=[], _accounts=[], _transactions=[],
                          demo_mode=False, _entry=entry)
    monkeypatch.setattr(setup, "_get_manager", lambda hass: mgr)

    async def _load(hass):
        return wiz._merge_state(None)

    async def _save(hass, state):
        saved.append(state)

    monkeypatch.setattr(setup.wiz, "async_load_state", _load)
    monkeypatch.setattr(setup.wiz, "async_save_state", _save)
    req = _request(True, body={"paydays": [{"person": "Anna", "day": 25}], "region": {"state": "Rheinland"}})
    req.app["hass"].config_entries = SimpleNamespace(
        async_update_entry=lambda *a, **kw: updates.append(kw))
    view = setup.FinanceDashboardSetupView()
    view.json = _Json().json
    resp = await view.put(req)
    assert resp._status == 400 and resp._data["error"] == "invalid_region"
    assert updates == [] and saved == []
