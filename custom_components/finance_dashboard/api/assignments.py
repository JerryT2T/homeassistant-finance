"""Persons & accounts settings endpoint (admin only, cache/config only)."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ..account_identity import account_key
from ..const import DOMAIN
from ..manager import AssignmentError
from ..plan_wizard import earliest_booked_by_key
from ._helpers import _get_manager


class FinanceDashboardAssignmentsView(HomeAssistantView):
    """Who is who: persons, HA-user mapping and account owners."""

    url = f"/api/{DOMAIN}/assignments"
    name = f"api:{DOMAIN}:assignments"
    requires_auth = True

    @staticmethod
    def _is_admin(request: web.Request) -> bool:
        user = request.get("hass_user")
        return bool(user and user.is_admin)

    async def get(self, request: web.Request) -> web.Response:
        """Return persons, HA users, accounts (IBAN last 4 only) and plan persons.

        Each account carries its owner set: ``owner`` (person | "shared" | ""),
        ``household`` (bool, a person account also used for the household) and
        ``owner_kind`` (open | person | person_household | household).
        """
        if not self._is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        users = await hass.auth.async_get_users()
        return self.json(self._with_account_info(manager, manager.get_assignments(users)))

    @staticmethod
    def _with_account_info(manager, payload: dict) -> dict:
        """Additive: per account ``earliest_booked`` (ledger, cache) and ``account_type``."""
        earliest = earliest_booked_by_key(getattr(manager, "_ledger", None))
        types = {
            account_key(a): str(a.get("account_type") or "")
            for a in getattr(manager, "_accounts", []) or []
        }
        for acc in payload.get("accounts", []):
            key = acc.get("key")
            acc["earliest_booked"] = earliest.get(key)
            acc["account_type"] = types.get(key) or None
        return payload

    async def put(self, request: web.Request) -> web.Response:
        """Validate and persist the assignments; returns the GET payload."""
        if not self._is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return self.json(
                {"error": "invalid_body", "detail": "Body must be a JSON object"},
                status_code=400,
            )
        users = await hass.auth.async_get_users()
        try:
            changed = manager.async_set_assignments(body, users)
        except AssignmentError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        if changed:  # re-derive stored bookings from the ledger: no bank call
            await manager.async_apply_owner_change()
        return self.json(self._with_account_info(manager, manager.get_assignments(users)))
