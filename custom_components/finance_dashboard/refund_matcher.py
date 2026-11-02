"""Match insurance / health refunds to the expenses they pay back (#119).

A private insurer pays a doctor's or pharmacy bill back days to weeks later,
often in another budget cycle. Left alone the refund counts as income and the
bill as a full expense. This module finds which refund belongs to which
expense(s): pure functions over the booking list, no I/O, no clock, no AI.

Signals, strongest first:

- **Service dates in the remittance** ("KV-LSTG. 12.08.2026"): every cited
  date points at an expense of that day.
- **Amount**: the refund equals one open expense (full) or the sum of a few
  (subset sum); a refund below an expense refunds it in part.
- **Payee**: the refund comes from an insurer / health fund; the expense goes
  to a medical payee, is in the health category or carries the label
  ``refundable``.
- **Window**: the expense lies at most ``WINDOW_DAYS`` before the refund.

One refund may cover several expenses and one expense may be refunded in
parts, so the result is an allocation ``{refund: {expense: amount}}``. Each
match carries a confidence; only matches at or above ``CONFIDENT`` are applied
automatically, the rest are proposals the user decides on. A manual choice
(``manual``: refund -> expense ids) replaces the automatic one for that refund.

Booking ids are ``labels.booking_key`` (``<account>|<ledger id>``); bookings
without a ledger id fall back to ``transactionId``.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from itertools import combinations
from typing import Any

from .labels import booking_key
from .life_areas import INSURER
from .tx_dates import effective_day

WINDOW_DAYS = 56  # up to 8 weeks between the bill and the refund
CONFIDENT = 0.7  # at or above: applied without asking
PROPOSAL_MIN = 0.35  # below: not even worth a question
MAX_POOL = 12  # subset-sum search is bounded: C(12, k) stays small
MAX_SUBSET = 4
LABEL_REFUNDABLE = "refundable"
_EPS = 0.005

_DATE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})?(?!\d)")
_HEALTH_TEXT = re.compile(
    r"kv-?\s?lstg|leistungsabrechnung|krankenversicher|krankenkasse|beihilfe|arztrechnung"
    r"|heilbehandl|behandlungskosten|erstattung\w*\s+(?:ihrer\s+)?(?:rechnung|arzt|kosten)",
    re.IGNORECASE,
)
_INSURER_NAME = re.compile(r"kranken|versicher|assekuranz|beihilfe", re.IGNORECASE)
_MEDICAL = re.compile(
    r"(?<![a-zäöüß])(dr\.?|prof\.?|arzt|ärzt\w*|praxis|apotheke|klinik\w*|krankenhaus|physio\w*"
    r"|zahn\w*|therap\w*|labor|augen\w*|optik\w*|ortho\w*|radiolog\w*|hausarzt|facharzt"
    r"|sanitätshaus|hörakustik\w*|med\.|mvz|heilprakt\w*|psycho\w*)",
    re.IGNORECASE,
)


def ref_id(txn: dict[str, Any]) -> str:
    """Booking id used in allocations."""
    return booking_key(txn) or str(txn.get("transactionId") or "")


def _amount(txn: dict[str, Any]) -> float:
    try:
        return float((txn.get("transactionAmount") or {}).get("amount", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _payee(txn: dict[str, Any]) -> str:
    return str(txn.get("creditorName") or txn.get("debtorName") or "")


def _text(txn: dict[str, Any]) -> str:
    return str(txn.get("remittanceInformationUnstructured") or "")


def _cents(value: float) -> int:
    return round(value * 100)


def _days(txn: dict[str, Any]) -> set[date]:
    """Every date the bill might be cited by: booking, value and transaction date."""
    out: set[date] = set()
    for field in ("bookingDate", "valueDate", "transactionDate"):
        try:
            out.add(date.fromisoformat(str(txn.get(field))[:10]))
        except (TypeError, ValueError):
            continue
    return out


def is_refund_source(txn: dict[str, Any]) -> bool:
    """An incoming booking from an insurer / health fund."""
    if _amount(txn) <= 0:
        return False
    name, text = _payee(txn), _text(txn)
    return bool(
        INSURER.search(name) or _INSURER_NAME.search(name) or _HEALTH_TEXT.search(text)
    )


def is_medical_expense(txn: dict[str, Any], labels: dict[str, list[str]] | None = None) -> bool:
    """An outgoing booking that insurance may pay back."""
    if _amount(txn) >= 0:
        return False
    if LABEL_REFUNDABLE in ((labels or {}).get(ref_id(txn)) or ()):
        return True
    return txn.get("category") == "health" or bool(_MEDICAL.search(_payee(txn)))


def cited_dates(text: str, around: date) -> list[date]:
    """Dates named in a remittance text; a missing year takes ``around``'s."""
    out: list[date] = []
    for d, m, y in _DATE.findall(text):
        year = int(y) if y else around.year
        year += 2000 if year < 100 else 0  # noqa: PLR2004
        try:
            day = date(year, int(m), int(d))
        except ValueError:
            continue
        if not y and day > around:
            day = day.replace(year=day.year - 1)
        if day not in out:
            out.append(day)
    return out


def _fill(amount_c: int, expenses: list[tuple[str, int]]) -> dict[str, int]:
    """Spread ``amount_c`` over ``expenses`` (id, open cents) in the given order."""
    out: dict[str, int] = {}
    left = amount_c
    for eid, cap in expenses:
        if left <= 0:
            break
        take = min(left, cap)
        if take > 0:
            out[eid] = take
            left -= take
    return out


def split_manual(
    refund: dict[str, Any], expenses: list[dict[str, Any]], used: dict[str, int] | None = None
) -> dict[str, float]:
    """Amounts for a hand-picked set of expenses: oldest first, capped at what is open."""
    used = used or {}
    ordered = sorted(expenses, key=lambda t: (effective_day(t) or date.min, ref_id(t)))
    caps = [(ref_id(t), max(0, -_cents(_amount(t)) - used.get(ref_id(t), 0))) for t in ordered]
    return {k: v / 100 for k, v in _fill(_cents(_amount(refund)), caps).items()}


def _score_cited(allocated: int, amount_c: int, n_cited: int, n_hit: int) -> float:
    if n_hit == 0:
        return 0.0
    if allocated == amount_c and n_hit == n_cited:
        return 0.95
    if allocated == amount_c:
        return 0.85  # amount fully explained, a cited date found nothing
    if n_hit == n_cited:
        return 0.6  # insurer paid more than the cited bills: the rest is unexplained
    return 0.45


def _match_one(
    refund: dict[str, Any],
    pool: list[dict[str, Any]],
    open_c: dict[str, int],
) -> tuple[dict[str, int], float, str]:
    """Best allocation of one refund over ``pool``: ``(cents per expense, confidence, why)``."""
    amount_c = _cents(_amount(refund))
    rday = effective_day(refund)
    if rday is None:
        return {}, 0.0, ""
    lo = rday - timedelta(days=WINDOW_DAYS)
    near = [
        t for t in pool
        if open_c.get(ref_id(t), 0) > 0
        and (d := effective_day(t)) is not None
        and lo <= d <= rday + timedelta(days=3)
    ]
    if not near:
        return {}, 0.0, ""

    # 1. service dates cited in the text
    wanted = cited_dates(_text(refund), rday)
    if wanted:
        picked: list[dict[str, Any]] = []
        for day in wanted:
            hits = [t for t in near if day in _days(t) and t not in picked]
            if len(hits) > 1:  # same day twice: prefer the amount the refund can cover
                hits.sort(key=lambda t: abs(open_c[ref_id(t)] - amount_c))
            if hits:
                picked.append(hits[0])
        if picked:
            alloc = _fill(amount_c, [(ref_id(t), open_c[ref_id(t)]) for t in picked])
            score = _score_cited(sum(alloc.values()), amount_c, len(wanted), len(picked))
            return alloc, score, "service_date"

    # 2. amount: one expense in full, else a small subset adding up exactly
    by_age = sorted(near, key=lambda t: effective_day(t) or date.min, reverse=True)
    single = [t for t in by_age if open_c[ref_id(t)] == amount_c]
    if single:
        # the same amount twice (two identical bills) cannot be told apart
        return {ref_id(single[0]): amount_c}, 0.85 if len(single) == 1 else 0.5, "amount"
    pool_small = by_age[:MAX_POOL]
    found: list[tuple[str, ...]] = []
    for size in range(2, MAX_SUBSET + 1):
        for combo in combinations(pool_small, size):
            if sum(open_c[ref_id(t)] for t in combo) == amount_c:
                found.append(tuple(ref_id(t) for t in combo))
        if found:
            break
    if found:
        return {k: open_c[k] for k in found[0]}, 0.75 if len(found) == 1 else 0.5, "subset"

    # 3. partial: a smaller refund against the one open bigger bill
    bigger = [t for t in by_age if open_c[ref_id(t)] > amount_c]
    if bigger:
        return {ref_id(bigger[0]): amount_c}, 0.55 if len(bigger) == 1 else 0.4, "partial"
    return {}, 0.0, ""


def analyse(
    txns: list[dict[str, Any]],
    *,
    manual: dict[str, list[str]] | None = None,
    labels: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Allocations and proposals over ``txns``.

    Returns ``{"allocations": {refund: {expense: amount}}, "proposals": [...],
    "confidence": {refund: score}}``. ``allocations`` holds the manual choices
    and the confident automatic matches; ``proposals`` the unsure ones
    (``refund``, ``allocation``, ``confidence``, ``reason``). Booked lines only.
    """
    manual = manual or {}
    booked = [
        t for t in txns
        if t.get("_status", "booked") == "booked" and effective_day(t) is not None and ref_id(t)
    ]
    by_id = {ref_id(t): t for t in booked}
    open_c = {ref_id(t): -_cents(_amount(t)) for t in booked if _amount(t) < 0}
    allocations: dict[str, dict[str, float]] = {}
    confidence: dict[str, float] = {}

    # manual choices first: they use up expenses before the automatic pass
    for rid, eids in manual.items():
        refund = by_id.get(rid)
        if refund is None or _amount(refund) <= 0:
            continue
        picked = [by_id[e] for e in eids if e in by_id and _amount(by_id[e]) < 0]
        alloc = split_manual(refund, picked, {k: -_cents(_amount(by_id[k])) - v
                                              for k, v in open_c.items()})
        allocations[rid] = alloc
        confidence[rid] = 1.0
        for eid, amount in alloc.items():
            open_c[eid] -= _cents(amount)

    pool = [t for t in booked if is_medical_expense(t, labels)]
    refunds = sorted(
        (t for t in booked if is_refund_source(t) and ref_id(t) not in manual),
        key=lambda t: (effective_day(t), ref_id(t)),
    )
    proposals: list[dict[str, Any]] = []
    for refund in refunds:
        rid = ref_id(refund)
        alloc_c, score, why = _match_one(refund, pool, open_c)
        if not alloc_c or score < PROPOSAL_MIN:
            continue
        alloc = {k: v / 100 for k, v in alloc_c.items()}
        if score >= CONFIDENT:
            allocations[rid] = alloc
            confidence[rid] = score
            for eid, cents in alloc_c.items():
                open_c[eid] -= cents
        else:
            proposals.append(
                {"refund": rid, "allocation": alloc, "confidence": score, "reason": why}
            )
    return {"allocations": allocations, "proposals": proposals, "confidence": confidence}


def match_refunds(
    txns: list[dict[str, Any]],
    *,
    manual: dict[str, list[str]] | None = None,
    labels: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, float]]:
    """``{refund id: {expense id: refunded amount}}`` for the confident matches."""
    return analyse(txns, manual=manual, labels=labels)["allocations"]


def open_claims(
    txns: list[dict[str, Any]],
    allocations: dict[str, dict[str, float]],
    labels: dict[str, list[str]],
    *,
    today: date,
) -> list[dict[str, Any]]:
    """Expenses labelled ``refundable`` that no refund has covered in full yet."""
    paid: dict[str, int] = {}
    for alloc in allocations.values():
        for eid, amount in alloc.items():
            paid[eid] = paid.get(eid, 0) + _cents(amount)
    out = []
    for t in txns:
        rid = ref_id(t)
        if _amount(t) >= 0 or t.get("_status", "booked") != "booked" or not rid:
            continue
        if LABEL_REFUNDABLE not in (labels.get(rid) or ()):
            continue
        left = -_cents(_amount(t)) - paid.get(rid, 0)
        day = effective_day(t)
        if left > 0 and day is not None:
            out.append(
                {"id": rid, "date": day.isoformat(), "open": left / 100,
                 "age_days": (today - day).days}
            )
    return sorted(out, key=lambda r: r["date"])


def net_refunds(
    counted: list[dict[str, Any]], allocations: dict[str, dict[str, float]]
) -> list[dict[str, Any]]:
    """Counted bookings with matched refunds netted into their expenses.

    The expense keeps its date, category and owner and shrinks by the refunded
    amount (so it lands in the expense's cycle); the refund leaves income. A
    refund part whose expense is not counted (a transfer, say) stays as it was.
    """
    present = {ref_id(t) for t in counted}
    reduce_c: dict[str, int] = {}
    keep_c: dict[str, int] = {}
    for rid, alloc in allocations.items():
        for eid, amount in alloc.items():
            if eid in present:
                reduce_c[eid] = reduce_c.get(eid, 0) + _cents(amount)
                keep_c[rid] = keep_c.get(rid, 0) - _cents(amount)
    by_id = {ref_id(t): t for t in counted}
    for rid in list(keep_c):
        if rid in by_id:
            keep_c[rid] += _cents(_amount(by_id[rid]))
        else:
            del keep_c[rid]
    out: list[dict[str, Any]] = []
    for t in counted:
        rid = ref_id(t)
        if rid in reduce_c and _amount(t) < 0:
            left = max(0, -_cents(_amount(t)) - reduce_c[rid])
            if left <= 0:
                continue
            t = _with_amount(t, -left / 100)
        elif rid in keep_c and _amount(t) > 0:
            left = keep_c[rid]
            if left <= 0:
                continue
            t = _with_amount(t, left / 100)
            t["_refund_role"] = None  # the rest is income, not the detector's refund
        out.append(t)
    return out


def _with_amount(txn: dict[str, Any], amount: float) -> dict[str, Any]:
    copy = dict(txn)
    copy["transactionAmount"] = {**(txn.get("transactionAmount") or {}), "amount": f"{amount:.2f}"}
    return copy
