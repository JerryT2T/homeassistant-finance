"""Contracts, reserves and savings-account endpoints (cache only).

Reads: admin sees everything; other users only shared/own contracts, reduced
to aggregates (no payment history). Edits are admin-only.
"""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.util import dt as dt_util

from .. import ai_consent, ai_provider
from .. import contract_filter as cf
from ..const import DOMAIN
from ..life_areas import LIFE_AREAS, OTHER
from ..contracts import (
    own_account_names,
    REVIEW_NOT_CONTRACT,
    SOURCE_MANUAL,
    Contract,
    ContractError,
    aggregate_view,
    contract_totals,
    merge_mismatch,
    async_get_store,
    build_contracts,
    build_reserves,
    set_account_savings,
    visible_to,
)
from ..labels import booking_key
from ..recurring import PLAN_MODE_FIXED
from ..pots import pot_coverage
from ..household_summary import counted_transactions, pending_debits
from ._helpers import _get_manager


def _viewer(manager, request: web.Request) -> dict:
    """Who is asking and who lives here: resolves the owner filters "me" and "partner" (#118)."""
    resolve = getattr(manager, "resolve_person", None)
    me = resolve(request.get("hass_user")) if resolve else None
    persons = [str(p.get("name")) for p in getattr(manager, "persons", None) or [] if p.get("name")]
    return {"me": me, "persons": persons}


def _is_admin(request: web.Request) -> bool:
    user = request.get("hass_user")
    return bool(user and user.is_admin)


async def _contracts_for(request: web.Request, manager):
    """All expense contracts from the cache (never hits the bank).

    Only real expenses count: own transfers between household accounts
    (whole chains, also their source leg) are not contracts.
    """
    store = await async_get_store(request.app["hass"])
    txns = counted_transactions(manager._transactions, manager._accounts)  # noqa: SLF001
    txns += pending_debits(manager._transactions)  # noqa: SLF001
    contracts = build_contracts(txns, store, own_names=own_account_names(manager._accounts))  # noqa: SLF001
    await store.async_save_if_changed()
    return store, contracts


class FinanceDashboardContractsView(HomeAssistantView):
    """Series + contract fields + derived deadlines, soonest deadline first."""

    url = f"/api/{DOMAIN}/contracts"
    name = f"api:{DOMAIN}:contracts"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        _store, contracts = await _contracts_for(request, manager)
        if _is_admin(request):
            return self.json(
                {
                    "contracts": contracts,
                    "totals": contract_totals(contracts),
                    "viewer": _viewer(manager, request),
                }
            )
        person = manager.resolve_person(request.get("hass_user"))
        shown = [aggregate_view(c) for c in contracts if visible_to(c, person)]
        return self.json(
            {
                "contracts": shown,
                "totals": contract_totals(shown),
                "viewer": _viewer(manager, request),
            }
        )

    async def post(self, request: web.Request) -> web.Response:
        """Add a contract by hand (#117 D, admin only) -> the new contract, 201."""
        if not _is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _json_body(request)
        if not isinstance(body, dict):
            return self.json({"error": "invalid_body", "detail": "Body must be a JSON object"}, status_code=400)
        if (bad := await _unknown_labels(request, body)) is not None:
            return bad
        store = await async_get_store(request.app["hass"])
        try:
            owners = getattr(manager, "_valid_owners", None)  # slim hosts: no owner check
            mid = store.add_manual(body, dt_util.now().date(), owners() if owners else None)
        except ContractError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        await store.async_save()
        _store, contracts = await _contracts_for(request, manager)
        item = next(c for c in contracts if c["id"] == mid)
        return self.json(item, status_code=201)


async def _json_body(request: web.Request):
    try:
        return await request.json()
    except ValueError:
        return None


async def _unknown_labels(request: web.Request, body: dict):
    """400 response when ``body.labels`` names a label outside the catalogue."""
    if not body.get("labels"):
        return None
    from ..labels import async_get_label_store

    known = (await async_get_label_store(request.app["hass"])).known()
    if not isinstance(body["labels"], list) or any(i not in known for i in body["labels"]):
        return web.json_response(
            {"error": "unknown_label", "detail": "label is not in the catalogue"}, status=400
        )
    return None


async def _query_ai_status(hass, manager) -> dict:
    cfg = await ai_provider.async_load_config(hass)
    creds = getattr(manager, "_credential_manager", None)
    svc = hass.services
    usable = ai_provider.provider_usable(
        cfg,
        has_key=bool(ai_provider.read_key(cfg, creds)),
        has_ai_task=svc.has_service("ai_task", "generate_data"),
        has_conversation=svc.has_service("conversation", "process"),
    )
    usage = ai_provider.usage_view(cfg, dt_util.now().date())
    return {
        "usable": usable,
        "consented": await ai_consent.async_granted(hass, "contract_query"),
        "remaining": usage["remaining"],
    }


async def _query_vocab(hass, manager) -> dict:
    """Names the AI may use: life areas, label ids / own label names, persons. No data."""
    from ..labels import async_get_label_store

    catalogue = (await async_get_label_store(hass)).catalogue()
    labels = {i["id"]: i.get("name") for i in catalogue if i.get("kind") != "auto"}
    owners = {str(p.get("name")) for p in getattr(manager, "persons", None) or [] if p.get("name")}
    return {"categories": [*LIFE_AREAS, OTHER], "labels": labels, "owners": owners}


async def run_contract_query(hass, manager, body) -> tuple[dict, int]:
    """Ask the AI for a filter spec: ``(payload, http status)``. Never raises on AI output."""
    raw_q = body.get("question") if isinstance(body, dict) else None
    question = cf.clean_question(raw_q) if isinstance(raw_q, str) else ""
    if not question:
        return {"error": "invalid_body", "detail": "Need a question"}, 400
    status = await _query_ai_status(hass, manager)
    if not status["consented"]:
        return {"error": "consent_required"}, 403
    if not status["usable"]:
        return {"error": "no_provider"}, 400
    if status["remaining"] < 1:
        return {"error": "budget_exhausted"}, 400
    vocab = await _query_vocab(hass, manager)
    answers, error = await ai_provider.async_extract_history(
        hass,
        credentials=getattr(manager, "_credential_manager", None),
        prompts=[cf.build_query_prompt(question, vocab)],
        max_tokens=cf.QUERY_MAX_TOKENS,
        today=dt_util.now().date(),
        usable=True,
    )
    if error:
        return {"error": error}, 502
    await ai_consent.async_mark_used(hass, "contract_query")
    raw = cf.parse_answer(answers[0] if answers else "")
    spec, errors = cf.validate_spec(raw, vocab)
    if raw is None:
        errors = [{"field": "_", "reason": "unparsable"}]
    return {"spec": spec, "errors": errors}, 200


class FinanceDashboardContractQueryView(HomeAssistantView):
    """Optional AI search: a question in, a validated filter spec out (#118, purpose ``contract_query``).

    ``GET`` tells whether the AI search can be offered (provider usable, consent
    given, budget left). ``POST {question}`` asks the AI for a **filter spec only**;
    the spec is validated and answered as ``{spec, errors}`` - a partial or invalid
    answer yields the valid parts plus the errors, never a failure. One call
    against the shared monthly AI budget. Only the question and the allowed names
    leave Home Assistant.
    """

    url = f"/api/{DOMAIN}/contracts/query"
    name = f"api:{DOMAIN}:contracts_query"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        return self.json(await _query_ai_status(hass, manager))

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        manager = _get_manager(hass)
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        data, status = await run_contract_query(hass, manager, await _json_body(request))
        return self.json(data, status_code=status)


class FinanceDashboardContractView(HomeAssistantView):
    """Edit the contract fields of one series (admin only)."""

    url = f"/api/{DOMAIN}/contracts/{{series_id}}"
    name = f"api:{DOMAIN}:contract"
    requires_auth = True

    async def put(self, request: web.Request, series_id: str) -> web.Response:
        if not _is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        manager = _get_manager(request.app["hass"])
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
        store, contracts = await _contracts_for(request, manager)
        if not any(c["id"] == series_id for c in contracts):
            return self.json({"error": "unknown_series"}, status_code=404)
        if (bad := await _unknown_labels(request, body)) is not None:
            return bad
        contract = Contract.from_dict(series_id, store.get(series_id).to_dict())  # a copy
        try:
            contract.apply(body)
            if series_id in store.manual and contract.plan_mode != PLAN_MODE_FIXED:
                # no payments to derive an amount from: the user's amount is the plan
                raise ContractError("manual_needs_amount", "A manual contract keeps a fixed amount")
        except ContractError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        store.contracts[series_id] = contract
        await store.async_save()
        if contract.review == REVIEW_NOT_CONTRACT and store.structure.merges.pop(series_id, None):
            await store.structure.async_save()  # its merged sources come back on their own
        _store, contracts = await _contracts_for(request, manager)
        item = next((c for c in contracts if c["id"] == series_id), None)
        if item is None:  # answered "Kein Vertrag": the series is gone for good
            return self.json({"id": series_id, "dismissed": True})
        return self.json(item)

    async def delete(self, request: web.Request, series_id: str) -> web.Response:
        """Delete a contract added by hand (#117 D); detected ones are answered "Kein Vertrag"."""
        if not _is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        store = await async_get_store(request.app["hass"])
        if not store.remove_manual(series_id):
            return self.json({"error": "not_manual"}, status_code=404)
        await store.async_save()
        await store.structure.async_save()  # its booking assignments were dropped
        return self.json({"id": series_id, "deleted": True})


class FinanceDashboardContractOverridesView(HomeAssistantView):
    """Merge / split series and assign bookings (#117 E, F; admin only).

    ``POST {action, ...}``: ``merge`` / ``unmerge`` ``{target, source}``,
    ``split`` ``{series_id, by: reference|amount}``, ``unsplit`` ``{series_id}``,
    ``assign`` ``{booking, series_id}``, ``unassign`` ``{booking}``.
    Answers the refreshed ``{contracts, totals}``.
    """

    url = f"/api/{DOMAIN}/contract_overrides"
    name = f"api:{DOMAIN}:contract_overrides"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        if not _is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        body = await _json_body(request)
        if not isinstance(body, dict):
            return self.json({"error": "invalid_body", "detail": "Body must be a JSON object"}, status_code=400)
        store, contracts = await _contracts_for(request, manager)
        st = store.structure
        by_id = {c["id"]: c for c in contracts}
        action = body.get("action")
        try:
            if action in ("merge", "unmerge"):
                target, source = body.get("target"), body.get("source")
                if action == "unmerge":
                    if not st.unmerge(str(target), str(source)):
                        return self.json({"error": "unknown_merge"}, status_code=404)
                else:
                    target = st.final_target(str(target))  # a merged-away target means its final one
                    for sid in (target, source):
                        if sid not in by_id or by_id[sid].get("source") == SOURCE_MANUAL:
                            return self.json({"error": "unknown_series"}, status_code=404)
                    if (mismatch := merge_mismatch(by_id[target], by_id[source])) is not None:
                        return self.json({"error": mismatch, "detail": "Only series with the same "
                                          "direction and interval can be merged"}, status_code=400)
                    st.merge(target, source)
            elif action in ("split", "unsplit"):
                item = by_id.get(body.get("series_id"))
                if item is None or not item.get("payee_key"):
                    return self.json({"error": "unknown_series"}, status_code=404)
                if action == "unsplit":
                    st.unsplit(item["payee_key"])
                else:
                    st.split(item["payee_key"], body.get("by"))
                    _s, after = await _contracts_for(request, manager)
                    if sum(1 for c in after if c.get("payee_key") == item["payee_key"]) < 2:
                        st.unsplit(item["payee_key"])
                        return self.json(
                            {"error": "nothing_to_split", "detail": "No second series found"},
                            status_code=400,
                        )
            elif action in ("assign", "unassign"):
                key = body.get("booking")
                if not isinstance(key, str) or not key:
                    return self.json({"error": "invalid_booking"}, status_code=400)
                if action == "unassign":
                    if not st.unassign(key):
                        return self.json({"error": "unknown_assignment"}, status_code=404)
                else:
                    if body.get("series_id") not in by_id:
                        return self.json({"error": "unknown_series"}, status_code=404)
                    if not any(booking_key(t) == key for t in manager._transactions):  # noqa: SLF001
                        return self.json({"error": "unknown_booking"}, status_code=404)
                    st.assign(key, body["series_id"])
            else:
                return self.json({"error": "invalid_action"}, status_code=400)
        except ContractError as err:
            return self.json({"error": err.code, "detail": err.detail}, status_code=400)
        await st.async_save()
        _store, contracts = await _contracts_for(request, manager)
        return self.json({"contracts": contracts, "totals": contract_totals(contracts)})


class FinanceDashboardReservesView(HomeAssistantView):
    """Monthly reserves for annual/irregular costs + pot coverage."""

    url = f"/api/{DOMAIN}/reserves"
    name = f"api:{DOMAIN}:reserves"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        _store, contracts = await _contracts_for(request, manager)
        if _is_admin(request):
            coverage = pot_coverage(
                manager.pots,
                manager._accounts,  # noqa: SLF001
                manager.get_cached_balances(),
            )
            return self.json({"reserves": build_reserves(contracts), "coverage": coverage})
        person = manager.resolve_person(request.get("hass_user"))
        shown = [c for c in contracts if visible_to(c, person)]
        reserves = build_reserves(shown)
        reserves["items"] = [
            {k: i.get(k) for k in ("creditor", "owner", "interval", "type", "next_due", "monthly_reserve")}
            for i in reserves["items"]
        ]
        return self.json({"reserves": reserves, "coverage": None})


class FinanceDashboardAccountSavingsView(HomeAssistantView):
    """Flag an account as savings account (admin only)."""

    url = f"/api/{DOMAIN}/accounts/{{key}}/savings"
    name = f"api:{DOMAIN}:account_savings"
    requires_auth = True

    async def put(self, request: web.Request, key: str) -> web.Response:
        if not _is_admin(request):
            return self.json({"error": "admin_required"}, status_code=403)
        manager = _get_manager(request.app["hass"])
        if not manager:
            return self.json({"error": "Not configured"}, status_code=404)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("savings"), bool):
            return self.json(
                {"error": "invalid_body", "detail": "Expected {savings: bool}"}, status_code=400
            )
        if not set_account_savings(manager, key, body["savings"]):
            return self.json({"error": "unknown_account"}, status_code=404)
        return self.json({"key": key, "savings": body["savings"]})
