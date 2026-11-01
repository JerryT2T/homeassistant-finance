"""QuestionsMixin -- open questions and learning from the user's answers.

Derivation always runs from the ledger (``_derive_from_ledger``); an answer
changes the memory and re-derives, it never mutates the ledger.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from homeassistant.util import dt as dt_util

from ..const import CATEGORY_OTHER, DEFAULT_CATEGORIES
from ..merchants import POINT_EVERY, _counterparty, merchant_key
from ..points_target import EVENT_POINTS_AWARDED, async_award, person_of_user

_LOGGER = logging.getLogger(__name__)

EVENT_POINTS = EVENT_POINTS_AWARDED
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_FALLBACK_SUGGESTIONS = ("shopping", "food", "leisure")
_NOT_SUGGESTED = (CATEGORY_OTHER, "income", "transfers")
REACH_BOOKING = "booking"
REACH_MERCHANT = "merchant"
_MAX_ID = 120


class QuestionError(Exception):
    """Invalid answer; ``code`` is machine-readable."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


class QuestionsMixin:
    """Question list + answering for FinanceDashboardManager."""

    def _week_answered(self) -> int:
        mem = getattr(self, "_memory", None)
        return mem.week_answered(dt_util.now().date()) if mem else 0

    def _suggest_categories(self, _merchant_id: str) -> list[str]:
        """Top 3: categories the user taught most often, padded with defaults."""
        mem = getattr(self, "_memory", None)
        counts = Counter(
            r.get("category") for r in (mem.known_merchants().values() if mem else [])
        )
        out = [c for c, _ in counts.most_common() if c and c not in _NOT_SUGGESTED]
        for c in (*_FALLBACK_SUGGESTIONS, *DEFAULT_CATEGORIES):
            if len(out) >= 3:  # noqa: PLR2004
                break
            if c not in out and c not in _NOT_SUGGESTED:
                out.append(c)
        return out[:3]

    def _question_kwargs(self) -> dict[str, Any]:
        return {"week_answered": self._week_answered(), "suggest": self._suggest_categories}

    def get_questions(self) -> dict[str, Any]:
        """Open questions of the household cycle (cache read, admin only)."""
        data = self.get_home(
            person=None, view="household", horizon="cycle", include_questions=True
        )
        mem = getattr(self, "_memory", None)
        today = dt_util.now().date()
        return {
            "questions": data.get("questions", []),
            "questions_open": data.get("questions_open", 0),
            "questions_total": data.get("questions_total", 0),
            "answered_total": mem.answered if mem else 0,
            "week_answered": mem.week_answered(today) if mem else 0,
            "points": mem.points if mem else 0,
            "points_every": POINT_EVERY,
        }

    def get_question_history(self) -> dict[str, Any]:
        """Past categorisations (merchant memory, cache read, admin only)."""
        mem = getattr(self, "_memory", None)
        if mem is None:
            return {"items": [], "total": 0, "by_user": 0, "by_ai": 0, "bookings": 0}
        return mem.history()

    # --- opt-in AI categorisation (background, derive/import paths only) ----
    def schedule_ai_categorization(self) -> None:
        """Start the AI pass in the background; never blocks, never raises.

        Called after a derive that follows a reprocess or an import -- never
        from a GET or a page view.  One pass at a time.
        """
        if getattr(self, "_demo_mode", False) or getattr(self, "_memory", None) is None:
            return
        running = getattr(self, "_ai_task", None)
        if running is not None and not running.done():
            return
        coro = self._async_ai_categorize()
        try:
            self._ai_task = self._hass.async_create_background_task(
                coro, "finance_dashboard_ai_categorize"
            )
        except Exception:  # noqa: BLE001 - AI is optional, never break a derive
            coro.close()
            _LOGGER.debug("AI categorisation could not be scheduled", exc_info=True)

    async def _async_ai_categorize(self) -> int:
        """Categorise leftover merchants via AI; returns how many were learned."""
        try:
            return await self._ai_pass()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("AI categorisation pass failed", exc_info=True)
            return 0

    async def _ai_pass(self) -> int:
        from .. import ai_provider as ai
        from ..contracts import is_own_name, own_account_names
        from ..ai_consent import async_granted

        mem = self._memory
        if not await async_granted(self._hass, "categorize"):
            return 0
        cfg = await ai.async_load_config(self._hass)
        creds = getattr(self, "_credential_manager", None)
        services = self._hass.services
        if not ai.provider_usable(
            cfg,
            has_key=bool(ai.read_key(cfg, creds)),
            has_ai_task=services.has_service("ai_task", "generate_data"),
            has_conversation=services.has_service("conversation", "process"),
        ):
            return 0
        tried: set[str] = self.__dict__.setdefault("_ai_tried", set())
        candidates = ai.select_candidates(
            self._transactions,
            key_of=merchant_key,
            counterparty_of=_counterparty,
            own_names=own_account_names(self._accounts),
            is_own=is_own_name,
            # Cached merchants stay candidates: a cached answer is learned below
            # without a call, so a result whose memory save got lost is not stranded.
            skip=tried,
            has_rule=lambda k: k in mem.known_merchants(),
        )
        known = [
            *DEFAULT_CATEGORIES,
            *(self._categorizer.get_rules() if getattr(self, "_categorizer", None) else {}),
            *(r.get("category") for r in mem.known_merchants().values()),
        ]
        categories = list(dict.fromkeys(c for c in known if c and c not in ai.NEVER_AI))
        learned = 0
        for cand in candidates:
            today = dt_util.now().date()
            current = await ai.async_load_config(self._hass)
            if cand["id"] not in current["cache"] and ai.usage_view(current, today)["remaining"] <= 0:
                continue  # monthly cap reached - only cached answers are still free
            tried.add(cand["id"])
            category = await ai.async_categorize(
                self._hass,
                credentials=creds,
                opt_in=True,
                merchant_id=cand["id"],
                merchant=cand["merchant"],
                remittance=cand["remittance"],
                categories=categories,
                today=today,
            )
            if (
                category
                and category not in ai.NEVER_AI
                and mem.learn_ai_merchant(cand["id"], category)
            ):
                learned += 1
        if learned:
            await mem.async_save()
            self._derive_from_ledger(self._transfer_overrides)
            await self._push_coordinator()
        return learned

    async def _push_coordinator(self) -> None:
        from ..const import DOMAIN

        data = self._hass.data.get(DOMAIN, {})
        entry = data.get("entry")
        coordinator = data.get(f"{entry.entry_id}_coordinator") if entry else None
        if coordinator is not None:
            try:
                await coordinator.async_refresh()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Coordinator push after AI pass failed", exc_info=True)

    def _valid_owners(self) -> set[str]:
        owners = {"shared"}
        owners |= {str(p.get("name")) for p in self.persons if p.get("name")}
        owners |= {str(a.get("person")) for a in self._accounts if a.get("person")}
        return owners

    async def async_answer_question(
        self,
        *,
        question_id: str,
        category: str,
        reach: str,
        owner: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply an answer; returns counters. Raises :class:`QuestionError`."""
        mem = getattr(self, "_memory", None)
        if mem is None or getattr(self, "_demo_mode", False):
            raise QuestionError("unavailable")
        if not isinstance(question_id, str) or not question_id or len(question_id) > _MAX_ID:
            raise QuestionError("invalid_id")
        if not isinstance(category, str) or not _SLUG.match(category) or category == CATEGORY_OTHER:
            raise QuestionError("invalid_category")
        if reach not in (REACH_BOOKING, REACH_MERCHANT):
            raise QuestionError("invalid_reach")
        if owner is not None and (not isinstance(owner, str) or owner not in self._valid_owners()):
            raise QuestionError("invalid_owner")

        if reach == REACH_MERCHANT:
            mem.learn_merchant(question_id, category, owner)
        else:
            lids = [
                tx["_ledger_id"]
                for tx in self._transactions
                if tx.get("_ledger_id")
                and tx.get("category") == CATEGORY_OTHER
                and not tx.get("_transfer_chain_id")
                and merchant_key(tx) == question_id
            ]
            if not lids:
                raise QuestionError("unknown_question")
            for lid in lids:
                mem.learn_booking(lid, category, owner)

        today = dt_util.now().date()
        point = mem.record_answer(today)
        await mem.async_save()
        self._derive_from_ledger(self._transfer_overrides)
        if point:
            from ..setup_wizard import async_load_state

            state = await async_load_state(self._hass)
            await async_award(
                self._hass,
                target=state.get("points_target", ""),
                user_id=user_id,
                person=person_of_user(self.persons, user_id),
                answered=mem.answered,
            )
        return {
            "answered_total": mem.answered,
            "week_answered": mem.week_answered(today),
            "point_awarded": point,
        }
