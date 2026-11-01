"""Household summary: transfers excluded, savings rate honesty, owners, privacy. Invented figures."""

from __future__ import annotations

from datetime import datetime

from custom_components.finance_dashboard.budget_plan import BudgetPlan, CostPosition
from custom_components.finance_dashboard.household_summary import (
    build_household_summary,
    counted_transactions,
)

NOW = datetime(2026, 4, 15, 12, 0)

ACCOUNTS = [
    {"id": "a1", "type": "personal", "person": "Anna", "name": "Anna Giro", "institution": "DKB"},
    {"id": "a2", "type": "personal", "person": "Max", "name": "Max Giro", "institution": "DKB"},
    {"id": "a3", "type": "shared", "person": "", "name": "Joint", "institution": "DKB"},
]
OWNER = {"a1": ("personal", "Anna"), "a2": ("personal", "Max"), "a3": ("shared", "")}


def tx(acc, amount, day, name="Shop", month=4, cat="other", tid=None, **extra):
    t, p = OWNER[acc]
    d = {
        "transactionId": tid or f"{acc}-{month}-{day}-{amount}",
        "bookingDate": f"2026-{month:02d}-{day:02d}",
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "creditorName": name,
        "category": cat,
        "_account_id": acc,
        "_account_type": t,
        "_account_person": p,
        "_status": "booked",
    }
    d.update(extra)
    return d


def build(txs, *, person=None, admin=True, cycle="current", plan=None, recurring=None, accounts=ACCOUNTS):
    return build_household_summary(
        accounts=accounts, transactions=txs, plan=plan, recurring=recurring or [], now=NOW,
        cycle=cycle, viewer_person=person, is_admin=admin,
    )


def test_transfers_excluded_and_savings_rate_null_without_income():
    txs = [
        # own transfer pair: both legs dropped
        tx("a1", -500, 3, "Anna Savings", cat="transfers", _transfer_chain_id="c1", _transfer_role="source"),
        tx("a3", 500, 3, "Anna", _transfer_chain_id="c1", _transfer_role="destination"),
        # transfer-categorised line without chain
        tx("a1", 200, 4, "Own", cat="transfers"),
        tx("a3", -80, 5, "Market", cat="food"),
    ]
    out = build(txs)
    assert out["income"] == 0
    assert out["expenses"] == 80
    assert out["savings_rate"] is None
    assert out["cycle"]["rule"] == "calendar_fallback"
    assert out["cycle"]["label"] == "Zyklus"


def test_chain_with_intermediate_counts_source_once():
    txs = [
        tx("a3", -39.9, 5, "HelloFresh", _transfer_chain_id="c", _transfer_role="source"),
        tx("a1", -39.9, 5, "PayPal", _transfer_chain_id="c", _transfer_role="intermediate"),
        tx("a2", 39.9, 5, "x", _transfer_chain_id="c", _transfer_role="destination"),
    ]
    assert build(txs)["expenses"] == 39.9


def test_rejected_chain_counts_as_normal():
    txs = [
        tx("a3", -10, 5, _transfer_chain_id="c", _transfer_role="source", _transfer_confirmed=False),
        tx("a1", 10, 5, "Gift", _transfer_chain_id="c", _transfer_role="destination", _transfer_confirmed=False),
    ]
    out = build(txs)
    assert out["expenses"] == 10 and out["income"] == 10


PP_ACCOUNTS = [
    *ACCOUNTS,
    {"id": "pp", "type": "personal", "person": "Anna", "name": "PayPal", "institution": "PayPal"},
]


def _pp_line(amount, day, **dates):
    """A PayPal-side line: no booking date unless given (#107)."""
    line = {
        "transactionId": f"pp-{day}-{amount}",
        "bookingDate": "",
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "creditorName": "Streamly",
        "category": "other",
        "_account_id": "pp",
        "_account_type": "personal",
        "_account_person": "Anna",
        "_status": "booked",
    }
    line.update(dates)
    return line


def test_paypal_funding_debit_counts_without_a_paypal_line():
    txs = [tx("a1", -40, 5, "PayPal (Europe) S.a.r.l.")]
    assert counted_transactions(txs, ACCOUNTS) == txs
    assert counted_transactions(txs, PP_ACCOUNTS) == txs


def test_paypal_funding_debit_dropped_when_a_dated_paypal_line_counts_it():
    debit = tx("a1", -40, 5, "PayPal (Europe) S.a.r.l.")
    line = _pp_line(-40, 4, transactionDate="2026-04-04")
    assert counted_transactions([debit, line], PP_ACCOUNTS) == [line]


def test_undated_paypal_line_leaves_the_bank_debit_counting():
    debit = tx("a1", -40, 5, "PayPal (Europe) S.a.r.l.")
    line = _pp_line(-40, 4)
    assert counted_transactions([debit, line], PP_ACCOUNTS) == [debit]


def test_one_paypal_line_mirrors_one_debit_only():
    first = tx("a1", -40, 5, "PayPal (Europe) S.a.r.l.")
    second = tx("a1", -40, 6, "PayPal (Europe) S.a.r.l.")
    line = _pp_line(-40, 5, transactionDate="2026-04-05")
    out = counted_transactions([first, second, line], PP_ACCOUNTS)
    assert len(out) == 2 and line in out


def test_paypal_line_too_far_away_is_no_mirror():
    debit = tx("a1", -40, 20, "PayPal (Europe) S.a.r.l.")
    line = _pp_line(-40, 4, transactionDate="2026-04-04")
    assert len(counted_transactions([debit, line], PP_ACCOUNTS)) == 2


def test_refund_netted_not_income():
    txs = [
        tx("a3", -50, 5, "Zalando", cat="shopping", _refund_role="original"),
        tx("a3", 50, 9, "Zalando", cat="shopping", _refund_role="refund"),
        tx("a3", -20, 10, "Market"),
    ]
    out = build(txs)
    assert out["income"] == 0
    assert out["expenses"] == 20


def test_cycle_from_salary_income_pending_and_previous_comparison():
    txs = [
        tx("a1", 3000, 27, "Employer", month=2),
        tx("a1", 3000, 30, "Employer", month=3),
        tx("a3", -100, 5, "Market", month=3),
        tx("a3", -70, 5, "Market", month=4),
    ]
    recurring = [
        {"creditor": "employer", "average_amount": 3000.0, "expected_day": 30, "last_seen": "2026-03-30"},
    ]
    out = build(txs, recurring=recurring)
    # Cycle opened with the March salary; April salary still due.
    assert out["cycle"]["start"] == "2026-03-30"
    assert out["income"] == 3000
    assert out["income_pending"] is False  # next salary opens the next cycle, not this one
    prev = build(txs, cycle="previous", recurring=recurring)
    assert prev["cycle"]["selected"] == "previous"
    assert prev["cycle"]["end"] == "2026-03-29"


def test_income_pending_when_salary_not_yet_in_calendar_cycle():
    txs = [tx("a3", -70, 5, "Market")]
    recurring = [{"creditor": "employer", "average_amount": 5750.0, "expected_day": 30, "last_seen": "2026-03-30"}]
    out = build(txs, recurring=recurring)
    assert out["savings_rate"] is None
    assert out["income_pending"] is True
    assert out["expected_income_date"] == "2026-04-30"


def test_fixed_variable_and_owner_resolution_with_plan_and_correction():
    plan = BudgetPlan(
        persons=["Anna", "Max"],
        positions=[CostPosition(id="n", name="Netflix Abo", owner="shared", amount=15.0)],
    )
    txs = [
        tx("a1", -15, 3, "NETFLIX.COM", tid="t1"),  # plan: personal account, shared position
        tx("a1", -30, 4, "Kiosk", tid="t2"),  # default: Anna
        tx("a2", -12, 6, "Rent Co", tid="t3"),  # recurring -> fixed
        tx("a2", -9, 7, "Gift", tid="t4"),
    ]
    recurring = [{"creditor": "rent co", "average_amount": -12.0, "expected_day": 6}]
    out = build_household_summary(
        accounts=ACCOUNTS, transactions=txs, plan=plan, recurring=recurring, now=NOW,
        is_admin=True, corrections={"t4": "shared"},
    )
    by = {o["owner"]: o for o in out["owners"]}
    assert by["shared"]["expenses"] == 24  # netflix by plan + gift by correction
    assert by["shared"]["fixed"] == 15
    assert by["Anna"]["expenses"] == 30 and by["Anna"]["variable"] == 30
    assert by["Max"]["fixed"] == 12
    assert out["fixed"] == 27 and out["variable"] == 39


def test_privacy_other_persons_as_totals_only():
    txs = [
        tx("a1", -60, 4, "Secret Hobby Shop", cat="leisure"),
        tx("a2", -45, 5, "Max Garage", cat="transport"),
        tx("a3", -10, 6, "Market", cat="food"),
    ]
    out = build(txs, person="Anna", admin=False)
    by = {o["owner"]: o for o in out["owners"]}
    assert out["privacy"] == "restricted"
    assert by["Max"]["restricted"] is True
    assert "categories" not in by["Max"] and "fixed" not in by["Max"]
    assert by["Max"]["expenses"] == 45
    assert by["Anna"]["categories"][0]["category"] == "leisure"
    assert "Garage" not in repr(out) and "Secret Hobby" not in repr(out)
    # non-admin without person mapping: every person restricted
    anon = build(txs, person=None, admin=False)
    assert all(o["restricted"] for o in anon["owners"] if o["kind"] == "person")
    # admin sees all
    full = build(txs)
    assert full["privacy"] == "full" and not any(o["restricted"] for o in full["owners"])


def test_owner_kinds_follow_the_contract():
    """kind is person|shared|open — the frontend sums the household share by "shared"."""
    txs = [tx("a1", -60, 4, "Shop"), tx("a3", -10, 6, "Market", cat="food")]
    kinds = {o["kind"] for o in build(txs)["owners"]}
    assert kinds <= {"person", "shared", "open"} and "shared" in kinds
