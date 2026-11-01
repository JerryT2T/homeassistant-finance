"""Confidence score of detected series (#129)."""

from __future__ import annotations

from datetime import date

from custom_components.finance_dashboard.recurring import add_months, detect_series
from custom_components.finance_dashboard.series_confidence import (
    CANDIDATE_BELOW,
    _day_spread,
    score_series,
)

TODAY = date(2026, 6, 15)


def _rows(amounts, text="", start=date(2026, 1, 10), name="Shop"):
    return [
        (
            add_months(start, i),
            a,
            {"remittanceInformationUnstructured": text, "creditorName": name},
        )
        for i, a in enumerate(amounts)
    ]


def test_card_purchases_at_a_cafe_are_a_candidate():
    conf = score_series(_rows([-12.4, -13.1, -11.8], "VISA Debitkarte Cafe"), "monthly", "food")
    assert conf["score"] < CANDIDATE_BELOW
    assert {"card_payment", "varying_amount", "everyday_category"} <= set(conf["reasons"])


def test_card_paid_streaming_with_a_stable_price_stays_a_contract():
    conf = score_series(_rows([-12.99] * 3, "VISA Streamflix"), "monthly", "other")
    assert conf["score"] >= CANDIDATE_BELOW


def test_direct_debit_with_contract_reference_is_sure():
    conf = score_series(
        _rows([-85.0] * 4, "SEPA Lastschrift Abschlag"), "monthly", "utilities", reference="5550123"
    )
    assert conf["score"] == 100
    assert conf["reasons"][0] == "contract_reference"


def test_two_payments_only_lower_the_score_for_monthly_but_not_yearly():
    monthly = score_series(_rows([-20.0] * 2), "monthly", "other")
    yearly = score_series(_rows([-89.0] * 2), "yearly", "other")
    assert "few_payments" in monthly["reasons"]
    assert "few_payments" not in yearly["reasons"]


def test_reasons_hold_no_amounts_or_names():
    conf = score_series(
        _rows([-12.99] * 3, "VISA Streamflix", name="Streamflix"), "monthly", "other"
    )
    assert all(r.isidentifier() for r in conf["reasons"])


def test_month_end_days_count_as_regular():
    assert _day_spread([30, 1, 31]) <= 2
    assert _day_spread([5, 20]) > 4


def test_detect_series_marks_candidates():
    txns = [
        {
            "_status": "booked",
            "bookingDate": d.isoformat(),
            "creditorName": "Cafe Bohne",
            "transactionAmount": {"amount": str(a), "currency": "EUR"},
            "category": "food",
            "remittanceInformationUnstructured": "VISA Debitkarte",
        }
        for d, a, _ in _rows([-12.4, -13.1, -11.8])
    ]
    (s,) = detect_series(txns, today=TODAY)
    assert s["candidate"] is True
    assert s["confidence"]["score"] < CANDIDATE_BELOW
