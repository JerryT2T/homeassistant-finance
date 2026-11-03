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

from .contract_kind import series_trait, suggest_kind
from .series_confidence import is_candidate, score_series
from .settlement import (
    TRAIT_USAGE_BASED,
    advance_basis,
    attach,
    booking_key,
    is_settlement,
    is_usage_payee,
    split_settlements,
)
from .text_norm import canonical_name
from .tx_dates import effective_day

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
                "category": "housing_cold",
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
        day = effective_day(txn)
        if day is None:
            continue
        amounts.append(amount)
        dates.append(datetime(day.year, day.month, day.day))

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
# Intervals whose gaps may be whole multiples (skipped weeks or months, #114).
PAUSABLE_INTERVALS = ("weekly", "monthly")
MAX_PAUSE_PERIODS = 4
PAUSE_PATTERN_MIN = 3  # skipped periods within the last 12 that make a pattern
STEADY_PRICE_SPREAD = 1.01  # payments within 1 % count as one price
CATCH_UP_RATIO = 1.8  # a single payment this much higher is a catch-up, not a new price
# Pauses and a tolerated outlier only for a fixed price: random purchases vary (QA #114).
FIXED_PRICE_TOLERANCE = 0.05

PLAN_MODE_AUTO = "auto"  # new price after a confirmed step, else the median (#114)
PLAN_MODE_HIGHEST = "highest"
PLAN_MODE_AVERAGE = "average"
PLAN_MODE_LAST = "last"
PLAN_MODE_MEDIAN = "median"
PLAN_MODE_FIXED = "fixed"
PLAN_MODES = (
    PLAN_MODE_AUTO,
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
    """Yield ``(canonical key, key, negative, date-sorted rows)`` per payee group.

    A group whose spellings already own two or more stored ids ("Acme GmbH"
    and "Acme AG" with user data each) were separate payees before name
    grouping; they stay split by spelling so no stored contract is orphaned.
    """
    for (key, negative), rows in groups.items():
        rows.sort(key=lambda r: r[0])
        names = _names_first_seen(rows)
        if len({series_id(n, negative) for n in names} & known) < 2:
            yield key, key, negative, rows
            continue
        for name in names:
            part = [r for r in rows if _row_name(r) == name]
            yield key, name, negative, part


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


def _auto_amount(mags: list[float]) -> float:
    """New price after a price step, else the median.

    A step is two or more payments at the new amount, or one latest payment
    after a steady price that is no catch-up or double charge (below 1.8x).
    Any other odd payment never moves the plan: the median ignores it.
    """
    last = round(mags[-1], 2)
    tail = 0
    for m in reversed(mags):
        if round(m, 2) != last:
            break
        tail += 1
    before = mags[: len(mags) - tail]
    if before:
        base = statistics.median(before)
        if tail >= 2 and round(base, 2) != last:
            return last
        steady = max(before) <= min(before) * STEADY_PRICE_SPREAD
        if tail == 1 and steady and base and 0.5 < last / base < CATCH_UP_RATIO:
            return last
    return round(statistics.median(mags), 2)


def plan_amount(
    amounts: list[float], mode: str = PLAN_MODE_AUTO, fixed: float | None = None
) -> float:
    """Amount (absolute) a series contributes to the plan, per ``mode``."""
    mags = [abs(a) for a in amounts] or [0.0]
    if mode == PLAN_MODE_AUTO:
        return _auto_amount(mags)
    if mode == PLAN_MODE_FIXED and fixed is not None:
        return round(abs(fixed), 2)
    if mode == PLAN_MODE_AVERAGE:
        return round(sum(mags) / len(mags), 2)
    if mode == PLAN_MODE_LAST:
        return round(mags[-1], 2)
    if mode == PLAN_MODE_MEDIAN:
        return round(statistics.median(mags), 2)
    return round(max(mags), 2)


def _gap_periods(gap: int, nominal: int, tol: int, pausable: bool) -> int:
    """How many periods ``gap`` spans (1 = on time), 0 when it fits none."""
    if abs(gap - nominal) <= tol + 2:
        return 1
    if not pausable:
        return 0
    periods = round(gap / nominal)
    if 2 <= periods <= MAX_PAUSE_PERIODS and abs(gap - periods * nominal) <= tol + 2:
        return periods
    return 0


def _classify_interval(dates: list[date], date_tol: int, allow_pauses: bool = False) -> str | None:
    """Return the interval name when every gap fits it, else None.

    Weekly and monthly series may skip whole periods (a paused meal kit), as
    long as at most a third of the gaps are pauses.
    """
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    med = statistics.median(gaps)
    for name, (nominal, _per_year, min_occ) in INTERVALS.items():
        # weekly must not swallow neighbours; month-based periods drift by calendar
        tol = min(date_tol, 2) if name == "weekly" else date_tol + 2
        if abs(med - nominal) > tol:
            continue
        if len(dates) < min_occ:
            return None
        pausable = allow_pauses and name in PAUSABLE_INTERVALS
        spans = [_gap_periods(g, nominal, tol, pausable) for g in gaps]
        if all(spans) and sum(1 for p in spans if p > 1) * 3 <= len(gaps):
            return name
        return None
    return None


def _pauses(dates: list[date], interval: str, date_tol: int) -> tuple[int, int, int]:
    """``(skipped periods overall, skipped within the last 12 periods,
    longest gap in periods)``."""
    if interval not in PAUSABLE_INTERVALS or len(dates) < 2:
        return 0, 0, 1
    nominal = INTERVALS[interval][0]
    tol = min(date_tol, 2) if interval == "weekly" else date_tol + 2
    spans = [
        max(1, _gap_periods((dates[i + 1] - dates[i]).days, nominal, tol, True))
        for i in range(len(dates) - 1)
    ]
    total = sum(p - 1 for p in spans)
    recent = covered = 0
    for p in reversed(spans):
        if covered >= 12:
            break
        recent += p - 1
        covered += p
    return total, recent, max(spans)


def _amounts_consistent(amounts: list[float], tolerance: float) -> bool:
    """Stable within ``tolerance`` between payments, allowing one price step
    and, in a longer history, one single outlier (a doubled instalment)."""
    if _steady(amounts, tolerance):
        return True
    if len(amounts) < 4:
        return False
    tol = min(tolerance, FIXED_PRICE_TOLERANCE)
    return any(_steady(amounts[:i] + amounts[i + 1 :], tol) for i in range(len(amounts) - 1))


def _steady(amounts: list[float], tolerance: float) -> bool:
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


def detect_series(
    transactions: list[dict[str, Any]],
    *,
    today: date | None = None,
    amount_tolerance: float = SERIES_AMOUNT_TOLERANCE,
    date_tolerance_days: int = SERIES_DATE_TOLERANCE_DAYS,
    overrides: dict[str, dict[str, Any]] | None = None,
    aliases: dict[str, str] | None = None,
    known_ids: set[str] | frozenset[str] = frozenset(),
    merges: dict[str, list[str]] | None = None,
    splits: dict[str, str] | None = None,
    assignments: dict[str, str] | None = None,
    external_ids: set[str] | frozenset[str] = frozenset(),
    _retry: bool = False,
) -> list[dict[str, Any]]:
    """Detect recurring series of any interval in booked transactions.

    The user's structure (#117 E, F): ``merges`` maps a target series id to
    the ids merged into it, ``splits`` a ``payee_key`` to a split mode
    (``reference`` / ``amount``), ``assignments`` a booking key to the series
    id the booking belongs to. ``external_ids`` are ids the caller resolves
    itself (manual contracts): bookings assigned to them never form a series.
    A booking assigned to an id that is neither detected nor external goes
    back to its own payee.

    Pending debits in ``transactions`` never form or price a series; one that
    lands about a period after the last booked payment proves the series is
    alive (``pending_since``), so a debit still pending at month end does not
    read as a missing payment (#115).

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
    assignments = assignments or {}
    assigned: dict[str, list[tuple[date, float, dict[str, Any]]]] = defaultdict(list)
    groups: dict[tuple[str, bool], list[tuple[date, float, dict[str, Any]]]] = defaultdict(list)
    pending: dict[tuple[str, bool], list[tuple[date, float, dict[str, Any]]]] = defaultdict(list)
    for txn in transactions:
        status = txn.get("_status")
        if status not in ("booked", "pending"):
            continue
        raw = txn.get("creditorName", "") or txn.get("debtorName", "")
        day = effective_day(txn)
        if not _normalize_name(raw) or day is None:
            continue
        try:
            amount = float(txn.get("transactionAmount", {}).get("amount", 0))
        except (TypeError, ValueError):
            continue
        if amount == 0:
            continue
        target = assignments.get(booking_key(txn) or "") if status == "booked" else None
        if target:  # assigned by hand: leaves its payee group (#117 F)
            assigned[target].append((day, amount, txn))
            continue
        bucket = groups if status == "booked" else pending
        bucket[(canonical_name(raw), amount < 0)].append((day, amount, txn))

    # Usage-based payees: a settlement never prices or breaks the advance (#116).
    pool: dict[str, list[tuple[date, float, dict[str, Any]]]] = defaultdict(list)
    usage: set[str] = set()
    for (key, negative), rows in list(groups.items()):
        if not negative or not is_usage_payee(rows):
            continue
        usage.add(key)
        rows.sort(key=lambda r: r[0])
        rest, settle = split_settlements(rows)
        if settle and _series_parts(rest, date_tolerance_days, amount_tolerance):
            groups[(key, negative)] = rest
            pool[key] += settle
    for key in usage:
        incoming = groups.get((key, False))
        if not incoming:
            continue
        pool[key] += [r for r in incoming if is_settlement(r[2])]
        rest = [r for r in incoming if not is_settlement(r[2])]
        if rest:
            groups[(key, False)] = rest
        else:
            del groups[(key, False)]
    for rows in pool.values():
        rows.sort(key=lambda r: r[0])

    known = set(known_ids) | set(overrides) | set((aliases or {}).values())
    aliases = aliases or {}
    splits = splits or {}
    out: list[dict[str, Any]] = []
    staged: list[dict[str, Any]] = []
    claimed_by: dict[str, set[int]] = defaultdict(set)
    for canon, key, negative, rows in _keep_known_apart(groups, known):
        names = _names_first_seen(rows)
        name = names[-1]
        payee = alias_key(key, negative)
        parts = _series_parts(rows, date_tolerance_days, amount_tolerance, splits.get(payee))
        if not parts:
            continue
        in_parts = {id(r) for p in parts for r in p.rows}
        loose = [r for r in rows if id(r) not in in_parts]
        # a payee split by spelling: each spelling keeps its own settlements (QA #116)
        mine = (lambda r: True) if key == canon else (lambda r: _row_name(r) == key)
        if negative:
            loose += [r for r in groups.get((canon, False), []) if mine(r)]
        own_pool = [r for r in pool.get(canon, []) if mine(r)] if negative else []
        settle_rows = _settlements_per_part(parts, own_pool)
        claimed = claimed_by[canon]
        # earliest payment keeps the payee id; same day -> the tag decides, not input order
        base = min(range(len(parts)), key=lambda i: (parts[i].rows[0][0], parts[i].tag))
        used: set[str] = set()
        part_pending = _assign_pending(parts, pending.get((key, negative), []))
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
            keys = [alias_key(key, negative)] if i == base else []
            if part.tag:
                keys.append(alias_key(key + part.tag, negative))
            if part.ref:
                keys.append(_ref_alias_key(part.ref, negative))
            staged.append(
                {
                    "sid": sid,
                    "name": name,
                    "negative": negative,
                    "part": part,
                    "pending": list(part_pending[i]),
                    "keys": keys,
                    "payee": payee,
                    "settle": settle_rows[i],
                    "loose": list(loose) if negative else [],
                    "claimed": claimed,
                    "usage": canon in usage,
                    "merged_from": [],
                    "assigned": [],
                    "extra_manual": [],
                }
            )
    live = {st["sid"] for st in staged} | set(external_ids)
    missing = {t for t in assigned if t not in live}
    if missing and not _retry:
        # a booking assigned to a series that is gone goes back to its payee
        return detect_series(
            transactions,
            today=today,
            amount_tolerance=amount_tolerance,
            date_tolerance_days=date_tolerance_days,
            overrides=overrides,
            aliases=aliases,
            known_ids=known_ids,
            merges=merges,
            splits=splits,
            assignments={k: v for k, v in assignments.items() if v not in missing},
            external_ids=external_ids,
            _retry=True,
        )
    staged = _apply_merges(
        _apply_assignments(staged, assigned),
        merges or {},
        date_tolerance_days,
        amount_tolerance,
        overrides,
    )
    for st in staged:
        sid, part, negative = st["sid"], st["part"], st["negative"]
        series = _build_series(
            sid,
            st["name"],
            negative,
            part.rows,
            part.interval,
            today,
            date_tolerance_days,
            overrides,
            st["pending"],
            amount_tolerance,
        )
        keys = st["keys"]
        series["alias_key"] = keys[0]
        series["alias_keys"] = keys
        series["payee_key"] = st["payee"]
        series["split_by"] = splits.get(st["payee"])
        series["merged_from"] = st["merged_from"]
        series["assigned"] = sorted(
            (_assigned_entry(r) for r in st["assigned"]), key=lambda e: e["date"]
        )
        # an assigned refund is no payment, but the booking still belongs here
        series["ledger_ids"] += [
            a["key"] for a in series["assigned"] if a["key"] and a["key"] not in series["ledger_ids"]
        ]
        series["confidence"] = score_series(
            part.rows, part.interval, series["category"], part.ref, series["pauses"]
        )
        series["candidate"] = is_candidate(series["confidence"])
        series["kind_suggested"] = suggest_kind(
            part.rows, part.interval, series["category"], series["confidence"]["reasons"]
        )
        series["kind_trait"] = series_trait(part.rows)
        settlements, candidates = attach(
            st["settle"],
            st["loose"],
            [*(overrides.get(sid, {}).get("settlements") or ()), *st["extra_manual"]],
            today,
            st["claimed"],
        )
        series["settlements"] = settlements
        series["settlement_candidates"] = candidates
        series["advance_at_settlement"] = advance_basis(part.rows, settlements)
        if negative and not series["kind_trait"] and (settlements or st["usage"]):
            series["kind_trait"] = TRAIT_USAGE_BASED
        out.append(series)
    out.sort(key=lambda s: s["annual_cost"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# The user's structure: merges, splits, booking assignments (#117 E, F)
# ---------------------------------------------------------------------------
#
# Applied on every detection, never stored in the ledger: a split forces
# ``_series_parts`` (above), an assigned booking leaves its own payee group
# and joins the chosen series, a merge moves the payments of its sources into
# the target. Ids stay those the detector derives, so undoing any of it
# brings the original series back under their old ids.


def _assigned_entry(row) -> dict[str, Any]:
    txn = row[2]
    return {
        "key": booking_key(txn),
        "date": row[0].isoformat(),
        "amount": round(row[1], 2),
        "name": " ".join(str(txn.get("creditorName") or txn.get("debtorName") or "").split()),
    }


def _apply_assignments(staged, assigned):
    """Bookings the user assigned to a series join it: a payment in the
    series' direction as a payment, the opposite sign (refund, credit) as a
    hand-assigned settlement."""
    if not assigned:
        return staged
    for st in staged:
        rows = assigned.get(st["sid"])
        if not rows:
            continue
        pay = [r for r in rows if (r[1] < 0) == st["negative"]]
        back = [r for r in rows if (r[1] < 0) != st["negative"]]
        part = st["part"]
        if pay:
            st["part"] = _Part(
                sorted([*part.rows, *pay], key=lambda r: r[0]), part.interval, part.tag, part.ref
            )
        st["loose"] = [*st["loose"], *back]
        st["extra_manual"] = [booking_key(r[2]) for r in back]
        st["assigned"] = list(rows)
    return staged


def _apply_merges(
    staged, merges: dict[str, list[str]], date_tol: int, amount_tol: float, overrides=None
):
    """Move the payments of every merge source into its target, with its
    settlements: keyword ones, its loose bookings and the keys assigned by
    hand (stored on the source or via an assignment). A merge whose target is
    not detected right now changes nothing."""
    overrides = overrides or {}
    if not merges:
        return staged
    by_id = {st["sid"]: st for st in staged}
    gone: set[str] = set()
    for target, sources in merges.items():
        tgt = by_id.get(target)
        if tgt is None or target in gone:
            continue
        for sid in sources:
            src = by_id.get(sid)
            if src is None or sid in gone or sid == target:
                continue
            if src["negative"] != tgt["negative"]:  # the API refuses this (merge_sign_mismatch)
                _LOGGER.warning("Skipping a stored merge of an expense and an income series")
                continue
            rows = sorted([*tgt["part"].rows, *src["part"].rows], key=lambda r: r[0])
            found = _as_series(rows, date_tol, amount_tol)
            interval = found[1] if found else tgt["part"].interval
            tgt["part"] = _Part(rows, interval, tgt["part"].tag, tgt["part"].ref)
            tgt["pending"] += src["pending"]
            tgt["assigned"] += src["assigned"]
            tgt["settle"] = sorted([*tgt["settle"], *src["settle"]], key=lambda r: r[0])
            seen = {id(r) for r in tgt["loose"]}
            tgt["loose"] = [*tgt["loose"], *(r for r in src["loose"] if id(r) not in seen)]
            tgt["extra_manual"] = [
                *tgt["extra_manual"],
                *src["extra_manual"],
                *(overrides.get(sid, {}).get("settlements") or ()),
            ]
            tgt["usage"] = tgt["usage"] or src["usage"]
            tgt["merged_from"].append({"id": sid, "name": src["name"]})
            gone.add(sid)
    return [st for st in staged if st["sid"] not in gone]


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
BAND_TOLERANCE = 0.05  # a stream inside a mixed payee keeps its amount; steps are joined
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


REMITTANCE_SAMPLES = 3
REMITTANCE_SAMPLE_LEN = 140


def _remittance_samples(txns: list[dict[str, Any]]) -> list[str]:
    """Distinct purpose texts of the latest bookings, for the contract search (#118)."""
    out: list[str] = []
    for txn in reversed(txns):
        text = " ".join(_remittance(txn).split())[:REMITTANCE_SAMPLE_LEN]
        if text and text not in out:
            out.append(text)
        if len(out) >= REMITTANCE_SAMPLES:
            break
    return out


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
    amounts = [r[1] for r in dedup]
    fixed_price = _steady(amounts, min(amount_tol, FIXED_PRICE_TOLERANCE))
    interval = _classify_interval([r[0] for r in dedup], date_tol, allow_pauses=fixed_price)
    if interval is None or not _amounts_consistent(amounts, amount_tol):
        return None
    return dedup, interval


def _amount_bands(rows, tolerance: float):
    """Rows clustered around their most frequent amounts, each band within
    ``tolerance`` of its anchor; a price step becomes two bands that
    :func:`_join_successors` puts back together."""
    left = list(rows)
    bands: list[list[tuple[date, float, dict[str, Any]]]] = []
    while left:
        counts: dict[float, int] = defaultdict(int)
        for row in left:
            counts[round(abs(row[1]), 2)] += 1
        anchor = max(counts, key=lambda a: (counts[a], a))
        band = [r for r in left if abs(abs(r[1]) - anchor) <= anchor * tolerance]
        left = [r for r in left if r not in band]
        bands.append(sorted(band, key=lambda r: r[0]))
    return bands


def _whole_or_bands(rows, date_tol: int, amount_tol: float, tag: str = "", ref: str = ""):
    whole = _as_series(rows, date_tol, amount_tol)
    if whole:
        return [_Part(whole[0], whole[1], tag, ref)]
    plain = [r for r in rows if not _FINITE_INSTALMENT.search(_remittance(r[2]))]
    found = [
        _as_series(band, date_tol, amount_tol) for band in _amount_bands(plain, BAND_TOLERANCE)
    ]
    streams = sorted(
        (f for f in found if f and _band_is_regular(f[0], f[1], date_tol)),
        key=lambda f: f[0][0][0],
    )
    parts = []
    for rows_, interval in _join_successors(streams, date_tol, amount_tol):
        mid = statistics.median(abs(r[1]) for r in rows_[:MIN_BAND_OCCURRENCES])
        # a band never claims the reference: two bands would fight over it
        parts.append(_Part(rows_, interval, f"{tag}~{_digest(f'{mid:.2f}')}"))
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


SPLIT_REFERENCE = "reference"
SPLIT_AMOUNT = "amount"
SPLIT_MODES = (SPLIT_REFERENCE, SPLIT_AMOUNT)


def _forced_parts(rows, by_ref, date_tol: int, amount_tol: float, force: str) -> list[_Part]:
    """A split the user asked for (#117 E): by contract reference or by amount
    band, even where the detector saw one series. Fewer than two parts -> []."""
    if force == SPLIT_REFERENCE:
        parts: list[_Part] = []
        rest: list[tuple[date, float, dict[str, Any]]] = []
        for ref, rs in by_ref.items():
            found = _as_series(rs, date_tol, amount_tol) if ref else None
            if found:
                parts.append(_Part(found[0], found[1], "#" + _digest(ref), ref))
            else:
                rest += rs
        if rest:
            parts += _whole_or_bands(sorted(rest, key=lambda r: r[0]), date_tol, amount_tol, "#-")
        return parts if len(parts) >= 2 else []
    plain = [r for r in rows if not _FINITE_INSTALMENT.search(_remittance(r[2]))]
    parts = []
    for band in _amount_bands(plain, BAND_TOLERANCE):
        found = _as_series(band, date_tol, amount_tol)
        if found:
            mid = statistics.median(abs(r[1]) for r in found[0][:MIN_BAND_OCCURRENCES])
            parts.append(_Part(found[0], found[1], f"~{_digest(f'{mid:.2f}')}"))
    return parts if len(parts) >= 2 else []


def _series_parts(rows, date_tol: int, amount_tol: float, force: str | None = None) -> list[_Part]:
    """The series inside one payee group (date-sorted ``rows``); ``force`` is
    a split mode the user chose for this payee."""
    by_ref: dict[str, list[tuple[date, float, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        by_ref[contract_reference(_remittance(row[2]))].append(row)
    if force in SPLIT_MODES:
        forced = _forced_parts(rows, by_ref, date_tol, amount_tol, force)
        if forced:
            return forced
    # only a reference whose payments are a series of their own is a contract
    recurring = {
        ref: rs for ref, rs in by_ref.items() if ref and _as_series(rs, date_tol, amount_tol)
    }
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


def _settlements_per_part(parts, pool):
    """Keyword settlements per part: by contract reference, the rest to the
    earliest part (the payee's own series)."""
    out: list[list[tuple[date, float, dict[str, Any]]]] = [[] for _ in parts]
    refs = {p.ref: i for i, p in enumerate(parts) if p.ref}
    base = min(range(len(parts)), key=lambda i: (parts[i].rows[0][0], parts[i].tag))
    for row in pool:
        out[refs.get(contract_reference(_remittance(row[2])), base)].append(row)
    return out


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
    sid = series_id(f"{names[0]} {part.tag or part.ref}", negative)
    n = 1
    while sid in used:  # two tags may still collide; ids within a payee must not
        n += 1
        sid = series_id(f"{names[0]} {part.tag or part.ref} {n}", negative)
    return sid


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
    pending: Any = (),
    amount_tol: float = SERIES_AMOUNT_TOLERANCE,
) -> dict[str, Any]:
    nominal, per_year, _ = INTERVALS[interval]
    dates = [r[0] for r in rows]
    amounts = [r[1] for r in rows]
    ov = overrides.get(sid, {})
    mode = ov.get("plan_mode") if ov.get("plan_mode") in PLAN_MODES else PLAN_MODE_AUTO
    fixed = ov.get("plan_fixed_amount")
    plan = plan_amount(amounts, mode, fixed)

    expected = _add_period(dates[-1], interval)
    alive = _pending_alive(
        dates[-1], expected, pending, plan, nominal, amount_tol, today, date_tol
    )
    last_day = alive or dates[-1]
    next_expected = _add_period(last_day, interval)
    pauses, pauses_recent, longest = _pauses(dates, interval, date_tol)
    # A series that paused before may pause again as long as it did then.
    slack = (longest - 1) * nominal if pauses_recent else 0
    overdue = (today - next_expected).days - slack
    if overdue > 2 * nominal:
        status = STATUS_ENDED
    elif overdue > date_tol:
        status = STATUS_MISSING
    else:
        status = STATUS_ACTIVE

    sign = -1.0 if negative else 1.0
    price_change = None
    step = _price_step(dates, amounts, today)
    if step is not None:
        prev, last, day = step
        price_change = {
            "previous": round(sign * prev, 2),
            "last": round(sign * last, 2),
            "change_pct": round((last - prev) / prev * 100, 1) if prev else None,
            "increase": last > prev,
            "date": day.isoformat(),
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
        "last_seen": last_day.isoformat(),
        "pending_since": alive.isoformat() if alive else None,
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
        "annual_cost": round(plan * per_year, 2),  # full rhythm, pauses ignored
        "pauses": pauses,
        "pauses_recent": pauses_recent,
        "pause_pattern": pauses_recent >= PAUSE_PATTERN_MIN,
        "status": status,
        "price_change": price_change,
        # the bookings' own category: a contract's choice must not feed back into itself (#177)
        "category": _most_common_value(
            [t.get("_own_category") or t.get("category") for t in txns], "other"
        ),
        # bookings of the series, for inherited category and labels (#113); hashes only
        "ledger_ids": [
            f"{t.get('_account_key') or ''}|{t['_ledger_id']}" for t in txns if t.get("_ledger_id")
        ],
        "account_key": _most_common_value([t.get("_account_key") for t in txns], ""),
        "account_type": _most_common_value([t.get("_account_type") for t in txns], "personal"),
        "account_person": _most_common_value([t.get("_account_person") for t in txns], ""),
        "remittance": _remittance_samples(txns),
    }


PRICE_STEP_MAX_AGE_DAYS = 365


def _price_step(
    dates: list[date], amounts: list[float], today: date
) -> tuple[float, float, date] | None:
    """``(previous, new, date)`` of the latest price change, else None.

    The last two payments differ -> that change. Otherwise a step the last
    payments kept (85, 85, 95, 95, 95) still counts within a year, but only
    after a steady previous price: a single outlier in between (a doubled
    instalment) is no step (#116).
    """
    mags = [round(abs(a), 2) for a in amounts]
    if len(mags) < 2:
        return None
    if mags[-1] != mags[-2]:
        return mags[-2], mags[-1], dates[-1]
    i = len(mags) - 1
    while i > 0 and mags[i - 1] == mags[-1]:
        i -= 1
    if i == 0 or (i >= 2 and mags[i - 2] != mags[i - 1]):
        return None
    if (today - dates[i]).days > PRICE_STEP_MAX_AGE_DAYS:
        return None
    return mags[i - 1], mags[-1], dates[i]


PENDING_MAX_AGE_DAYS = 14  # a debit pending longer was most likely dropped by the bank


def _assign_pending(parts, pending):
    """Pending debits per part of one payee (#115, QA): a debit carrying a
    contract reference goes to the part with that reference; otherwise to the
    part whose amounts it is closest to. A tie means the debit cannot tell the
    parts apart and proves nothing."""
    out: list[list[tuple[date, float, dict[str, Any]]]] = [[] for _ in parts]
    if len(parts) == 1:
        out[0] = list(pending)
        return out
    for row in pending:
        ref = contract_reference(_remittance(row[2]))
        pool = [i for i, p in enumerate(parts) if ref and p.ref == ref] or list(range(len(parts)))
        typical = {i: statistics.median(abs(r[1]) for r in parts[i].rows) for i in pool}
        dist = {i: abs(abs(row[1]) - typical[i]) for i in pool}
        best = min(dist.values())
        winners = [i for i, d in dist.items() if d == best]
        if len(winners) == 1:
            out[winners[0]].append(row)
    return out


def _pending_alive(
    last_booked: date,
    expected: date,
    pending: Any,
    plan: float,
    nominal: int,
    amount_tol: float,
    today: date,
    date_tol: int,
) -> date | None:
    """Date of a pending debit that stands for the next payment, else None.

    It must fall on the expected next date (within a quarter period, at least
    the date tolerance), be after the last booked payment, be recent (a debit
    pending for weeks was dropped) and match the plan amount within the series
    tolerance (not a one-off purchase at the same payee).
    """
    window = max(date_tol, nominal / 4)
    hits = [
        day
        for day, amount, _txn in pending
        if day > last_booked
        and abs((day - expected).days) <= window
        and (today - day).days <= PENDING_MAX_AGE_DAYS
        and plan
        and abs(abs(amount) - plan) / plan <= amount_tol
    ]
    return max(hits) if hits else None


def add_months(day: date, months: int) -> date:
    """``day`` plus ``months`` calendar months, clamped to the month length."""
    year, month0 = divmod(day.year * 12 + (day.month - 1) + months, 12)
    month = month0 + 1
    first_next = date(year + (month == 12), month % 12 + 1, 1)
    return date(year, month, min(day.day, (first_next - timedelta(days=1)).day))


def add_period(start: date, interval: str) -> date:
    """Next occurrence after ``start`` (public, see :func:`_add_period`)."""
    return _add_period(start, interval)


def _add_period(start: date, interval: str) -> date:
    """Next occurrence: calendar months for month-based intervals, 7 days weekly."""
    months = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}.get(interval)
    return start + timedelta(days=7) if months is None else add_months(start, months)
