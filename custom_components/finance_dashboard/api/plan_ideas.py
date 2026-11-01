"""Spreadsheet-as-idea-source endpoint (admin only, cache only - never a bank call).

View classes (registered via ``VIEWS``):

* ``FinanceDashboardSheetIdeasView``  ``POST /api/finance_dashboard/plan_wizard/sheet_ideas``

Body ``{"content_base64": "..."}`` (upload) or ``{"url": "<google sheets link>"}``.
Only position names are read from the sheet; the plan is never written.
"""

from __future__ import annotations

import logging

from aiohttp import web
from aiohttp.client_exceptions import ClientError
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .. import plan_ideas
from ..const import DOMAIN
from ..sheet_source import SheetSourceError, decode_upload, fetch_google_sheet
from ._helpers import _get_manager, admin_denied

_LOGGER = logging.getLogger(__name__)


class FinanceDashboardSheetIdeasView(HomeAssistantView):
    """Names from a budget sheet, matched against the ledger; nothing is imported."""

    url = f"/api/{DOMAIN}/plan_wizard/sheet_ideas"
    name = f"api:{DOMAIN}:plan_wizard_sheet_ideas"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return self.json({"error": "Invalid JSON"}, status_code=400)
        try:
            if body.get("content_base64"):
                workbook = decode_upload(str(body["content_base64"]))
            elif body.get("url"):
                workbook = await fetch_google_sheet(async_get_clientsession(hass), str(body["url"]))
            else:
                return self.json({"error": "Provide content_base64 or url"}, status_code=400)
        except SheetSourceError as err:
            return self.json({"error": str(err)}, status_code=400)
        except ClientError:
            _LOGGER.warning("Google Sheets download failed")
            return self.json({"error": "Google Sheets could not be reached"}, status_code=502)
        try:
            result = await plan_ideas.async_sheet_ideas(
                hass, manager, workbook, dt_util.now().date()
            )
        except Exception:  # noqa: BLE001 - a malformed workbook must not 500 the wizard
            _LOGGER.warning("Sheet ideas could not be built", exc_info=True)
            return self.json({"error": "The spreadsheet could not be read"}, status_code=400)
        return self.json(result)


VIEWS = [FinanceDashboardSheetIdeasView]
