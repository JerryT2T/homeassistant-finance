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

from ..const import CATEGORY_OTHER, DEFAULT_CATEGORIES, DOMAIN
from ..merchants import POINT_EVERY, _counterparty, merchant_key
from ..points_target import EVENT_POINTS_AWARDED, async_award, person_of_user
from ..refund_matcher import QUESTION_PREFIX, refund_questions
from ..transfer_detector import transfer_questions

_LOGGER = logging.getLogger(__name__)

EVENT_POINTS = EVENT_POINTS_AWARDED
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_FALLBACK_SUGGESTIONS = ("groceries", "leisure", "media")
_NOT_SUGGESTED = (CATEGORY_OTHER, "transfers")
REACH_BOOKING = "booking"
REACH_MERCHANT = "merchant"
_MAX_ID = 120
TRANSFER_PREFIX = "transfer:"
MAX_TRANSFER_QUESTIONS = 5


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
        refunds = self.get_refund_questions()
        transfers = self.get_transfer_questions()
        return {
            # Unsure matches come first: one answer settles a whole bill (#119) or transfer (#174).
            "questions": [*refunds, *transfers, *data.get("questions", [])],
            "questions_open": data.get("questions_open", 0) + len(refunds) + len(transfers),
            "questions_total": data.get("questions_total", 0) + len(refunds) + len(transfers),
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
        from ..ai_consent import async_granted
        from ..contracts import is_own_name, own_account_names
        from ..counted import counted_transactions

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
            # What does not count (a PayPal debit, a transfer) is worth no AI call.
            counted_transactions(self._transactions, getattr(self, "_accounts", None) or []),
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
            refresh = getattr(self, "_async_refresh_contract_categories", None)
            if refresh is not None:
                await refresh()
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
        choice: str | None = None,
        expenses: list[str] | None = None,
    ) -> dict[str, Any]:
        """Apply an answer; returns counters. Raises :class:`QuestionError`."""
        mem = getattr(self, "_memory", None)
        if mem is None or getattr(self, "_demo_mode", False):
            raise QuestionError("unavailable")
        if isinstance(question_id, str) and question_id.startswith(QUESTION_PREFIX):
            return await self._answer_refund(mem, question_id, choice, expenses, user_id)
        if isinstance(question_id, str) and question_id.startswith(TRANSFER_PREFIX):
            return await self._answer_transfer(mem, question_id, choice, user_id)
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

        return await self._finish_answer(mem, user_id, derive=True)

    def get_refund_questions(self) -> list[dict[str, Any]]:
        """Question cards for the unsure refund matches (#119); cache only."""
        analysis = getattr(self, "get_refund_analysis", None)  # a host without refunds asks none
        if getattr(self, "_demo_mode", False) or analysis is None:
            return []
        result = analysis()
        labels = self._hass.data.get(DOMAIN, {}).get("_label_store")
        return refund_questions(
            self._transactions,
            result["proposals"],
            result["allocations"],
            labels.bookings if labels else None,
        )

    def get_transfer_questions(self) -> list[dict[str, Any]]:
        """Question cards for pairs that match on amount and date only (#174); cache only."""
        if getattr(self, "_demo_mode", False):
            return []
        from ..tx_dates import effective_date_str

        def row(tx: dict[str, Any]) -> dict[str, Any]:
            return {
                "date": effective_date_str(tx),
                "amount": float((tx.get("transactionAmount") or {}).get("amount", 0) or 0),
                "account": str(tx.get("_account_name") or ""),
                "party": _counterparty(tx),
                "description": str(tx.get("remittanceInformationUnstructured") or "")[:120],
            }

        cards = transfer_questions(
            self._transactions, self._accounts, getattr(self, "_transfer_overrides", None)
        )
        # Newest first and few at a time: an imported history must not flood the list.
        cards.sort(key=lambda card: effective_date_str(card["out"]), reverse=True)
        return [
            {
                "kind": "transfer",
                "id": f"{TRANSFER_PREFIX}{card['id']}",
                "merchant": _counterparty(card["out"]) or _counterparty(card["in"]),
                "out": row(card["out"]),
                "in": row(card["in"]),
            }
            for card in cards[:MAX_TRANSFER_QUESTIONS]
        ]

    async def _answer_transfer(
        self, mem: Any, question_id: str, choice: str | None, user_id: str | None
    ) -> dict[str, Any]:
        """``confirm`` links the pair for good, ``no`` keeps both bookings counted."""
        if choice not in ("confirm", "no"):
            raise QuestionError("invalid_choice")
        if question_id not in {q["id"] for q in self.get_transfer_questions()}:
            raise QuestionError("unknown_question")
        await self.async_confirm_transfer_chain(
            question_id[len(TRANSFER_PREFIX) :], choice == "confirm"
        )
        return await self._finish_answer(mem, user_id, derive=True)

    async def _answer_refund(
        self,
        mem: Any,
        question_id: str,
        choice: str | None,
        expenses: list[str] | None,
        user_id: str | None,
    ) -> dict[str, Any]:
        """``confirm`` the proposal, ``no`` (pays nothing back) or ``other`` expenses."""
        from ..labels import async_get_label_store
        from ..refund_store import RefundError, async_get_refund_store

        if len(question_id) > _MAX_ID * 2:
            raise QuestionError("invalid_id")
        await async_get_label_store(self._hass)
        store = await async_get_refund_store(self._hass)
        refund_id = question_id[len(QUESTION_PREFIX):]
        card = next((q for q in self.get_refund_questions() if q["id"] == question_id), None)
        if card is None:
            raise QuestionError("unknown_question")
        if choice == "confirm":
            picked = [p["id"] for p in card["proposed"]]
        elif choice == "no":
            picked = []
        elif choice == "other":
            allowed = {o["id"] for o in card["others"]} | {p["id"] for p in card["proposed"]}
            if not isinstance(expenses, list) or not expenses or not set(expenses) <= allowed:
                raise QuestionError("invalid_expenses")
            picked = expenses
        else:
            raise QuestionError("invalid_choice")
        try:
            store.set(refund_id, picked)
        except RefundError as err:
            raise QuestionError(err.code, err.detail) from err
        await store.async_save()
        return await self._finish_answer(mem, user_id, derive=False)

    async def async_count_contract_answer(self, user_id: str | None = None) -> dict[str, Any]:
        """A contract question was answered (#117 B, G): it counts towards
        the week and the points like a merchant answer. Raises :class:`QuestionError`."""
        mem = getattr(self, "_memory", None)
        if mem is None or getattr(self, "_demo_mode", False):
            raise QuestionError("unavailable")
        return await self._finish_answer(mem, user_id, derive=False)

    async def _finish_answer(self, mem: Any, user_id: str | None, *, derive: bool) -> dict[str, Any]:
        today = dt_util.now().date()
        point = mem.record_answer(today)
        await mem.async_save()
        if derive:
            self._derive_from_ledger(self._transfer_overrides)
            refresh = getattr(self, "_async_refresh_contract_categories", None)
            if refresh is not None:
                await refresh()
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
