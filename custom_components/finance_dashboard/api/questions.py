"""Open-question endpoints (admin only; the list shows bookings)."""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..contracts import ContractError, answer_fields
from ..manager._questions import QuestionError
from ..questions import (
    MAX_CONTRACT_QUESTIONS,
    QUESTION_CONTRACT,
    QUESTION_PRICE,
    WEEKLY_QUESTIONS,
    contract_questions,
)
from ._helpers import _get_manager
from .refunds import load_refund_inputs

_LOGGER = logging.getLogger(__name__)


class _AdminView(HomeAssistantView):
    requires_auth = True

    @staticmethod
    def _is_admin(request: web.Request) -> bool:
        user = request.get("hass_user")
        return bool(user and user.is_admin)


class FinanceDashboardQuestionsView(_AdminView):
    """``GET /api/finance_dashboard/questions`` -- this week's open questions."""

    url = f"/api/{DOMAIN}/questions"
    name = f"api:{DOMAIN}:questions"

    async def get(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        await load_refund_inputs(request.app["hass"])  # manual allocations survive a restart
        data = manager.get_questions()
        try:
            data = await _with_contract_questions(request, manager, data)
        except Exception:  # noqa: BLE001 - contract questions are an addition
            _LOGGER.debug("Contract questions unavailable", exc_info=True)
        return self.json(data)


async def _with_contract_questions(request: web.Request, manager, data: dict) -> dict:
    """Put this week's contract questions (#117 B, G) after the refund cards
    (#119, outside the quota) and before the merchant ones; contract and
    merchant questions share the weekly quota."""
    from .contracts import _contracts_for

    _store, contracts = await _contracts_for(request, manager)
    left = max(0, WEEKLY_QUESTIONS - int(data.get("week_answered") or 0))
    cq, total = contract_questions(
        contracts, today=dt_util.now().date(), limit=min(MAX_CONTRACT_QUESTIONS, left)
    )
    rest = list(data.get("questions") or [])
    refunds = [q for q in rest if q.get("kind") == "refund"]
    merchants = [q for q in rest if q.get("kind") != "refund"]
    merged = refunds + cq + merchants[: max(0, left - len(cq))]
    return {
        **data,
        "questions": merged,
        "questions_open": len(merged),
        "questions_total": int(data.get("questions_total") or 0) + total,
    }


async def _answer_contract_question(request: web.Request, manager, body: dict) -> dict:
    """Write a contract-question answer into the contract (the sheet's fields)."""
    from .contracts import _contracts_for

    qtype = body.get("type")
    qid = body.get("id")
    if not isinstance(qid, str) or not qid.startswith(f"{qtype}:"):
        raise QuestionError("invalid_id")
    if getattr(manager, "_memory", None) is None or getattr(manager, "_demo_mode", False):
        raise QuestionError("unavailable")
    sid = qid.split(":", 1)[1]
    store, contracts = await _contracts_for(request, manager)
    item = next((c for c in contracts if c["id"] == sid), None)
    if item is None:
        raise QuestionError("unknown_question")
    try:
        fields = answer_fields(qtype, body.get("answer"), item)
        contract = store.get(sid)
        contract.apply(fields)
    except ContractError as err:
        raise QuestionError(err.code, err.detail) from err
    store.contracts[sid] = contract
    await store.async_save()
    count = getattr(manager, "async_count_contract_answer", None)
    if count is None:  # a host without the questions mixin awards nothing
        return {"point_awarded": False}
    return await count(request["hass_user"].id)


class FinanceDashboardQuestionHistoryView(_AdminView):
    """``GET /api/finance_dashboard/questions/history`` -- past categorisations."""

    url = f"/api/{DOMAIN}/questions/history"
    name = f"api:{DOMAIN}:questions:history"

    async def get(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        return self.json(manager.get_question_history())


class FinanceDashboardQuestionAnswerView(_AdminView):
    """``POST /api/finance_dashboard/questions/answer``."""

    url = f"/api/{DOMAIN}/questions/answer"
    name = f"api:{DOMAIN}:questions:answer"

    async def post(self, request: web.Request) -> web.Response:
        if not self._is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return self.json({"error": "invalid_body"}, status_code=400)
        if body.get("type") in (QUESTION_CONTRACT, QUESTION_PRICE):
            try:
                return self.json(await _answer_contract_question(request, manager, body))
            except QuestionError as err:
                return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        try:
            result = await manager.async_answer_question(
                question_id=body.get("id"),
                category=body.get("category"),
                reach=body.get("reach"),
                owner=body.get("owner") or None,
                choice=body.get("choice"),
                expenses=body.get("expenses"),
                user_id=request["hass_user"].id,
            )
        except QuestionError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        return self.json(result)
