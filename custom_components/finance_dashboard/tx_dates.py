"""The date a transaction happened, whichever field the bank filled.

Some sources deliver no booking date at all: PayPal's own lines carry only
the transaction date. ``bookingDate`` stays untouched (it is part of the
ledger fingerprint); readers that need *a* date use :func:`effective_day`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

_DATE_FIELDS = ("bookingDate", "valueDate", "transactionDate", "bookingDateTime")
# The dates a bill can be cited by; bookingDateTime never differs from bookingDate there.
_CITED_FIELDS = ("bookingDate", "valueDate", "transactionDate")


def _to_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def effective_day(tx: dict[str, Any]) -> date | None:
    """Booking date, else value date, else transaction date (None when none)."""
    for field in _DATE_FIELDS:
        day = _to_date(tx.get(field))
        if day is not None:
            return day
    return None


def effective_date_str(tx: dict[str, Any]) -> str:
    """:func:`effective_day` as ``YYYY-MM-DD``; ``""`` when the row has no date.

    What a list shows, sorts and filters by: PayPal rows must not read as dateless.
    """
    day = effective_day(tx)
    return day.isoformat() if day else ""


def cited_days(tx: dict[str, Any]) -> set[date]:
    """Every date the bank states for the row (a bill may cite any of them)."""
    return {day for field in _CITED_FIELDS if (day := _to_date(tx.get(field))) is not None}


def fingerprint_date(tx: dict[str, Any]) -> str:
    """The date part of a ledger fingerprint, verbatim from the bank.

    ``transactionDate`` joins only as the last resort, so a row that has a
    booking or value date keeps the identity it always had; a PayPal row gets
    one per payment instead of one for every equal payment (#168).
    """
    return str(tx.get("bookingDate") or tx.get("valueDate") or tx.get("transactionDate") or "")


def only_transaction_date(tx: dict[str, Any]) -> bool:
    """The row has a transaction date and neither a booking nor a value date."""
    return bool(tx.get("transactionDate")) and not (tx.get("bookingDate") or tx.get("valueDate"))
