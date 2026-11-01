"""Label catalogue and per-booking labels (#113). Cache only, admin edits."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ..const import DOMAIN
from ..contracts import async_get_store
from ..labels import LabelError, async_get_label_store
from ._helpers import _get_manager, admin_denied


async def _json_body(request: web.Request) -> dict | None:
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _error(view: HomeAssistantView, err: LabelError) -> web.Response:
    status = 404 if err.code == "unknown_label" else 400
    return view.json({"error": err.code, "detail": err.detail}, status_code=status)


class FinanceDashboardLabelsView(HomeAssistantView):
    """``GET`` the catalogue; ``POST {name}`` adds an own label (admin)."""

    url = f"/api/{DOMAIN}/labels"
    name = f"api:{DOMAIN}:labels"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        store = await async_get_label_store(request.app["hass"])
        return self.json({"labels": store.catalogue()})

    async def post(self, request: web.Request) -> web.Response:
        if denied := admin_denied(self, request):
            return denied
        body = await _json_body(request)
        if body is None:
            return self.json({"error": "invalid_body"}, status_code=400)
        store = await async_get_label_store(request.app["hass"])
        try:
            lid = store.add(body.get("name"))
        except LabelError as err:
            return _error(self, err)
        await store.async_save()
        return self.json({"id": lid, "labels": store.catalogue()})


class FinanceDashboardLabelView(HomeAssistantView):
    """``PUT {name}`` renames, ``DELETE`` removes an own label everywhere (admin)."""

    url = f"/api/{DOMAIN}/labels/{{label_id}}"
    name = f"api:{DOMAIN}:label"
    requires_auth = True

    async def put(self, request: web.Request, label_id: str) -> web.Response:
        if denied := admin_denied(self, request):
            return denied
        body = await _json_body(request)
        if body is None:
            return self.json({"error": "invalid_body"}, status_code=400)
        store = await async_get_label_store(request.app["hass"])
        try:
            store.rename(label_id, body.get("name"))
        except LabelError as err:
            return _error(self, err)
        await store.async_save()
        return self.json({"labels": store.catalogue()})

    async def delete(self, request: web.Request, label_id: str) -> web.Response:
        if denied := admin_denied(self, request):
            return denied
        hass = request.app["hass"]
        store = await async_get_label_store(hass)
        try:
            store.remove(label_id)
        except LabelError as err:
            return _error(self, err)
        contracts = await async_get_store(hass)
        changed = False
        for contract in contracts.contracts.values():
            if contract.labels and label_id in contract.labels:
                contract.labels = [i for i in contract.labels if i != label_id] or None
                changed = True
        await store.async_save()
        if changed:
            await contracts.async_save()
        return self.json({"labels": store.catalogue()})


class FinanceDashboardBookingLabelsView(HomeAssistantView):
    """``PUT {labels: [...]}`` sets the own labels of one booking (admin)."""

    url = f"/api/{DOMAIN}/transactions/{{ledger_id}}/labels"
    name = f"api:{DOMAIN}:booking_labels"
    requires_auth = True

    async def put(self, request: web.Request, ledger_id: str) -> web.Response:
        if denied := admin_denied(self, request):
            return denied
        body = await _json_body(request)
        if body is None:
            return self.json({"error": "invalid_body"}, status_code=400)
        manager = _get_manager(request.app["hass"])
        known = manager and any(
            t.get("_ledger_id") == ledger_id for t in manager._transactions  # noqa: SLF001
        )
        if not known:
            return self.json({"error": "unknown_booking"}, status_code=404)
        store = await async_get_label_store(request.app["hass"])
        try:
            labels = store.set_booking(ledger_id, body.get("labels"))
        except LabelError as err:
            return _error(self, err)
        await store.async_save()
        return self.json({"ledger_id": ledger_id, "labels_own": labels})


VIEWS = [FinanceDashboardLabelsView, FinanceDashboardLabelView, FinanceDashboardBookingLabelsView]
