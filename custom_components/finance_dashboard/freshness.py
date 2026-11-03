"""Freshness, import log and monthly validity of the derived data.

Pure functions, no I/O.  Everything here is aggregate: timestamps, counts
and euro differences per month.  No single amount, IBAN or counterparty is
ever written to the log.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .tx_dates import effective_day

LOG_LIMIT = 100
LOG_KEY = "import_log"
KINDS = ("import_attended", "import_scheduled", "reprocess", "processing_upgrade")
IMPORT_KINDS = ("import_attended", "import_scheduled")
REPROCESS_KINDS = ("reprocess", "processing_upgrade")
# Balance types that describe the booked ledger position, best first.
BOOKED_TYPES = ("CLBD", "CLAV", "ITBD", "INTERIMBOOKED", "CLOSINGBOOKED")
TOLERANCE = 0.005


def make_entry(
    kind: str,
    *,
    at: str,
    banks: list[str] | None = None,
    new: int = 0,
    total: int = 0,
    processing_version: int,
    outcome: str,
    duration_ms: int = 0,
) -> dict[str, Any]:
    """One log entry — only counts, bank titles, version and outcome."""
    return {
        "at": at,
        "kind": kind,
        "banks": sorted({str(b) for b in (banks or []) if b}),
        "new": int(new),
        "total": int(total),
        "processing_version": int(processing_version),
        "outcome": str(outcome),
        "duration_ms": int(duration_ms),
    }


def append_log(meta: dict[str, Any], entry: dict[str, Any]) -> None:
    """Append ``entry`` to ``meta[LOG_KEY]`` keeping the newest ``LOG_LIMIT``."""
    log = list(meta.get(LOG_KEY) or [])
    log.append(entry)
    meta[LOG_KEY] = log[-LOG_LIMIT:]


def last_of(log: list[dict[str, Any]], kinds: tuple[str, ...]) -> dict[str, Any] | None:
    """Newest log entry of one of ``kinds`` that did not fail."""
    for entry in reversed(log):
        if entry.get("kind") in kinds and entry.get("outcome") not in (
            "error",
            "unavailable",
            "rate_limited",
        ):
            return entry
    return None


# ---------------------------------------------------------------------------
# Validity
# ---------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _amount(tx: dict[str, Any]) -> float:
    return _num((tx.get("transactionAmount") or {}).get("amount")) or 0.0


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _booked_points(series: list[dict[str, Any]]) -> list[tuple[date, float]]:
    """One (day, amount) point per fetch, preferring a booked balance type."""
    by_at: dict[str, dict[str, float]] = {}
    for p in series:
        amount = _num(p.get("amount"))
        if amount is None or not p.get("at"):
            continue
        by_at.setdefault(str(p["at"]), {})[str(p.get("type", "")).upper()] = amount
    out: list[tuple[date, float]] = []
    for at in sorted(by_at):
        types = by_at[at]
        d = _day(at)
        if d is None:
            continue
        for t in BOOKED_TYPES:
            if t in types:
                out.append((d, types[t]))
                break
    return out


def _next_month(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def monthly_validity(
    accounts: dict[str, dict[str, Any]],
    names: dict[str, str],
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Compare balance movement with the sum of bookings per account and month.

    ``accounts`` is the ledger's ``{key: {transactions, balances}}``.  For a
    month, the first and last balance snapshot inside it span a window; the
    bookings dated after the first snapshot's day up to the last snapshot's
    day must add up to the balance difference.  Fewer than two snapshots on
    different days in the month -> ``unknown``.  Bookings that reach the
    ledger later than a same-day snapshot are the known source of small
    false gaps.
    """
    today = today or date.today()
    result: list[dict[str, Any]] = []
    for key, acct in accounts.items():
        booked = []
        for t in acct.get("transactions") or []:
            d = effective_day(t)
            if d and t.get("_status", "booked") == "booked":
                booked.append((d, _amount(t)))
        points = _booked_points(acct.get("balances") or [])
        days = [d for d, _ in booked] + [d for d, _ in points]
        if not days:
            continue
        name = names.get(key, "")
        cur = min(days).replace(day=1)
        last = max(max(days), today).replace(day=1)
        while cur <= last:
            nxt = _next_month(cur)
            inside = [p for p in points if cur <= p[0] < nxt]
            row: dict[str, Any] = {"month": cur.strftime("%Y-%m"), "account_name": name}
            if len(inside) < 2 or inside[0][0] == inside[-1][0]:
                row.update(status="unknown", diff=None)
            else:
                (d0, b0), (d1, b1) = inside[0], inside[-1]
                moved = sum(a for d, a in booked if d0 < d <= d1)
                diff = round((b1 - b0) - moved, 2)
                row.update(status="ok" if abs(diff) < TOLERANCE else "gap", diff=diff)
            result.append(row)
            cur = nxt
    result.sort(key=lambda r: (r["month"], r["account_name"]), reverse=True)
    return result


def undated_accounts(
    accounts: dict[str, dict[str, Any]], names: dict[str, str]
) -> list[dict[str, Any]]:
    """Accounts whose booked lines carry no date at all (no booking, value or
    transaction date). Such lines are invisible to cycles and series (#107)."""
    out: list[dict[str, Any]] = []
    for key, acct in accounts.items():
        booked = [
            t for t in acct.get("transactions") or [] if t.get("_status", "booked") == "booked"
        ]
        undated = sum(1 for t in booked if effective_day(t) is None)
        if undated:
            out.append(
                {"account_name": names.get(key, ""), "undated": undated, "total": len(booked)}
            )
    out.sort(key=lambda r: r["account_name"])
    return out


def derivation_check(
    ledger_txs: list[dict[str, Any]], derived_txs: list[dict[str, Any]]
) -> dict[str, Any]:
    """No euro lost between the ledger and the categorised/transfer view.

    Sums booked amounts in cents three ways: ledger, derived list, and
    categories plus transfers.  Aggregate only.
    """

    def booked(txs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [t for t in txs if t.get("_status", "booked") == "booked"]

    def cents(txs: list[dict[str, Any]]) -> int:
        return sum(round(_amount(t) * 100) for t in txs)

    ledger_b, derived = booked(ledger_txs), booked(derived_txs)
    transfers: list[dict[str, Any]] = []
    by_cat: dict[str, int] = {}
    for t in derived:
        if (
            t.get("_transfer_role") in ("intermediate", "destination")
            and t.get("_transfer_confirmed") is not False
        ):
            transfers.append(t)
        else:
            cat = t.get("category") or "other"
            by_cat[cat] = by_cat.get(cat, 0) + round(_amount(t) * 100)
    parts = sum(by_cat.values()) + cents(transfers)
    ledger_total, derived_total = cents(ledger_b), cents(derived)
    return {
        "ok": ledger_total == derived_total == parts,
        "diff": round((ledger_total - parts) / 100, 2),
        "ledger_count": len(ledger_b),
        "derived_count": len(derived),
    }


def build_freshness(
    *,
    as_of: str,
    log: list[dict[str, Any]],
    processing_version: int,
    validity: list[dict[str, Any]],
    check: dict[str, Any],
    admin: bool,
    last_bank_success: str | None = None,
    data_quality: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the endpoint payload; non-admins get only ``as_of`` / ``last_import``.

    ``last_bank_success`` covers imports from before the import log existed:
    without a logged import, the newest successful bank fetch is the last import.
    """
    last_import = last_of(log, IMPORT_KINDS)
    li = last_import["at"] if last_import else last_bank_success
    if not admin:
        return {"as_of": as_of, "last_import": li}
    last_rp = last_of(log, REPROCESS_KINDS)
    return {
        "as_of": as_of,
        "last_import": li,
        "last_reprocess": last_rp["at"] if last_rp else None,
        "processing_version": processing_version,
        "log": list(reversed(log)),
        "validity": validity,
        "derivation": check,
        "data_quality": data_quality or [],
    }
