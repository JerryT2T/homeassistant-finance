"""Hand-made refund allocations (#119).

The matcher decides automatically; this store holds what the user decided
instead: per refund booking the list of expense bookings it pays back (an empty
list = "this refund pays nothing back"). Keys are ``labels.booking_key``.
Amounts are not stored; they are derived on every read (``split_manual``).
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION

STORAGE_KEY_REFUNDS = f"{DOMAIN}_refunds"
MAX_EXPENSES = 50
_MAX_KEY = 200


class RefundError(ValueError):
    """Invalid request; ``code`` goes to the API response."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


class RefundStore:
    """``.storage/finance_dashboard_refunds``."""

    def __init__(self, hass: HomeAssistant | None, store: Any | None = None) -> None:
        if store is None:
            store = Store(hass, STORAGE_VERSION, STORAGE_KEY_REFUNDS)
        self._store = store
        self.manual: dict[str, list[str]] = {}

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        manual = raw.get("manual") if isinstance(raw, dict) else None
        manual = manual if isinstance(manual, dict) else {}
        self.manual = {
            str(k): [e for e in v if isinstance(e, str)][:MAX_EXPENSES]
            for k, v in manual.items()
            if isinstance(v, list)
        }

    async def async_save(self) -> None:
        await self._store.async_save({"manual": self.manual})

    def set(self, refund: Any, expenses: Any) -> list[str]:
        if not isinstance(refund, str) or not refund or len(refund) > _MAX_KEY:
            raise RefundError("invalid_id", "unknown booking")
        if (
            not isinstance(expenses, list)
            or len(expenses) > MAX_EXPENSES
            or any(not isinstance(e, str) or not e or len(e) > _MAX_KEY for e in expenses)
        ):
            raise RefundError(
                "invalid_expenses", f"expenses must be a list of at most {MAX_EXPENSES} ids"
            )
        clean = list(dict.fromkeys(expenses))
        if refund in clean:
            raise RefundError("invalid_expenses", "a booking cannot refund itself")
        self.manual[refund] = clean
        return clean

    def clear(self, refund: str) -> None:
        """Back to the automatic match."""
        self.manual.pop(refund, None)


async def async_get_refund_store(hass: HomeAssistant) -> RefundStore:
    """The loaded store, cached in ``hass.data``."""
    data = hass.data.setdefault(DOMAIN, {})
    store = data.get("_refund_store")
    if store is None:
        store = RefundStore(hass)
        await store.async_load()
        data["_refund_store"] = store
    return store
