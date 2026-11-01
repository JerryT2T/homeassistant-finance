"""How sure we are that a detected series is a contract (#129, epic #110).

Two card payments a month apart at a café look like a monthly series, but
nobody signed anything. Each series gets a score 0-100 from what the
payments themselves tell; below ``CANDIDATE_BELOW`` it is a *candidate*: shown
for review, never counted as a fixed cost. Reasons are codes for the UI
tooltip, never amounts or names.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .const import (
    CATEGORY_FOOD,
    CATEGORY_HOUSING,
    CATEGORY_INSURANCE,
    CATEGORY_LOANS,
    CATEGORY_SUBSCRIPTIONS,
    CATEGORY_UTILITIES,
)

CANDIDATE_BELOW = 50
REASON_OWN_NAME = "own_name"  # paid to an own account holder's name (#109)

_CARD = re.compile(
    r"\b(visa|mastercard|maestro|debitkarte|kreditkarte|girocard|ec[- ]?karte"
    r"|kartenzahlung|apple ?pay|google ?pay|card payment)\b",
    re.IGNORECASE,
)
_DIRECT_DEBIT = re.compile(
    r"\b(lastschrift|sepa|mandat\w*|mref|einzug|dauerauftrag|direct debit)\b", re.IGNORECASE
)
_SUBSCRIPTION = re.compile(
    r"\b(abo|abonnement|subscription|mitglied\w*|beitrag|premium|membership|tarif|monatsgeb\w*"
    r"|abschlag|miete|rate|versicherung|police|darlehen|kredit|mobilfunk|strom)\b",
    re.IGNORECASE,
)
# Money moved aside, not owed. Whole words only: "Sparkasse" is a bank, not savings.
_SAVINGS = re.compile(
    r"\b(sparen|sparrate|sparplan|sparbuch|rücklage\w*|tagesgeld|festgeld|taschengeld"
    r"|haushaltsgeld|umbuchung|übertrag|savings)\b",
    re.IGNORECASE,
)
_CONTRACT_CATEGORIES = {
    CATEGORY_HOUSING,
    CATEGORY_INSURANCE,
    CATEGORY_LOANS,
    CATEGORY_SUBSCRIPTIONS,
    CATEGORY_UTILITIES,
}
# Spending that recurs by habit, not by contract.
_EVERYDAY_CATEGORIES = {CATEGORY_FOOD, "shopping", "health", "gastro", "groceries"}
_MONTH_BASED = ("monthly", "quarterly", "half_yearly", "yearly")


def _remittance(txn: dict[str, Any]) -> str:
    text = str(txn.get("remittanceInformationUnstructured") or "")
    if not text:
        text = " ".join(str(a) for a in txn.get("remittanceInformationUnstructuredArray") or [])
    return text


def score_series(
    rows: list[tuple[date, float, dict[str, Any]]],
    interval: str,
    category: str,
    reference: str = "",
) -> dict[str, Any]:
    """``{"score", "reasons"}`` for one series (``rows`` date-sorted)."""
    texts = [_remittance(r[2]) for r in rows]
    mags = [abs(r[1]) for r in rows]
    score = 50
    reasons: list[str] = []

    def add(points: int, code: str) -> None:
        nonlocal score
        score += points
        reasons.append(code)

    if reference:
        add(25, "contract_reference")
    elif any(_DIRECT_DEBIT.search(t) for t in texts):
        add(20, "direct_debit")
    if sum(1 for t in texts if _CARD.search(t)) * 2 > len(texts):
        add(-15, "card_payment")
    if any(_SUBSCRIPTION.search(t) for t in texts):
        add(15, "contract_keyword")
    if any(_SAVINGS.search(t) for t in texts):
        add(-10, "savings_text")

    distinct = {round(m, 2) for m in mags}
    if len(distinct) <= 2 and _is_step(mags):
        add(15, "stable_amount")
    else:
        add(-10, "varying_amount")

    if len(rows) >= 4:
        add(10, "many_payments")
    elif len(rows) == 2 and interval in ("weekly", "monthly"):
        add(-15, "few_payments")

    if interval in _MONTH_BASED and len(rows) >= 3:
        spread = _day_spread([r[0].day for r in rows])
        if spread <= 2:
            add(10, "regular_day")
        elif spread > 4:
            add(-5, "irregular_day")

    if category in _CONTRACT_CATEGORIES:
        add(15, "contract_category")
    elif category in _EVERYDAY_CATEGORIES:
        add(-15, "everyday_category")

    return {"score": max(0, min(100, score)), "reasons": reasons}


def _day_spread(days: list[int]) -> int:
    """Width of the days of month on a 31-day circle (the 30th and the 1st are close)."""
    ds = sorted(set(days))
    gaps = [ds[i + 1] - ds[i] for i in range(len(ds) - 1)] + [ds[0] + 31 - ds[-1]]
    return 31 - max(gaps)


def _is_step(mags: list[float]) -> bool:
    """Amounts change at most once (a price step), never back and forth."""
    changes = sum(1 for i in range(1, len(mags)) if round(mags[i], 2) != round(mags[i - 1], 2))
    return changes <= 1


def own_name_contract(confidence: dict[str, Any]) -> bool:
    """A payment to an own name that still reads like a contract: a contract
    word or number in the text and a stable amount (a loan instalment to an
    own account at an unlinked bank). Savings transfers carry neither, or
    say so ("Sparplan Rate", "Rücklage Strom")."""
    reasons = set(confidence.get("reasons") or ())
    named = bool(reasons & {"contract_keyword", "contract_reference"})
    return named and "stable_amount" in reasons and "savings_text" not in reasons


def is_candidate(confidence: dict[str, Any]) -> bool:
    return int(confidence.get("score", 0)) < CANDIDATE_BELOW
