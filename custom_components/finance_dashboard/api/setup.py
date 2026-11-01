"""Setup-wizard endpoints (admin only, cache/config only - never a bank call).

* ``GET/PUT /api/finance_dashboard/setup``                     wizard state (Einrichtung)
  (the household-plan wizard lives in ``plan_wizard.py`` / ``api/plan_wizard.py``)
* ``GET /api/finance_dashboard/setup/payday_suggestions``      per-person payday hints
* ``GET/POST /api/finance_dashboard/setup/pot_suggestions``    pots from history
* ``GET/POST /api/finance_dashboard/setup/plan_prefill``       plan positions from contracts
* ``GET/POST /api/finance_dashboard/setup/goals``              savings goals (list / add)
* ``DELETE /api/finance_dashboard/setup/goals/{goal_id}``      remove a goal
* ``GET/PUT /api/finance_dashboard/setup/points``              points hand-off helper
* ``GET/PUT /api/finance_dashboard/setup/ai``                  AI provider, key, budget, results
* ``POST /api/finance_dashboard/setup/ai/test``                one test call (made-up merchant)
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.util import dt as dt_util

from .. import ai_provider as ai
from .. import plan_prefill as prefill
from .. import points_target as pts
from .. import savings_goals as goals_mod
from .. import setup_wizard as wiz
from ..account_identity import account_key
from ..const import DEFAULT_CATEGORIES, DOMAIN, OPT_BENCHMARK_POSTCODE, OPT_BENCHMARK_STATE
from ..contracts import async_get_store as async_get_contract_store
from ..contracts import build_contracts, own_account_names
from ..household_summary import counted_transactions
from ..merchants import POINT_EVERY
from ..pots import Pot
from ..transfer_detector import get_effective_transactions
from ._helpers import _get_manager, admin_denied


async def _body(request: web.Request) -> dict | None:
    try:
        data = await request.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _bad(view, err: wiz.SetupError) -> web.Response:
    return view.json({"error": err.code, "detail": err.detail}, status_code=400)


def _options(manager) -> dict:
    entry = getattr(manager, "_entry", None)
    return dict(getattr(entry, "options", None) or {})


def _region(raw) -> dict | None:
    """Benchmark region from the wizard: federal state code + optional postcode."""
    if not isinstance(raw, dict):
        return None
    state = str(raw.get("state") or "").strip().upper()
    postcode = str(raw.get("postcode") or "").strip()
    code = state.removeprefix("DE-")
    if state and not (code.isalpha() and len(code) == 2):
        return None
    if postcode and not (postcode.isdigit() and len(postcode) == 5):
        return None
    return {OPT_BENCHMARK_STATE: state, OPT_BENCHMARK_POSTCODE: postcode}


async def _ai_opt_in(hass, state: dict) -> bool:
    """Categorisation consent: the per-purpose store when present, else the legacy flag."""
    try:
        from .. import ai_consent
    except ImportError:  # parallel module not merged yet
        return bool(state.get("ai_opt_in"))
    return bool(await ai_consent.async_granted(hass, "categorize"))


async def _set_ai_opt_in(hass, state: dict, value: bool) -> None:
    state["ai_opt_in"] = value  # legacy mirror
    try:
        from .. import ai_consent
    except ImportError:
        return
    await ai_consent.async_set(hass, "categorize", value)


async def _payload(hass, manager) -> dict:
    state = await wiz.async_load_state(hass)
    accounts = getattr(manager, "_accounts", []) or []
    hints = wiz.data_hints(
        manager.persons,
        accounts,
        region=bool(_options(manager).get(OPT_BENCHMARK_STATE)),
        points=bool(state["points_target"]),
    )
    return {
        "current_step": wiz.current_step(state, hints),
        "steps": wiz.effective_steps(state, hints),
        "completed": bool(state["completed"]),
        "ai_opt_in": await _ai_opt_in(hass, state),
        "points_target": state["points_target"],
        "notifications": state["notifications"],
        "persons": [
            {
                "name": str(p.get("name") or ""),
                "display_name": str(p.get("display_name") or "") or str(p.get("name") or ""),
                "payday": wiz.person_payday(p),
            }
            for p in manager.persons
        ],
        "region": {
            "state": _options(manager).get(OPT_BENCHMARK_STATE) or "",
            "postcode": _options(manager).get(OPT_BENCHMARK_POSTCODE) or "",
        },
    }


class FinanceDashboardSetupView(HomeAssistantView):
    """Wizard state: resumes until completed once."""

    url = f"/api/{DOMAIN}/setup"
    name = f"api:{DOMAIN}:setup"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        return self.json(await _payload(hass, manager))

    async def put(self, request: web.Request) -> web.Response:
        """Body (all optional): step+status, complete, ai_opt_in, notifications, paydays,
        region, nicknames ``[{person, display_name}]`` (empty display_name clears)."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _body(request)
        if body is None:
            return self.json({"error": "invalid_body", "detail": "Body must be a JSON object"},
                             status_code=400)
        try:
            state = wiz.apply_update(await wiz.async_load_state(hass), body)
            paydays = (
                wiz.validate_paydays(body["paydays"], manager.persons) if "paydays" in body else {}
            )
        except wiz.SetupError as err:
            return _bad(self, err)
        nicknames = None
        if "nicknames" in body:
            try:
                nicknames = wiz.validate_nicknames(body["nicknames"], manager.persons)
            except wiz.SetupError as err:
                return _bad(self, err)
        region = _region(body["region"]) if "region" in body else None
        if "region" in body and region is None:
            return self.json({"error": "invalid_region"}, status_code=400)
        if paydays:
            if getattr(manager, "demo_mode", False):
                return self.json({"error": "demo_mode"}, status_code=400)
            hass.config_entries.async_update_entry(
                manager._entry,  # noqa: SLF001
                data={
                    **manager._entry.data,  # noqa: SLF001
                    "persons": wiz.apply_paydays(manager.persons, paydays),
                },
            )
        if nicknames:
            if getattr(manager, "demo_mode", False):
                return self.json({"error": "demo_mode"}, status_code=400)
            hass.config_entries.async_update_entry(
                manager._entry,  # noqa: SLF001
                data={
                    **manager._entry.data,  # noqa: SLF001
                    "persons": wiz.apply_nicknames(manager.persons, nicknames),
                },
            )
        if region is not None:
            hass.config_entries.async_update_entry(
                manager._entry,  # noqa: SLF001
                options={**manager._entry.options, **region},  # noqa: SLF001
            )
        if "ai_opt_in" in body:
            await _set_ai_opt_in(hass, state, state["ai_opt_in"])
        await wiz.async_save_state(hass, state)
        return self.json(await _payload(hass, manager))


class FinanceDashboardPaydaySuggestionsView(HomeAssistantView):
    url = f"/api/{DOMAIN}/setup/payday_suggestions"
    name = f"api:{DOMAIN}:setup_payday_suggestions"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        txs = get_effective_transactions(manager._transactions)  # noqa: SLF001
        return self.json({"suggestions": wiz.suggest_paydays(txs, manager.persons)})


class FinanceDashboardPotSuggestionsView(HomeAssistantView):
    url = f"/api/{DOMAIN}/setup/pot_suggestions"
    name = f"api:{DOMAIN}:setup_pot_suggestions"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        txs = get_effective_transactions(manager._transactions)  # noqa: SLF001
        today = dt_util.now().date()
        return self.json({"suggestions": wiz.suggest_pots(txs, manager.pots, today)})

    async def post(self, request: web.Request) -> web.Response:
        """Accept suggestions: ``{"accept": [{category, owner, cycle_budget, name?,
        account_keys?}]}`` (``account_keys``: account identity keys, null = all accounts)."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _body(request)
        try:
            known = {account_key(a) for a in manager._accounts}  # noqa: SLF001
            payloads = wiz.validate_pot_acceptance(body, known)
            for payload in payloads:  # validate everything before saving anything
                Pot.from_dict(payload)
            created = []
            for payload in payloads:
                created.append(await manager.async_save_pot(payload, replace=False))
        except wiz.SetupError as err:
            return _bad(self, err)
        except ValueError as err:
            return self.json({"error": "invalid_pot", "detail": str(err)}, status_code=400)
        return self.json({"ok": True, "pots": created}, status_code=201)


def _valid_owners(manager) -> set[str]:
    return {str(p.get("name")) for p in manager.persons if p.get("name")}


class FinanceDashboardPlanPrefillView(HomeAssistantView):
    """Propose plan positions from detected contracts; accept the confirmed subset."""

    url = f"/api/{DOMAIN}/setup/plan_prefill"
    name = f"api:{DOMAIN}:setup_plan_prefill"
    requires_auth = True

    @staticmethod
    async def _proposals(hass, manager) -> list[dict]:
        store = await async_get_contract_store(hass)
        txns = counted_transactions(manager._transactions, manager._accounts)  # noqa: SLF001
        contracts = build_contracts(
            txns, store, own_names=own_account_names(manager._accounts)  # noqa: SLF001
        )
        return prefill.propose_positions(contracts, manager.budget_plan.positions)

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        return self.json({"proposals": await self._proposals(hass, manager)})

    async def post(self, request: web.Request) -> web.Response:
        """``{"accept": [{series_id, name?, owner?, amount?, category?}]}`` -> 201."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        if getattr(manager, "demo_mode", False):
            return self.json({"error": "demo_mode"}, status_code=400)
        body = await _body(request)
        try:
            positions = prefill.validate_acceptance(
                body, await self._proposals(hass, manager), _valid_owners(manager)
            )
        except prefill.PrefillError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        existing = {p.id for p in manager.budget_plan.positions}
        created, skipped = [], []
        for pos in positions:
            if pos.id in existing:
                skipped.append(pos.id)  # never overwrite a plan position the user has
                continue
            created.append(await manager.async_set_cost_position(pos.to_dict()))
        return self.json({"ok": True, "created": created, "skipped": skipped}, status_code=201)


class FinanceDashboardGoalsView(HomeAssistantView):
    url = f"/api/{DOMAIN}/setup/goals"
    name = f"api:{DOMAIN}:setup_goals"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        if not _get_manager(hass):
            return self.json({"error": "Not configured"}, status_code=404)
        return self.json({"goals": await goals_mod.async_get_goals(hass)})

    async def post(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _body(request)
        try:
            goal = await goals_mod.async_add_goal(hass, body, _valid_owners(manager))
        except goals_mod.GoalError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        return self.json({"ok": True, "goal": goal}, status_code=201)


class FinanceDashboardGoalView(HomeAssistantView):
    url = f"/api/{DOMAIN}/setup/goals/{{goal_id}}"
    name = f"api:{DOMAIN}:setup_goal"
    requires_auth = True

    async def delete(self, request: web.Request, goal_id: str) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        if not _get_manager(hass):
            return self.json({"error": "Not configured"}, status_code=404)
        if not await goals_mod.async_remove_goal(hass, goal_id):
            return self.json({"error": "not_found"}, status_code=404)
        return self.json({"ok": True})


class FinanceDashboardPointsView(HomeAssistantView):
    """Optional helper entity that is incremented per awarded point."""

    url = f"/api/{DOMAIN}/setup/points"
    name = f"api:{DOMAIN}:setup_points"
    requires_auth = True

    @staticmethod
    async def _view(hass, manager) -> dict:
        state = await wiz.async_load_state(hass)
        mem = getattr(manager, "_memory", None)
        return {
            "entity_id": state["points_target"],
            "event": pts.EVENT_POINTS_AWARDED,
            "every": POINT_EVERY,
            "answered_total": mem.answered if mem else 0,
        }

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        return self.json(await self._view(hass, manager))

    async def put(self, request: web.Request) -> web.Response:
        """``{"entity_id": "counter.x" | "input_number.x" | ""}`` ("" clears)."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _body(request)
        if body is None or "entity_id" not in body:
            return self.json(
                {"error": "invalid_body", "detail": "entity_id required"}, status_code=400
            )
        try:
            target = pts.validate_target(hass, body["entity_id"])
        except pts.PointsTargetError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        state = await wiz.async_load_state(hass)
        state["points_target"] = target
        await wiz.async_save_state(hass, state)
        return self.json(await self._view(hass, manager))


def _ai_usable(hass, cfg: dict, manager) -> bool:
    creds = getattr(manager, "_credential_manager", None)
    return ai.provider_usable(
        cfg,
        has_key=bool(ai.read_key(cfg, creds)),
        has_ai_task=hass.services.has_service("ai_task", "generate_data"),
        has_conversation=hass.services.has_service("conversation", "process"),
    )


class FinanceDashboardAiTestView(HomeAssistantView):
    """One test call with a made-up merchant - no bank data, counts as one AI call."""

    url = f"/api/{DOMAIN}/setup/ai/test"
    name = f"api:{DOMAIN}:setup_ai_test"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        state = await wiz.async_load_state(hass)
        cfg = await ai.async_load_config(hass)
        result = await ai.async_test(
            hass,
            credentials=getattr(manager, "_credential_manager", None),
            opt_in=await _ai_opt_in(hass, state),
            categories=[c for c in DEFAULT_CATEGORIES if c not in ai.NEVER_AI],
            today=dt_util.now().date(),
            usable=_ai_usable(hass, cfg, manager),
        )
        return self.json({"test": result, "ai": await FinanceDashboardAiView._view(hass)})


class FinanceDashboardAiView(HomeAssistantView):
    """Opt-in AI categorisation: provider, model, key (write-only), monthly budget."""

    url = f"/api/{DOMAIN}/setup/ai"
    name = f"api:{DOMAIN}:setup_ai"
    requires_auth = True

    @staticmethod
    async def _view(hass) -> dict:
        state = await wiz.async_load_state(hass)
        cfg = await ai.async_load_config(hass)
        view = ai.public_view(cfg, dt_util.now().date(), await _ai_opt_in(hass, state))
        view["usable"] = _ai_usable(hass, cfg, _get_manager(hass))
        return view

    async def get(self, request: web.Request) -> web.Response:
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        if not _get_manager(hass):
            return self.json({"error": "Not configured"}, status_code=404)
        return self.json(await self._view(hass))

    async def put(self, request: web.Request) -> web.Response:
        """All optional: provider, model, ha_agent, budget_cap (0-1000), api_key
        (write-only, "" removes), ai_opt_in. The key is never returned."""
        if (denied := admin_denied(self, request)) is not None:
            return denied
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _body(request)
        if body is None:
            return self.json(
                {"error": "invalid_body", "detail": "Body must be a JSON object"}, status_code=400
            )
        try:
            changes = ai.validate_update(body)
            if "ai_opt_in" in body and not isinstance(body["ai_opt_in"], bool):
                raise ai.AiError("invalid_ai_opt_in", "ai_opt_in must be a boolean")
            cfg = ai.apply_update(
                await ai.async_load_config(hass),
                changes,
                getattr(manager, "_credential_manager", None),
            )
        except ai.AiError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        await ai.async_save_config(hass, cfg)
        if "ai_opt_in" in body:
            state = await wiz.async_load_state(hass)
            await _set_ai_opt_in(hass, state, body["ai_opt_in"])
            await wiz.async_save_state(hass, state)
        return self.json(await self._view(hass))
