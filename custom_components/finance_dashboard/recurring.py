"""Recurring transaction detection.

Auto-detects monthly recurring payments by analyzing:
- Same creditor/debtor appearing multiple months
- Similar amounts (±10% tolerance)
- Regular timing pattern

Detected recurring transactions become "Fixkosten" and are
assigned to their logical month (with bank day correction).
"""

from __future__ import annotations

import hashlib
import logging
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from .text_norm import canonical_name

_LOGGER = logging.getLogger(__name__)

# Amount tolerance for "same" recurring payment
AMOUNT_TOLERANCE = 0.10  # ±10%

# Minimum occurrences to consider a pattern recurring
MIN_OCCURRENCES = 2


def detect_recurring(
    transactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect recurring payment patterns in transaction history.

    Groups transactions by creditor name, then checks for monthly
    recurrence with similar amounts.

    Returns:
        List of detected recurring patterns:
        [
            {
                "creditor": "Vermieter GmbH",
                "average_amount": -1590.02,
                "frequency": "monthly",
                "expected_day": 1,
                "occurrences": 3,
                "category": "housing",
                "last_seen": "2026-03-01",
                "confirmed": False,
            }
        ]
    """
    # Group by creditor name (normalized)
    by_creditor: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for txn in transactions:
        if txn.get("_status") != "booked":
            continue

        creditor = _normalize_name(txn.get("creditorName", "") or txn.get("debtorName", ""))
        if not creditor:
            continue

        by_creditor[creditor].append(txn)

    # Analyze each creditor group for recurring pattern
    patterns = []
    for creditor, txns in by_creditor.items():
        if len(txns) < MIN_OCCURRENCES:
            continue

        pattern = _analyze_pattern(creditor, txns)
        if pattern:
            patterns.append(pattern)

    # Sort by absolute amount (largest first)
    patterns.sort(key=lambda p: abs(p["average_amount"]), reverse=True)

    _LOGGER.info("Detected %d recurring patterns", len(patterns))
    return patterns


def _analyze_pattern(creditor: str, transactions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Analyze a creditor's transactions for recurring pattern."""
    amounts = []
    dates = []

    for txn in transactions:
        amount = float(txn.get("transactionAmount", {}).get("amount", 0))
        booking_str = txn.get("bookingDate", "")
        if not booking_str:
            continue

        try:
            booking = datetime.strptime(booking_str, "%Y-%m-%d")
            amounts.append(amount)
            dates.append(booking)
        except ValueError:
            continue

    if len(amounts) < MIN_OCCURRENCES:
        return None

    # Check amount consistency (±10%)
    avg_amount = sum(amounts) / len(amounts)
    if avg_amount == 0:
        return None

    amount_consistent = all(
        abs(a - avg_amount) / abs(avg_amount) <= AMOUNT_TOLERANCE for a in amounts
    )
    if not amount_consistent:
        return None

    # Check monthly frequency — transactions should be ~30 days apart
    dates.sort()
    if len(dates) >= 2:
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_interval = sum(intervals) / len(intervals)

        # Monthly: 25-35 days between occurrences
        if not (25 <= avg_interval <= 35):
            return None

    # Detect expected day of month
    days = [d.day for d in dates]
    expected_day = _most_common(days)

    return {
        "creditor": creditor,
        "average_amount": round(avg_amount, 2),
        "frequency": "monthly",
        "expected_day": expected_day,
        "occurrences": len(amounts),
        "category": transactions[0].get("category", "other"),
        "last_seen": max(dates).strftime("%Y-%m-%d"),
        "confirmed": False,
    }


def _normalize_name(name: str) -> str:
    """Normalize creditor/debtor name for grouping."""
    if not name:
        return ""
    # Lowercase, strip extra spaces
    return " ".join(name.lower().strip().split())


def _most_common(values: list[int]) -> int:
    """Return the most common value in a list."""
    if not values:
        return 1
    counts: dict[int, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.get)


# ---------------------------------------------------------------------------
# Series of any interval (Phase 4d)
# ---------------------------------------------------------------------------
#
# ``detect_recurring`` above stays the monthly-only detector that feeds the
# home screen. ``detect_series`` is the wider model behind contracts and
# reserves: weekly .. yearly, tolerances configurable, expected next date and
# amount, a ``missing`` state, price-change detection and the annual cost.

SERIES_AMOUNT_TOLERANCE = 0.20  # ±20 %
SERIES_DATE_TOLERANCE_DAYS = 5  # ±5 days

# interval -> (nominal days, payments per year, minimum occurrences)
INTERVALS: dict[str, tuple[int, int, int]] = {
    "weekly": (7, 52, 4),
    "monthly": (30, 12, 2),
    "quarterly": (91, 4, 2),
    "half_yearly": (182, 2, 2),
    "yearly": (365, 1, 2),
}
IRREGULAR_INTERVALS = ("quarterly", "half_yearly", "yearly")

PLAN_MODE_HIGHEST = "highest"
PLAN_MODE_AVERAGE = "average"
PLAN_MODE_LAST = "last"
PLAN_MODE_MEDIAN = "median"
PLAN_MODE_FIXED = "fixed"
PLAN_MODES = (
    PLAN_MODE_HIGHEST,
    PLAN_MODE_AVERAGE,
    PLAN_MODE_LAST,
    PLAN_MODE_MEDIAN,
    PLAN_MODE_FIXED,
)

STATUS_ACTIVE = "active"
STATUS_MISSING = "missing"  # overdue by more than the date tolerance
STATUS_ENDED = "ended"  # overdue by more than two periods


def series_id(creditor: str, negative: bool) -> str:
    """Stable id from the normalized counterparty and the direction."""
    raw = f"{_normalize_name(creditor)}|{'out' if negative else 'in'}"
    return "s_" + hashlib.sha1(raw.encode()).hexdigest()[:12]  # noqa: S324 - not security


def alias_key(canonical: str, negative: bool) -> str:
    """Key under which a series remembers its id across name variants."""
    return f"{canonical}|{'out' if negative else 'in'}"


def resolve_series_id(
    canonical: str,
    names: list[str],
    negative: bool,
    aliases: dict[str, str],
    known: set[str],
) -> str:
    """Id of a payee group: remembered alias, else a known id of one of its
    spellings, else the id of the first-seen spelling.

    For a payee whose spelling never changed this is ``series_id(name)`` as
    before, so ids stored before name grouping existed stay valid.
    """
    remembered = aliases.get(alias_key(canonical, negative))
    if remembered:
        return remembered
    candidates = [series_id(n, negative) for n in names]
    return next((c for c in candidates if c in known), candidates[0])


def _keep_known_apart(
    groups: dict[tuple[str, bool], list[tuple[date, float, dict[str, Any]]]],
    known: set[str],
):
    """Yield ``(key, negative, date-sorted rows)`` per payee group.

    A group whose spellings already own two or more stored ids ("Acme GmbH"
    and "Acme AG" with user data each) were separate payees before name
    grouping; they stay split by spelling so no stored contract is orphaned.
    """
    for (key, negative), rows in groups.items():
        rows.sort(key=lambda r: r[0])
        names = _names_first_seen(rows)
        if len({series_id(n, negative) for n in names} & known) < 2:
            yield key, negative, rows
            continue
        for name in names:
            part = [r for r in rows if _row_name(r) == name]
            yield name, negative, part


def _row_name(row: tuple[date, float, dict[str, Any]]) -> str:
    txn = row[2]
    return _normalize_name(txn.get("creditorName", "") or txn.get("debtorName", ""))


def _names_first_seen(rows: list[tuple[date, float, dict[str, Any]]]) -> list[str]:
    """Distinct normalized counterparty names of ``rows`` (date-sorted), oldest first."""
    names: list[str] = []
    for row in rows:
        name = _row_name(row)
        if name not in names:
            names.append(name)
    return names


def plan_amount(
    amounts: list[float], mode: str = PLAN_MODE_HIGHEST, fixed: float | None = None
) -> float:
    """Amount (absolute) a series contributes to the plan, per ``mode``."""
    mags = [abs(a) for a in amounts] or [0.0]
    if mode == PLAN_MODE_FIXED and fixed is not None:
        return round(abs(fixed), 2)
    if mode == PLAN_MODE_AVERAGE:
        return round(sum(mags) / len(mags), 2)
    if mode == PLAN_MODE_LAST:
        return round(mags[-1], 2)
    if mode == PLAN_MODE_MEDIAN:
        return round(statistics.median(mags), 2)
    return round(max(mags), 2)


def _classify_interval(dates: list[date], date_tol: int) -> str | None:
    """Return the interval name when every gap fits it, else None."""
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    med = statistics.median(gaps)
    for name, (nominal, _per_year, min_occ) in INTERVALS.items():
        # weekly must not swallow neighbours; month-based periods drift by calendar
        tol = min(date_tol, 2) if name == "weekly" else date_tol + 2
        if abs(med - nominal) > tol:
            continue
        if len(dates) < min_occ:
            return None
        if all(abs(g - nominal) <= tol + 2 for g in gaps):
            return name
        return None
    return None


def _amounts_consistent(amounts: list[float], tolerance: float) -> bool:
    """Stable within ``tolerance`` between payments, allowing one price step."""
    mags = [abs(a) for a in amounts]
    if not mags or min(mags) == 0:
        return False
    jumps = [i for i in range(1, len(mags)) if abs(mags[i] - mags[i - 1]) / mags[i - 1] > tolerance]
    if not jumps:
        return True
    if len(jumps) > 1:
        return False
    after = mags[jumps[0] :]
    return all(abs(a - after[-1]) / after[-1] <= tolerance for a in after)


def _parse_day(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def detect_series(
    transactions: list[dict[str, Any]],
    *,
    today: date | None = None,
    amount_tolerance: float = SERIES_AMOUNT_TOLERANCE,
    date_tolerance_days: int = SERIES_DATE_TOLERANCE_DAYS,
    overrides: dict[str, dict[str, Any]] | None = None,
    aliases: dict[str, str] | None = None,
    known_ids: set[str] | frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Detect recurring series of any interval in booked transactions.

    ``overrides`` maps a series id to ``{"plan_mode", "plan_fixed_amount"}``.
    Amounts in the result are in the bank sign (expense negative).

    Payees are grouped by their spelling-independent name, so a bank that
    changes punctuation, legal form or encoding does not split a series.
    ``aliases`` maps an ``alias_key`` to the id the series had before
    (see :func:`resolve_series_id`); each result carries its ``alias_key``.
    ``known_ids`` are ids that hold user data (stored contracts): a payee
    group that contains one of their spellings keeps that id.
    """
    today = today or date.today()
    overrides = overrides or {}
    groups: dict[tuple[str, bool], list[tuple[date, float, dict[str, Any]]]] = defaultdict(list)
    for txn in transactions:
        if txn.get("_status") != "booked":
            continue
        raw = txn.get("creditorName", "") or txn.get("debtorName", "")
        day = _parse_day(txn.get("bookingDate", ""))
        if not _normalize_name(raw) or day is None:
            continue
        try:
            amount = float(txn.get("transactionAmount", {}).get("amount", 0))
        except (TypeError, ValueError):
            continue
        if amount == 0:
            continue
        groups[(canonical_name(raw), amount < 0)].append((day, amount, txn))

    known = set(known_ids) | set(overrides) | set((aliases or {}).values())
    aliases = aliases or {}
    out: list[dict[str, Any]] = []
    for key, negative, rows in _keep_known_apart(groups, known):
        names = _names_first_seen(rows)
        name = names[-1]
        parts = _series_parts(rows, date_tolerance_days, amount_tolerance)
        if not parts:
            continue
        # earliest payment keeps the payee id; same day -> the tag decides, not input order
        base = min(range(len(parts)), key=lambda i: (parts[i].rows[0][0], parts[i].tag))
        used: set[str] = set()
        for i, part in enumerate(parts):
            sid = _part_id(
                part,
                is_base=i == base,
                canonical=key,
                names=names,
                negative=negative,
                aliases=aliases,
                known=known,
                used=used,
            )
            used.add(sid)
            series = _build_series(
                sid, name, negative, part.rows, part.interval, today, date_tolerance_days, overrides
            )
            keys = [alias_key(key, negative)] if i == base else []
            if part.tag:
                keys.append(alias_key(key + part.tag, negative))
            if part.ref:
                keys.append(_ref_alias_key(part.ref, negative))
            series["alias_key"] = keys[0]
            series["alias_keys"] = keys
            out.append(series)
    out.sort(key=lambda s: s["annual_cost"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# One payee, several series (#108)
# ---------------------------------------------------------------------------
#
# A lender with two loans, an app store with a subscription and one-off
# purchases, a BNPL provider with a membership and instalments: one payee
# name, several payment streams. A payee group is split
#  - by contract reference (loan / contract / customer / mandate number in the
#    remittance text) when two or more references each recur and run at the
#    same time - a reference that merely changes once (new mandate) is a
#    successor, not a second contract;
#  - else, only when the whole group is no series, into amount bands; finite
#    instalments ("Teil 1/3", "Rate 2 von 6") never form a band.
# A real price step is therefore never split: the whole group is a series.

_REF_KEYWORDS = (
    r"darlehen(?:skonto|s?-?nr)?|kredit(?:konto|-?nr)?|vertrag(?:s?nummer|s?-?nr)?"
    r"|vertragskonto|kunden-?(?:nr|nummer)|kd-?nr|mandat(?:s?referenz)?|mref"
    r"|police(?:n-?nr)?|versicherungs(?:schein|nummer)(?:-?nr)?"
    r"|mitglieds-?(?:nr|nummer)|loan|contract"
)
_REF = re.compile(
    rf"\b(?:{_REF_KEYWORDS})\b\.?[\s:#.-]*(?:(?:nr|no)\b\.?[\s:#.-]*)?"
    r"([a-z]{0,4}-?\d[\d/-]{3,}\w*)",
    re.IGNORECASE,
)
MIN_BAND_OCCURRENCES = 3
_FINITE_INSTALMENT = re.compile(r"\b(?:teil|rate)\s*\d+\s*(?:/|von|of)\s*\d+\b", re.IGNORECASE)


def contract_reference(remittance: str) -> str:
    """Contract / loan / customer / mandate number named in ``remittance``.

    Only a number that follows a contract keyword counts, so a varying order
    or invoice number never splits a payee ("" when none).
    """
    match = _REF.search(remittance or "")
    return match.group(1).lower().rstrip("/-") if match else ""


def _remittance(txn: dict[str, Any]) -> str:
    text = str(txn.get("remittanceInformationUnstructured") or "")
    if not text:
        arr = txn.get("remittanceInformationUnstructuredArray") or []
        text = " ".join(str(a) for a in arr)
    return text


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode()).hexdigest()[:10]  # noqa: S324 - not security


def _ref_alias_key(ref: str, negative: bool) -> str:
    """Name-independent alias key of a contract reference (hashed, never the number)."""
    return alias_key("#ref:" + _digest(ref), negative)


class _Part:
    """One series inside a payee group."""

    __slots__ = ("interval", "ref", "rows", "tag")

    def __init__(self, rows, interval: str, tag: str = "", ref: str = "") -> None:
        self.rows = rows
        self.interval = interval
        self.tag = tag  # "" for the whole group, else "#<ref hash>" / "~<band hash>"
        self.ref = ref


def _as_series(rows, date_tol: int, amount_tol: float):
    """``(deduplicated rows, interval)`` when ``rows`` form a series, else None."""
    dedup: list[tuple[date, float, dict[str, Any]]] = []
    for row in rows:  # same-day duplicates carry no interval information
        if dedup and dedup[-1][0] == row[0]:
            continue
        dedup.append(row)
    if len(dedup) < 2:
        return None
    interval = _classify_interval([r[0] for r in dedup], date_tol)
    if interval is None or not _amounts_consistent([r[1] for r in dedup], amount_tol):
        return None
    return dedup, interval


def _amount_bands(rows, tolerance: float):
    """Rows clustered by amount (each band within ``tolerance`` of its smallest)."""
    bands: list[list[tuple[date, float, dict[str, Any]]]] = []
    for row in sorted(rows, key=lambda r: abs(r[1])):
        if bands and abs(row[1]) <= abs(bands[-1][0][1]) * (1 + tolerance):
            bands[-1].append(row)
        else:
            bands.append([row])
    return [sorted(b, key=lambda r: r[0]) for b in bands]


def _whole_or_bands(rows, date_tol: int, amount_tol: float, tag: str = "", ref: str = ""):
    whole = _as_series(rows, date_tol, amount_tol)
    if whole:
        return [_Part(whole[0], whole[1], tag, ref)]
    plain = [r for r in rows if not _FINITE_INSTALMENT.search(_remittance(r[2]))]
    found = [_as_series(band, date_tol, amount_tol) for band in _amount_bands(plain, amount_tol)]
    streams = sorted(
        (f for f in found if f and _band_is_regular(f[0], f[1], date_tol)),
        key=lambda f: f[0][0][0],
    )
    parts = []
    for rows_, interval in _join_successors(streams, date_tol, amount_tol):
        mid = statistics.median(abs(r[1]) for r in rows_[:MIN_BAND_OCCURRENCES])
        # a band never claims the reference: two bands would fight over it
        parts.append(_Part(rows_, interval, f"{tag}~{_digest(f'{mid:.0f}')}"))
    return parts


def _band_is_regular(rows, interval: str, date_tol: int) -> bool:
    """A band cut out of a mixed payee needs more evidence than a whole payee:
    at least three payments, each within ``date_tol`` days of the date the one
    before it predicts. Two similar purchases a month apart are chance."""
    if len(rows) < MIN_BAND_OCCURRENCES:
        return False
    return all(
        abs((rows[i][0] - _add_period(rows[i - 1][0], interval)).days) <= date_tol
        for i in range(1, len(rows))
    )


def _join_successors(streams, date_tol: int, amount_tol: float):
    """Join a band that continues where an earlier one stopped (a price step
    beside a one-off purchase splits a series into two bands)."""
    joined: list = []
    for rows_, interval in streams:
        if joined and joined[-1][1] == interval and rows_[0][0] > joined[-1][0][-1][0]:
            gap = (rows_[0][0] - joined[-1][0][-1][0]).days
            merged = _as_series(joined[-1][0] + rows_, date_tol, amount_tol)
            if gap <= INTERVALS[interval][0] + date_tol + 2 and merged:
                joined[-1] = merged
                continue
        joined.append((rows_, interval))
    return joined


def _series_parts(rows, date_tol: int, amount_tol: float) -> list[_Part]:
    """The series inside one payee group (date-sorted ``rows``)."""
    by_ref: dict[str, list[tuple[date, float, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        by_ref[contract_reference(_remittance(row[2]))].append(row)
    recurring = {ref: rs for ref, rs in by_ref.items() if ref and len(rs) >= 2}
    if len(recurring) >= 2 and _run_in_parallel(list(recurring.values())):
        parts: list[_Part] = []
        for ref, part_rows in recurring.items():
            parts += _whole_or_bands(part_rows, date_tol, amount_tol, "#" + _digest(ref), ref)
        rest = sorted(
            (r for ref, rs in by_ref.items() if ref not in recurring for r in rs),
            key=lambda r: r[0],
        )
        return parts + _whole_or_bands(rest, date_tol, amount_tol, "#-")
    single_ref = next(iter(by_ref)) if len(by_ref) == 1 else ""
    return _whole_or_bands(rows, date_tol, amount_tol, ref=single_ref)


def _run_in_parallel(streams) -> bool:
    """Two of the date-sorted ``streams`` overlap in time."""
    spans = sorted((s[0][0], s[-1][0]) for s in streams)
    return any(spans[i][0] <= spans[i - 1][1] for i in range(1, len(spans)))


def _part_id(
    part: _Part,
    *,
    is_base: bool,
    canonical: str,
    names: list[str],
    negative: bool,
    aliases: dict[str, str],
    known: set[str],
    used: set[str],
) -> str:
    """Id of one part: its own remembered alias first; the earliest part keeps
    the payee's id, every other part gets an id derived from its tag."""
    candidates = []
    if part.ref:
        candidates.append(aliases.get(_ref_alias_key(part.ref, negative)))
    if part.tag:
        candidates.append(aliases.get(alias_key(canonical + part.tag, negative)))
    if is_base:
        candidates.append(resolve_series_id(canonical, names, negative, aliases, known))
    for sid in candidates:
        if sid and sid not in used:
            return sid
    return series_id(f"{names[0]} {part.tag or part.ref}", negative)


def _most_common_value(values: list[Any], default: Any) -> Any:
    counts: dict[Any, int] = {}
    for v in values:
        if v not in (None, ""):
            counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.get) if counts else default


def _build_series(
    sid: str,
    name: str,
    negative: bool,
    rows: list[tuple[date, float, dict[str, Any]]],
    interval: str,
    today: date,
    date_tol: int,
    overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    nominal, per_year, _ = INTERVALS[interval]
    dates = [r[0] for r in rows]
    amounts = [r[1] for r in rows]
    ov = overrides.get(sid, {})
    mode = ov.get("plan_mode") if ov.get("plan_mode") in PLAN_MODES else PLAN_MODE_HIGHEST
    fixed = ov.get("plan_fixed_amount")
    plan = plan_amount(amounts, mode, fixed)

    next_expected = _add_period(dates[-1], interval)
    overdue = (today - next_expected).days
    if overdue > 2 * nominal:
        status = STATUS_ENDED
    elif overdue > date_tol:
        status = STATUS_MISSING
    else:
        status = STATUS_ACTIVE

    sign = -1.0 if negative else 1.0
    price_change = None
    if len(amounts) >= 2 and round(abs(amounts[-1]), 2) != round(abs(amounts[-2]), 2):
        prev, last = abs(amounts[-2]), abs(amounts[-1])
        price_change = {
            "previous": round(sign * prev, 2),
            "last": round(sign * last, 2),
            "change_pct": round((last - prev) / prev * 100, 1) if prev else None,
            "increase": last > prev,
            "date": dates[-1].isoformat(),
        }

    txns = [r[2] for r in rows]
    latest = txns[-1] if txns else {}
    raw_name = latest.get("creditorName", "") or latest.get("debtorName", "")
    return {
        "id": sid,
        "creditor": name,
        "display_name": " ".join(str(raw_name).split()) or name,
        "direction": "out" if negative else "in",
        "interval": interval,
        "period_days": nominal,
        "occurrences": len(rows),
        "first_seen": dates[0].isoformat(),
        "last_seen": dates[-1].isoformat(),
        "expected_day": _most_common([d.day for d in dates]),
        "last_amount": round(amounts[-1], 2),
        "previous_amount": round(amounts[-2], 2) if len(amounts) >= 2 else None,
        "amounts": [round(a, 2) for a in amounts[-12:]],
        "dates": [d.isoformat() for d in dates[-12:]],
        "next_expected": next_expected.isoformat(),
        "expected_amount": round(sign * plan, 2),
        "plan_mode": mode,
        "plan_fixed_amount": fixed if mode == PLAN_MODE_FIXED else None,
        "plan_amount": round(sign * plan, 2),
        "annual_cost": round(plan * per_year, 2),
        "status": status,
        "price_change": price_change,
        "category": _most_common_value([t.get("category") for t in txns], "other"),
        "account_key": _most_common_value([t.get("_account_key") for t in txns], ""),
        "account_type": _most_common_value([t.get("_account_type") for t in txns], "personal"),
        "account_person": _most_common_value([t.get("_account_person") for t in txns], ""),
    }


def add_months(day: date, months: int) -> date:
    """``day`` plus ``months`` calendar months, clamped to the month length."""
    year, month0 = divmod(day.year * 12 + (day.month - 1) + months, 12)
    month = month0 + 1
    first_next = date(year + (month == 12), month % 12 + 1, 1)
    return date(year, month, min(day.day, (first_next - timedelta(days=1)).day))


def _add_period(start: date, interval: str) -> date:
    """Next occurrence: calendar months for month-based intervals, 7 days weekly."""
    months = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}.get(interval)
    return start + timedelta(days=7) if months is None else add_months(start, months)
