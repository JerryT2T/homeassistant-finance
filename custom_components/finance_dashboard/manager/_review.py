"""ReviewMixin -- the reconciliation review (Abgleich) and the year view's extras.

Cache only: the groups, the check and the report are pure functions
(:mod:`review`) over the stored bookings; the only writes are merchant rules /
series decisions (Wave 1 methods), transfer-chain confirmations, the plan's
``suspended`` flag and the review state kept in the merchant memory. Never a
bank call. The AI pass reuses ``async_ai_review_pass`` (consent + budget).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from homeassistant.util import dt as dt_util

from .. import review as rv
from ..contracts import async_get_store, build_contracts, own_account_names
from ..counted import counted_transactions, net_counted
from ..household_summary import counted_transactions as _ct  # noqa: F401  (rule re-export)
from ..household_summary import pending_debits
from ..merchants import merchant_key
from ._questions import QuestionError

_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_MAX_GROUP_IDS = 100
_KINDS = (
    rv.KIND_SERIES, rv.KIND_MERCHANT, rv.KIND_CATEGORY, rv.KIND_CHAIN,
    rv.KIND_POSITION, rv.KIND_ACCOUNT, rv.KIND_LINK,
)


def _refund_allocations_of(manager: Any) -> dict[str, dict[str, float]]:
    from . import _refund_allocations

    return _refund_allocations(manager)


class ReviewMixin:
    """Review endpoints' logic and the year payload's extra inputs."""

    # -- shared inputs ---------------------------------------------------
    def _review_memory(self) -> Any | None:
        return getattr(self, "_memory", None)

    def _review_state(self) -> dict[str, Any]:
        mem = self._review_memory()
        return mem.review_state() if mem is not None else {}

    async def _contracts_list(self) -> list[dict[str, Any]]:
        """Expense series with contract fields (cache; same input as the contracts tab)."""
        store = await async_get_store(self._hass)
        txns = counted_transactions(self._transactions, self._accounts)
        txns += pending_debits(self._transactions)
        contracts = build_contracts(
            txns, store, own_names=own_account_names(self._accounts)
        )
        await store.async_save_if_changed()
        return contracts

    def _ai_merchant_suggestions(self) -> dict[str, str]:
        mem = self._review_memory()
        if mem is None:
            return {}
        return {
            k: r["category"]
            for k, r in mem.known_merchants().items()
            if r.get("source") == "ai" and r.get("category")
        }

    def _review_build(
        self, series_list: list[dict[str, Any]], *, since_last: bool = False
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """``(review payload, netted counted bookings)``."""
        today = dt_util.now().date()
        txs = net_counted(
            counted_transactions(self._transactions, self._accounts), _refund_allocations_of(self)
        )
        from ..household_summary import plan_persons

        payload = rv.build_review(
            raw=self._transactions,
            txs=txs,
            accounts=self._accounts,
            plan=self.budget_plan,
            clf=self._classifier(),
            persons=plan_persons(self.budget_plan, self._accounts),
            series_list=series_list,
            state=self._review_state(),
            today=today,
            ai_merchants=self._ai_merchant_suggestions(),
            since_last=since_last,
        )
        return payload, txs

    # -- year view inputs --------------------------------------------------
    async def async_year_inputs(self, *, is_admin: bool) -> dict[str, Any]:
        """Contracts, benchmark teaser and review state for ``GET /home?horizon=year``."""
        out: dict[str, Any] = {}
        try:
            series_list = await self._contracts_list()
        except Exception:  # noqa: BLE001 - the year must not depend on contract detection
            series_list = []
        out["contracts"] = series_list
        state = self._review_state()
        out["review"] = {"reviewed_at": state.get("reviewed_at")}
        if not is_admin:
            return out
        try:
            bench = await self.async_get_benchmarks()
            out["benchmark_teaser"] = bench.get("teaser", [])
        except Exception:  # noqa: BLE001 - a teaser is optional
            out["benchmark_teaser"] = []
        try:
            payload, txs = self._review_build(series_list)
            today = dt_util.now().date()
            # One counting rule: the year's expenses are the sum of the cycle
            # figures over the year's cycle windows, as in the year view.
            from ..household_summary import figures, plan_persons
            from ..year_view import month_windows

            booked = [t for t in txs if t.get("_status", "booked") == "booked"]
            clf = self._classifier()
            year_expenses = sum(
                figures(booked, window, clf)["expenses"]
                for _m, window in month_windows(booked, today.year, plan_persons(self.budget_plan, self._accounts))
                if window is not None and window[0] <= today
            )
            out["review"]["hint"] = rv.hint(payload, state, year_expenses)
        except Exception:  # noqa: BLE001
            out["review"]["hint"] = None
        return out

    # -- review ------------------------------------------------------------
    async def async_get_review(self, *, since_last: bool = False) -> dict[str, Any]:
        payload, _txs = self._review_build(await self._contracts_list(), since_last=since_last)
        return payload

    async def async_review_start(self) -> dict[str, Any]:
        """Store the before-snapshot once per review (G6 diff). Idempotent."""
        mem = self._memory_or_raise()
        state = mem.review_state()
        if not state.get("started_snapshot"):
            payload, txs = self._review_build(await self._contracts_list())
            today = dt_util.now().date()
            state["started_snapshot"] = rv.snapshot(
                txs, self._classifier(), (date(today.year, 1, 1), today), payload
            )
            state["started"] = dt_util.now().isoformat()
            await mem.async_save()
        return {"started": state["started"], "snapshot": state["started_snapshot"]}

    async def async_review_complete(self) -> dict[str, Any]:
        """Store ``reviewed_at`` and the seen groups; keep before/after for the report."""
        mem = self._memory_or_raise()
        state = mem.review_state()
        series_list = await self._contracts_list()
        payload, txs = self._review_build(series_list)
        today = dt_util.now().date()
        state["last_before"] = state.pop("started_snapshot", None) or state.get("last_before")
        state["last_after"] = rv.snapshot(
            txs, self._classifier(), (date(today.year, 1, 1), today), payload
        )
        state["reviewed_at"] = dt_util.now().isoformat()
        state["seen"] = sorted({i for s in payload["steps"] for i in s.get("group_ids", [])})
        state.pop("started", None)
        await mem.async_save()
        return {"reviewed_at": state["reviewed_at"]}

    async def async_review_confirm(  # noqa: PLR0912, PLR0913
        self,
        *,
        group_id: str,
        kind: str,
        owner: str | None = None,
        category: str | None = None,
        confirmed: bool | None = None,
        suspended: bool | None = None,
    ) -> dict[str, Any]:
        """Confirm a group: write the rule (-> 95 % next time) and mark it done."""
        mem = self._memory_or_raise()
        if not isinstance(group_id, str) or not group_id or len(group_id) > 160:
            raise QuestionError("invalid_id")
        gkind, _, key = group_id.partition(":")
        if kind != gkind or kind not in _KINDS or not key:
            raise QuestionError("invalid_group")
        owner = self._check_owner(owner)
        if category is not None and (not isinstance(category, str) or not _SLUG.match(category)):
            raise QuestionError("invalid_category")
        series_list = await self._contracts_list()
        today = dt_util.now().date()
        if kind in (rv.KIND_SERIES, rv.KIND_MERCHANT, rv.KIND_CATEGORY):
            txs = net_counted(
                counted_transactions(self._transactions, self._accounts),
                _refund_allocations_of(self),
            )
            groups = rv.expense_groups(
                txs, self._classifier(), (date(today.year, 1, 1), today),
                rv.series_index(series_list), self._review_state(),
            )
            group = next((g for g in groups if g["group_id"] == group_id), None)
            if group is None:
                raise QuestionError("unknown_group")
            if kind == rv.KIND_SERIES:
                full = next((s for s in series_list if str(s["id"]) == key), None)
                refs = list((full or {}).get("ledger_ids") or group["ledger_refs"])
                if owner:
                    mem.learn_series_owner(key, owner, refs)
            elif kind == rv.KIND_MERCHANT:
                if owner:
                    mem.set_merchant_owner(key, owner)
            elif owner:
                for ref in group["ledger_refs"]:
                    lid = ref.split("|", 1)[1]
                    mem.set_booking_owner(lid, owner, group["category"])
            if category and kind != rv.KIND_CATEGORY:
                known = mem.known_merchants().get(key if kind == rv.KIND_MERCHANT else "", {})
                if kind == rv.KIND_MERCHANT:
                    mem.learn_merchant(key, category, owner=known.get("owner"))
        elif kind == rv.KIND_CHAIN:
            if not isinstance(confirmed, bool):
                raise QuestionError("invalid_body", "confirmed (bool) is required for a chain")
            await self.async_confirm_transfer_chain(key, confirmed)
        elif kind == rv.KIND_POSITION and isinstance(suspended, bool):
            plan = await self._plan_store.async_load()
            pos = next((p for p in plan.positions if p.id == key), None)
            if pos is None:
                raise QuestionError("unknown_group")
            pos.suspended = suspended
            await self._plan_store.async_save(plan)
        state = mem.review_state()
        state.setdefault("confirmed", {})[group_id] = dt_util.now().isoformat()
        await self._after_ownership_change(mem)
        return {"group_id": group_id, "kind": kind, "owner": owner, "confidence": rv.CONFIRMED_CONFIDENCE}

    async def async_review_ai(self, group_ids: list[str]) -> dict[str, Any]:
        """D3: the AI pass over the merchants of these groups, then the refreshed groups."""
        if (
            not isinstance(group_ids, list)
            or len(group_ids) > _MAX_GROUP_IDS
            or not all(isinstance(g, str) and len(g) <= 160 for g in group_ids)
        ):
            raise QuestionError("invalid_body")
        series_list = await self._contracts_list()
        today = dt_util.now().date()
        txs = net_counted(
            counted_transactions(self._transactions, self._accounts), _refund_allocations_of(self)
        )
        groups = rv.expense_groups(
            txs, self._classifier(), (date(today.year, 1, 1), today),
            rv.series_index(series_list), self._review_state(),
        )
        wanted = set(group_ids)
        by_ref = {rv.ref_of(t): t for t in txs}
        merchants: list[str] = []
        for g in groups:
            if g["group_id"] not in wanted:
                continue
            if g["kind"] == rv.KIND_MERCHANT:
                merchants.append(g["key"])
            elif g["kind"] == rv.KIND_SERIES:
                tx = next((by_ref[r] for r in g["ledger_refs"] if r in by_ref), None)
                if tx is not None and merchant_key(tx):
                    merchants.append(merchant_key(tx))
        result = await self.async_ai_review_pass(list(dict.fromkeys(merchants)))
        payload, _ = self._review_build(series_list)
        result["groups"] = [
            g for s in payload["steps"] for g in s["groups"] if g["group_id"] in wanted
        ]
        return result

    async def async_get_review_report(self, viewer_person: str | None) -> dict[str, Any]:
        """G6: the six report views."""
        series_list = await self._contracts_list()
        payload, txs = self._review_build(series_list)
        from ..household_summary import plan_persons

        names = sorted(
            {str(p.get("name") or "") for p in self.persons}
            | set(plan_persons(self.budget_plan, self._accounts))
        ) or []
        return rv.build_report(
            txs=txs,
            plan=self.budget_plan,
            clf=self._classifier(),
            persons_cfg=self.persons,
            person_names=[n for n in names if n],
            today=dt_util.now().date(),
            viewer_person=viewer_person,
            contracts=series_list,
            review=payload,
            state=self._review_state(),
            ledger_earliest=self._ledger_earliest(),
        )
