"""What a recurring payment *is*, separate from what it is *for* (#111).

The category says what money goes to (media, housing …); the **kind** says how
binding the payment is:

- ``contract``      term, renewal and notice period (rent, loan, insurance)
- ``subscription``  cancelable any time or monthly (streaming, gym, app)
- ``regular``       a habit without a contract (meal kit, weekly allowance)
- ``irregular``     recurring but irregular (pharmacy, doctor, contact lenses)

The detector *suggests* a kind on every read; the user's choice is stored on
the contract (``Contract.kind``, ``None`` = follow the suggestion), so no
stored data is ever rewritten. Notice deadlines exist only for contracts and
subscriptions. Traits (telecom) refine the contract defaults instead of being
kinds of their own.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .life_areas import INSURER as _INSURANCE

KIND_CONTRACT = "contract"
KIND_SUBSCRIPTION = "subscription"
KIND_REGULAR = "regular"
KIND_IRREGULAR = "irregular"
KINDS = (KIND_CONTRACT, KIND_SUBSCRIPTION, KIND_REGULAR, KIND_IRREGULAR)
# Spending without a notice period: no deadline, no reminder.
NO_NOTICE_KINDS = (KIND_REGULAR, KIND_IRREGULAR)

TRAIT_TELECOM = "telecom"

_CONTRACT_WORDS = re.compile(
    r"\b(darlehen\w*|kredit|miete|kaltmiete|versicherung\w*|police|abschlag\w*|mobilfunk"
    r"|strom|\w*vertrag\w*|tilgung|leasing|rate|ratenzahlung|beitrag)\b",
    re.IGNORECASE,
)
_SUBSCRIPTION_WORDS = re.compile(
    r"\b(abo|abonnement|subscription|premium|membership|mitgliedschaft|mitgliedsbeitrag"
    r"|streaming)\b",
    re.IGNORECASE,
)
_TELECOM = re.compile(
    r"\b(mobilfunk|handy|dsl|glasfaser|festnetz|telekom|vodafone|o2|congstar)\b",
    re.IGNORECASE,
)
_FITNESS = re.compile(r"\b(fitness\w*|mcfit|gym|urban sports|sportverein|verein)\b", re.IGNORECASE)
# Life areas as the categorizer writes them (#112). Media is a contract only
# with the telecom trait; health only with an insurance word (else a doctor).
_CONTRACT_CATEGORIES = {"housing_cold", "housing_warm", "finance"}
_HABIT_CATEGORIES = {"groceries"}
_IRREGULAR_CATEGORIES = {"health"}
_YEAR_BASED = ("quarterly", "half_yearly", "yearly")

# category or trait -> (min_term_months, renewal_months, notice_value, notice_unit)
CATEGORY_DEFAULTS: dict[str, tuple[int, int, int, str]] = {
    "health": (12, 12, 3, "months"),
    "telecom": (24, 12, 1, "months"),
    "housing_warm": (12, 12, 1, "months"),
    "finance": (12, 12, 3, "months"),
    "housing_cold": (12, 12, 3, "months"),
}
CONTRACT_FALLBACK = (12, 12, 1, "months")
SUBSCRIPTION_DEFAULTS = (1, 1, 0, "days")  # monthly, cancelable any time


def _texts(rows: list[tuple[date, float, dict[str, Any]]]) -> list[str]:
    out = []
    for _day, _amount, t in rows:
        text = str(t.get("remittanceInformationUnstructured") or "")
        if not text:
            text = " ".join(str(a) for a in t.get("remittanceInformationUnstructuredArray") or [])
        out.append(f"{text} {t.get('creditorName') or ''}")
    return out


def series_trait(rows: list[tuple[date, float, dict[str, Any]]]) -> str:
    """``telecom`` when the payments name a phone or internet line, else ``""``."""
    return TRAIT_TELECOM if any(_TELECOM.search(t) for t in _texts(rows)) else ""


def suggest_kind(
    rows: list[tuple[date, float, dict[str, Any]]],
    interval: str,
    category: str,
    reasons: list[str] | tuple[str, ...] = (),
) -> str:
    """The kind the payments themselves suggest; the user can override it."""
    texts = _texts(rows)
    if interval in _YEAR_BASED:
        return KIND_CONTRACT  # nobody pays a yearly habit
    if "contract_reference" in reasons:
        return KIND_CONTRACT
    # Everyday spending wins over loose words ("Brötchen Rate", "Praxis Dr. Strom").
    if category in _HABIT_CATEGORIES or "savings_text" in reasons:
        return KIND_REGULAR
    if category == "leisure":  # the gym is a subscription, the pizzeria a habit
        if any(_SUBSCRIPTION_WORDS.search(t) or _FITNESS.search(t) for t in texts):
            return KIND_SUBSCRIPTION
        return KIND_REGULAR
    if category in _IRREGULAR_CATEGORIES:
        # Codex #112: an insurer is a contract even without a contract word
        return KIND_CONTRACT if any(_INSURANCE.search(t) for t in texts) else KIND_IRREGULAR
    if any(_CONTRACT_WORDS.search(t) for t in texts):
        return KIND_CONTRACT
    if any(_SUBSCRIPTION_WORDS.search(t) for t in texts):
        return KIND_SUBSCRIPTION
    if interval != "monthly":
        return KIND_REGULAR
    if category in _CONTRACT_CATEGORIES or (
        category == "media" and any(_TELECOM.search(t) for t in texts)
    ):
        return KIND_CONTRACT
    if "stable_amount" in reasons:
        return KIND_SUBSCRIPTION  # a fixed monthly price without words: an app, a stream
    return KIND_REGULAR


def kind_defaults(kind: str, category: str, trait: str = "") -> dict[str, Any] | None:
    """Prefilled contract terms for ``kind``; ``None`` for kinds without notice."""
    if kind in NO_NOTICE_KINDS:
        return None
    if kind == KIND_SUBSCRIPTION:
        term, renewal, notice, unit = SUBSCRIPTION_DEFAULTS
    else:
        key = TRAIT_TELECOM if trait == TRAIT_TELECOM else category
        term, renewal, notice, unit = CATEGORY_DEFAULTS.get(key, CONTRACT_FALLBACK)
    return {
        "min_term_months": term,
        "renewal_months": renewal,
        "notice_value": notice,
        "notice_unit": unit,
        "notice_reference": "end_of_term",
    }
