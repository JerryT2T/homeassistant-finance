"""Ownership endpoints (admin only, cache + merchant memory, never a bank call).

* ``POST /api/finance_dashboard/ownership/correct``    owner of a booking / merchant
* ``POST /api/finance_dashboard/ownership/series``     owner of a recurring series
* ``GET|PUT /api/finance_dashboard/ownership/household-categories``
* ``POST /api/finance_dashboard/ownership/ai-review``  AI pass over unclear merchants
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from ..const import DOMAIN
from ..manager._questions import QuestionError
from ._helpers import _get_manager, admin_denied


async def _body(request: web.Request) -> dict | None:
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


class _OwnershipView(HomeAssistantView):
    requires_auth = True

    def _manager(self, request: web.Request):
        return _get_manager(request.app["hass"])

    def _bad(self, err: QuestionError) -> web.Response:
        return self.json({"error": err.code, "detail": err.detail}, status_code=400)


class FinanceDashboardOwnerCorrectView(_OwnershipView):
    """``POST {ledger_id, owner, reach}``: owner = person | "shared" | null (undo);
    reach = "booking" | "merchant" ("für alle von X merken"). Any booking."""

    url = f"/api/{DOMAIN}/ownership/correct"
    name = f"api:{DOMAIN}:ownership:correct"

    async def post(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager = self._manager(request)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _body(request)
        if body is None:
            return self.json({"error": "invalid_body"}, status_code=400)
        try:
            return self.json(
                await manager.async_correct_owner(
                    ledger_id=body.get("ledger_id"),
                    owner=body.get("owner"),
                    reach=body.get("reach"),
                )
            )
        except QuestionError as err:
            return self._bad(err)


class FinanceDashboardOwnerSeriesView(_OwnershipView):
    """``POST {series_id, owner, ledger_ids?}``: decide a recurring series once."""

    url = f"/api/{DOMAIN}/ownership/series"
    name = f"api:{DOMAIN}:ownership:series"

    async def post(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager = self._manager(request)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _body(request)
        if body is None:
            return self.json({"error": "invalid_body"}, status_code=400)
        try:
            return self.json(
                await manager.async_set_series_owner(
                    series_id=body.get("series_id"),
                    owner=body.get("owner"),
                    ledger_ids=body.get("ledger_ids"),
                )
            )
        except QuestionError as err:
            return self._bad(err)


class FinanceDashboardHouseholdCategoriesView(_OwnershipView):
    """``GET`` the categories counted as household on a {person, household} account;
    ``PUT {categories: [...] | null}`` sets them (null = defaults)."""

    url = f"/api/{DOMAIN}/ownership/household-categories"
    name = f"api:{DOMAIN}:ownership:household_categories"

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager = self._manager(request)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        return self.json(manager.get_household_categories())

    async def put(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager = self._manager(request)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _body(request)
        if body is None or "categories" not in body:
            return self.json({"error": "invalid_body"}, status_code=400)
        try:
            return self.json(await manager.async_set_household_categories(body["categories"]))
        except QuestionError as err:
            return self._bad(err)


class FinanceDashboardAiReviewView(_OwnershipView):
    """``POST {merchants: [merchant keys]}``: category + shared/personal tendency
    for those merchants. Needs the categorisation consent and AI budget; the
    counters say what happened (``reason`` when refused). Spends AI calls only."""

    url = f"/api/{DOMAIN}/ownership/ai-review"
    name = f"api:{DOMAIN}:ownership:ai_review"

    async def post(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager = self._manager(request)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _body(request)
        merchants = (body or {}).get("merchants")
        if not isinstance(merchants, list) or not all(isinstance(m, str) for m in merchants):
            return self.json({"error": "invalid_body"}, status_code=400)
        return self.json(await manager.async_ai_review_pass(merchants))


VIEWS = [
    FinanceDashboardOwnerCorrectView,
    FinanceDashboardOwnerSeriesView,
    FinanceDashboardHouseholdCategoriesView,
    FinanceDashboardAiReviewView,
]
