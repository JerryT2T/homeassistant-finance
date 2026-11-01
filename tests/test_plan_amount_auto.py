"""Smarter plan amount and pauses (#114)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from custom_components.finance_dashboard.recurring import detect_series, plan_amount
from tests.test_contracts import TODAY, monthly, txn


@pytest.mark.parametrize(
    ("amounts", "expected"),
    [
        ([150, 150, 300, 150, 150], 150),  # doubled instalment: median
        ([10, 10, 10, 12, 12], 12),  # step confirmed by two payments
        ([13.99, 13.99, 17.99], 17.99),  # one new price after a steady one
        ([10, 10, 10, 20], 10),  # a single double charge at the end: catch-up
        ([10, 10, 12, 10], 10),  # one odd payment in between
        ([10, 12, 20, 14], 13),  # noise: median
        ([9.99], 9.99),
    ],
)
def test_auto_mode(amounts, expected):
    assert plan_amount([-a for a in amounts]) == expected


def test_explicit_modes_are_kept():
    amounts = [-150, -150, -300, -150]
    assert plan_amount(amounts, "highest") == 300
    assert plan_amount(amounts, "last") == 150


def test_quarterly_with_one_doubled_instalment_is_a_series():
    rows = []
    day = date(2024, 3, 15)
    for i in range(8):
        rows.append(txn(day.isoformat(), -300.0 if i == 3 else -150.0, "Hausrat"))
        month = day.month + 3
        day = day.replace(year=day.year + (month - 1) // 12, month=(month - 1) % 12 + 1)
    (s,) = detect_series(rows, today=date(2026, 3, 20))
    assert s["interval"] == "quarterly"
    assert s["plan_amount"] == -150.0
    assert s["annual_cost"] == 600.0


def _weekly(skips, weeks=12):
    start = date(2026, 3, 6)
    return [
        txn((start + timedelta(weeks=i)).isoformat(), -59.9, "Kochkiste")
        for i in range(weeks)
        if i not in skips
    ]


def test_weekly_with_skipped_weeks_projects_the_full_rhythm():
    (s,) = detect_series(_weekly({3, 7}), today=date(2026, 5, 30))
    assert s["interval"] == "weekly"
    assert s["pauses"] == 2
    assert s["pause_pattern"] is False
    assert s["annual_cost"] == round(59.9 * 52, 2)


def test_three_recent_pauses_make_a_pattern():
    (s,) = detect_series(_weekly({2, 5, 9}, weeks=14), today=date(2026, 6, 10))
    assert s["pauses_recent"] >= 3
    assert s["pause_pattern"] is True


def test_too_many_gaps_are_no_series():
    # every other week: the median gap is two weeks, not a paused weekly rhythm
    rows = _weekly({1, 3, 5, 7, 9, 11})
    assert all(s["interval"] != "weekly" for s in detect_series(rows, today=date(2026, 5, 30)))


def test_monthly_skip_counts_as_a_pause():
    rows = [r for i, r in enumerate(monthly([-20.0] * 7)) if i != 3]
    (s,) = detect_series(rows, today=TODAY)
    assert s["interval"] == "monthly"
    assert s["pauses"] == 1


def test_quarterly_gaps_stay_strict():
    days = ("2025-01-10", "2025-04-10", "2025-10-10", "2026-01-10")
    rows = [txn(d, -99.0, "Versicherung") for d in days]
    assert all(s["interval"] != "quarterly" for s in detect_series(rows, today=TODAY))
