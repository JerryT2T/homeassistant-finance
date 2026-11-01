"""AI consent endpoints (admin only, no bank or AI call).

View classes (registered via ``VIEWS``):

* ``FinanceDashboardAiConsentsView``  ``GET/PUT /api/finance_dashboard/setup/ai/consents``
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .. import ai_consent as consent
from ..const import DOMAIN
from ._helpers import admin_denied

# Shown next to each consent switch: at most 3 pros and 3 risks, i18n keys.
PURPOSE_TEXTS: dict[str, dict[str, list[str]]] = {
    "categorize": {
        "pros": [f"ai.purpose.categorize.pro{i}" for i in (1, 2, 3)],
        "risks": [f"ai.purpose.categorize.risk{i}" for i in (1, 2, 3)],
    },
    "sheet_analysis": {
        "pros": [f"ai.purpose.sheet_analysis.pro{i}" for i in (1, 2, 3)],
        "risks": [f"ai.purpose.sheet_analysis.risk{i}" for i in (1, 2, 3)],
    },
}


def purposes_view() -> dict[str, dict]:
    return {p: {"mode": meta["mode"], **PURPOSE_TEXTS[p]} for p, meta in consent.PURPOSES.items()}


class FinanceDashboardAiConsentsView(HomeAssistantView):
    """Per-purpose AI consent: what is sent, and whether the user agreed."""

    url = f"/api/{DOMAIN}/setup/ai/consents"
    name = f"api:{DOMAIN}:setup_ai_consents"
    requires_auth = True

    async def _payload(self, hass) -> dict:
        return {"consents": await consent.async_load(hass), "purposes": purposes_view()}

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        return self.json(await self._payload(request.app["hass"]))

    async def put(self, request: web.Request) -> web.Response:
        """Body ``{"purpose": "categorize"|"sheet_analysis", "granted": bool}``."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        try:
            body = await request.json()
        except ValueError:
            body = None
        if (
            not isinstance(body, dict)
            or body.get("purpose") not in consent.PURPOSES
            or not isinstance(body.get("granted"), bool)
        ):
            return self.json(
                {"error": "invalid_body", "detail": "Need purpose (known) and granted (boolean)"},
                status_code=400,
            )
        hass = request.app["hass"]
        await consent.async_set(hass, body["purpose"], body["granted"])
        return self.json(await self._payload(hass))


VIEWS = [FinanceDashboardAiConsentsView]
