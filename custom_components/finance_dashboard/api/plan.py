"""Budget plan endpoints — the migrated spreadsheet model.

All read endpoints are pure cache reads and never touch the banking API.

Provides:
- BudgetPlanView       — income breakdown, cost ledger, split result
- TransferPlanView     — the monthly transfer choreography
- PlanVsActualView     — planned vs. actually booked, per category and position
- BenchmarkView        — our ratios against German national averages
- PlanPositionView     — create/update/delete a cost position (admin)
- PlanIncomeView       — set a person's income entry (admin)
- PlanImportView       — import a household workbook (admin)
- PlanUploadView       — import an uploaded workbook (admin)
- PlanImportUrlView    — import a Google Sheets link as xlsx (admin)

PRIVACY: individual cost positions name what a specific person spends money on,
so the itemised ledger is admin-only — the same rule the transactions endpoint
follows. Non-admin users receive the aggregates and the shared positions, which
is what the household agreed on collectively.

SECURITY: the import endpoint reads a file path supplied by the caller. Paths
are validated against Home Assistant's allowlist (``allowlist_external_dirs``),
so the endpoint cannot be used to read arbitrary files from the host. The
upload endpoint takes bytes, never a path. The Google Sheets endpoint never
fetches the pasted URL: it extracts the sheet id and builds the export URL
against docs.google.com itself (see ``sheet_source``).
"""

from __future__ import annotations

import logging

from aiohttp import ClientError, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import DOMAIN, OWNER_SHARED
from ..sheet_source import SheetSourceError, decode_upload, fetch_google_sheet
from ._helpers import _get_manager, admin_denied
from .refunds import load_refund_inputs

_LOGGER = logging.getLogger(__name__)


def _month_year(request: web.Request) -> tuple[int | None, int | None]:
    """Read optional ``month``/``year`` query parameters.

    Invalid values fall back to None (current month) instead of erroring — a
    stray query string must not break the dashboard.
    """

    def _parse(name: str, low: int, high: int) -> int | None:
        raw = request.query.get(name)
        if not raw:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if low <= value <= high else None

    return (_parse("month", 1, 12), _parse("year", 1970, 2200))


def _is_admin(request: web.Request) -> bool:
    """Whether the calling user is a Home Assistant admin."""
    user = request.get("hass_user")
    return bool(user and user.is_admin)


class FinanceDashboardBudgetPlanView(HomeAssistantView):
    """Income breakdown, cost ledger and resulting split."""

    url = f"/api/{DOMAIN}/budget_plan"
    name = f"api:{DOMAIN}:budget_plan"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the plan for the requested month (cache read)."""
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        month, year = _month_year(request)
        view = manager.get_budget_plan_view(month, year)

        if not _is_admin(request):
            # Aggregates and shared positions only — individual positions are
            # another person's private spending.
            view = dict(view)
            view["positions"] = [
                position
                for position in view.get("positions", [])
                if position.get("owner") == OWNER_SHARED
            ]
            view["restricted"] = True

        return self.json(view)


class FinanceDashboardTransferPlanView(HomeAssistantView):
    """The monthly transfer choreography."""

    url = f"/api/{DOMAIN}/transfer_plan"
    name = f"api:{DOMAIN}:transfer_plan"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the transfer plan for the requested month (cache read, admin)."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        month, year = _month_year(request)
        return self.json(manager.get_transfer_plan(month, year))


class FinanceDashboardPlanVsActualView(HomeAssistantView):
    """Planned figures against what the bank actually booked."""

    url = f"/api/{DOMAIN}/plan_vs_actual"
    name = f"api:{DOMAIN}:plan_vs_actual"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the plan-vs-actual comparison (cache read)."""
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        month, year = _month_year(request)
        await load_refund_inputs(hass)  # manual allocations + labels (#119)
        result = manager.get_plan_vs_actual(month, year)

        if not _is_admin(request):
            result = dict(result)
            result.pop("positions", None)
            result["restricted"] = True

        return self.json(result)


class FinanceDashboardBenchmarkView(HomeAssistantView):
    """Our spending ratios against German national averages."""

    url = f"/api/{DOMAIN}/benchmark"
    name = f"api:{DOMAIN}:benchmark"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return benchmark comparisons (cache read, no external fetch, admin)."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        month, year = _month_year(request)
        return self.json(await manager.async_get_benchmarks(month, year))


class FinanceDashboardPlanPositionView(HomeAssistantView):
    """Create, update or delete a single cost position."""

    url = f"/api/{DOMAIN}/budget_plan/position"
    name = f"api:{DOMAIN}:budget_plan:position"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Create or update a cost position (admin only)."""
        hass = request.app["hass"]
        if not _is_admin(request):
            return self.json({"error": "Admin required"}, status_code=403)
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        try:
            data = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON"}, status_code=400)

        try:
            position = await manager.async_set_cost_position(data)
        except ValueError as err:
            return self.json({"error": str(err)}, status_code=400)
        except Exception:
            _LOGGER.exception("Saving cost position failed")
            return self.json({"error": "Saving the position failed"}, status_code=500)

        return self.json({"ok": True, "position": position})

    async def delete(self, request: web.Request) -> web.Response:
        """Delete a cost position by id (admin only)."""
        hass = request.app["hass"]
        if not _is_admin(request):
            return self.json({"error": "Admin required"}, status_code=403)
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        position_id = request.query.get("id")
        if not position_id:
            return self.json({"error": "Missing id"}, status_code=400)

        removed = await manager.async_delete_cost_position(position_id)
        if not removed:
            return self.json({"error": "Unknown position"}, status_code=404)
        return self.json({"ok": True})


class FinanceDashboardPlanIncomeView(HomeAssistantView):
    """Set a person's planned income."""

    url = f"/api/{DOMAIN}/budget_plan/income"
    name = f"api:{DOMAIN}:budget_plan:income"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Create or update one person's income entry (admin only)."""
        hass = request.app["hass"]
        if not _is_admin(request):
            return self.json({"error": "Admin required"}, status_code=403)
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        try:
            data = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON"}, status_code=400)

        try:
            entry = await manager.async_set_income(data)
        except ValueError as err:
            return self.json({"error": str(err)}, status_code=400)
        except Exception:
            _LOGGER.exception("Saving income entry failed")
            return self.json({"error": "Saving the income entry failed"}, status_code=500)

        return self.json({"ok": True, "income": entry})


class FinanceDashboardPlanImportView(HomeAssistantView):
    """Import a household workbook into the budget plan."""

    url = f"/api/{DOMAIN}/budget_plan/import"
    name = f"api:{DOMAIN}:budget_plan:import"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Replace the plan with the contents of a workbook (admin only).

        The path must lie inside a directory Home Assistant is configured to
        allow (``allowlist_external_dirs``) or inside the config directory.
        Without that check this endpoint would read any file on the host.
        """
        hass = request.app["hass"]
        if not _is_admin(request):
            return self.json({"error": "Admin required"}, status_code=403)
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        try:
            data = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON"}, status_code=400)

        path = str(data.get("path") or "").strip()
        if not path:
            return self.json({"error": "Missing path"}, status_code=400)

        if not hass.config.is_allowed_path(path):
            _LOGGER.warning("Spreadsheet import rejected — path not allowed")
            return self.json(
                {
                    "error": (
                        "Path not allowed. Add its directory to "
                        "allowlist_external_dirs in configuration.yaml, or place "
                        "the file in the config directory."
                    )
                },
                status_code=400,
            )

        try:
            report = await manager.async_import_spreadsheet(path)
        except FileNotFoundError:
            return self.json({"error": "File not found"}, status_code=404)
        except ImportError as err:
            return self.json({"error": str(err)}, status_code=500)
        except ValueError as err:
            return self.json({"error": str(err)}, status_code=400)
        except Exception:
            _LOGGER.exception("Spreadsheet import failed")
            return self.json({"error": "Import failed — see the log"}, status_code=500)

        return self.json({"ok": True, "report": report})


async def _import_bytes(view: HomeAssistantView, manager, data: bytes) -> web.Response:
    """Replace the plan with an in-memory workbook; shared by upload and link."""
    try:
        report = await manager.async_import_spreadsheet_bytes(data)
    except ImportError as err:
        return view.json({"error": str(err)}, status_code=500)
    except ValueError as err:
        return view.json({"error": str(err)}, status_code=400)
    except Exception:
        _LOGGER.exception("Spreadsheet import failed")
        return view.json({"error": "Import failed — see the log"}, status_code=500)
    return view.json({"ok": True, "report": report})


class FinanceDashboardPlanUploadView(HomeAssistantView):
    """Import an uploaded household workbook into the budget plan."""

    url = f"/api/{DOMAIN}/budget_plan/upload"
    name = f"api:{DOMAIN}:budget_plan:upload"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Replace the plan with an uploaded workbook (admin only).

        Body: ``{"content_base64": "..."}`` — the ``.xlsx`` file, at most 5 MB.
        """
        hass = request.app["hass"]
        if not _is_admin(request):
            return self.json({"error": "Admin required"}, status_code=403)
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        try:
            data = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON"}, status_code=400)

        try:
            workbook = decode_upload(str(data.get("content_base64") or ""))
        except SheetSourceError as err:
            return self.json({"error": str(err)}, status_code=400)

        return await _import_bytes(self, manager, workbook)


class FinanceDashboardPlanImportUrlView(HomeAssistantView):
    """Import a Google Sheets spreadsheet into the budget plan."""

    url = f"/api/{DOMAIN}/budget_plan/import_url"
    name = f"api:{DOMAIN}:budget_plan:import_url"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Replace the plan with a Google spreadsheet (admin only).

        Body: ``{"url": "https://docs.google.com/spreadsheets/d/<id>/..."}``.
        The sheet must be shared as "anyone with the link".
        """
        hass = request.app["hass"]
        if not _is_admin(request):
            return self.json({"error": "Admin required"}, status_code=403)
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)

        try:
            data = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON"}, status_code=400)

        try:
            workbook = await fetch_google_sheet(
                async_get_clientsession(hass), str(data.get("url") or "")
            )
        except SheetSourceError as err:
            return self.json({"error": str(err)}, status_code=400)
        except ClientError:
            _LOGGER.warning("Google Sheets download failed")
            return self.json(
                {"error": "Google Sheets could not be reached"}, status_code=502
            )

        return await _import_bytes(self, manager, workbook)
