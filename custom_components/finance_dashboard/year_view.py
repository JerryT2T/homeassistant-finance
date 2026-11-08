"""The year view of the home payload (``GET /home?horizon=year``).

Pure assembly from cached data -- no I/O, no clock, never a bank call.

One counting rule: ``txs`` are the counted, refund-netted bookings
(:mod:`counted`); every figure is :func:`household_summary.figures` inside a
window from :func:`household_summary.window_of_month` (the cycle holding the
15th of a month, so a cycle belongs to exactly one month and no month is
written twice). Owners come from the one chain (``Classifier``); this module
filters nothing by itself except by owner.

Scope and privacy:

* ``view == "person"``: the person's own owner-bucket; ``split`` and
  ``categories`` carry the person's figures, the other persons only as totals.
* ``view == "household"``: the household total in ``balance``; ``split`` is
  the shared bucket first and every person only as a total; ``categories`` and
  ``outliers`` are the shared bucket only (a person's categories and
  bookings are private).
* Individual bookings (``outliers.items``) only for an admin caller.

Prior year (A9): ``vs_last_year`` is present only when every counted account
has bookings since before the prior-year window opens; otherwise the key is
absent and so is every ``delta_prev``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .budget_plan import BudgetPlan
from .const import OWNER_SHARED
from .counted import amount_of, is_income_line
from .household_summary import (
    OWNER_OPEN,
    Classifier,
    figures,
    month_of_window,
    owner_fields,
    window_of_month,
)
from .labels import booking_key
from .pots import status_for
from .tx_dates import effective_day

TOP_CATEGORIES = 8
TOP_OUTLIERS = 5
TOP_FIXED = 5
HINT_MIN_EUR = 100.0
HINT_MIN_SHARE = 0.02

Window = tuple[date, date]


def _same_day_last_year(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 Feb
        return day - timedelta(days=365)


def month_windows(
    txs: list[dict[str, Any]],
    year: int,
    persons: list[dict[str, Any]] | None,
) -> list[tuple[int, Window | None]]:
    """``[(month, window | None)]`` for the 12 months of ``year`` (A1).

    The window is the cycle holding the 15th; it is dropped (``None``) when the
    cycle rule cannot name a cycle that belongs to this month, so a cycle never
    lands on a month it does not own.
    """
    out: list[tuple[int, Window | None]] = []
    for month in range(1, 13):
        window = window_of_month(txs, month, year, persons)[0][0]
        ok = window is not None and month_of_window(window) == (month, year)
        out.append((month, window if ok else None))
    return out


def account_earliest(
    txs: list[dict[str, Any]], extra: dict[str, str | None] | None = None
) -> dict[str, date | None]:
    """Earliest dated booking per account key (from the bookings themselves),
    merged with the ledger's own ``earliest_booked`` (``plan_wizard`` helper)."""
    out: dict[str, date | None] = {}
    for tx in txs:
        key = str(tx.get("_account_key") or tx.get("_account_id") or "")
        day = effective_day(tx)
        if key and day is not None and (out.get(key) is None or day < out[key]):  # type: ignore[operator]
            out[key] = day
    for key, value in (extra or {}).items():
        if key not in out:
            continue  # only accounts that count
        try:
            first = date.fromisoformat(str(value)[:10]) if value else None
        except ValueError:
            first = None
        if first is not None and (out[key] is None or first < out[key]):  # type: ignore[operator]
            out[key] = first
    return out


def covers(earliest: dict[str, date | None], start: date) -> bool:
    """Every counted account has bookings from ``start`` or earlier (A9)."""
    return bool(earliest) and all(d is not None and d <= start for d in earliest.values())


def _bucket(fig: dict[str, Any], view: str, person: str | None) -> dict[str, float]:
    owners = fig["owners"]
    keys = [person] if view == "person" else list(owners)
    out = {"income": 0.0, "expenses": 0.0, "fixed": 0.0, "variable": 0.0}
    for key in keys:
        row = owners.get(key)
        if row:
            for k in out:
                out[k] += row[k]
    return out


def _add(into: dict[str, float], row: dict[str, float]) -> None:
    for k, v in row.items():
        into[k] = into.get(k, 0.0) + v


def _r(v: float) -> float:
    return round(v, 2)


def _rate(income: float, expenses: float) -> float | None:
    return round((income - expenses) / income, 4) if income > 0 else None


def _month_budget(
    plan: BudgetPlan | None, month: int, year: int, view: str, person: str | None
) -> float | None:
    """That month's planned cost of the scope; ``None`` without a plan (A4)."""
    if plan is None or plan.is_empty():
        return None
    value = (
        plan.cost_total(person or "", month, year)
        if view == "person"
        else plan.cost_grand_total(month, year)
    )
    return round(value, 2) if value > 0 else None


def _scope_categories(fig: dict[str, Any], view: str, person: str | None) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    owner = person if view == "person" else OWNER_SHARED
    for (o, cat), value in fig["categories"].items():
        if o == owner:
            out[cat] += value
    return out


def fixed_year(contracts: list[dict[str, Any]] | None, view: str, person: str | None) -> dict[str, Any]:
    """Annualised fixed costs of the scope from the contract list (A6).

    Person view: the person's own contracts; household view: shared ones only
    (a person's contract is private). Candidates and ended series never count.
    """
    owner = person if view == "person" else OWNER_SHARED
    rows = [
        c
        for c in contracts or []
        if c.get("owner") == owner
        and not c.get("candidate")
        and c.get("status") != "ended"
        and c.get("kind", "contract") in ("contract", "subscription")
    ]
    rows.sort(key=lambda c: -float(c.get("annual_total", c.get("annual_cost")) or 0))
    yearly = sum(float(c.get("annual_total", c.get("annual_cost")) or 0) for c in rows)
    return {
        "yearly": _r(yearly),
        "monthly": _r(yearly / 12),
        "count": len(rows),
        "link": "contracts",
        "items": [
            {
                "id": c.get("id"),
                "name": c.get("display_name") or c.get("creditor"),
                "yearly": _r(float(c.get("annual_total", c.get("annual_cost")) or 0)),
                "interval": c.get("interval"),
            }
            for c in rows[:TOP_FIXED]
        ],
    }


def _outliers(
    txs: list[dict[str, Any]],
    clf: Classifier,
    start: date,
    end: date,
    view: str,
    person: str | None,
    is_admin: bool,
) -> dict[str, Any]:
    owner = person if view == "person" else OWNER_SHARED
    rows = []
    for tx in txs:
        day = effective_day(tx)
        if day is None or not start <= day <= end or is_income_line(tx):
            continue
        spent = -amount_of(tx)
        if spent <= 0:
            continue
        o, fixed, _source, _conf = clf.classify_detail(tx, day)
        if o != owner or fixed:
            continue
        rows.append((spent, day, tx, o))
    rows.sort(key=lambda r: (-r[0], r[1]))
    top = rows[:TOP_OUTLIERS]
    out: dict[str, Any] = {
        "count": len(top),
        "total": _r(sum(r[0] for r in top)),
        "items": [],
    }
    if is_admin:
        out["items"] = [
            {
                "ledger_id": booking_key(tx) or "",
                "date": day.isoformat(),
                "label": str(tx.get("creditorName") or tx.get("debtorName") or "")
                or str(tx.get("remittanceInformationUnstructured") or "")[:40],
                "category": str(tx.get("category") or "other"),
                "amount": _r(spent),
                **owner_fields(clf, tx),
            }
            for spent, day, tx, o in top
        ]
    return out


def build_year(  # noqa: PLR0912, PLR0914, PLR0915
    *,
    txs: list[dict[str, Any]],
    plan: BudgetPlan | None,
    clf: Classifier,
    persons: list[dict[str, Any]] | None,
    today: date,
    view: str,
    person: str | None,
    contracts: list[dict[str, Any]] | None = None,
    is_admin: bool = False,
    ledger_earliest: dict[str, str | None] | None = None,
    benchmark_teaser: list[dict[str, Any]] | None = None,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The year payload (see module doc and ``docs/dev/entities-and-services.md``)."""
    year = today.year
    booked = [t for t in txs if t.get("_status", "booked") == "booked"]
    earliest = account_earliest(booked, ledger_earliest)
    first_booking = min((d for d in earliest.values() if d), default=None)
    windows = month_windows(booked, year, persons)

    cycles: list[dict[str, Any]] = []
    ytd: dict[str, float] = {}
    cats: dict[str, float] = defaultdict(float)
    per_owner: dict[str, float] = defaultdict(float)
    used: list[tuple[int, Window]] = []
    for month, window in windows:
        row: dict[str, Any] = {
            "month": month,
            "year": year,
            "start": window[0].isoformat() if window else None,
            "end": window[1].isoformat() if window else None,
            "current": bool(window and window[0] <= today <= window[1]),
            "future": window is None or window[0] > today,
            "before_history": bool(
                window and window[0] <= today and (first_booking is None or window[0] < first_booking)
            ),
            "spent": None,
            "income": None,
            "budget": _month_budget(plan, month, year, view, person),
            "status": None,
        }
        if window and not row["future"] and not row["before_history"]:
            fig = figures(booked, window, clf)
            b = _bucket(fig, view, person)
            row["spent"], row["income"] = _r(b["expenses"]), _r(b["income"])
            row["spent_shared"] = _r(fig["owners"].get(OWNER_SHARED, {}).get("expenses", 0.0))
            if row["budget"]:
                days = (window[1] - window[0]).days + 1
                done = min(days, (today - window[0]).days + 1) if row["current"] else days
                row["status"] = status_for(b["expenses"], row["budget"] * done / days)
            _add(ytd, b)
            for cat, v in _scope_categories(fig, view, person).items():
                cats[cat] += v
            for owner, vals in fig["owners"].items():
                per_owner[owner] += vals["expenses"]
            used.append((month, window))
        cycles.append(row)

    income, expenses = ytd.get("income", 0.0), ytd.get("expenses", 0.0)
    balance = {
        "income": _r(income),
        "expenses": _r(expenses),
        "saved": _r(income - expenses),
        "savings_rate": _rate(income, expenses),
        "fixed": _r(ytd.get("fixed", 0.0)),
        "variable": _r(ytd.get("variable", 0.0)),
        "through": today.isoformat(),
        "cycles_counted": len(used),
    }

    # --- prior year (A9): same cycles, up to the same day ---------------------
    vs_last_year: dict[str, Any] | None = None
    prior_cats: dict[str, float] = defaultdict(float)
    if used:
        cur_month = used[-1][0]
        prior = month_windows(booked, year - 1, persons)
        prior_used = [(m, w) for m, w in prior if m <= cur_month and w is not None]
        if len(prior_used) == cur_month and covers(earliest, prior_used[0][1][0]):
            cutoff = _same_day_last_year(today)
            pytd: dict[str, float] = {}
            for month, (a, b_) in prior_used:
                fig = figures(booked, (a, min(b_, cutoff)), clf)
                _add(pytd, _bucket(fig, view, person))
                for cat, v in _scope_categories(fig, view, person).items():
                    prior_cats[cat] += v
            pe, pi = pytd.get("expenses", 0.0), pytd.get("income", 0.0)
            vs_last_year = {
                "through": cutoff.isoformat(),
                "spent": _r(expenses),
                "spent_last_year": _r(pe),
                "delta": _r(expenses - pe),
                "delta_pct": round((expenses - pe) / pe, 4) if pe > 0 else None,
                "income": _r(income),
                "income_last_year": _r(pi),
                "saved": _r(income - expenses),
                "saved_last_year": _r(pi - pe),
            }

    top = sorted(((c, v) for c, v in cats.items() if v > 0), key=lambda kv: -kv[1])[:TOP_CATEGORIES]
    total_cats = sum(v for v in cats.values() if v > 0) or 1.0
    categories = []
    for cat, value in top:
        item: dict[str, Any] = {"category": cat, "amount": _r(value), "share": round(value / total_cats, 4)}
        if vs_last_year is not None:
            item["delta_prev"] = _r(value - prior_cats.get(cat, 0.0))
        categories.append(item)

    # --- split (A7/A10): shared first, persons as totals -----------------------
    shared_total = per_owner.get(OWNER_SHARED, 0.0)
    split: dict[str, Any] = {
        "shared": _r(shared_total),
        "persons": {
            o: _r(v) for o, v in sorted(per_owner.items()) if o not in (OWNER_SHARED, OWNER_OPEN)
        },
    }
    if per_owner.get(OWNER_OPEN):
        split["open"] = _r(per_owner[OWNER_OPEN])
    if view == "person" and person:
        split["own"] = {"person": person, "total": _r(per_owner.get(person, 0.0))}
        if plan is not None and not plan.is_empty() and plan.persons:
            share = plan.income_rel(person)
        else:
            names = [o for o in per_owner if o not in (OWNER_SHARED, OWNER_OPEN)]
            share = 1 / len(names) if person in names else 0.0
        split["own"]["shared_share"] = _r(shared_total * share)

    out: dict[str, Any] = {
        "year": year,
        "scope": "person" if view == "person" else "household",
        "cycles": cycles,
        "balance": balance,
        "categories": categories,
        "categories_scope": "own" if view == "person" else "shared",
        "fixed_year": fixed_year(contracts, view, person),
        "split": split,
        "outliers": _outliers(
            booked, clf, used[0][1][0] if used else today, today, view, person, is_admin
        ),
        "benchmark_teaser": list(benchmark_teaser or []),
        "reviewed_at": (review or {}).get("reviewed_at"),
    }
    if vs_last_year is not None:
        out["vs_last_year"] = vs_last_year
    if is_admin and review and review.get("hint"):
        out["review_hint"] = review["hint"]
    return out


def actual_year(
    txs: list[dict[str, Any]],
    clf: Classifier,
    persons: list[dict[str, Any]] | None,
    today: date,
    ledger_earliest: dict[str, str | None] | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    """The household's real monthly averages of ``year`` for the benchmark (B1).

    Counts the finished cycles of the year that lie inside the booking history
    (``months_covered``), whole household, every owner. A year not yet over is
    therefore extrapolated by averaging, and the caller says so.
    """
    year = year or today.year
    booked = [t for t in txs if t.get("_status", "booked") == "booked"]
    first = min((d for d in account_earliest(booked, ledger_earliest).values() if d), default=None)
    income = 0.0
    cats: dict[str, float] = defaultdict(float)
    n = 0
    for _month, window in month_windows(booked, year, persons):
        if window is None or first is None or window[0] < first or window[1] >= today:
            continue
        fig = figures(booked, window, clf)
        income += fig["income"]
        for (_owner, cat), value in fig["categories"].items():
            cats[cat] += value
        n += 1
    return {
        "year": year,
        "months_covered": n,
        "income_monthly": round(income / n, 2) if n else 0.0,
        "by_category_monthly": {c: round(v / n, 2) for c, v in cats.items()} if n else {},
    }
