"""Household-plan wizard endpoints (admin only, cache/config only - never a bank call).

* ``GET/PUT /api/finance_dashboard/plan_wizard``                    wizard state
* ``GET /api/finance_dashboard/plan_wizard/gate``                   >= 3 full payday cycles?
* ``GET /api/finance_dashboard/plan_wizard/income_suggestions``     salary per person
* ``PUT /api/finance_dashboard/plan_wizard/income``                 store accepted income
* ``GET/POST /api/finance_dashboard/plan_wizard/fixed``             alias of ``setup/plan_prefill``
* ``GET /api/finance_dashboard/plan_wizard/result``                 monthly balance + history
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.util import dt as dt_util

from .. import plan_wizard as pw
from .. import savings_goals as goals_mod
from .. import setup_wizard as wiz
from ..const import DOMAIN
from ..household_summary import counted_transactions
from ..transfer_detector import get_effective_transactions
from ._helpers import _get_manager, admin_denied
from .setup import FinanceDashboardPlanPrefillView, _body


def _manager_or_404(view, request):
    manager = _get_manager(request.app["hass"])
    if not manager:
        return None, view.json({"error": "Not configured"}, status_code=404)
    return manager, None


def _gate(manager, today) -> dict:
    ledger = getattr(manager, "_ledger", None)
    return pw.build_gate(pw.earliest_booked(ledger), today, pw.household_payday(manager.persons))


async def _build_result(hass, manager) -> dict:
    today = dt_util.now().date()
    cycles = pw.full_cycles(
        pw.household_payday(manager.persons),
        pw.earliest_booked(getattr(manager, "_ledger", None)),
        today,
    )
    txns = counted_transactions(manager._transactions, manager._accounts)  # noqa: SLF001
    txns = await manager._net_matched_refunds(txns)  # noqa: SLF001 - matched refunds are no income (#119)
    return pw.build_result(
        manager.budget_plan,
        # The auto Taschengeld pots ARE the remainder; counting them would shrink it.
        [p for p in manager.pots if p.auto != "remainder"],
        await goals_mod.async_get_goals(hass),
        today,
        pw.history_averages(txns, cycles),
    )


class FinanceDashboardPlanWizardView(HomeAssistantView):
    url = f"/api/{DOMAIN}/plan_wizard"
    name = f"api:{DOMAIN}:plan_wizard"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        _manager, err = _manager_or_404(self, request)
        if err:
            return err
        state = await wiz.async_load_state(hass)
        return self.json(pw.public_state(state["plan_wizard"]))

    async def put(self, request: web.Request) -> web.Response:
        """Body (all optional): ``step`` + ``status``, ``current_step``, ``complete``."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager, err = _manager_or_404(self, request)
        if err:
            return err
        body = await _body(request)
        if body is None:
            return self.json(
                {"error": "invalid_body", "detail": "Body must be a JSON object"}, status_code=400
            )
        state = await wiz.async_load_state(hass)
        if body.get("restart") is True:
            if getattr(manager, "demo_mode", False):
                return self.json({"error": "demo_mode"}, status_code=400)
            # Rebuild: plan positions + income go, pots and goals stay.
            plan = await manager._plan_store.async_load()  # noqa: SLF001
            plan.positions = []
            plan.income = {}
            await manager._plan_store.async_save(plan)  # noqa: SLF001
            state["plan_wizard"] = pw.restart_state()
            await wiz.async_save_state(hass, state)
            return self.json(pw.public_state(state["plan_wizard"]))
        try:
            state["plan_wizard"] = pw.apply_update(state["plan_wizard"], body)
        except pw.PlanWizardError as e:
            return self.json({"error": e.code, "detail": e.detail}, status_code=400)
        remainder_pots = None
        if body.get("complete") is True:
            if getattr(manager, "demo_mode", False):
                return self.json({"error": "demo_mode"}, status_code=400)
            result = await _build_result(hass, manager)
            remainder_pots = await pw.async_upsert_remainder_pots(manager, result)
        await wiz.async_save_state(hass, state)
        payload = pw.public_state(state["plan_wizard"])
        if remainder_pots is not None:
            payload["remainder_pots"] = remainder_pots
        return self.json(payload)


class FinanceDashboardPlanWizardGateView(HomeAssistantView):
    url = f"/api/{DOMAIN}/plan_wizard/gate"
    name = f"api:{DOMAIN}:plan_wizard_gate"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager, err = _manager_or_404(self, request)
        if err:
            return err
        return self.json(_gate(manager, dt_util.now().date()))


class FinanceDashboardPlanWizardIncomeSuggestionsView(HomeAssistantView):
    url = f"/api/{DOMAIN}/plan_wizard/income_suggestions"
    name = f"api:{DOMAIN}:plan_wizard_income_suggestions"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager, err = _manager_or_404(self, request)
        if err:
            return err
        txs = get_effective_transactions(manager._transactions)  # noqa: SLF001
        return self.json({"suggestions": pw.suggest_income(txs, manager.persons)})


class FinanceDashboardPlanWizardIncomeView(HomeAssistantView):
    url = f"/api/{DOMAIN}/plan_wizard/income"
    name = f"api:{DOMAIN}:plan_wizard_income"
    requires_auth = True

    async def put(self, request: web.Request) -> web.Response:
        """``{"income": [{person, amount_net}]}`` -> ``{ok, income: [entry]}``."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager, err = _manager_or_404(self, request)
        if err:
            return err
        if getattr(manager, "demo_mode", False):
            return self.json({"error": "demo_mode"}, status_code=400)
        body = await _body(request)
        names = {str(p.get("name")) for p in manager.persons if p.get("name")}
        try:
            payloads = pw.validate_income(body, names)
        except pw.PlanWizardError as e:
            return self.json({"error": e.code, "detail": e.detail}, status_code=400)
        saved = [await manager.async_set_income(p) for p in payloads]
        return self.json({"ok": True, "income": saved})


class FinanceDashboardPlanWizardFixedView(FinanceDashboardPlanPrefillView):
    """Fixed-cost step: same proposals / accept as ``setup/plan_prefill``."""

    url = f"/api/{DOMAIN}/plan_wizard/fixed"
    name = f"api:{DOMAIN}:plan_wizard_fixed"


class FinanceDashboardPlanWizardResultView(HomeAssistantView):
    url = f"/api/{DOMAIN}/plan_wizard/result"
    name = f"api:{DOMAIN}:plan_wizard_result"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager, err = _manager_or_404(self, request)
        if err:
            return err
        return self.json(await _build_result(hass, manager))
