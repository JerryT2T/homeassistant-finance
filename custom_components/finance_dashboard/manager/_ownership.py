"""Ownership corrections, series decisions and the AI review pass.

Everything here works on cached data and the merchant memory -- never a bank
call. An owner correction is a rule (booking or merchant) in the same
:class:`merchants.MerchantMemory` the questions inbox uses, so there is one
store, and every answer ends in a re-derive from the ledger.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.util import dt as dt_util

from ..const import CATEGORY_OTHER, DEFAULT_CATEGORIES
from ..merchants import merchant_key
from ._questions import REACH_BOOKING, REACH_MERCHANT, QuestionError

_LOGGER = logging.getLogger(__name__)

_MAX_ID = 120
_MAX_REVIEW_MERCHANTS = 100
_MAX_SERIES_LEDGER_IDS = 2000
REASON_NO_CONSENT = "no_consent"
REASON_UNUSABLE = "provider_unusable"
REASON_UNAVAILABLE = "unavailable"


class OwnershipMixin:
    """Owner corrections (E1), series decisions (C3), the AI review pass (D3)."""

    def _check_owner(self, owner: Any) -> str | None:
        if owner in (None, ""):
            return None
        if not isinstance(owner, str) or owner not in self._valid_owners():
            raise QuestionError("invalid_owner")
        return owner

    def _memory_or_raise(self) -> Any:
        mem = getattr(self, "_memory", None)
        if mem is None or getattr(self, "_demo_mode", False):
            raise QuestionError("unavailable")
        return mem

    async def _after_ownership_change(self, mem: Any) -> None:
        await mem.async_save()
        await self.async_apply_owner_change()

    async def async_correct_owner(
        self, *, ledger_id: str, owner: str | None, reach: str
    ) -> dict[str, Any]:
        """Set (or, with ``owner=None``, remove) the owner of ONE booking or of
        every booking of its merchant ("für alle von X merken"). Any booking,
        whatever its category. Raises :class:`QuestionError`.
        """
        mem = self._memory_or_raise()
        if not isinstance(ledger_id, str) or not ledger_id or len(ledger_id) > _MAX_ID:
            raise QuestionError("invalid_id")
        if reach not in (REACH_BOOKING, REACH_MERCHANT):
            raise QuestionError("invalid_reach")
        owner = self._check_owner(owner)
        tx = next((t for t in self._transactions if t.get("_ledger_id") == ledger_id), None)
        if tx is None:
            raise QuestionError("unknown_booking")
        key = merchant_key(tx)
        if reach == REACH_MERCHANT:
            if not key:
                raise QuestionError("no_merchant")
            mem.set_merchant_owner(key, owner)
        else:
            mem.set_booking_owner(ledger_id, owner, tx.get("_own_category") or tx.get("category") or CATEGORY_OTHER)
        await self._after_ownership_change(mem)
        return {"ledger_id": ledger_id, "reach": reach, "owner": owner, "merchant": key}

    async def async_set_series_owner(
        self, *, series_id: str, owner: str | None, ledger_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """Decide a recurring series once: its owner applies to all its bookings.

        ``ledger_ids``: the series' bookings as ``"<account_key>|<ledger_id>"``
        (``recurring`` reports them). ``owner=None`` forgets the decision.
        """
        mem = self._memory_or_raise()
        if not isinstance(series_id, str) or not series_id or len(series_id) > _MAX_ID:
            raise QuestionError("invalid_id")
        if ledger_ids is not None and (
            not isinstance(ledger_ids, list)
            or len(ledger_ids) > _MAX_SERIES_LEDGER_IDS
            or not all(isinstance(i, str) and len(i) <= 2 * _MAX_ID for i in ledger_ids)
        ):
            raise QuestionError("invalid_ledger_ids")
        owner = self._check_owner(owner)
        if owner:
            mem.learn_series_owner(series_id, owner, ledger_ids)
        else:
            mem.forget_series_owner(series_id)
        await self._after_ownership_change(mem)
        return {"series_id": series_id, "owner": owner}

    def get_household_categories(self) -> dict[str, Any]:
        mem = getattr(self, "_memory", None)
        from ..ownership import DEFAULT_HOUSEHOLD_CATEGORIES

        return {
            "categories": list(mem.household_categories() if mem else DEFAULT_HOUSEHOLD_CATEGORIES),
            "defaults": list(DEFAULT_HOUSEHOLD_CATEGORIES),
            "available": [c for c in DEFAULT_CATEGORIES if c != CATEGORY_OTHER],
        }

    async def async_set_household_categories(
        self, categories: list[str] | None
    ) -> dict[str, Any]:
        """Categories counted as household on a {person, household} account;
        ``None`` restores the defaults."""
        mem = self._memory_or_raise()
        if categories is not None:
            allowed = {c for c in DEFAULT_CATEGORIES if c != CATEGORY_OTHER}
            if not isinstance(categories, list) or not all(c in allowed for c in categories):
                raise QuestionError("invalid_category")
            categories = list(dict.fromkeys(categories))
        mem.set_household_categories(categories)
        await self._after_ownership_change(mem)
        return self.get_household_categories()

    async def async_ai_review_pass(self, merchants: list[str]) -> dict[str, Any]:
        """One AI pass over unclear merchants: category AND shared/personal tendency.

        Only with the categorisation consent, only within the user's monthly AI
        budget (a cached answer is free), payload unchanged (merchant +
        remittance text). Results are suggestions: an AI category never
        replaces a user rule, a tendency is confidence 60 in the chain.
        Never touches the bank. Returns counters; ``reason`` explains a refusal.
        """
        from .. import ai_provider as ai
        from ..ai_consent import async_granted
        from ..contracts import is_own_name, own_account_names
        from ..counted import counted_transactions
        from ..merchants import _counterparty

        out: dict[str, Any] = {
            "asked": 0, "categorized": 0, "tendencies": 0, "skipped_budget": 0, "reason": None,
        }
        mem = getattr(self, "_memory", None)
        if mem is None or getattr(self, "_demo_mode", False):
            return {**out, "reason": REASON_UNAVAILABLE}
        if not await async_granted(self._hass, "categorize"):
            return {**out, "reason": REASON_NO_CONSENT}
        cfg = await ai.async_load_config(self._hass)
        creds = getattr(self, "_credential_manager", None)
        services = self._hass.services
        if not ai.provider_usable(
            cfg,
            has_key=bool(ai.read_key(cfg, creds)),
            has_ai_task=services.has_service("ai_task", "generate_data"),
            has_conversation=services.has_service("conversation", "process"),
        ):
            return {**out, "reason": REASON_UNUSABLE}
        wanted = [m for m in dict.fromkeys(merchants or []) if isinstance(m, str) and m]
        wanted = wanted[:_MAX_REVIEW_MERCHANTS]
        groups: dict[str, dict[str, Any]] = {}
        own = own_account_names(self._accounts)
        for tx in counted_transactions(self._transactions, getattr(self, "_accounts", None) or []):
            key = merchant_key(tx)
            amount = (tx.get("transactionAmount") or {}).get("amount")
            try:
                is_debit = float(amount or 0) < 0
            except (TypeError, ValueError):
                is_debit = False
            if key not in wanted or not is_debit or key in groups:
                continue
            name = _counterparty(tx)
            if is_own_name(name.lower(), own):
                continue
            groups[key] = {
                "undecided": tx.get("category") in (CATEGORY_OTHER, None),
                "merchant": name or key,
                "remittance": str(tx.get("remittanceInformationUnstructured") or ""),
            }
        known = [
            *DEFAULT_CATEGORIES,
            *(self._categorizer.get_rules() if getattr(self, "_categorizer", None) else {}),
            *(r.get("category") for r in mem.known_merchants().values()),
        ]
        categories = list(dict.fromkeys(c for c in known if c and c not in ai.NEVER_AI))
        for key in wanted:
            group = groups.get(key)
            if group is None:
                continue
            today = dt_util.now().date()
            current = await ai.async_load_config(self._hass)
            cached = key in current["cache"] and key in current["tendency"]
            if not cached and ai.usage_view(current, today)["remaining"] <= 0:
                out["skipped_budget"] += 1
                continue
            out["asked"] += 0 if cached else 1
            category, tendency = await ai.async_categorize_full(
                self._hass,
                credentials=creds,
                opt_in=True,
                merchant_id=key,
                merchant=group["merchant"],
                remittance=group["remittance"],
                categories=categories,
                today=today,
                ask_missing_tendency=True,
            )
            if (
                group["undecided"]
                and category
                and category not in ai.NEVER_AI
                and mem.learn_ai_merchant(key, category)
            ):
                out["categorized"] += 1
            if tendency and mem.learn_tendency(key, tendency):
                out["tendencies"] += 1
        if out["categorized"] or out["tendencies"]:
            await mem.async_save()
            await self.async_apply_owner_change()
        return out
