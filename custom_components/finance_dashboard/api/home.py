"""Home-screen and pot endpoints.

Provides:
- HomeView  — the home-screen payload (cache read, never a bank call)
- PotsView  — create / update / delete pots
- PotCarryView — accept / drop a pot's carry-over into the current week (admin)

PRIVACY: the person view is bound to the logged-in HA user (mapped to a person
through the accounts' ``ha_users``); there is no parameter to look at another
person's data. The household view shows other persons' pots only as totals.

Pot write access: HA admins may manage every pot. Other users may manage only
their *own personal* pots - never shared pots and never another person's.
"""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ..const import DOMAIN
from ..home import HORIZONS, VIEWS
from ..pots import CARRY_ACTIONS
from ._helpers import _get_manager
from .refunds import load_refund_inputs

_LOGGER = logging.getLogger(__name__)


def _is_admin(request: web.Request) -> bool:
    user = request.get("hass_user")
    return bool(user and user.is_admin)


class FinanceDashboardHomeView(HomeAssistantView):
    """Home screen: Heute / Woche / Zyklus / Jahr for a person or the household."""

    url = f"/api/{DOMAIN}/home"
    name = f"api:{DOMAIN}:home"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the home payload (pure cache read)."""
        hass = request.app["hass"]
        horizon = request.query.get("horizon", "cycle")
        view = request.query.get("view", "person")
        if horizon not in HORIZONS or view not in VIEWS:
            return self.json({"error": "Invalid horizon or view"}, status_code=400)

        manager = _get_manager(hass)
        want_demo = request.query.get("demo") in ("1", "true")
        user = request.get("hass_user")

        if manager is None:
            if not want_demo:
                return self.json({"error": "Not configured"}, status_code=404)
            from ..demo import generate_demo_home

            person = None
            if view == "person":
                person = "Anna"  # demo has no HA-user mapping
            return self.json(
                generate_demo_home(
                    person=person, view=view, horizon=horizon, include_recent=_is_admin(request)
                )
            )

        person = manager.resolve_person(user)
        try:
            await load_refund_inputs(hass)  # manual allocations + labels (#119)
        except Exception:  # noqa: BLE001 - the home view must not depend on the refund hint
            _LOGGER.debug("Refund inputs unavailable", exc_info=True)
        year_inputs = None
        if horizon == "year" and not (want_demo or getattr(manager, "demo_mode", False) is True):
            try:
                year_inputs = await manager.async_year_inputs(is_admin=_is_admin(request))
            except Exception:  # noqa: BLE001 - the year renders without the extras
                _LOGGER.debug("Year inputs unavailable", exc_info=True)
        return self.json(
            manager.get_home(
                person=person,
                view=view,
                horizon=horizon,
                demo=want_demo,
                include_recent=_is_admin(request),  # individual bookings: admin only
                year_inputs=year_inputs,
            )
        )


class FinanceDashboardPotsView(HomeAssistantView):
    """Create, update or delete a pot."""

    url = f"/api/{DOMAIN}/pots"
    name = f"api:{DOMAIN}:pots"
    requires_auth = True

    def _allowed(self, request: web.Request, manager, owner: str) -> bool:
        if _is_admin(request):
            return True
        person = manager.resolve_person(request.get("hass_user"))
        return bool(person) and owner == person

    async def _read(self, request: web.Request):
        try:
            data = await request.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def post(self, request: web.Request) -> web.Response:
        """Create a pot (admin: any owner; others: own personal pots)."""
        return await self._save(request, replace=False)

    async def put(self, request: web.Request) -> web.Response:
        """Update a pot (same gating as create, also on the existing owner)."""
        return await self._save(request, replace=True)

    async def _save(self, request: web.Request, *, replace: bool) -> web.Response:
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        data = await self._read(request)
        if data is None:
            return self.json({"error": "Invalid JSON"}, status_code=400)

        owner = str(data.get("owner") or "shared")
        if replace:
            existing = next((p for p in manager.pots if p.id == data.get("id")), None)
            if existing is None:
                return self.json({"error": "Unknown pot"}, status_code=404)
            if not self._allowed(request, manager, existing.owner):
                return self.json({"error": "Not allowed"}, status_code=403)
        if not self._allowed(request, manager, owner):
            return self.json({"error": "Not allowed"}, status_code=403)

        try:
            pot = await manager.async_save_pot(data, replace=replace)
        except ValueError as err:
            return self.json({"error": str(err)}, status_code=400)
        except Exception:
            _LOGGER.exception("Saving pot failed")
            return self.json({"error": "Saving the pot failed"}, status_code=500)
        return self.json({"ok": True, "pot": pot}, status_code=200 if replace else 201)

    async def delete(self, request: web.Request) -> web.Response:
        """Delete a pot by id."""
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        pot_id = request.query.get("id")
        if not pot_id:
            return self.json({"error": "Missing id"}, status_code=400)
        existing = next((p for p in manager.pots if p.id == pot_id), None)
        if existing is None:
            return self.json({"error": "Unknown pot"}, status_code=404)
        if not self._allowed(request, manager, existing.owner):
            return self.json({"error": "Not allowed"}, status_code=403)
        await manager.async_delete_pot(pot_id)
        return self.json({"ok": True})


class FinanceDashboardPotCarryView(HomeAssistantView):
    """``POST /pots/carry`` ``{"id", "action": "accept"|"drop"}`` (admin only).

    Decides what happens with the balance a pot carries into the *current* week
    ("Übertrag übernehmen / verwerfen"). Idempotent: repeating the same action
    changes nothing; the last action for the week wins. No bank call.
    """

    url = f"/api/{DOMAIN}/pots/carry"
    name = f"api:{DOMAIN}:pots:carry"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        if not _is_admin(request):
            return self.json({"error": "Admin only"}, status_code=403)
        try:
            data = await request.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return self.json({"error": "Invalid JSON"}, status_code=400)
        pot_id, action = str(data.get("id") or ""), str(data.get("action") or "")
        if not pot_id or action not in CARRY_ACTIONS:
            return self.json({"error": "Need id and action accept|drop"}, status_code=400)
        result = await manager.async_set_pot_carry(pot_id, action)
        if result is None:
            return self.json({"error": "Unknown pot"}, status_code=404)
        return self.json({"ok": True, **result})
