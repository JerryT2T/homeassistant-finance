"""Household summary endpoint - honest numbers per income cycle (cache read)."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ..const import DOMAIN
from ..household_summary import CYCLES
from ._helpers import _get_manager
from .refunds import load_refund_inputs


class FinanceDashboardHouseholdSummaryView(HomeAssistantView):
    """``GET /api/finance_dashboard/household_summary?cycle=current|previous``.

    Aggregates only - no booking lists. Non-admins (and anyone whose HA user
    maps to a person) see other persons' personal accounts as totals only.
    """

    url = f"/api/{DOMAIN}/household_summary"
    name = f"api:{DOMAIN}:household_summary"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the cycle summary (pure cache read)."""
        cycle = request.query.get("cycle", "current")
        if cycle not in CYCLES:
            return self.json({"error": "Invalid cycle"}, status_code=400)
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        user = request.get("hass_user")
        is_admin = bool(user and user.is_admin)
        person = manager.resolve_person(user)
        # An admin who is a person sees the person view only on request.
        if is_admin and request.query.get("view") != "person":
            person = None
        await load_refund_inputs(request.app["hass"])  # manual allocations + labels (#119)
        return self.json(
            manager.get_household_summary(cycle=cycle, person=person, is_admin=is_admin)
        )
