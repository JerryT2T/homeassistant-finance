"""Reconciliation-review endpoints (admin only, cache only, never a bank call).

* ``GET  /api/finance_dashboard/review[?since=last]``  steps with groups + final check
* ``GET  /api/finance_dashboard/review/report``        hh_year, hh_cycle, p_year, p_cycle, settle, diff
* ``POST /api/finance_dashboard/review/start``         store the before-snapshot (idempotent)
* ``POST /api/finance_dashboard/review/confirm``       confirm a group -> rule (95 %)
* ``POST /api/finance_dashboard/review/ai``            AI pass over groups (consent + budget)
* ``POST /api/finance_dashboard/review/complete``      store ``reviewed_at`` + seen groups

Demo: ``?demo=1`` (or the manager's demo mode / no manager) answers from the
invented dataset; writes are accepted and not stored.
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


def _demo(request: web.Request, manager) -> bool:
    return request.query.get("demo") in ("1", "true") or (
        manager is not None and getattr(manager, "demo_mode", False) is True
    )


class _ReviewView(HomeAssistantView):
    requires_auth = True

    def _setup(self, request: web.Request):
        """``(manager, demo, error response)``."""
        if (denied := admin_denied(self, request)) is not None:
            return None, False, denied
        manager = _get_manager(request.app["hass"])
        demo = _demo(request, manager)
        if manager is None and not demo:
            return None, False, self.json({"error": "Not configured"}, status_code=404)
        return manager, demo, None

    def _bad(self, err: QuestionError) -> web.Response:
        return self.json({"error": err.code, "detail": err.detail}, status_code=400)


class FinanceDashboardReviewView(_ReviewView):
    url = f"/api/{DOMAIN}/review"
    name = f"api:{DOMAIN}:review"

    async def get(self, request: web.Request) -> web.Response:
        manager, demo, err = self._setup(request)
        if err is not None:
            return err
        if demo:
            from ..demo import generate_demo_review

            return self.json(generate_demo_review())
        return self.json(await manager.async_get_review(since_last=request.query.get("since") == "last"))


class FinanceDashboardReviewReportView(_ReviewView):
    url = f"/api/{DOMAIN}/review/report"
    name = f"api:{DOMAIN}:review:report"

    async def get(self, request: web.Request) -> web.Response:
        manager, demo, err = self._setup(request)
        if err is not None:
            return err
        if demo:
            from ..demo import generate_demo_report

            return self.json(generate_demo_report())
        person = manager.resolve_person(request.get("hass_user"))
        return self.json(await manager.async_get_review_report(person))


class FinanceDashboardReviewStartView(_ReviewView):
    url = f"/api/{DOMAIN}/review/start"
    name = f"api:{DOMAIN}:review:start"

    async def post(self, request: web.Request) -> web.Response:
        manager, demo, err = self._setup(request)
        if err is not None:
            return err
        if demo:
            return self.json({"started": None, "demo": True})
        try:
            return self.json(await manager.async_review_start())
        except QuestionError as e:
            return self._bad(e)


class FinanceDashboardReviewConfirmView(_ReviewView):
    """``POST {group_id, kind, owner?, category?, confirmed?, suspended?}``."""

    url = f"/api/{DOMAIN}/review/confirm"
    name = f"api:{DOMAIN}:review:confirm"

    async def post(self, request: web.Request) -> web.Response:
        manager, demo, err = self._setup(request)
        if err is not None:
            return err
        body = await _body(request)
        if body is None:
            return self.json({"error": "invalid_body"}, status_code=400)
        if demo:
            return self.json({"group_id": body.get("group_id"), "confidence": 95, "demo": True})
        try:
            return self.json(
                await manager.async_review_confirm(
                    group_id=body.get("group_id"),
                    kind=body.get("kind"),
                    owner=body.get("owner"),
                    category=body.get("category"),
                    confirmed=body.get("confirmed"),
                    suspended=body.get("suspended"),
                )
            )
        except QuestionError as e:
            return self._bad(e)


class FinanceDashboardReviewAiView(_ReviewView):
    """``POST {group_ids: [...]}``: AI pass; ``reason`` says why nothing happened."""

    url = f"/api/{DOMAIN}/review/ai"
    name = f"api:{DOMAIN}:review:ai"

    async def post(self, request: web.Request) -> web.Response:
        manager, demo, err = self._setup(request)
        if err is not None:
            return err
        body = await _body(request)
        if body is None:
            return self.json({"error": "invalid_body"}, status_code=400)
        if demo:
            return self.json(
                {"asked": 0, "categorized": 0, "tendencies": 0, "skipped_budget": 0,
                 "reason": "unavailable", "groups": [], "demo": True}
            )
        try:
            return self.json(await manager.async_review_ai(body.get("group_ids")))
        except QuestionError as e:
            return self._bad(e)


class FinanceDashboardReviewCompleteView(_ReviewView):
    url = f"/api/{DOMAIN}/review/complete"
    name = f"api:{DOMAIN}:review:complete"

    async def post(self, request: web.Request) -> web.Response:
        manager, demo, err = self._setup(request)
        if err is not None:
            return err
        if demo:
            return self.json({"reviewed_at": None, "demo": True})
        try:
            return self.json(await manager.async_review_complete())
        except QuestionError as e:
            return self._bad(e)


VIEWS = [
    FinanceDashboardReviewView,
    FinanceDashboardReviewReportView,
    FinanceDashboardReviewStartView,
    FinanceDashboardReviewConfirmView,
    FinanceDashboardReviewAiView,
    FinanceDashboardReviewCompleteView,
]
