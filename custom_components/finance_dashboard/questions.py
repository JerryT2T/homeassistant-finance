"""Open questions: booked expenses the categoriser could not place.

A question is a *merchant*, not a booking: all open "other" expenses of the
cycle from one merchant collapse into one question with a count and total.
Bookings inside a transfer chain never become questions.  At most
``WEEKLY_QUESTIONS`` are offered per calendar week (answered ones count
against the quota), ordered by euro impact.  Each question carries its
bookings (date, amount, own account, counterparty, IBAN last four digits,
remittance text) and how often the merchant shows up over the whole history,
so the user can recognise what they are being asked about.  Pure functions;
no I/O.
"""

from __future__ import annotations

from datetime import date
from typing import Any

WEEKLY_QUESTIONS = 10
SAMPLE_DATES = 3
MAX_BOOKINGS = 8


def merchant_history(bookings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per merchant over all given bookings: ``{count, first, last, months}``.

    ``months`` is the number of distinct calendar months the merchant appeared
    in -- "12 of 12 months" reads as a standing order, "1" as a one-off.
    """
    out: dict[str, dict[str, Any]] = {}
    for b in bookings:
        key = b.get("merchant")
        if not key:
            continue
        h = out.setdefault(key, {"count": 0, "first": b["date"], "last": b["date"], "months": set()})
        h["count"] += 1
        h["first"] = min(h["first"], b["date"])
        h["last"] = max(h["last"], b["date"])
        h["months"].add((b["date"].year, b["date"].month))
    return {
        k: {"count": h["count"], "first": h["first"].isoformat(), "last": h["last"].isoformat(),
            "months": len(h["months"])}
        for k, h in out.items()
    }


def select_questions(
    candidates: list[dict[str, Any]],
    *,
    week_answered: int = 0,
    suggest: Any = None,
    history: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Group candidates per merchant; return ``(visible, total_backlog)``.

    ``candidates``: dicts with ``merchant`` (key), ``display``, ``amount``
    (bank amount, expense negative), ``date`` and optional ``lid``,
    ``account``, ``counterparty``, ``counter_iban`` (last four digits only)
    and ``text``.  ``history`` comes from :func:`merchant_history`.
    ``total_backlog`` is the number of merchants waiting overall.
    """
    groups: dict[str, dict[str, Any]] = {}
    for c in candidates:
        key = c.get("merchant")
        if not key:
            continue
        g = groups.setdefault(
            key,
            {"id": key, "merchant": c.get("display") or key, "count": 0, "total": 0.0,
             "dates": [], "booking_ids": [], "bookings": []},
        )
        g["count"] += 1
        g["total"] += abs(float(c["amount"]))
        g["dates"].append(c["date"])
        if c.get("lid"):
            g["booking_ids"].append(c["lid"])
        g["bookings"].append(c)
    ordered = sorted(groups.values(), key=lambda g: (-g["total"], g["id"]))
    quota = max(0, WEEKLY_QUESTIONS - max(0, week_answered))
    visible = []
    for g in ordered[:quota]:
        dates = sorted(g.pop("dates"), reverse=True)[:SAMPLE_DATES]
        g["total"] = round(g["total"], 2)
        g["dates"] = [d.isoformat() for d in dates]
        rows = sorted(g.pop("bookings"), key=lambda c: c["date"], reverse=True)[:MAX_BOOKINGS]
        g["bookings"] = [
            {"date": c["date"].isoformat(), "amount": round(float(c["amount"]), 2),
             "account": c.get("account") or "", "counterparty": c.get("counterparty") or "",
             "iban_last4": c.get("counter_iban") or "", "text": c.get("text") or ""}
            for c in rows
        ]
        g["history"] = (history or {}).get(g["id"])
        g["suggested"] = suggest(g["id"]) if suggest else []
        visible.append(g)
    return visible, len(ordered)


# ---------------------------------------------------------------------------
# Contract questions (#117 B, G)
# ---------------------------------------------------------------------------

QUESTION_CONTRACT = "contract"
QUESTION_PRICE = "price"
MAX_CONTRACT_QUESTIONS = 5  # per week, before the merchant questions
PRICE_QUESTION_DAYS = 60  # a price jump older than this is no longer news
CANDIDATE_ANSWERS = ("contract", "subscription", "regular", "irregular", "coincidence")
PRICE_ANSWERS = ("new_price", "one_off")
STEADY_PRICE_SPREAD = 1.01  # as recurring.STEADY_PRICE_SPREAD


def _price_open(c: dict[str, Any], today: date) -> bool:
    """The last payment differs from the one before and nobody answered it yet."""
    pc = c.get("price_change")
    dates = c.get("dates") or []
    if not pc or not dates or pc.get("date") != dates[-1] or c.get("status") == "ended":
        return False
    stored = (c.get("contract") or {}).get("stored") or {}
    if stored.get("price_reviewed") == pc["date"]:
        return False
    # only a jump after a steady price: amounts that always vary have no "price"
    before = [abs(a) for a in (c.get("amounts") or [])[:-1]]
    if len(before) < 2 or max(before) > min(before) * STEADY_PRICE_SPREAD:
        return False
    return (today - date.fromisoformat(pc["date"])).days <= PRICE_QUESTION_DAYS


def contract_questions(
    contracts: list[dict[str, Any]], *, today: date, limit: int = MAX_CONTRACT_QUESTIONS
) -> tuple[list[dict[str, Any]], int]:
    """Candidates ("Vertrag, Abo, regelmäßige Ausgabe oder Zufall?") and
    price jumps ("neuer Preis oder einmaliger Betrag?") as question cards;
    returns ``(visible, total)``. ``contracts`` are admin views of
    :func:`contracts.build_contracts`; the question id is ``<type>:<series id>``.
    """
    cands = sorted(
        (c for c in contracts if c.get("candidate") and c.get("status") != "ended"),
        key=lambda c: (-float(c.get("annual_cost") or 0), c["id"]),
    )
    prices = sorted(
        (c for c in contracts if not c.get("candidate") and _price_open(c, today)),
        key=lambda c: (-abs(float(c["price_change"].get("change_pct") or 0)), c["id"]),
    )
    out: list[dict[str, Any]] = [
        {
            "type": QUESTION_CONTRACT,
            "id": f"{QUESTION_CONTRACT}:{c['id']}",
            "series_id": c["id"],
            "merchant": c.get("display_name") or c.get("creditor"),
            "interval": c.get("interval"),
            "count": c.get("occurrences", 0),
            "monthly": c.get("monthly_equivalent"),
            "last_amount": c.get("last_amount"),
            "dates": list(reversed(c.get("dates") or []))[:SAMPLE_DATES],
            "reasons": list((c.get("confidence") or {}).get("reasons") or []),
            "suggested_kind": c.get("kind_suggested"),
        }
        for c in cands
    ]
    out += [
        {
            "type": QUESTION_PRICE,
            "id": f"{QUESTION_PRICE}:{c['id']}",
            "series_id": c["id"],
            "merchant": c.get("display_name") or c.get("creditor"),
            "interval": c.get("interval"),
            "previous": c["price_change"]["previous"],
            "last": c["price_change"]["last"],
            "change_pct": c["price_change"].get("change_pct"),
            "date": c["price_change"]["date"],
        }
        for c in prices
    ]
    return out[: max(0, limit)], len(out)
