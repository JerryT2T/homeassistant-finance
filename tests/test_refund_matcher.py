"""Refund matching (#119): matcher, manual allocation, netting, store. Invented figures."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from custom_components.finance_dashboard.household_summary import build_household_summary
from custom_components.finance_dashboard.refund_matcher import (
    analyse,
    cited_dates,
    match_refunds,
    net_refunds,
    open_claims,
    split_manual,
)
from custom_components.finance_dashboard.refund_store import RefundError, RefundStore
from tests.fakes import FakeStore
from tests.test_household_summary import ACCOUNTS, NOW, tx

_n = 0


def row(day: date, amount: float, name: str, text: str = "", **extra) -> dict:
    global _n  # noqa: PLW0603
    _n += 1
    d = {
        "transactionId": f"r{_n:03d}",
        "_status": "booked",
        "bookingDate": day.isoformat(),
        "transactionAmount": {"amount": f"{amount:.2f}", "currency": "EUR"},
        "creditorName" if amount < 0 else "debtorName": name,
        "remittanceInformationUnstructured": text,
    }
    d.update(extra)
    return d


def test_service_date_full_and_one_to_many():
    bill = row(date(2026, 8, 4), -120, "Dr. med. Beispiel")
    pharm = row(date(2026, 8, 20), -42.30, "Rosen-Apotheke")
    bill2 = row(date(2026, 9, 19), -85.50, "Dr. med. Beispiel")
    full = row(date(2026, 8, 29), 120, "Kranken AG", "KV-LSTG. 04.08.2026")
    many = row(date(2026, 10, 10), 110.70, "Kranken AG", "KV-LSTG. 20.08.2026 19.09.2026")
    out = match_refunds([bill, pharm, bill2, full, many])
    assert out == {
        full["transactionId"]: {bill["transactionId"]: 120.0},
        many["transactionId"]: {pharm["transactionId"]: 42.3, bill2["transactionId"]: 68.4},
    }


def test_expense_refunded_in_parts_by_two_refunds():
    bill = row(date(2026, 3, 2), -200, "Zahnarzt Dr. Muster")
    a = row(date(2026, 3, 20), 120, "Debeka Krankenversicherung", "Leistung 02.03.2026")
    b = row(date(2026, 4, 10), 80, "Debeka Krankenversicherung", "Leistung 02.03.2026")
    out = match_refunds([bill, a, b])
    assert out[a["transactionId"]] == {bill["transactionId"]: 120.0}
    assert out[b["transactionId"]] == {bill["transactionId"]: 80.0}


def test_amount_without_date_is_matched_when_unique():
    bill = row(date(2026, 5, 3), -64.20, "Praxis Dr. Muster")
    other = row(date(2026, 5, 4), -15, "Apotheke am Markt")
    refund = row(date(2026, 5, 30), 64.20, "AOK Krankenkasse")
    assert match_refunds([bill, other, refund]) == {
        refund["transactionId"]: {bill["transactionId"]: 64.2}
    }


def test_subset_sum_without_dates():
    a = row(date(2026, 5, 3), -30, "Apotheke A")
    b = row(date(2026, 5, 5), -12.50, "Apotheke B")
    c = row(date(2026, 5, 6), -99, "Praxis C")
    refund = row(date(2026, 5, 30), 42.50, "Barmer Krankenkasse")
    assert match_refunds([a, b, c, refund]) == {
        refund["transactionId"]: {a["transactionId"]: 30.0, b["transactionId"]: 12.5}
    }


def test_partial_without_date_is_only_a_proposal():
    bill = row(date(2026, 5, 3), -100, "Praxis Dr. Muster")
    refund = row(date(2026, 5, 30), 60, "AOK Krankenkasse")
    result = analyse([bill, refund])
    assert result["allocations"] == {}
    assert [p["refund"] for p in result["proposals"]] == [refund["transactionId"]]
    assert result["proposals"][0]["confidence"] < 0.7


def test_two_identical_bills_are_ambiguous():
    a = row(date(2026, 5, 3), -50, "Apotheke A")
    b = row(date(2026, 5, 9), -50, "Apotheke A")
    refund = row(date(2026, 5, 30), 50, "AOK Krankenkasse")
    result = analyse([a, b, refund])
    assert result["allocations"] == {}
    assert len(result["proposals"]) == 1


def test_outside_window_and_foreign_payee_do_not_match():
    bill = row(date(2026, 1, 3), -50, "Apotheke A")
    late = row(date(2026, 5, 30), 50, "AOK Krankenkasse")
    salary = row(date(2026, 1, 20), 50, "Arbeitgeber GmbH", "Gehalt")
    assert analyse([bill, late, salary]) == {"allocations": {}, "proposals": [], "confidence": {}}


def test_label_makes_any_payee_a_claim_candidate():
    bill = row(date(2026, 5, 3), -64.20, "Schuhhaus Müller", _ledger_id="L1", _account_key="k")
    refund = row(date(2026, 5, 30), 64.20, "Kranken AG")
    assert match_refunds([bill, refund]) == {}
    out = match_refunds([bill, refund], labels={"k|L1": ["refundable"]})
    assert out == {refund["transactionId"]: {"k|L1": 64.2}}


def test_one_refund_does_not_take_what_another_already_covered():
    bill = row(date(2026, 5, 3), -50, "Apotheke A")
    r1 = row(date(2026, 5, 20), 50, "AOK Krankenkasse", "03.05.2026")
    r2 = row(date(2026, 5, 25), 50, "AOK Krankenkasse", "03.05.2026")
    out = match_refunds([bill, r1, r2])
    assert list(out) == [r1["transactionId"]]


def test_cited_dates_variants():
    assert cited_dates("KV-LSTG. 04.08.2026 und 5.9.26", date(2026, 10, 1)) == [
        date(2026, 8, 4), date(2026, 9, 5)
    ]
    assert cited_dates("Rechnung vom 12.08.", date(2026, 10, 1)) == [date(2026, 8, 12)]
    assert cited_dates("Rechnung vom 31.02.2026", date(2026, 10, 1)) == []


def test_manual_allocation_replaces_automatic_and_splits_oldest_first():
    a = row(date(2026, 5, 3), -30, "Kiosk")
    b = row(date(2026, 5, 5), -40, "Optiker Klar")
    refund = row(date(2026, 5, 30), 50, "Beihilfestelle")
    ids = [a["transactionId"], b["transactionId"]]
    out = match_refunds([a, b, refund], manual={refund["transactionId"]: ids})
    assert out[refund["transactionId"]] == {ids[0]: 30.0, ids[1]: 20.0}
    # an empty choice means "pays nothing back"
    assert match_refunds([a, b, refund], manual={refund["transactionId"]: []}) == {
        refund["transactionId"]: {}
    }


def test_split_manual_caps_at_expense():
    bill = row(date(2026, 5, 3), -30, "Kiosk")
    refund = row(date(2026, 5, 30), 100, "Beihilfestelle")
    assert split_manual(refund, [bill]) == {bill["transactionId"]: 30.0}


def test_open_claims_lists_uncovered_refundable_bookings():
    bill = row(date(2026, 5, 3), -100, "Praxis", _ledger_id="L1", _account_key="k")
    labels = {"k|L1": ["refundable"]}
    got = open_claims([bill], {"x": {"k|L1": 40.0}}, labels, today=date(2026, 6, 1))
    assert got == [{"id": "k|L1", "date": "2026-05-03", "open": 60.0, "age_days": 29}]
    assert open_claims([bill], {"x": {"k|L1": 100.0}}, labels, today=date(2026, 6, 1)) == []


def test_net_refunds_moves_the_refund_into_the_expense():
    bill = row(date(2026, 3, 3), -100, "Praxis", category="health")
    refund = row(date(2026, 4, 3), 60, "Kranken AG")
    out = net_refunds([bill, refund], {refund["transactionId"]: {bill["transactionId"]: 60.0}})
    assert [t["transactionAmount"]["amount"] for t in out] == ["-40.00"]
    assert out[0]["category"] == "health"
    # an expense that is not counted leaves the refund where it was
    out = net_refunds([refund], {refund["transactionId"]: {bill["transactionId"]: 60.0}})
    assert out == [refund]


def test_household_summary_nets_health_cost_in_the_expense_cycle():
    bill = tx("a3", -100, 10, "Praxis Dr. Muster", month=3, cat="health", tid="bill")
    refund = tx("a3", 100, 8, "Kranken AG", month=4, tid="refund")
    other = tx("a3", -20, 9, "Market", month=4, tid="m")
    plain = {"accounts": ACCOUNTS, "transactions": [bill, refund, other], "plan": None,
             "recurring": [], "now": NOW, "is_admin": True}
    before = build_household_summary(**plain, cycle="current")
    assert before["income"] == 100
    alloc = {"refund": {"bill": 100.0}}
    cur = build_household_summary(**plain, cycle="current", refund_allocations=alloc)
    prev = build_household_summary(**plain, cycle="previous", refund_allocations=alloc)
    assert cur["income"] == 0
    assert cur["expenses"] == 20
    assert prev["expenses"] == 0  # the bill is fully paid back: no health cost left


def test_store_set_clear_and_validation():
    store = RefundStore(None, store=FakeStore())
    asyncio.run(store.async_load())
    assert store.set("a|1", ["a|2", "a|2", "a|3"]) == ["a|2", "a|3"]
    asyncio.run(store.async_save())
    again = RefundStore(None, store=store._store)
    asyncio.run(again.async_load())
    assert again.manual == {"a|1": ["a|2", "a|3"]}
    again.clear("a|1")
    assert again.manual == {}
    with pytest.raises(RefundError):
        store.set("a|1", "a|2")
    with pytest.raises(RefundError):
        store.set("a|1", ["a|1"])
    with pytest.raises(RefundError):
        store.set("", [])
