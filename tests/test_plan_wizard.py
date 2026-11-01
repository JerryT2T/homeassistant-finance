"""Plan wizard backend: state, gate, income, pot binding, result, step migration.

All figures are invented.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from custom_components.finance_dashboard import plan_wizard as pw
from custom_components.finance_dashboard import setup_wizard as wiz
from custom_components.finance_dashboard.budget_plan import BudgetPlan, CostPosition, IncomeEntry
from custom_components.finance_dashboard.const import OWNER_SHARED
from custom_components.finance_dashboard.pots import Pot, pot_status
from tests.test_setup_wizard import _Json, _request, _salary

TODAY = date(2026, 10, 29)


# --- setup steps / migration ---------------------------------------------------


def test_setup_steps_new_order_and_skippable() -> None:
    assert wiz.STEPS == (
        "persons", "accounts", "payday", "region", "notifications", "ai", "points", "done",
    )
    assert wiz.SKIPPABLE == {"payday", "region", "notifications", "ai", "points"}


def test_old_state_is_migrated_gracefully() -> None:
    old = {
        "steps": {"persons": "done", "accounts": "done", "pots": "skipped", "plan": "done",
                  "goals": "skipped", "payday": "skipped", "ai": "pending"},
        "completed": False,
    }
    state = wiz._merge_state(old)
    assert set(state["steps"]) == {
        "persons", "accounts", "payday", "region", "notifications", "ai", "points"}
    assert state["steps"]["payday"] == "skipped"
    assert wiz.current_step(state, {}) == "region"  # first pending, old entries ignored
    assert state["plan_wizard"]["steps"]["income"] == "pending"


def test_region_and_points_hints_resolve_steps() -> None:
    state = wiz.default_state()
    hints = wiz.data_hints([{"name": "A"}], [], region=True, points=True)
    assert wiz.effective_steps(state, hints)["region"] == "done"
    assert wiz.effective_steps(state, hints)["points"] == "done"


# --- plan wizard state -----------------------------------------------------------


def test_plan_wizard_state_flow() -> None:
    st = pw.default_state()
    assert pw.public_state(st)["current_step"] == "income"
    st = pw.apply_update(st, {"step": "income"})
    assert st["steps"]["income"] == "done" and st["current_step"] == "fixed"
    st = pw.apply_update(st, {"step": "fixed", "status": "skipped"})
    assert st["current_step"] == "pots"
    st = pw.apply_update(st, {"complete": True})
    assert pw.public_state(st)["current_step"] == "result"


@pytest.mark.parametrize(
    "body,code",
    [
        ({"step": "nope"}, "unknown_step"),
        ({"step": "income", "status": "skipped"}, "not_skippable"),
        ({"step": "fixed", "status": "maybe"}, "invalid_status"),
        ({"current_step": "x"}, "unknown_step"),
        ({"complete": "yes"}, "invalid_complete"),
    ],
)
def test_plan_wizard_rejects_bad_updates(body, code) -> None:
    with pytest.raises(pw.PlanWizardError) as err:
        pw.apply_update(pw.default_state(), body)
    assert err.value.code == code


# --- gate ----------------------------------------------------------------------------


def test_gate_without_data() -> None:
    g = pw.build_gate(None, TODAY, 1)
    assert g == {"ready": False, "cycles": 0, "required": 3, "earliest_booked": None,
                 "ready_from": None}


def test_gate_payday_cycles_counted_from_first_payday() -> None:
    # Earliest 2026-08-10, payday 27: boundaries 08-27, 09-27, 10-27 -> 2 full cycles.
    g = pw.build_gate(date(2026, 8, 10), TODAY, 27)
    assert g["cycles"] == 2 and not g["ready"]
    assert g["ready_from"] == "2026-11-27"
    assert g["earliest_booked"] == "2026-08-10"


def test_gate_ready_after_three_cycles() -> None:
    g = pw.build_gate(date(2026, 7, 1), TODAY, 27)  # 07-27, 08-27, 09-27, 10-27 -> 3
    assert g["cycles"] == 3 and g["ready"] and g["ready_from"] is None


def test_gate_boundary_day_closes_the_cycle() -> None:
    assert pw.build_gate(date(2026, 7, 27), date(2026, 10, 26), 27)["cycles"] == 2
    assert pw.build_gate(date(2026, 7, 27), date(2026, 10, 27), 27)["cycles"] == 3


def test_gate_calendar_fallback_and_short_month() -> None:
    assert pw.household_payday([{"name": "A"}]) == 1
    assert pw.build_gate(date(2026, 7, 1), date(2026, 10, 1), 1)["cycles"] == 3
    assert pw.build_gate(date(2026, 7, 1), date(2026, 9, 30), 1)["cycles"] == 2
    # payday 31 clamps to the month end
    assert pw.build_gate(date(2026, 1, 31), date(2026, 5, 1), 31)["cycles"] == 3


def test_household_payday_uses_confirmed_person_payday() -> None:
    persons = [{"name": "A"}, {"name": "B", "payday": {"day": 15, "confirmed": True}}]
    assert pw.household_payday(persons) == 15


def test_earliest_booked_across_accounts_and_meta_fallback() -> None:
    class L:
        meta = {"history": {"b": {"earliest_booked": "2026-03-04"}}}

        def account_keys(self):
            return ["a", "b", "c"]

        def first_booked_date(self, key):
            return {"a": "2026-05-02", "b": None, "c": None}[key]

    assert pw.earliest_booked_by_key(L()) == {"a": "2026-05-02", "b": "2026-03-04", "c": None}
    assert pw.earliest_booked(L()) == date(2026, 3, 4)
    assert pw.earliest_booked(None) is None


# --- income ----------------------------------------------------------------------------


def test_income_suggestion_from_recurring_salary() -> None:
    txs = [_salary(m, amount=2500.0) for m in (7, 8, 9, 10)]
    out = pw.suggest_income(txs, [{"name": "Anna"}, {"name": "Max"}])
    assert len(out) == 1
    assert out[0]["person"] == "Anna"
    assert out[0]["amount_net"] == 2500.0  # plan sign, positive
    assert out[0]["samples"] >= 3 and out[0]["source"]


def test_income_validation_builds_entries() -> None:
    out = pw.validate_income({"income": [{"person": "Anna", "amount_net": 2500}]}, {"Anna"})
    assert IncomeEntry.from_dict(out[0]).net == 2500.0
    for bad, code in [
        ({"income": []}, "invalid_body"),
        ({"income": [{"person": "X", "amount_net": 1}]}, "unknown_person"),
        ({"income": [{"person": "Anna", "amount_net": -1}]}, "invalid_amount"),
        ({"income": [{"person": "Anna", "amount_net": True}]}, "invalid_amount"),
    ]:
        with pytest.raises(pw.PlanWizardError) as err:
            pw.validate_income(bad, {"Anna"})
        assert err.value.code == code


# --- pot account binding --------------------------------------------------------------------


def _bk(day, amount, key):
    return {"date": date(2026, 4, day), "amount": amount, "category": "food",
            "pending": False, "label": "x", "account_key": key}


def test_pot_binding_filters_spending_by_account() -> None:
    cycle = (date(2026, 4, 1), date(2026, 4, 30))
    bookings = [_bk(2, 40.0, "acc1"), _bk(3, 25.0, "acc2")]
    free = Pot(id="p", name="Food", cycle_budget=300, category_keys=["food"])
    bound = Pot(id="p", name="Food", cycle_budget=300, category_keys=["food"],
                account_keys=["acc1"])
    assert pot_status(free, bookings, cycle, date(2026, 4, 10))["spent"] == 65.0
    assert pot_status(bound, bookings, cycle, date(2026, 4, 10))["spent"] == 40.0


def test_pot_account_keys_model() -> None:
    assert Pot.from_dict({"name": "x"}).account_keys is None
    assert Pot.from_dict({"name": "x", "account_keys": []}).account_keys is None
    p = Pot.from_dict({"name": "x", "account_keys": ["a", "a", " b "]})
    assert p.account_keys == ["a", "b"] and p.to_dict()["account_keys"] == ["a", "b"]
    assert Pot.from_dict(p.to_dict()).account_keys == ["a", "b"]
    assert Pot.from_dict({"name": "x"}).to_dict()["account_keys"] is None
    with pytest.raises(ValueError):
        Pot.from_dict({"name": "x", "account_keys": "a"})


def test_pot_acceptance_takes_account_keys() -> None:
    out = wiz.validate_pot_acceptance(
        {"accept": [{"category": "food", "cycle_budget": 100, "account_keys": ["k1"]}]}, {"k1"}
    )
    assert out[0]["account_keys"] == ["k1"]
    with pytest.raises(wiz.SetupError) as err:
        wiz.validate_pot_acceptance(
            {"accept": [{"category": "food", "account_keys": ["zz"]}]}, {"k1"}
        )
    assert err.value.code == "unknown_account"
    plain = wiz.validate_pot_acceptance({"accept": [{"category": "food"}]}, {"k1"})
    assert "account_keys" not in plain[0]


def test_home_pot_bookings_respect_binding() -> None:
    from custom_components.finance_dashboard.home import _pot_bookings

    pot = Pot(id="p", name="F", owner="shared", category_keys=["food"], account_keys=["k1"])
    bks = [
        {"owner": "shared", "bank_amount": -5, "category": "food", "account_key": "k1"},
        {"owner": "shared", "bank_amount": -5, "category": "food", "account_key": "k2"},
        {"owner": "shared", "upcoming": True, "bank_amount": -5, "category": "food"},
    ]
    assert len(_pot_bookings(pot, bks)) == 2  # k1 + unknown-account upcoming


# --- result -------------------------------------------------------------------------------


def _plan() -> BudgetPlan:
    plan = BudgetPlan()
    plan.set_income(IncomeEntry(person="Anna", deposit=3000))
    plan.set_income(IncomeEntry(person="Max", deposit=1000))
    plan.upsert_position(CostPosition.from_dict({"name": "Rent", "owner": OWNER_SHARED, "amount": 1200}))
    plan.upsert_position(CostPosition.from_dict({"name": "Gym", "owner": "Max", "amount": 40}))
    return plan


def test_result_math_and_sign_convention() -> None:
    pots = [Pot(id="a", name="Food", owner="shared", cycle_budget=400, category_keys=["food"]),
            Pot(id="b", name="Fun", owner="Max", cycle_budget=60)]
    goals = [{"kind": "reserve_topup", "owner": "shared", "monthly_amount": 100},
             {"kind": "savings_rate", "owner": "Anna", "rate_percent": 10},
             {"kind": "target_by_date", "owner": "Max", "target_amount": 600,
              "target_date": "2027-04-29"},
             {"kind": "category_cap", "owner": "shared", "category": "food", "cap_amount": 300}]
    hist = {"months": 0, "avg_income": None, "avg_spent": None, "avg_left_over": None}
    r = pw.build_result(_plan(), pots, goals, TODAY, hist)
    assert r["income_total"] == 4000.0
    assert r["fixed_total"] == 1240.0  # expense positive
    assert r["pots_total"] == 460.0
    assert r["goals_total"] == 100 + 400 + 100  # topup + 10% of 4000 + 600/6 months; cap adds 0
    assert r["left_over"] == 4000 - 1240 - 460 - 600
    assert r["balanced"] is True
    anna, max_ = r["per_person"]
    assert anna["share"] == 0.75 and max_["share"] == 0.25
    # shared = 1200 + 400 + 100 = 1700
    assert anna["pocket_money"] == round(3000 - 1700 * 0.75 - 400, 2)
    assert max_["pocket_money"] == round(1000 - 1700 * 0.25 - (40 + 60 + 100), 2)
    assert sum(p["pocket_money"] for p in r["per_person"]) == pytest.approx(r["left_over"], abs=0.02)


def test_result_not_balanced_when_overspent() -> None:
    pots = [Pot(id="a", name="Food", cycle_budget=4000)]
    r = pw.build_result(_plan(), pots, [], TODAY, {})
    assert r["balanced"] is False and r["left_over"] < 0


def test_history_averages_over_full_cycles() -> None:
    cycles = [(date(2026, 8, 1), date(2026, 8, 31)), (date(2026, 9, 1), date(2026, 9, 30))]

    def tx(m, d, amount):
        return {"transactionAmount": {"amount": str(amount)},
                "bookingDate": date(2026, m, d).isoformat()}

    txs = [tx(8, 2, 2000), tx(8, 5, -500), tx(9, 2, 2200), tx(9, 5, -700), tx(10, 5, -999)]
    h = pw.history_averages(txs, cycles)
    assert h == {"months": 2, "avg_income": 2100.0, "avg_spent": 600.0, "avg_left_over": 1500.0}
    assert pw.history_averages(txs, [])["months"] == 0


# --- endpoints ----------------------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch):
    from custom_components.finance_dashboard.api import plan_wizard as view_mod

    store: dict = {}
    ledger = SimpleNamespace(
        meta={},
        account_keys=lambda: ["k1"],
        first_booked_date=lambda k: "2026-07-01",
    )
    saved = []

    async def set_income(payload):
        saved.append(payload)
        return payload

    mgr = SimpleNamespace(
        persons=[{"name": "Anna", "payday": {"day": 27, "confirmed": True}}],
        pots=[], _accounts=[], _transactions=[], _ledger=ledger, demo_mode=False,
        budget_plan=_plan(), async_set_income=set_income,
    )
    monkeypatch.setattr(view_mod, "_get_manager", lambda hass: mgr)

    async def _load(hass):
        return wiz._merge_state(store.get("s"))

    async def _save(hass, state):
        store["s"] = state

    monkeypatch.setattr(view_mod.wiz, "async_load_state", _load)
    monkeypatch.setattr(view_mod.wiz, "async_save_state", _save)
    monkeypatch.setattr(view_mod.dt_util, "now", lambda: SimpleNamespace(date=lambda: TODAY))
    return SimpleNamespace(mod=view_mod, saved=saved, mgr=mgr)


def _view(cls):
    v = cls()
    v.json = _Json().json
    return v


async def test_endpoints_state_gate_income_result(api, monkeypatch) -> None:
    m = api.mod
    r = await _view(m.FinanceDashboardPlanWizardView).get(_request(True))
    assert r._data == {"current_step": "income", "completed": False,
                       "steps": dict.fromkeys(pw.STEPS, "pending")}
    r = await _view(m.FinanceDashboardPlanWizardView).put(
        _request(True, body={"step": "fixed", "status": "skipped"}))
    assert r._data["steps"]["fixed"] == "skipped"
    r = await _view(m.FinanceDashboardPlanWizardView).put(_request(True, body={"step": "x"}))
    assert r._status == 400

    r = await _view(m.FinanceDashboardPlanWizardGateView).get(_request(True))
    assert r._data["cycles"] == 3 and r._data["ready"] is True  # 2026-07-01, payday 27

    r = await _view(m.FinanceDashboardPlanWizardIncomeView).put(
        _request(True, body={"income": [{"person": "Anna", "amount_net": 2400}]}))
    assert r._status == 200 and api.saved[0]["deposit"] == 2400.0
    r = await _view(m.FinanceDashboardPlanWizardIncomeView).put(
        _request(True, body={"income": [{"person": "Zed", "amount_net": 1}]}))
    assert r._status == 400 and r._data["error"] == "unknown_person"

    async def goals(hass):
        return []

    monkeypatch.setattr(m.goals_mod, "async_get_goals", goals)
    monkeypatch.setattr(m, "counted_transactions", lambda t, a: [])
    r = await _view(m.FinanceDashboardPlanWizardResultView).get(_request(True))
    assert r._data["income_total"] == 4000.0
    assert r._data["history"]["months"] == 3

    for cls in (m.FinanceDashboardPlanWizardGateView, m.FinanceDashboardPlanWizardResultView,
                m.FinanceDashboardPlanWizardView):
        assert (await _view(cls).get(_request(False)))._status == 403


async def test_assignments_payload_gets_earliest_and_type() -> None:
    from custom_components.finance_dashboard.account_identity import account_key
    from custom_components.finance_dashboard.api.assignments import (
        FinanceDashboardAssignmentsView,
    )

    acc = {"id": "uid1", "iban": "DE00 1234", "institution": "Bank", "account_type": "SVGS"}
    key = account_key(acc)
    ledger = SimpleNamespace(meta={}, account_keys=lambda: [key],
                             first_booked_date=lambda k: "2026-02-03")
    mgr = SimpleNamespace(_accounts=[acc], _ledger=ledger)
    payload = {"accounts": [{"key": key}, {"key": "other"}]}
    out = FinanceDashboardAssignmentsView._with_account_info(mgr, payload)
    assert out["accounts"][0]["earliest_booked"] == "2026-02-03"
    assert out["accounts"][0]["account_type"] == "SVGS"
    assert out["accounts"][1] == {"key": "other", "earliest_booked": None, "account_type": None}


async def test_ai_opt_in_routes_through_ai_consent(monkeypatch) -> None:
    import sys
    import types

    from custom_components.finance_dashboard.api import setup

    calls = []
    fake = types.ModuleType("custom_components.finance_dashboard.ai_consent")

    async def granted(hass, purpose):
        return purpose == "categorize"

    async def set_(hass, purpose, value):
        calls.append((purpose, value))
        return {}

    fake.async_granted, fake.async_set = granted, set_
    monkeypatch.setitem(sys.modules, "custom_components.finance_dashboard.ai_consent", fake)
    monkeypatch.setattr("custom_components.finance_dashboard.ai_consent", fake, raising=False)
    assert await setup._ai_opt_in(None, {"ai_opt_in": False}) is True
    await setup._set_ai_opt_in(None, {}, False)
    assert calls == [("categorize", False)]
