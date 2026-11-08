"""Year payload, benchmark vs actual, reconciliation review, report (Wave 2).

Everything runs on the invented demo household; no network, no bank.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from custom_components.finance_dashboard import benchmark as bm
from custom_components.finance_dashboard import demo
from custom_components.finance_dashboard import review as rv
from custom_components.finance_dashboard.budget_plan import CostPosition
from custom_components.finance_dashboard.household_summary import figures, owner_fields
from custom_components.finance_dashboard.year_view import build_year, month_windows

NOW = datetime(2026, 11, 8, 12, 0).astimezone()
TODAY = NOW.date()


@pytest.fixture(scope="module")
def world():
    return demo._demo_context(NOW)  # noqa: SLF001


def _year(world, view="household", person=None, admin=True, txs=None):
    _now, _acc, _raw, counted, plan, clf = world
    return build_year(
        txs=counted if txs is None else txs, plan=plan, clf=clf,
        persons=[{"name": "Anna"}, {"name": "Max"}], today=TODAY, view=view,
        person=person, contracts=demo._DEMO_CONTRACTS, is_admin=admin,  # noqa: SLF001
    )


def test_cycles_one_per_month_no_overwrite(world):
    y = _year(world)
    assert [c["month"] for c in y["cycles"]] == list(range(1, 13))
    starts = [c["start"] for c in y["cycles"] if c["start"]]
    assert len(starts) == len(set(starts))
    cur = [c for c in y["cycles"] if c["current"]]
    assert len(cur) == 1 and not cur[0]["future"]
    assert any(c["future"] for c in y["cycles"]) is False or y["cycles"][-1]["spent"] is None
    assert all(c["budget"] and c["budget"] > 0 for c in y["cycles"])  # plan of that month


def test_balance_is_the_sum_of_the_cycle_figures(world):
    y = _year(world)
    spent = round(sum(c["spent"] for c in y["cycles"] if c["spent"] is not None), 2)
    assert y["balance"]["expenses"] == spent
    assert y["balance"]["saved"] == round(y["balance"]["income"] - y["balance"]["expenses"], 2)
    # same number the one counting rule gives for a window
    _n, _a, _r, counted, _p, clf = world
    first = month_windows(counted, 2026, [{"name": "Anna"}, {"name": "Max"}])[0][1]
    fig = figures(counted, first, clf)
    row = y["cycles"][0]
    assert row["spent"] == round(fig["expenses"], 2)


def test_prior_year_present_with_history_and_absent_without(world):
    y = _year(world)
    assert "vs_last_year" in y
    assert y["vs_last_year"]["spent_last_year"] > 0
    assert all("delta_prev" in c for c in y["categories"])
    short = [t for t in world[3] if (d := t.get("bookingDate")) and d >= "2026-02-01"]
    y2 = _year(world, txs=short)
    assert "vs_last_year" not in y2
    assert all("delta_prev" not in c for c in y2["categories"])


def test_privacy_person_and_household_scopes(world):
    h = _year(world)
    assert h["categories_scope"] == "shared"
    assert set(h["split"]["persons"]) == {"Anna", "Max"}
    assert all(isinstance(v, float) for v in h["split"]["persons"].values())
    p = _year(world, view="person", person="Anna")
    assert p["split"]["own"]["person"] == "Anna"
    assert p["categories_scope"] == "own"
    assert p["fixed_year"]["count"] == 2 or p["fixed_year"]["count"] == 1  # own contracts only
    assert all(i["name"] != "Autoversicherung" for i in p["fixed_year"]["items"])


def test_person_saved_carries_shared_part_and_budget_includes_free_money(world):
    p = _year(world, view="person", person="Anna")
    b = p["balance"]
    assert b["shared_share"] > 0
    assert b["saved"] == pytest.approx(b["income"] - b["expenses"] - b["shared_share"], abs=0.02)
    assert p["split"]["own"]["shared_share"] == b["shared_share"]
    # The bar counts every own expense, pocket money included, so the budget
    # is own planned costs plus the free money of the split -- not costs alone.
    _n, _a, _raw, _c, plan, _clf = world
    cyc = next(c for c in p["cycles"] if c["budget"] is not None)
    assert cyc["budget"] > plan.cost_total("Anna", cyc["month"], cyc["year"])


def test_outliers_admin_only_with_owner_fields(world):
    admin = _year(world)["outliers"]
    assert admin["items"] and admin["count"] == len(admin["items"])
    for item in admin["items"]:
        assert {"ledger_id", "owner", "owner_source", "owner_confidence"} <= item.keys()
    assert item["amount"] <= admin["items"][0]["amount"]
    plain = _year(world, admin=False)["outliers"]
    assert plain["items"] == [] and plain["count"] == admin["count"]


def test_owner_fields_wire_format(world):
    _n, _a, _raw, counted, _p, clf = world
    rent = next(t for t in counted if t.get("creditorName") == "Vermieter Schmidt")
    f = owner_fields(clf, rent)
    assert f["owner"] == "shared" and f["owner_source"] and f["owner_confidence"] >= 85
    anna = next(t for t in counted if t.get("creditorName") == "Kino")
    assert owner_fields(clf, anna)["owner"] == "Anna"


def test_home_year_demo_contract():
    out = demo.generate_demo_home(person="Anna", view="person", horizon="year", now=NOW, include_recent=True)
    y = out["year"]
    for key in ("cycles", "balance", "categories", "fixed_year", "split", "outliers", "benchmark_teaser", "review_hint"):
        assert key in y
    assert len(y["benchmark_teaser"]) == 3
    hh = demo.generate_demo_home(person=None, view="household", horizon="cycle", now=NOW)
    assert "settlement" in hh and "balances" in hh["settlement"]


def test_deviation_bands():
    assert bm.deviation(100, 100)[2] == "typical"
    assert bm.deviation(150, 100)[2] == "above"
    d, pos, band = bm.deviation(40, 100)
    assert band == "below" and pos == 0.0 and d == -0.6
    assert bm.deviation(1, 0) == (None, None, None)


def test_benchmark_actual_ordered_and_flags():
    out = demo.generate_demo_benchmark()
    comps = out["comparisons"]
    assert comps and out["basis"]["has_actual"]
    devs = [abs(c["deviation_pct"]) for c in comps]
    assert devs == sorted(devs, reverse=True)
    for c in comps:
        assert c["basis"] in ("actual", "plan")
        assert {"plan_value", "actual_value", "extrapolated", "months_covered", "position", "band",
                "statistic", "source", "survey_year"} <= c.keys()
    assert any(c["extrapolated"] for c in comps if c["basis"] == "actual")
    assert len(out["teaser"]) == 3


def test_review_steps_and_groups(world):
    now, accounts, raw, counted, plan, clf = world
    r = rv.build_review(raw=raw, txs=counted, accounts=accounts, plan=plan, clf=clf,
                        persons=["Anna", "Max"], series_list=[], state={}, today=TODAY)
    assert [s["id"] for s in r["steps"]] == ["acc", "links", "fixed", "owner", "cat", "check"]
    owner = next(s for s in r["steps"] if s["id"] == "owner")
    amounts = [abs(g["amount"]) for g in owner["groups"] if not g["auto"]]
    assert amounts == sorted(amounts, reverse=True)
    for g in owner["groups"]:
        assert g["auto"] == (g["confidence"] >= 85)
        assert g["bookings"] and {"owner", "owner_source", "owner_confidence", "ledger_id"} <= g["bookings"][0].keys()
    cat = next(s for s in r["steps"] if s["id"] == "cat")
    assert any(g["label"] == "Kino" for g in cat["groups"])
    assert r["threshold"]["auto_confidence"] == 85


def test_confirmed_group_is_done_at_95(world):
    now, accounts, raw, counted, plan, clf = world
    def cat_step(state):
        r = rv.build_review(raw=raw, txs=counted, accounts=accounts, plan=plan, clf=clf,
                            persons=["Anna", "Max"], series_list=[], state=state, today=TODAY)
        return next(s for s in r["steps"] if s["id"] == "cat")

    target = next(g for g in cat_step({})["groups"] if g["label"] == "Kino")
    assert not target["auto"] and target["reason"] == "no_category"
    done = next(
        g for g in cat_step({"confirmed": {target["group_id"]: "x"}})["groups"]
        if g["group_id"] == target["group_id"]
    )
    assert done["auto"] and done["confidence"] == 95


def test_final_check_criteria(world):
    now, accounts, raw, counted, plan, clf = world
    r = rv.build_review(raw=raw, txs=counted, accounts=accounts, plan=plan, clf=clf,
                        persons=["Anna", "Max"], series_list=[], state={}, today=TODAY)
    crit = {c["id"]: c for c in next(s for s in r["steps"] if s["id"] == "check")["criteria"]}
    assert set(crit) == {"accounts", "open_ownership", "transfers", "reconcile", "plan"}
    assert crit["reconcile"]["ok"] and crit["reconcile"]["difference"] == 0
    assert crit["accounts"]["ok"] and crit["transfers"]["ok"]
    # a plan position without a booking is a shortfall until it is suspended
    plan.positions.append(CostPosition(id="ghost", name="Zeitung Phantom", owner="shared", amount=20.0))
    r2 = rv.build_review(raw=raw, txs=counted, accounts=accounts, plan=plan, clf=clf,
                         persons=["Anna", "Max"], series_list=[], state={}, today=TODAY)
    plan_c = next(c for s in r2["steps"] if s["id"] == "check" for c in s["criteria"] if c["id"] == "plan")
    assert not plan_c["ok"] and plan_c["shortfalls"][0]["position_id"] == "ghost"
    plan.positions[-1].suspended = True
    r3 = rv.build_review(raw=raw, txs=counted, accounts=accounts, plan=plan, clf=clf,
                         persons=["Anna", "Max"], series_list=[], state={}, today=TODAY)
    assert next(c for s in r3["steps"] if s["id"] == "check" for c in s["criteria"] if c["id"] == "plan")["ok"]
    plan.positions.pop()


def test_suspended_roundtrip():
    p = CostPosition.from_dict({"name": "X", "owner": "shared", "suspended": True})
    assert p.suspended and p.to_dict()["suspended"] is True
    assert CostPosition.from_dict({"name": "Y"}).suspended is False


def test_hint_threshold_and_restart():
    review = {"steps": [{"id": "owner", "groups": [
        {"group_id": "merchant:a", "auto": False, "amount": -60.0},
        {"group_id": "merchant:b", "auto": False, "amount": -70.0}]}]}
    assert rv.hint(review, {}, 50000.0) == {"open_groups": 2, "open_amount": 130.0}
    assert rv.hint(review, {"seen": ["merchant:a", "merchant:b"]}, 50000.0) is None
    small = {"steps": [{"id": "owner", "groups": [{"group_id": "merchant:c", "auto": False, "amount": -10.0}]}]}
    assert rv.hint(small, {}, 50000.0) is None
    assert rv.hint(small, {}, 400.0) == {"open_groups": 1, "open_amount": 10.0}


def test_report_views_privacy_and_diff(world):
    now, accounts, raw, counted, plan, clf = world
    review = rv.build_review(raw=raw, txs=counted, accounts=accounts, plan=plan, clf=clf,
                             persons=["Anna", "Max"], series_list=[], state={}, today=TODAY)
    rep = rv.build_report(
        txs=counted, plan=plan, clf=clf, persons_cfg=[{"name": "Anna"}, {"name": "Max"}],
        person_names=["Anna", "Max"], today=TODAY, viewer_person="Anna", contracts=[],
        review=review, state={"started_snapshot": {"owners": {"Anna": 1.0}, "open_groups": 5, "open_amount": 99.0, "settle": {}}},
    )
    assert {"hh_year", "hh_cycle", "p_year", "p_cycle", "settle", "diff"} <= rep.keys()
    assert rep["p_year"]["Max"]["restricted"] and "categories" not in rep["p_year"]["Max"]
    assert "categories" in rep["p_year"]["Anna"]
    assert rep["p_cycle"]["Max"].get("positions") is None
    assert rep["hh_cycle"]["positions"]
    assert rep["diff"]["open_groups"]["before"] == 5
    assert "balances" in rep["settle"]["cycle"]


def test_demo_review_and_report_run():
    assert demo.generate_demo_review()["steps"]
    assert demo.generate_demo_report()["diff"] is not None


# --- manager: confirm / complete / composite ledger id ----------------------


def _review_manager():
    import asyncio
    from unittest.mock import MagicMock

    from custom_components.finance_dashboard.manager._ownership import OwnershipMixin
    from custom_components.finance_dashboard.manager._review import ReviewMixin
    from custom_components.finance_dashboard.merchants import MerchantMemory

    async def noop():
        return None

    class Mgr(ReviewMixin, OwnershipMixin):
        def __init__(self):
            self._memory = MerchantMemory(store=MagicMock())
            self._memory.async_save = noop
            self._demo_mode = False
            self._hass = MagicMock()
            self.persons = [{"name": "Anna"}]
            self._accounts = [{"person": "Anna", "id": "a", "key": "k"}]
            self._transactions = [
                {"_ledger_id": "L1", "_account_key": "k", "creditorName": "REWE", "category": "groceries",
                 "bookingDate": "2026-05-02", "transactionAmount": {"amount": "-20", "currency": "EUR"}, "_status": "booked"},
            ]
            self.derived = 0

        def _valid_owners(self):
            return {"Anna", "shared"}

        async def async_apply_owner_change(self):
            self.derived += 1

        async def _contracts_list(self):
            return []

        def _classifier(self):
            from custom_components.finance_dashboard.household_summary import Classifier

            return Classifier(None, [], None, [])

        budget_plan = None

    return Mgr(), asyncio


def test_confirm_writes_rule_marks_done_and_validates(monkeypatch):
    from custom_components.finance_dashboard.manager import _review
    from custom_components.finance_dashboard.manager._questions import QuestionError

    monkeypatch.setattr(_review, "_refund_allocations_of", lambda _m: {})
    mgr, aio = _review_manager()
    out = aio.run(mgr.async_review_confirm(group_id="merchant:rewe", kind="merchant", owner="shared"))
    assert out["confidence"] == 95
    mem = mgr._memory  # noqa: SLF001
    assert mem.known_merchants()["rewe"]["owner"] == "shared"
    assert "merchant:rewe" in mem.review_state()["confirmed"] and mgr.derived == 1
    with pytest.raises(QuestionError):
        aio.run(mgr.async_review_confirm(group_id="series:x", kind="merchant", owner="shared"))
    with pytest.raises(QuestionError):
        aio.run(mgr.async_review_confirm(group_id="merchant:rewe", kind="merchant", owner="Bob"))
    # the list's composite "<account_key>|<id>" works for the owner correction too
    res = aio.run(mgr.async_correct_owner(ledger_id="k|L1", owner="Anna", reach="booking"))
    assert res["ledger_id"] == "L1"


def _account_review_manager():
    from types import SimpleNamespace

    mgr, aio = _review_manager()
    mgr.persons = [{"name": "Anna", "ha_users": ["u1"]}, {"name": "Ben", "ha_users": ["u2"]}]
    accounts = [
        {"name": "Giro", "iban": "DE00TEST0000000000000001", "person": "Anna", "type": "personal",
         "household_use": True},
        {"name": "Joint", "iban": "DE00TEST0000000000000002", "type": "shared", "card_owners": {"1111": "Anna"}},
    ]
    mgr._entry = SimpleNamespace(data={"accounts": accounts})  # noqa: SLF001

    def update(entry, data):
        entry.data = data

    mgr._hass.config_entries.async_update_entry.side_effect = update  # noqa: SLF001
    mgr._accounts = accounts  # noqa: SLF001
    type(mgr)._valid_owners = lambda self: {"Anna", "Ben", "shared"}
    return mgr, aio


def test_confirm_account_group_writes_the_owner_set(monkeypatch):
    """Picking an owner in the review's account step changes the account, not only a checkmark."""
    from custom_components.finance_dashboard import review as rv
    from custom_components.finance_dashboard.account_identity import account_key
    from custom_components.finance_dashboard.manager import _review
    from custom_components.finance_dashboard.ownership import account_kind

    monkeypatch.setattr(_review, "_refund_allocations_of", lambda _m: {})
    mgr, aio = _account_review_manager()
    giro, joint = (account_key(a) for a in mgr._accounts)  # noqa: SLF001

    aio.run(mgr.async_review_confirm(group_id=f"{rv.KIND_ACCOUNT}:{giro}", kind=rv.KIND_ACCOUNT, owner="Ben"))
    acc = next(a for a in mgr._accounts if account_key(a) == giro)  # noqa: SLF001
    assert acc["person"] == "Ben" and acc["household_use"] is True and acc["ha_users"] == ["u2"]
    assert mgr.derived == 1  # stored bookings re-derived, no bank call

    # the household as the views spell it ("__shared__") is accepted
    aio.run(mgr.async_review_confirm(group_id=f"{rv.KIND_ACCOUNT}:{giro}", kind=rv.KIND_ACCOUNT, owner="__shared__"))
    acc = next(a for a in mgr._accounts if account_key(a) == giro)  # noqa: SLF001
    assert account_kind(acc) == "household"

    # a joint account handed to a person loses its card mapping
    aio.run(mgr.async_review_confirm(group_id=f"{rv.KIND_ACCOUNT}:{joint}", kind=rv.KIND_ACCOUNT, owner="Anna"))
    acc = next(a for a in mgr._accounts if account_key(a) == joint)  # noqa: SLF001
    assert acc["person"] == "Anna" and "card_owners" not in acc
    assert mgr._entry.data["accounts"] == mgr._accounts  # noqa: SLF001


def test_confirm_link_info_group_cannot_be_answered_no(monkeypatch):
    from custom_components.finance_dashboard.manager import _review
    from custom_components.finance_dashboard.manager._questions import QuestionError

    monkeypatch.setattr(_review, "_refund_allocations_of", lambda _m: {})
    mgr, aio = _review_manager()
    with pytest.raises(QuestionError):
        aio.run(mgr.async_review_confirm(group_id="link:refunds", kind="link", confirmed=False))
    out = aio.run(mgr.async_review_confirm(group_id="link:refunds", kind="link", confirmed=True))
    assert out["group_id"] == "link:refunds"
    assert "link:refunds" in mgr._memory.review_state()["confirmed"]  # noqa: SLF001
