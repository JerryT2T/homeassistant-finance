"""The date a transaction happened, whichever field the bank filled.

Some sources deliver no booking date at all: PayPal's own lines carry only
the transaction date. ``bookingDate`` stays untouched (it is part of the
ledger fingerprint); readers that need *a* date use :func:`effective_day`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

_DATE_FIELDS = ("bookingDate", "valueDate", "transactionDate", "bookingDateTime")


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
