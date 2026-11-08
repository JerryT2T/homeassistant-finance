"""Honest household numbers per income cycle (``GET .../household_summary``).

Pure assembly from cached data - no I/O, no clock, never a bank call.

What is counted (and what is not):

- What counts is decided by :mod:`counted` for every view alike: own-account
  transfers, PayPal mirrors and pending lines do not. Refunds are netted into
  the expense they belong to and are no income.
- A credit in a spending category (a shop's or utility's credit) reduces that
  category's expenses.

Ownership of an expense resolves in the fixed chain: the account's owner is the
default, a matched plan position overrides it, a user correction overrides
both (:mod:`plan_match`). Fixed = the booking belongs to a recurring series or a plan position of
kind ``fixed``; everything else is variable.

Sign convention: every figure in this payload is a positive magnitude
(expenses positive, ``surplus = income - expenses``).

Privacy: the payload only carries aggregates, never booking lists. For a
non-admin viewer (or the person view) other persons' personal accounts appear
as totals only (``restricted: true``) and their categories are left out.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from .budget_plan import BudgetPlan
from .const import OWNER_SHARED, POSITION_KIND_FIXED
from .counted import (
    amount_of,
    counted_transactions,
    income_payer,
    is_income_line,
    is_salary_candidate,
    net_counted,
    paypal_account_ids,
)
from .cycle import calendar_cycle, household_cycle, household_starts
from .ownership import resolve_owner_detail
from .plan_match import best_position
from .tx_dates import effective_day

CYCLES = ("current", "previous")
MONTH_ANCHOR_DAY = 15
OWNER_OPEN = "open"
__all__ = ["counted_transactions", "paypal_account_ids"]  # the shared rule, re-exported


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_amount = amount_of


def _day(tx: dict[str, Any]) -> date | None:
    return effective_day(tx)


def _name(tx: dict[str, Any]) -> str:
    return " ".join(str(tx.get("creditorName") or tx.get("debtorName") or "").lower().split())


def owner_of(tx: dict[str, Any]) -> str:
    """Account default owner: person, ``shared`` or ``open`` (unassigned)."""
    if tx.get("_account_type") == "shared":
        return OWNER_SHARED
    return str(tx.get("_account_person") or "") or OWNER_OPEN


def pending_debits(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pending expenses: proof of life for contract series, never amounts (#115)."""
    out = []
    for t in transactions:
        if t.get("_status") != "pending":
            continue
        try:
            if float((t.get("transactionAmount") or {}).get("amount", 0)) < 0:
                out.append(t)
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# cycle windows
# ---------------------------------------------------------------------------


def _prev_month_window(start: date) -> tuple[date, date]:
    return calendar_cycle(start - timedelta(days=1))


def person_incomes(transactions: list[dict[str, Any]]) -> dict[str, list[tuple]]:
    """Per person the credits that may open a cycle: ``(day, amount, payer)``."""
    by_person: dict[str, list[tuple]] = defaultdict(list)
    for tx in transactions:
        day = _day(tx)
        if (
            day
            and tx.get("_status", "booked") == "booked"
            and is_salary_candidate(tx)
            and owner_of(tx) not in (OWNER_SHARED, OWNER_OPEN)
        ):
            by_person[owner_of(tx)].append((day, _amount(tx), income_payer(tx)))
    return dict(by_person)


def _payday_windows(
    persons: list[dict[str, Any]] | None, today: date
) -> list[tuple[date, date]] | None:
    """Current and earlier cycles from a payday confirmed in the setup wizard."""
    from .setup_wizard import payday_cycle, person_payday

    days = [d for p in persons or [] if (d := person_payday(p))]
    if not days:
        return None
    cur = payday_cycle(min(days), today)
    prev = payday_cycle(min(days), cur[0] - timedelta(days=1))
    return [cur, prev, payday_cycle(min(days), prev[0] - timedelta(days=1))]


def cycle_windows(
    transactions: list[dict[str, Any]],
    today: date,
    persons: list[dict[str, Any]] | None = None,
) -> tuple[list[tuple[date, date] | None], str, str | None]:
    """``([current, previous, before], rule, anchor)`` windows (None = unknown).

    ``today`` selects the cycle: any day inside it. ``transactions`` are the
    counted ones, so every view derives the same windows.
    """
    by_person = person_incomes(transactions)
    starts = [s for s, _ in household_starts(by_person)]
    ordered = sorted(starts)
    if not starts or today < ordered[0]:  # before the first known salary, too
        confirmed = _payday_windows(persons, today) if not starts else None
        if confirmed:
            return list(confirmed), "payday_confirmed", None
        cur = calendar_cycle(today)
        prev = _prev_month_window(cur[0])
        return [cur, prev, _prev_month_window(prev[0])], "calendar_fallback", None
    start, end, anchor = household_cycle(by_person, today)
    idx = ordered.index(start)
    windows: list[tuple[date, date] | None] = [(start, end)]
    for back in (1, 2):
        i = idx - back
        windows.append((ordered[i], ordered[i + 1] - timedelta(days=1)) if i >= 0 else None)
    return windows, "household_7_day", anchor


def window_of_month(
    transactions: list[dict[str, Any]],
    month: int,
    year: int,
    persons: list[dict[str, Any]] | None = None,
) -> tuple[list[tuple[date, date] | None], str, str | None]:
    """The cycle a month name stands for: the one holding the 15th.

    A salary on the 29th opens "next month's" cycle, one on the 1st its own, so
    a month selection means the same period as the panel in both cases.
    """
    return cycle_windows(transactions, date(year, month, MONTH_ANCHOR_DAY), persons)


def month_of_window(window: tuple[date, date]) -> tuple[int, int]:
    """``(month, year)`` a cycle goes by: the first 15th inside it, else its middle."""
    start, end = window
    anchor = start.replace(day=MONTH_ANCHOR_DAY)
    if anchor < start:
        anchor = (start.replace(day=1) + timedelta(days=32)).replace(day=MONTH_ANCHOR_DAY)
    if anchor > end:
        anchor = start + (end - start) / 2
    return anchor.month, anchor.year


# ---------------------------------------------------------------------------
# classification + figures
# ---------------------------------------------------------------------------


class Classifier:
    """Owner + fixed/variable for expenses."""

    def __init__(
        self,
        plan: BudgetPlan | None,
        recurring: list[dict[str, Any]] | None,
        corrections: dict[str, str] | None = None,
        persons: list[str] | None = None,
    ) -> None:
        self.plan = plan
        self.corrections = corrections or {}
        self.persons = persons
        self.recurring_names = {
            " ".join(str(p.get("creditor") or "").lower().split())
            for p in recurring or []
            if float(p.get("average_amount", 0) or 0) < 0
        } - {""}

    def classify_detail(self, tx: dict[str, Any], on: date) -> tuple[str, bool, str, int]:
        """``(owner, is_fixed, source, confidence)`` -- the one chain, see ``ownership``."""
        pos = None
        if self.plan is not None:
            pos = best_position(tx, self.plan.active_positions(on.month, on.year), self.persons)
        fixed = _name(tx) in self.recurring_names or (
            pos is not None and pos.kind == POSITION_KIND_FIXED
        )
        correction = self.corrections.get(str(tx.get("transactionId") or ""))
        owner, source, confidence = resolve_owner_detail(tx, pos, correction)
        return owner, fixed, source, confidence

    def classify(self, tx: dict[str, Any], on: date) -> tuple[str, bool]:
        """``(owner, is_fixed)``: correction -> rule -> plan match -> account default."""
        owner, fixed, _source, _conf = self.classify_detail(tx, on)
        return owner, fixed


def plan_persons(plan: BudgetPlan | None, accounts: list[dict[str, Any]] | None) -> list[str]:
    """Names a position may be named after without being about that person."""
    names = {str(a.get("person") or "") for a in accounts or []}
    names |= {str(n) for n in (plan.persons if plan is not None else [])}
    return sorted(names - {""})


def figures(
    txs: list[dict[str, Any]], window: tuple[date, date], clf: Classifier
) -> dict[str, Any]:
    """Income, expenses, fixed costs and per-owner / per-category splits of a period.

    ``txs`` are counted and netted (:mod:`counted`). The one place these totals
    are computed, for the household summary and the monthly summary alike.
    """
    start, end = window
    income = expenses = fixed = 0.0
    owners: dict[str, dict[str, float]] = defaultdict(
        lambda: {"income": 0.0, "expenses": 0.0, "fixed": 0.0, "variable": 0.0}
    )
    cats: dict[tuple[str, str], float] = defaultdict(float)
    income_cats: dict[str, float] = defaultdict(float)
    income_names: set[str] = set()
    for tx in txs:
        day = _day(tx)
        if day is None or not start <= day <= end:
            continue
        amount = _amount(tx)
        if is_income_line(tx):
            income += amount
            owners[owner_of(tx)]["income"] += amount
            income_names.add(_name(tx))
            income_cats[str(tx.get("category") or "other")] += amount
            continue
        owner, is_fixed = clf.classify(tx, day)
        spent = -amount  # a credit comes out negative -> netted against expenses
        expenses += spent
        owners[owner]["expenses"] += spent
        owners[owner]["fixed" if is_fixed else "variable"] += spent
        if is_fixed:
            fixed += spent
        cats[(owner, str(tx.get("category") or "other"))] += spent
    return {
        "income": income,
        "expenses": expenses,
        "fixed": fixed,
        "variable": expenses - fixed,
        "owners": owners,
        "categories": cats,
        "income_categories": income_cats,
        "income_names": income_names,
    }


def _r(value: float) -> float:
    return round(value, 2)


def _rate(income: float, expenses: float) -> float | None:
    return round((income - expenses) / income, 4) if income > 0 else None


def _line(cur: float | None, prev: float | None, digits: int = 2) -> dict[str, Any]:
    return {
        "current": None if cur is None else round(cur, digits),
        "previous": None if prev is None else round(prev, digits),
        "delta": None if cur is None or prev is None else round(cur - prev, digits),
    }


def _income_pending(
    recurring: list[dict[str, Any]] | None, seen: set[str], start: date, end: date, today: date
) -> str | None:
    """Earliest date a known recurring income is still expected in the cycle."""
    best: date | None = None
    for p in recurring or []:
        try:
            if float(p.get("average_amount", 0) or 0) <= 0:
                continue
            dom = int(p.get("expected_day", 0))
        except (TypeError, ValueError):
            continue
        name = " ".join(str(p.get("creditor") or "").lower().split())
        if name in seen or not 1 <= dom <= 31:
            continue
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            last = calendar.monthrange(cursor.year, cursor.month)[1]
            due = cursor.replace(day=min(dom, last))
            if start <= due <= end and due >= today and (best is None or due < best):
                best = due
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return best.isoformat() if best else None


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------


def build_household_summary(  # noqa: PLR0914
    *,
    accounts: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    plan: BudgetPlan | None,
    recurring: list[dict[str, Any]] | None,
    now: datetime,
    cycle: str = "current",
    viewer_person: str | None = None,
    is_admin: bool = False,
    corrections: dict[str, str] | None = None,
    refund_allocations: dict[str, dict[str, float]] | None = None,
    as_of: datetime | None = None,
    persons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the ``household_summary`` contract (docs/dev/contracts/household-summary.md)."""
    today = now.date()
    if cycle not in CYCLES:
        cycle = "current"
    txs = net_counted(counted_transactions(transactions, accounts), refund_allocations)
    windows, rule, anchor = cycle_windows(txs, today, persons)
    clf = Classifier(plan, recurring, corrections, plan_persons(plan, accounts))

    sel = 0 if cycle == "current" else 1
    window = windows[sel]
    comp_window = windows[sel + 1] if sel + 1 < len(windows) else None
    if window is None:  # defensive: previous cycle unknown
        window = windows[0]
    start, end = window  # type: ignore[misc]
    cur = figures(txs, window, clf)  # type: ignore[arg-type]
    prev = figures(txs, comp_window, clf) if comp_window else None

    days = (end - start).days + 1
    day = min(days, max(1, (today - start).days + 1)) if cycle == "current" else days

    pending = (
        _income_pending(recurring, cur["income_names"], start, end, today)
        if cycle == "current"
        else None
    )
    cur_rate = _rate(cur["income"], cur["expenses"])
    prev_rate = _rate(prev["income"], prev["expenses"]) if prev else None

    def pv(key: str) -> float | None:
        return prev[key] if prev else None

    lines = {
        "income": _line(cur["income"], pv("income")),
        "expenses": _line(cur["expenses"], pv("expenses")),
        "fixed": _line(cur["fixed"], pv("fixed")),
        "variable": _line(cur["variable"], pv("variable")),
        "surplus": _line(
            cur["income"] - cur["expenses"],
            prev["income"] - prev["expenses"] if prev else None,
        ),
        "savings_rate": _line(cur_rate, prev_rate, 4),
    }

    full_view = is_admin and viewer_person is None
    names = sorted(set(cur["owners"]) | (set(prev["owners"]) if prev else set()))
    owners = []
    for owner in names:
        c = cur["owners"].get(owner, {})
        p = prev["owners"].get(owner, {}) if prev else {}
        is_person = owner not in (OWNER_SHARED, OWNER_OPEN)
        visible = full_view or not is_person or owner == viewer_person
        inc, exp = c.get("income", 0.0), c.get("expenses", 0.0)
        row: dict[str, Any] = {
            "owner": owner,
            "kind": "person" if is_person else ("shared" if owner == OWNER_SHARED else "open"),
            "restricted": not visible,
            "income": _r(inc),
            "expenses": _r(exp),
            "surplus": _r(inc - exp),
            "previous_expenses": _r(p.get("expenses", 0.0)) if prev else None,
        }
        if visible:
            row["fixed"] = _r(c.get("fixed", 0.0))
            row["variable"] = _r(c.get("variable", 0.0))
            row["categories"] = sorted(
                (
                    {"category": cat, "amount": _r(v)}
                    for (o, cat), v in cur["categories"].items()
                    if o == owner and v
                ),
                key=lambda r: -r["amount"],
            )
        owners.append(row)

    return {
        "cycle": {
            "label": "Zyklus",
            "selected": cycle,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "day": day,
            "days": days,
            "rule": rule,
            "anchor": anchor,
            "previous_start": comp_window[0].isoformat() if comp_window else None,
            "previous_end": comp_window[1].isoformat() if comp_window else None,
        },
        "income": _r(cur["income"]),
        "expenses": _r(cur["expenses"]),
        "surplus": _r(cur["income"] - cur["expenses"]),
        "fixed": _r(cur["fixed"]),
        "variable": _r(cur["variable"]),
        "savings_rate": cur_rate,
        "income_pending": pending is not None,
        "expected_income_date": pending,
        "lines": lines,
        "owners": owners,
        "privacy": "full" if full_view else "restricted",
        "as_of": as_of.isoformat() if as_of else None,
    }
