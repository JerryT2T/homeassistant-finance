"""Honest household numbers per income cycle (``GET .../household_summary``).

Pure assembly from cached data - no I/O, no clock, never a bank call.

What is counted (and what is not):

- **Own-account transfers** are not income and not expenses. A transfer chain
  with only a source and a destination leg (money moved between the user's own
  accounts) is dropped completely. A chain with intermediate legs is a real
  purchase routed through own accounts (shop <- PayPal <- DKB <- savings): its
  source leg is the one real expense and counts once, the rest is dropped
  (same rule as ``get_effective_transactions``). A chain the user rejected is
  counted as ordinary bookings. Bookings categorised ``transfers`` are dropped.
- **PayPal mirror**: when a PayPal account is linked, its dated lines are the
  truth, so a debit on another account to PayPal that a PayPal line of the
  same amount (within a few days) shows is a funding and is dropped. Without
  such a line - PayPal not linked, or its lines carry no date - the debit is
  the only trace of the purchase and counts. Dates come from
  ``tx_dates.effective_day`` (PayPal lines often carry only a transaction date).
- **Refunds** (``_refund_role == "refund"``) are netted against expenses, they
  are not income.
- **Insurance refunds** matched to their expenses (``refund_matcher``, #119) are
  netted into the *expense's* cycle, category and owner and leave income.
- Only booked lines count; pending ones are ignored.

Ownership of an expense resolves in the fixed chain: the account's owner is the
default, a matched plan position overrides it, a user correction overrides
both. Fixed = the booking belongs to a recurring series or a plan position of
kind ``fixed``; everything else is variable.

Sign convention: every figure in this payload is a positive magnitude
(expenses positive, ``surplus = income - expenses``).

Privacy: the payload only carries aggregates, never booking lists. For a
non-admin viewer (or the person view) other persons' personal accounts appear
as totals only (``restricted: true``) and their categories are left out.
"""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from .budget_plan import BudgetPlan
from .const import OWNER_SHARED, POSITION_KIND_FIXED
from .cycle import calendar_cycle, household_cycle, household_starts
from .refund_matcher import net_refunds
from .text_norm import canonical_name, processor_merchant_text
from .tx_dates import effective_day

CYCLES = ("current", "previous")
OWNER_OPEN = "open"
_TOKEN_RE = re.compile(r"[a-zäöüß]{4,}")
_SKIP_CATEGORIES = {"transfers"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _amount(tx: dict[str, Any]) -> float:
    try:
        return float((tx.get("transactionAmount") or {}).get("amount", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _day(tx: dict[str, Any]) -> date | None:
    return effective_day(tx)


def _name(tx: dict[str, Any]) -> str:
    return " ".join(str(tx.get("creditorName") or tx.get("debtorName") or "").lower().split())


def _haystack(tx: dict[str, Any]) -> str:
    return " ".join(
        str(tx.get(k) or "").lower()
        for k in ("remittanceInformationUnstructured", "creditorName", "debtorName")
    )


def _is_paypal(text: str) -> bool:
    return "paypal" in text.lower()


def paypal_account_ids(accounts: list[dict[str, Any]]) -> set[str]:
    """Uids of linked accounts that are PayPal accounts."""
    return {
        str(a.get("id"))
        for a in accounts or []
        if a.get("id") and _is_paypal(f"{a.get('institution', '')} {a.get('name', '')}")
    }


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


def counted_transactions(
    transactions: list[dict[str, Any]], accounts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Booked transactions that are real income / expense (see module doc)."""
    booked = [t for t in transactions if t.get("_status", "booked") == "booked"]
    has_intermediate = {
        t.get("_transfer_chain_id")
        for t in booked
        if t.get("_transfer_role") == "intermediate" and t.get("_transfer_confirmed") is not False
    }
    pp_ids = paypal_account_ids(accounts)
    mirrors = _paypal_mirrors(booked, pp_ids)
    out: list[dict[str, Any]] = []
    for tx in booked:
        if _day(tx) is None:
            continue
        chain = tx.get("_transfer_chain_id")
        if chain and tx.get("_transfer_confirmed") is not False:
            real_purchase = tx.get("_transfer_role") == "source" and chain in has_intermediate
            if not real_purchase:
                continue
        elif str(tx.get("category") or "") in _SKIP_CATEGORIES:
            continue
        if id(tx) in mirrors:
            continue
        out.append(tx)
    return out


PAYPAL_MIRROR_DAYS = 5


def _paypal_mirrors(booked: list[dict[str, Any]], pp_ids: set[str]) -> set[int]:
    """Lines that only move money between a bank account and PayPal.

    A debit on another account to PayPal funds a purchase that PayPal's own
    line shows, or tops up the PayPal balance (PayPal then shows a funding
    credit). The debit is dropped only when such a dated PayPal line exists
    (same amount, within ``PAYPAL_MIRROR_DAYS``, each line used once); a
    matched funding credit is dropped with it, it is no income. Without a
    counterpart - PayPal not linked, or its lines carry no date - the debit
    is the only trace of the purchase and counts.
    """
    if not pp_ids:
        return set()
    purchases: dict[int, list[dict[str, Any]]] = defaultdict(list)
    credits: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for tx in booked:
        if _day(tx) is None or str(tx.get("_account_id") or "") not in pp_ids:
            continue
        cents = round(_amount(tx) * 100)
        if cents < 0:
            purchases[cents].append(tx)
        elif cents > 0:
            credits[-cents].append(tx)
    mirrors: set[int] = set()
    debits = sorted(
        (
            tx
            for tx in booked
            if _amount(tx) < 0
            and _day(tx) is not None
            and str(tx.get("_account_id") or "") not in pp_ids
            and _is_paypal(f"{tx.get('creditorName', '')} {tx.get('debtorName', '')}")
        ),
        key=_day,
    )

    def near(day: date, other: date) -> int | None:
        gap = abs((other - day).days)
        return gap if gap <= PAYPAL_MIRROR_DAYS else None

    for tx in debits:
        day, cents = _day(tx), round(_amount(tx) * 100)
        funding = [c for c in credits.get(cents, []) if near(day, _day(c)) is not None]
        if funding:
            credit = min(funding, key=lambda c: near(day, _day(c)))
            credits[cents].remove(credit)
            mirrors.add(id(credit))
        merchant = canonical_name(
            processor_merchant_text(str(tx.get("remittanceInformationUnstructured") or ""))
        )
        bought = [
            p
            for p in purchases.get(cents, [])
            if near(day, _day(p)) is not None and _same_merchant(merchant, p)
        ]
        if bought:
            purchases[cents].remove(min(bought, key=lambda p: near(day, _day(p))))
        if funding or bought:
            mirrors.add(id(tx))
    return mirrors


def _same_merchant(merchant: str, line: dict[str, Any]) -> bool:
    """The bank debit names no merchant, or the PayPal line's payee shares a word with it."""
    if not merchant:
        return True
    payee = canonical_name(str(line.get("creditorName") or line.get("debtorName") or ""))
    return not payee or bool(set(merchant.split()) & set(payee.split()))


# ---------------------------------------------------------------------------
# cycle windows
# ---------------------------------------------------------------------------


def _prev_month_window(start: date) -> tuple[date, date]:
    return calendar_cycle(start - timedelta(days=1))


def cycle_windows(
    transactions: list[dict[str, Any]], today: date
) -> tuple[list[tuple[date, date] | None], str, str | None]:
    """``([current, previous, before], rule, anchor)`` windows (None = unknown)."""
    by_person: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for tx in transactions:
        amount, day = _amount(tx), _day(tx)
        if amount > 0 and day and owner_of(tx) not in (OWNER_SHARED, OWNER_OPEN):
            if tx.get("_refund_role") != "refund":
                by_person[owner_of(tx)].append((day, amount))
    starts = [s for s, _ in household_starts(dict(by_person))]
    if not starts:
        cur = calendar_cycle(today)
        prev = _prev_month_window(cur[0])
        return [cur, prev, _prev_month_window(prev[0])], "calendar_fallback", None
    start, end, anchor = household_cycle(dict(by_person), today)
    ordered = sorted(starts)
    idx = ordered.index(start)
    windows: list[tuple[date, date] | None] = [(start, end)]
    for back in (1, 2):
        i = idx - back
        windows.append((ordered[i], ordered[i + 1] - timedelta(days=1)) if i >= 0 else None)
    return windows, "household_7_day", anchor


# ---------------------------------------------------------------------------
# classification + figures
# ---------------------------------------------------------------------------


class _Classifier:
    """Owner + fixed/variable for expenses."""

    def __init__(
        self,
        plan: BudgetPlan | None,
        recurring: list[dict[str, Any]] | None,
        corrections: dict[str, str] | None,
    ) -> None:
        self.plan = plan
        self.corrections = corrections or {}
        self.recurring_names = {
            " ".join(str(p.get("creditor") or "").lower().split())
            for p in recurring or []
            if float(p.get("average_amount", 0) or 0) < 0
        } - {""}

    def _position(self, tx: dict[str, Any], on: date):
        if self.plan is None:
            return None
        hay = _haystack(tx)
        for pos in self.plan.active_positions(on.month, on.year):
            tokens = _TOKEN_RE.findall(pos.name.lower())
            if tokens and any(t in hay for t in tokens):
                return pos
        return None

    def classify(self, tx: dict[str, Any], on: date) -> tuple[str, bool]:
        """``(owner, is_fixed)``: account default -> plan match -> correction."""
        owner = owner_of(tx)
        pos = self._position(tx, on)
        fixed = _name(tx) in self.recurring_names
        if pos is not None:
            owner = pos.owner or OWNER_SHARED
            fixed = fixed or pos.kind == POSITION_KIND_FIXED
        corrected = self.corrections.get(str(tx.get("transactionId") or ""))
        if corrected:
            owner = corrected
        return owner, fixed


def _figures(
    txs: list[dict[str, Any]], window: tuple[date, date], clf: _Classifier
) -> dict[str, Any]:
    start, end = window
    income = expenses = fixed = 0.0
    owners: dict[str, dict[str, float]] = defaultdict(
        lambda: {"income": 0.0, "expenses": 0.0, "fixed": 0.0, "variable": 0.0}
    )
    cats: dict[tuple[str, str], float] = defaultdict(float)
    income_names: set[str] = set()
    for tx in txs:
        day = _day(tx)
        if day is None or not start <= day <= end:
            continue
        amount = _amount(tx)
        owner, is_fixed = clf.classify(tx, day)
        if amount > 0 and tx.get("_refund_role") != "refund":
            income += amount
            owners[owner_of(tx)]["income"] += amount
            income_names.add(_name(tx))
            continue
        spent = -amount  # a refund comes out negative -> netted against expenses
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
) -> dict[str, Any]:
    """Assemble the ``household_summary`` contract (docs/dev/contracts/household-summary.md)."""
    today = now.date()
    if cycle not in CYCLES:
        cycle = "current"
    txs = counted_transactions(transactions, accounts)
    if refund_allocations:
        txs = net_refunds(txs, refund_allocations)  # #119: into the expense's cycle
    windows, rule, anchor = cycle_windows(txs, today)
    clf = _Classifier(plan, recurring, corrections)

    sel = 0 if cycle == "current" else 1
    window = windows[sel]
    comp_window = windows[sel + 1] if sel + 1 < len(windows) else None
    if window is None:  # defensive: previous cycle unknown
        window = windows[0]
    start, end = window  # type: ignore[misc]
    cur = _figures(txs, window, clf)  # type: ignore[arg-type]
    prev = _figures(txs, comp_window, clf) if comp_window else None

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
