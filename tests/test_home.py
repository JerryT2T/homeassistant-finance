"""Home payload: ownership, privacy, contract shape, HTTP gating. Invented figures only."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.finance_dashboard.budget_plan import BudgetPlan
from custom_components.finance_dashboard.home import build_home, resolve_person
from custom_components.finance_dashboard.pots import Pot

NOW = datetime(2026, 4, 15, 12, 0).astimezone()

ACCOUNTS = [
    {"id": "a1", "type": "personal", "person": "Anna", "ha_users": [{"id": "u-anna", "name": "anna"}]},
    {"id": "a2", "type": "personal", "person": "Max", "ha_users": [{"id": "u-max"}]},
    {"id": "a3", "type": "shared", "person": "", "ha_users": []},
]


def _tx(acc: str, amount: float, cat: str, day: int, name: str = "Shop", month: int = 4,
        status: str = "booked") -> dict:
    owner = {"a1": ("personal", "Anna"), "a2": ("personal", "Max"), "a3": ("shared", "")}[acc]
    return {
        "bookingDate": f"2026-{month:02d}-{day:02d}",
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "creditorName": name,
        "category": cat,
        "_account_type": owner[0],
        "_account_person": owner[1],
        "_status": status,
    }


TXS = [
    _tx("a1", 3100, "income", 1),
    _tx("a1", 3100, "income", 1, month=3),
    _tx("a2", 2400, "income", 1, month=3),
    _tx("a2", 2400, "income", 1),
    _tx("a3", -80.0, "food", 5, "Shared Market"),
    _tx("a1", -60.0, "leisure", 6, "Secret Hobby Shop"),
    _tx("a2", -45.0, "transport", 7, "Max Garage"),
    _tx("a3", -12.0, "food", 15, "Pending Market", status="pending"),
]

POTS = [
    Pot("food", "Food", "shared", 300.0, ["food"]),
    Pot("fun", "Anna Fun", "Anna", 150.0, ["leisure"]),
    Pot("car", "Max Car", "Max", 150.0, ["transport"]),
]


def _home(view: str, person: str | None, horizon: str = "cycle", pots=POTS) -> dict:
    return build_home(
        accounts=ACCOUNTS, transactions=TXS, plan=BudgetPlan(), pots=pots,
        recurring=[], banks=[], as_of=NOW, now=NOW, person=person, view=view, horizon=horizon,
    )


def test_person_view_contains_only_own_data() -> None:
    out = _home("person", "Anna")
    assert out["view"] == "person" and out["person"]["id"] == "Anna"
    assert [p["id"] for p in out["pots"]] == ["fun"]
    blob = str(out)
    assert "Max Car" not in blob and "Max Garage" not in blob and "Shared Market" not in blob


def test_household_view_shows_persons_only_as_totals() -> None:
    out = _home("household", None)
    assert [p["id"] for p in out["pots"]] == ["food"]  # shared pots only
    names = {p["name"] for p in out["persons"]}
    assert names == {"Anna", "Max"}
    for entry in out["persons"]:
        assert set(entry) == {"id", "name", "budget", "spent", "balance", "status"}
    blob = str(out)
    assert "Anna Fun" not in blob and "Secret Hobby Shop" not in blob and "Max Garage" not in blob


def test_household_cycle_uses_seven_day_rule_anchor() -> None:
    out = _home("household", None)
    assert out["cycle"]["start"] == "2026-04-01"
    assert out["cycle"]["anchor"] == "Anna"
    assert out["cycle"]["rule"] == "household_7_day"


def test_personal_pot_is_fed_only_from_personal_accounts() -> None:
    # A shared-account leisure booking must not feed Anna's personal pot.
    txs = [*TXS, _tx("a3", -500.0, "leisure", 8, "Joint Leisure")]
    out = build_home(accounts=ACCOUNTS, transactions=txs, plan=None, pots=POTS, recurring=[],
                     banks=[], as_of=NOW, now=NOW, person="Anna", view="person", horizon="cycle")
    assert out["pots"][0]["spent"] == 60.0


def _question_merchants(creditor: str, holder: str) -> list[str]:
    accounts = [{**ACCOUNTS[2], "name": holder}]
    txs = [_tx("a3", -250.0, "other", 10, creditor)]
    out = build_home(accounts=accounts, transactions=txs, plan=None, pots=[], recurring=[],
                     banks=[], as_of=NOW, now=NOW, person=None, view="household",
                     horizon="cycle", include_questions=True)
    return [q["merchant"] for q in out["questions"]]


def test_payment_to_own_name_is_never_a_question() -> None:
    # Middle name tolerated, same rule as contracts since 0.20.2.
    assert _question_merchants("Jeremy Tim Treder", "Jeremy Treder") == []
    assert _question_merchants("Treder, Jeremy", "Jeremy Treder und Anna Muster") == []


def test_look_alike_business_name_stays_a_question() -> None:
    assert _question_merchants("Treder Gartenbau GmbH", "Jeremy Treder") != []
    assert _question_merchants("Jeremy Handels GmbH", "Jeremy Treder") != []


def test_person_without_mapping_degrades_to_household() -> None:
    out = _home("person", None)
    assert out["view"] == "household" and out["person"] is None


def test_pending_booking_listed_in_next_with_label_flag() -> None:
    out = _home("household", None)
    assert out["next"][0]["pending"] is True
    assert out["next"][0]["label"] == "Pending Market"


def test_contract_fields_per_horizon() -> None:
    cyc = _home("person", "Anna", "cycle")
    for key in ("freshness", "alerts", "questions_open", "cycle", "status", "remaining", "pots",
                "next", "did_you_know", "reserves", "fixed_costs_covered"):
        assert key in cyc
    assert cyc["freshness"]["status"] == "fresh"
    assert {"id", "name", "owner", "balance", "per_day", "status", "kind"} <= set(cyc["pots"][0])
    assert "days" in _home("person", "Anna", "week")["week"]
    assert "cycles" in _home("person", "Anna", "year")["year"]
    assert "can_spend" in _home("person", "Anna", "today")["today"]


def test_resolve_person_maps_ha_user() -> None:
    assert resolve_person(SimpleNamespace(id="u-anna", name="x"), ACCOUNTS) == "Anna"
    assert resolve_person(SimpleNamespace(id="zzz", name="MAX"), ACCOUNTS) is None
    assert resolve_person(SimpleNamespace(id="u-max", name="x"), ACCOUNTS) == "Max"


def test_demo_home_serves_same_contract() -> None:
    from custom_components.finance_dashboard.demo import generate_demo_home

    for horizon in ("today", "week", "cycle", "year"):
        for view, person in (("person", "Anna"), ("household", None)):
            out = generate_demo_home(person=person, view=view, horizon=horizon, now=NOW)
            assert out["view"] == view and out["horizon"] == horizon
            assert out["cycle"]["start"] and out["pots"]
    household = generate_demo_home(person=None, view="household", horizon="cycle", now=NOW)
    assert household["cycle"]["anchor"] in {"Anna", "Max"}


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


class _Json:
    def json(self, data, status_code=200):
        r = MagicMock()
        r._data, r._status = data, status_code
        return r


def _request(user, query=None, body=None):
    req = MagicMock()
    req.get.side_effect = lambda k, d=None: user if k == "hass_user" else d
    req.query = query or {}
    req.app = {"hass": MagicMock()}
    req.json = AsyncMock(return_value=body or {})
    return req


def _manager():
    from custom_components.finance_dashboard.manager import FinanceDashboardManager

    pots = [Pot("fun", "Anna Fun", "Anna", 150.0, ["leisure"]),
            Pot("food", "Food", "shared", 300.0, ["food"])]
    mgr = SimpleNamespace(
        _demo_mode=False, _accounts=ACCOUNTS, persons=[], _transactions=TXS, budget_plan=BudgetPlan(),
        pots=pots, _recurring_patterns=[], _last_refresh=NOW,
        get_bank_status=lambda: [], _banking_client=MagicMock(), _refresh_lock=MagicMock(),
    )
    mgr.resolve_person = lambda user: FinanceDashboardManager.resolve_person(mgr, user)
    mgr.get_home = lambda **kw: FinanceDashboardManager.get_home(mgr, **kw)
    mgr.async_save_pot = AsyncMock(side_effect=lambda data, replace: dict(data))
    mgr.async_delete_pot = AsyncMock(return_value=True)
    return mgr


@pytest.mark.asyncio
async def test_home_view_reads_cache_and_never_touches_the_bank() -> None:
    from custom_components.finance_dashboard.api import FinanceDashboardHomeView

    mgr = _manager()
    view = FinanceDashboardHomeView()
    view.json = _Json().json
    user = SimpleNamespace(id="u-anna", name="a", is_admin=False)
    with patch("custom_components.finance_dashboard.api.home._get_manager", return_value=mgr):
        resp = await view.get(_request(user, {"horizon": "week", "view": "person"}))
    assert resp._status == 200 and resp._data["person"]["id"] == "Anna"
    assert mgr._banking_client.mock_calls == []
    assert mgr._refresh_lock.mock_calls == []


@pytest.mark.asyncio
async def test_home_view_rejects_bad_params_and_requires_auth_flag() -> None:
    from custom_components.finance_dashboard.api import FinanceDashboardHomeView

    assert FinanceDashboardHomeView.requires_auth is True
    view = FinanceDashboardHomeView()
    view.json = _Json().json
    resp = await view.get(_request(None, {"horizon": "decade"}))
    assert resp._status == 400


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_admin", "uid", "owner", "expected"),
    [
        (False, "u-anna", "Anna", 201),   # own personal pot
        (False, "u-anna", "Max", 403),    # someone else's pot
        (False, "u-anna", "shared", 403),  # shared needs admin
        (True, "admin", "Max", 201),
    ],
)
async def test_pot_create_gating(is_admin, uid, owner, expected) -> None:
    from custom_components.finance_dashboard.api import FinanceDashboardPotsView

    view = FinanceDashboardPotsView()
    view.json = _Json().json
    user = SimpleNamespace(id=uid, name="n", is_admin=is_admin)
    with patch("custom_components.finance_dashboard.api.home._get_manager",
               return_value=_manager()):
        resp = await view.post(_request(user, body={"name": "New", "owner": owner}))
    assert resp._status == expected


@pytest.mark.asyncio
async def test_pot_update_and_delete_check_existing_owner() -> None:
    from custom_components.finance_dashboard.api import FinanceDashboardPotsView

    view = FinanceDashboardPotsView()
    view.json = _Json().json
    anna = SimpleNamespace(id="u-anna", name="n", is_admin=False)
    max_ = SimpleNamespace(id="u-max", name="n", is_admin=False)
    mgr = _manager()
    with patch("custom_components.finance_dashboard.api.home._get_manager", return_value=mgr):
        # Max may not hijack Anna's pot by claiming it as his own on update.
        resp = await view.put(_request(max_, body={"id": "fun", "name": "X", "owner": "Max"}))
        assert resp._status == 403
        resp = await view.delete(_request(max_, {"id": "fun"}))
        assert resp._status == 403
        resp = await view.delete(_request(anna, {"id": "fun"}))
        assert resp._status == 200
        resp = await view.delete(_request(anna, {"id": "nope"}))
        assert resp._status == 404
        resp = await view.delete(_request(anna, {"id": "food"}))  # shared pot
        assert resp._status == 403


def _plan() -> BudgetPlan:
    from custom_components.finance_dashboard.budget_plan import CostPosition, IncomeEntry

    plan = BudgetPlan(persons=["Anna", "Max"])
    plan.set_income(IncomeEntry(person="Anna", deposit=3000.0))
    plan.upsert_position(
        CostPosition(id="rent", name="Rent", owner="Anna", amount=1000.0, category="housing")
    )
    plan.upsert_position(
        CostPosition(id="maxcar", name="Max Car", owner="Max", amount=400.0, category="transport")
    )
    return plan


def test_person_display_name_falls_back_to_name() -> None:
    out = build_home(
        accounts=ACCOUNTS, transactions=TXS, plan=BudgetPlan(), pots=POTS, recurring=[],
        banks=[], as_of=NOW, now=NOW, person="Anna", view="person", horizon="cycle",
        persons=[{"name": "Anna", "display_name": "Annie"}, {"name": "Max"}],
    )
    assert out["person"] == {"id": "Anna", "name": "Anna", "display_name": "Annie"}
    assert _home("person", "Anna")["person"]["display_name"] == "Anna"


def test_person_budget_from_history() -> None:
    pb = _home("person", "Anna")["person_budget"]
    assert pb == {"budget": 3100.0, "spent": 60.0, "remaining": 3040.0, "source": "history"}


def test_person_budget_from_plan_uses_own_items_only() -> None:
    out = build_home(
        accounts=ACCOUNTS, transactions=TXS, plan=_plan(), pots=POTS, recurring=[],
        banks=[], as_of=NOW, now=NOW, person="Anna", view="person", horizon="cycle",
    )
    pb = out["person_budget"]
    assert pb["source"] == "plan"
    assert pb["budget"] == 2000.0  # 3000 income - 1000 own fixed (Max's 400 ignored)
    assert pb["spent"] == 60.0 and pb["remaining"] == 1940.0
    assert "Max" not in str(pb)


def test_person_budget_absent_in_household_view() -> None:
    assert "person_budget" not in _home("household", None)
    assert "person_budget" not in _home("household", "Anna")


def test_viewer_person_present_on_every_view() -> None:
    assert _home("person", "Anna")["viewer_person"] == "Anna"
    household = _home("household", "Anna")
    assert household["view"] == "household" and household["person"] is None
    assert household["viewer_person"] == "Anna"  # UI keeps the person <-> household toggle
    assert _home("household", None)["viewer_person"] is None
    assert _home("person", None)["viewer_person"] is None


def test_today_is_a_date() -> None:
    assert isinstance(NOW.date(), date)


def test_confirmed_payday_anchors_cycle_without_salary_bookings() -> None:
    persons = [{"name": "Anna", "ha_users": [], "payday": {"day": 25, "confirmed": True}}]
    out = build_home(
        accounts=ACCOUNTS, transactions=[], plan=BudgetPlan(), pots=[],
        recurring=[], banks=[], as_of=NOW, now=NOW, person=None, view="household",
        horizon="cycle", persons=persons,
    )
    assert out["cycle"]["rule"] == "payday_confirmed"
    assert out["cycle"]["start"].endswith("-25")


# --- recent bookings for the cycle ledger (admin only) -------------------------


def _recent(view: str, person: str | None, **kw) -> dict:
    return build_home(
        accounts=ACCOUNTS, transactions=TXS, plan=BudgetPlan(), pots=POTS, recurring=[],
        banks=[], as_of=NOW, now=NOW, person=person, view=view, horizon=kw.pop("horizon", "cycle"),
        **kw,
    )


def test_recent_absent_unless_requested_or_not_cycle() -> None:
    assert "recent" not in _recent("person", "Anna")
    assert "recent" not in _recent("person", "Anna", horizon="week", include_recent=True)


def test_recent_person_view_is_own_bookings_newest_first_and_sanitised() -> None:
    tx = _tx("a1", -9.99, "media", 15, "Stream Co", status="pending")
    tx["creditorAccount"] = {"iban": "DE00123456780000001234"}
    tx["remittanceInformationUnstructured"] = "Customer 4711 secret text"
    out = build_home(
        accounts=ACCOUNTS, transactions=[*TXS, tx], plan=BudgetPlan(), pots=POTS, recurring=[],
        banks=[], as_of=NOW, now=NOW, person="Anna", view="person", horizon="cycle",
        include_recent=True,
    )
    rows = out["recent"]
    # newest first, the pending booking (dated today) on top; the April salary is inside the window too
    assert [r["label"] for r in rows][:2] == ["Stream Co", "Secret Hobby Shop"]
    assert {r["owner"] for r in rows} == {"Anna"}
    assert rows[0]["pending"] is True and rows[0]["amount"] == -9.99
    assert set(rows[0]) == {"date", "label", "category", "amount", "pending", "owner"}
    blob = str(rows)
    assert "1234" not in blob and "secret text" not in blob and "Max Garage" not in blob


def test_recent_household_view_has_shared_bookings_only() -> None:
    rows = _recent("household", None, include_recent=True)["recent"]
    assert {r["label"] for r in rows} == {"Pending Market", "Shared Market"}
    assert all(r["owner"] == "shared" for r in rows)


def test_recent_window_is_fourteen_days() -> None:
    old = _tx("a3", -5.0, "food", 1, "Old Shop")  # 14 days before the 15th -> still in, day 0 -> out
    older = _tx("a3", -5.0, "food", 1, "Older Shop", month=3)
    rows = build_home(
        accounts=ACCOUNTS, transactions=[old, older], plan=BudgetPlan(), pots=POTS, recurring=[],
        banks=[], as_of=NOW, now=NOW, person=None, view="household", horizon="cycle",
        include_recent=True,
    )["recent"]
    assert [r["label"] for r in rows] == ["Old Shop"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("is_admin", "expect"), [(True, True), (False, False)])
async def test_home_view_serves_recent_rows_to_admins_only(is_admin, expect) -> None:
    from custom_components.finance_dashboard.api import FinanceDashboardHomeView

    mgr = _manager()
    view = FinanceDashboardHomeView()
    view.json = _Json().json
    user = SimpleNamespace(id="u-anna", name="a", is_admin=is_admin)
    with patch("custom_components.finance_dashboard.api.home._get_manager", return_value=mgr):
        resp = await view.get(_request(user, {"horizon": "cycle", "view": "person"}))
    assert resp._status == 200 and ("recent" in resp._data) is expect


