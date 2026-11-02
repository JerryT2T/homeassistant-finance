"""Advance payments and annual settlements of usage-based contracts (#116).

Electricity, gas, district heating, water and service charges are paid as a
monthly **advance** plus a yearly **settlement**: a back-payment or a refund.
The advance is the series; a settlement must neither price it nor break it.

- A settlement is found by keyword (Abrechnung, Nachzahlung, Erstattung,
  Guthaben, Schlussrechnung) at a payee that shows advance or energy words,
  or assigned by hand from the payee's other bookings. A statistical outlier
  heuristic is deliberately not used (concept decision 8).
- The expected next settlement is the last one (within 18 months) minus the
  yearly effect of an advance change made after it: the utility raises the
  advance precisely to close that gap. A back-payment becomes a reserve, a
  refund lowers the contract's yearly cost.

Pure functions; amounts are in the bank sign (expense negative).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .life_areas import INSURER

TRAIT_USAGE_BASED = "usage_based"
SOURCE_KEYWORD = "keyword"
SOURCE_MANUAL = "manual"
RECENT_DAYS = 548  # a settlement older than ~18 months no longer predicts the next one
CANDIDATE_DAYS = 730
MAX_CANDIDATES = 10
MAX_MANUAL = 50

_SETTLEMENT = re.compile(
    r"(abrechnung|nachzahlung|erstattung|guthaben|schlussrechnung)", re.IGNORECASE
)
# an advance row may cite the last bill ("Abschlag lt. Abrechnung 2025"): still an advance (QA #116)
_ADVANCE = re.compile(r"(abschlag|vorauszahlung)", re.IGNORECASE)
_USAGE = re.compile(
    r"\b(abschlag\w*|\w*vorauszahlung\w*|stadtwerke\w*|\w*strom\w*|gas|erdgas\w*"
    r"|\w*energie\w*|\w*wasser\w*|fernw(?:ä|ae)rme\w*|heiz\w*|nebenkosten\w*"
    r"|betriebskosten\w*)\b",
    re.IGNORECASE,
)


def _remittance(txn: dict[str, Any]) -> str:
    text = str(txn.get("remittanceInformationUnstructured") or "")
    if not text:
        text = " ".join(str(a) for a in txn.get("remittanceInformationUnstructuredArray") or [])
    return text


def booking_key(txn: dict[str, Any]) -> str | None:
    """Same key as ``labels.booking_key``: the ledger id is unique per account only."""
    lid = txn.get("_ledger_id")
    return f"{txn.get('_account_key') or ''}|{lid}" if lid else None


def is_settlement(txn: dict[str, Any]) -> bool:
    text = _remittance(txn)
    return bool(_SETTLEMENT.search(text)) and not _ADVANCE.search(text)


def is_usage_payee(rows: list[tuple[date, float, dict[str, Any]]]) -> bool:
    """The payee's bookings name an advance or a metered supply - never an
    insurer: water-damage cover and its premium refund are no settlement."""
    texts = [
        f"{_remittance(t)} {t.get('creditorName') or t.get('debtorName') or ''}"
        for _day, _amount, t in rows
    ]
    if not texts or any(INSURER.search(t) for t in texts):
        return False
    # most bookings, not one: a PayPal stream with one "Energie Drink" is no utility (QA #116)
    return sum(1 for t in texts if _USAGE.search(t)) * 2 > len(texts)


def split_settlements(rows):
    """``(advance rows, settlement rows)`` of one outgoing payee group.

    Only a usage payee is split, and only when the settlements are the
    minority: a monthly "Kreditkartenabrechnung" stays a normal series.
    """
    if not is_usage_payee(rows):
        return rows, []
    settle = [r for r in rows if is_settlement(r[2])]
    rest = [r for r in rows if not is_settlement(r[2])]
    if not settle or not rest or len(settle) * 2 >= len(rows):
        return rows, []
    return rest, settle


def entry(row, source: str) -> dict[str, Any]:
    day, amount, txn = row
    return {
        "date": day.isoformat(),
        "amount": round(amount, 2),
        "key": booking_key(txn),
        "source": source,
    }


def attach(
    pool,
    loose,
    manual: list[str] | tuple[str, ...],
    today: date,
    claimed: set[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(settlements, candidates)`` of one series.

    ``pool`` are the payee's keyword settlements, ``loose`` its bookings that
    belong to no series (both signs). ``claimed`` collects the rows already
    given to a series of the same payee, so no row is attached twice.
    """
    manual_set = set(manual or ())
    out: list[dict[str, Any]] = []
    for row in pool:
        if id(row) not in claimed:
            claimed.add(id(row))
            out.append(entry(row, SOURCE_KEYWORD))
    candidates: list[dict[str, Any]] = []
    cutoff = today - timedelta(days=CANDIDATE_DAYS)
    for row in loose:
        if id(row) in claimed:
            continue
        key = booking_key(row[2])
        if key and key in manual_set:
            claimed.add(id(row))
            out.append(entry(row, SOURCE_MANUAL))
        elif key and row[0] >= cutoff:
            candidates.append(entry(row, ""))
    out.sort(key=lambda e: e["date"])
    candidates.sort(key=lambda e: e["date"], reverse=True)
    return out, candidates[:MAX_CANDIDATES]


def advance_basis(rows, settlements: list[dict[str, Any]]) -> float | None:
    """The advance (absolute) paid up to the last settlement, from the full
    payment history of the series - not the last 12 shown (QA #116)."""
    if not settlements:
        return None
    last_day = date.fromisoformat(settlements[-1]["date"])
    before = [abs(r[1]) for r in rows if r[0] <= last_day]
    return round(before[-1], 2) if before else None


def expected(
    settlements: list[dict[str, Any]],
    basis: float | None,
    current: float,
    per_year: int,
    today: date,
) -> dict[str, Any] | None:
    """The next settlement, in plan sign (positive = back-payment), or None.

    ``basis`` is the advance before the last settlement, ``current`` today's
    advance (both absolute).
    """
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    recent = [s for s in settlements if s["date"] >= cutoff]
    if not recent:
        return None
    last_day = recent[-1]["date"]
    # a settlement may come as several bookings within a few weeks (bill + correction)
    window = (date.fromisoformat(last_day) - timedelta(days=45)).isoformat()
    back = -sum(s["amount"] for s in recent if s["date"] >= window)
    step = (abs(current) - basis) if basis is not None else 0.0
    amount = round(back - step * per_year, 2)
    due = max(date.fromisoformat(last_day) + timedelta(days=365), today)  # overdue: due now
    return {
        "last_date": last_day,
        "last_amount": round(back, 2),
        "advance_step": round(step, 2),
        "amount": amount,
        "next_due": due.isoformat(),
        "monthly_reserve": round(max(amount, 0.0) / 12, 2),
    }
