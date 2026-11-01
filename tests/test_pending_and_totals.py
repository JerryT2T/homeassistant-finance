"""Pending debits as proof of life and totals per kind (#115)."""

from __future__ import annotations

from datetime import date

from custom_components.finance_dashboard.contracts import build_contracts, contract_totals
from custom_components.finance_dashboard.household_summary import pending_debits
from custom_components.finance_dashboard.recurring import detect_series
from tests.test_contracts import TODAY, blank_store, monthly, txn


def _gym(pending_day="2026-06-10", amount=-45.0, start=date(2026, 1, 10), n=5):
    rows = monthly([-45.0] * n, name="Fitnessclub", start=start)
    return [*rows, txn(pending_day, amount, "Fitnessclub", _status="pending")]


def test_pending_debit_moves_last_seen_and_keeps_status_active():
    (s,) = detect_series(_gym(), today=date(2026, 7, 12))
    assert s["last_seen"] == "2026-06-10"
    assert s["pending_since"] == "2026-06-10"
    assert s["next_expected"] == "2026-07-10"
    assert s["status"] == "active"
    assert s["occurrences"] == 5
    assert s["amounts"][-1] == -45.0


def test_without_the_pending_debit_the_payment_is_missing():
    rows = [t for t in _gym() if t["_status"] == "booked"]
    (s,) = detect_series(rows, today=date(2026, 7, 12))
    assert s["status"] == "missing"
    assert s["pending_since"] is None


def test_pending_purchase_at_another_amount_is_no_proof():
    (s,) = detect_series(_gym(amount=-12.0), today=date(2026, 7, 12))
    assert s["pending_since"] is None


def test_pending_debit_on_the_last_payment_day_is_no_new_payment():
    (s,) = detect_series(_gym(pending_day="2026-05-11"), today=date(2026, 6, 12))
    assert s["last_seen"] == "2026-05-10"


def test_pending_alone_never_forms_a_series():
    rows = [txn(f"2026-0{m}-10", -45.0, "Fitnessclub", _status="pending") for m in range(1, 6)]
    assert detect_series(rows, today=TODAY) == []


def test_pending_debits_keeps_only_pending_expenses():
    txns = [
        txn("2026-06-10", -45.0, "A", _status="pending"),
        txn("2026-06-10", 45.0, "B", _status="pending"),
        txn("2026-06-10", -45.0, "C"),
    ]
    assert [t["creditorName"] for t in pending_debits(txns)] == ["A"]


def _with_text(rows, text, category="other"):
    for r in rows:
        r["remittanceInformationUnstructured"] = text
        r["category"] = category
    return rows


def test_totals_split_fixed_and_regular_spending():
    rent = _with_text(monthly([-900.0] * 5, name="Hausverwaltung"), "Miete")
    stream = _with_text(monthly([-12.0] * 5, name="Streamflix"), "Abo")
    food = _with_text(monthly([-60.0] * 5, name="Kochkiste"), "Box", "food")
    contracts = build_contracts(rent + stream + food, blank_store(), today=TODAY)
    totals = contract_totals(contracts)
    assert totals["fixed"] == {"monthly": 912.0, "yearly": 10944.0, "count": 2}
    assert totals["regular"] == {"monthly": 60.0, "yearly": 720.0, "count": 1}


def test_candidates_and_ended_series_stay_out_of_the_totals():
    items = [
        {"kind": "contract", "annual_cost": 120.0, "status": "active"},
        {"kind": "contract", "annual_cost": 999.0, "status": "active", "candidate": True},
        {"kind": "subscription", "annual_cost": 999.0, "status": "ended"},
    ]
    assert contract_totals(items)["fixed"] == {"monthly": 10.0, "yearly": 120.0, "count": 1}


def test_stale_pending_debit_far_later_is_no_proof():
    # Codex #115: a pending debit three periods on must not keep the series alive
    (s,) = detect_series(_gym(pending_day="2026-08-10"), today=date(2026, 8, 12))
    assert s["pending_since"] is None
    assert s["last_seen"] == "2026-05-10"
