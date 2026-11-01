"""Budget-sheet positions as an idea source for the plan wizard.

The spreadsheet contributes **names only**: every amount in it is ignored. Names
are matched locally against the recurring series and category spend found in the
cached ledger (no bank call), amounts come from that data only. Names local
matching cannot place may go to the AI, but only with the one-time
``sheet_analysis`` consent and only as names. Nothing is written to the plan.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import defaultdict
from datetime import date
from typing import Any

from .budget_plan import actual_amount_to_plan_sign
from .const import CATEGORY_OTHER
from .recurring import IRREGULAR_INTERVALS, STATUS_ENDED, detect_series
from .spreadsheet_import import categorize_position, parse_workbook

MAX_SHEET_NAMES = 200
MIN_TOKEN = 4
FUZZY_RATIO = 0.84
HISTORY_MONTHS = 3

# Category -> idea kind. Variable everyday spending is a pot, the rest is a fixed cost.
_POT_CATEGORIES = frozenset({"groceries", "mobility", "leisure", "health", "other"})


def sheet_position_names(workbook: bytes) -> list[str]:
    """Distinct cost-position names of a workbook; amounts are dropped here."""
    plan, _report = parse_workbook(workbook)
    seen: dict[str, str] = {}
    for pos in plan.positions:
        name = " ".join(str(pos.name).split())
        if name and name.casefold() not in seen:
            seen[name.casefold()] = name
    return list(seen.values())[:MAX_SHEET_NAMES]


def normalize(text: str) -> str:
    """Lower-case, umlauts folded, only letters/digits and single spaces."""
    folded = unicodedata.normalize("NFKD", str(text).casefold().replace("ß", "ss"))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())


def _tokens(norm: str) -> set[str]:
    return {t for t in norm.split() if len(t) >= MIN_TOKEN}


def names_match(a: str, b: str) -> bool:
    """Loose equality of two names: containment, a shared long token or fuzzy ratio."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if min(len(na), len(nb)) >= MIN_TOKEN and (na in nb or nb in na):
        return True
    if _tokens(na) & _tokens(nb):
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= FUZZY_RATIO


def category_monthly(transactions: list[dict[str, Any]]) -> dict[str, float]:
    """Mean monthly expense per category over the latest months present (plan sign)."""
    months: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for tx in transactions:
        if tx.get("_status") != "booked":
            continue
        cat = tx.get("category")
        day = str(tx.get("bookingDate") or "")[:7]
        if not cat or cat == CATEGORY_OTHER or len(day) != 7:  # noqa: PLR2004
            continue
        try:
            amount = float((tx.get("transactionAmount") or {}).get("amount", 0) or 0)
        except (TypeError, ValueError):
            continue
        if amount < 0:
            months[cat][day] += actual_amount_to_plan_sign(amount)
    out: dict[str, float] = {}
    for cat, per_month in months.items():
        latest = sorted(per_month)[-HISTORY_MONTHS:]
        out[cat] = round(sum(per_month[m] for m in latest) / len(latest), 2)
    return out


def _series_idea(name: str, series: dict[str, Any]) -> dict[str, Any]:
    irregular = series["interval"] in IRREGULAR_INTERVALS
    return {
        "name": name,
        "matched": "series",
        "series_id": series["id"],
        "category": series.get("category") or None,
        "amount": round(series["annual_cost"] / 12, 2),  # monthly, plan sign
        "kind": "reserve" if irregular else "fixed",
    }


def _idea(name: str, matched: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "name": name,
        "matched": matched,
        "series_id": None,
        "category": None,
        "amount": None,
        "kind": None,
        **extra,
    }


def match_locally(
    names: list[str],
    series: list[dict[str, Any]],
    monthly_by_category: dict[str, float],
) -> list[dict[str, Any]]:
    """One idea per name: series first, then category, else unmatched (matched=None)."""
    expenses = [s for s in series if s["direction"] == "out" and s["status"] != STATUS_ENDED]
    ideas: list[dict[str, Any]] = []
    for name in names:
        hit = next(
            (s for s in expenses if names_match(name, s["display_name"])),
            None,
        )
        if hit is not None:
            ideas.append(_series_idea(name, hit))
            continue
        category = categorize_position(name)
        if category != CATEGORY_OTHER:
            ideas.append(
                _idea(
                    name,
                    "category",
                    category=category,
                    amount=monthly_by_category.get(category),
                    kind="pot" if category in _POT_CATEGORIES else "fixed",
                )
            )
            continue
        ideas.append(_idea(name))
    return ideas


async def async_sheet_ideas(
    hass: Any, manager: Any, workbook: bytes, today: date
) -> dict[str, Any]:
    """Ideas for a workbook. Cache only; AI only with ``sheet_analysis`` consent."""
    from . import ai_consent, ai_provider
    from .transfer_detector import get_effective_transactions

    names = await hass.async_add_executor_job(sheet_position_names, workbook)
    txns = get_effective_transactions(getattr(manager, "_transactions", None) or [])
    series = detect_series(txns, today=today)
    ideas = match_locally(names, series, category_monthly(txns))

    unmatched = [i for i in ideas if i["matched"] is None]
    needs_consent = False
    ai_used = False
    if unmatched:
        if not await ai_consent.async_granted(hass, "sheet_analysis"):
            needs_consent = True
        else:
            cfg = await ai_provider.async_load_config(hass)
            creds = getattr(manager, "_credential_manager", None)
            services = hass.services
            usable = ai_provider.provider_usable(
                cfg,
                has_key=bool(ai_provider.read_key(cfg, creds)),
                has_ai_task=services.has_service("ai_task", "generate_data"),
                has_conversation=services.has_service("conversation", "process"),
            )
            kinds = await ai_provider.async_classify_names(
                hass,
                credentials=creds,
                names=[i["name"] for i in unmatched],
                today=today,
                usable=usable,
            )
            if kinds is not None:
                ai_used = True
                for idea in unmatched:
                    kind = kinds.get(idea["name"])
                    if kind in ai_provider.POSITION_KINDS:
                        idea["matched"] = "ai"
                        idea["kind"] = kind
                # A real answer consumes the one-time consent; a failed call keeps it.
                await ai_consent.async_mark_used(hass, "sheet_analysis")
    return {"ideas": ideas, "needs_consent": needs_consent, "ai_used": ai_used}
