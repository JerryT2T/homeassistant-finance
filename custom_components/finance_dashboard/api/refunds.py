"""Insurance refunds matched to their expenses (#119). Cache only, admin only.

``GET /refunds`` lists the open claims and the matches waiting for a decision;
``GET/PUT/DELETE /refunds/{ledger_id}`` read, set or reset the allocation of one
booking (the refund side decides: a PUT names the expenses it pays back).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import DOMAIN
from ..labels import async_get_label_store, booking_key
from ..refund_matcher import WINDOW_DAYS, open_claims, ref_id
from ..refund_store import RefundError, async_get_refund_store
from ..tx_dates import effective_day
from ._helpers import _get_manager, admin_denied


async def load_refund_inputs(hass: HomeAssistant) -> None:
    """Make the manual allocations and booking labels available to the manager."""
    await async_get_refund_store(hass)
    await async_get_label_store(hass)


def _amount(txn: dict[str, Any]) -> float:
    try:
        return float((txn.get("transactionAmount") or {}).get("amount", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _row(txn: dict[str, Any]) -> dict[str, Any]:
    day = effective_day(txn)
    return {
        "id": ref_id(txn),
        "date": day.isoformat() if day else "",
        "amount": _amount(txn),
        "party": txn.get("creditorName") or txn.get("debtorName") or "",
        "description": txn.get("remittanceInformationUnstructured") or "",
    }


def candidates_for(refund: dict[str, Any], txns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expenses a refund may pay back: booked, before it, at most the window earlier."""
    rday = effective_day(refund)
    out = []
    for t in txns:
        day = effective_day(t)
        if (
            _amount(t) >= 0
            or t.get("_status", "booked") != "booked"
            or day is None
            or rday is None
            or not ref_id(t)
            or not 0 <= (rday - day).days <= WINDOW_DAYS
        ):
            continue
        out.append(t)
    return sorted(out, key=lambda t: effective_day(t) or date.min, reverse=True)


def describe(manager, ledger_id: str, manual: dict[str, list[str]]) -> dict[str, Any] | None:
    """The refund state of one booking, or ``None`` for an unknown id."""
    txns = manager._transactions  # noqa: SLF001
    txn = next((t for t in txns if booking_key(t) == ledger_id), None)
    if txn is None:
        return None
    result = manager.get_refund_analysis()
    alloc, proposals = result["allocations"], result["proposals"]
    by_id = {ref_id(t): t for t in txns}
    is_manual = ledger_id in manual
    out: dict[str, Any] = {"ledger_id": ledger_id, "kind": "refund" if _amount(txn) > 0 else "expense"}
    if _amount(txn) > 0:
        mine = alloc.get(ledger_id, {})
        out["allocated"] = [
            {**_row(by_id[e]), "refunded": amt} for e, amt in mine.items() if e in by_id
        ]
        out["source"] = ("manual" if is_manual else "auto") if mine or is_manual else None
        prop = next((p for p in proposals if p["refund"] == ledger_id), None)
        out["proposal"] = (
            {"confidence": prop["confidence"], "reason": prop["reason"],
             "expenses": [e for e in prop["allocation"] if e in by_id]}
            if prop else None
        )
        out["candidates"] = [_row(t) for t in candidates_for(txn, txns)]
    else:
        out["refunded"] = [
            {**_row(by_id[r]), "refunded": a[ledger_id]}
            for r, a in alloc.items()
            if ledger_id in a and r in by_id
        ]
    return out


class FinanceDashboardRefundsView(HomeAssistantView):
    """``GET`` open claims and proposals (admin)."""

    url = f"/api/{DOMAIN}/refunds"
    name = f"api:{DOMAIN}:refunds"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if denied := admin_denied(self, request):
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        await load_refund_inputs(hass)
        labels = (await async_get_label_store(hass)).bookings
        result = manager.get_refund_analysis()
        from homeassistant.util import dt as dt_util  # noqa: PLC0415

        return self.json(
            {
                "open_claims": open_claims(
                    manager._transactions,  # noqa: SLF001
                    result["allocations"],
                    labels,
                    today=dt_util.now().date(),
                ),
                "proposals": result["proposals"],
                "matched": len(result["allocations"]),
            }
        )


class FinanceDashboardRefundView(HomeAssistantView):
    """``GET`` one booking's state, ``PUT {expenses: [...]}`` assigns, ``DELETE`` resets (admin)."""

    url = f"/api/{DOMAIN}/refunds/{{ledger_id}}"
    name = f"api:{DOMAIN}:refund"
    requires_auth = True

    async def _context(self, request: web.Request, ledger_id: str):
        if denied := admin_denied(self, request):
            return denied, None, None
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404), None, None
        await load_refund_inputs(hass)
        store = await async_get_refund_store(hass)
        return None, manager, store

    async def get(self, request: web.Request, ledger_id: str) -> web.Response:
        denied, manager, store = await self._context(request, ledger_id)
        if denied:
            return denied
        info = describe(manager, ledger_id, store.manual)
        if info is None:
            return self.json({"error": "unknown_booking"}, status_code=404)
        return self.json(info)

    async def put(self, request: web.Request, ledger_id: str) -> web.Response:
        denied, manager, store = await self._context(request, ledger_id)
        if denied:
            return denied
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return self.json({"error": "invalid_body"}, status_code=400)
        txns = manager._transactions  # noqa: SLF001
        by_key = {booking_key(t): t for t in txns if booking_key(t)}
        refund = by_key.get(ledger_id)
        if refund is None:
            return self.json({"error": "unknown_booking"}, status_code=404)
        expenses = body.get("expenses")
        if _amount(refund) <= 0:
            return self.json({"error": "not_a_refund"}, status_code=400)
        if isinstance(expenses, list) and any(
            e not in by_key or _amount(by_key[e]) >= 0 for e in expenses
        ):
            return self.json({"error": "unknown_expense"}, status_code=400)
        try:
            store.set(ledger_id, expenses)
        except RefundError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        await store.async_save()
        return self.json(describe(manager, ledger_id, store.manual))

    async def delete(self, request: web.Request, ledger_id: str) -> web.Response:
        denied, manager, store = await self._context(request, ledger_id)
        if denied:
            return denied
        store.clear(ledger_id)
        await store.async_save()
        info = describe(manager, ledger_id, store.manual)
        if info is None:
            return self.json({"error": "unknown_booking"}, status_code=404)
        return self.json(info)


VIEWS = [FinanceDashboardRefundsView, FinanceDashboardRefundView]

