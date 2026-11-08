"""Who owns an expense: the account's owner set and the resolution chain.

An account's owner set is exactly one of (the user's rule, nothing else):

* ``{person}``              -> kind ``person``;
* ``{person, household}``   -> kind ``person_household`` ("auch für den Haushalt");
* ``{household}``           -> kind ``household``;
* nothing yet               -> kind ``open``.

Stored backward-compatibly on the account: ``type`` (``personal``/``shared``),
``person`` and the boolean ``household_use`` (only meaningful with a person).
Old configs have no ``household_use`` and read as ``False``: no meaning change.

The chain (:func:`resolve_owner_detail`, the one resolver every view uses):

* every account: correction (this booking) 100 > merchant rule 95 > plan position 90;
* ``{P, H}`` then: series decision 85 > category default 70 > AI tendency 60 >
  the person, 50;
* ``{P}``: the person, 100; ``{H}``: household, 100; ``open``: open, 0.

Pure functions; no I/O.
"""

from __future__ import annotations

from typing import Any

from .const import (
    CATEGORY_GROCERIES,
    CATEGORY_HOUSING_COLD,
    CATEGORY_HOUSING_WARM,
    OWNER_SHARED,
)

OWNER_OPEN = "open"

KIND_OPEN = "open"
KIND_PERSON = "person"
KIND_PERSON_HOUSEHOLD = "person_household"
KIND_HOUSEHOLD = "household"
KINDS = (KIND_OPEN, KIND_PERSON, KIND_PERSON_HOUSEHOLD, KIND_HOUSEHOLD)

SOURCE_CORRECTION = "correction"
SOURCE_MERCHANT_RULE = "merchant_rule"
SOURCE_PLAN = "plan"
SOURCE_SERIES = "series"
SOURCE_CATEGORY = "category"
SOURCE_AI = "ai"
SOURCE_ACCOUNT = "account"

CONFIDENCE = {
    SOURCE_CORRECTION: 100,
    SOURCE_MERCHANT_RULE: 95,
    SOURCE_PLAN: 90,
    SOURCE_SERIES: 85,
    SOURCE_CATEGORY: 70,
    SOURCE_AI: 60,
}
CONFIDENCE_PERSON_DEFAULT = 50  # a {P,H} booking nothing recognised: guessed as personal
CONFIDENCE_AUTO = 85  # at or above: counts as done without asking

SCOPE_BOOKING = "booking"
SCOPE_MERCHANT = "merchant"

# Sensible defaults: what a household buys together. Configurable (MerchantMemory).
DEFAULT_HOUSEHOLD_CATEGORIES = (CATEGORY_HOUSING_COLD, CATEGORY_HOUSING_WARM, CATEGORY_GROCERIES)


def account_kind(account: dict[str, Any]) -> str:
    """Owner-set kind of an account config (or of a tx's ``_account_*`` stamp)."""
    if account.get("type") == "shared":
        return KIND_HOUSEHOLD
    if not str(account.get("person") or ""):
        return KIND_OPEN
    return KIND_PERSON_HOUSEHOLD if account.get("household_use") else KIND_PERSON


def tx_kind(tx: dict[str, Any]) -> str:
    return account_kind(
        {
            "type": tx.get("_account_type"),
            "person": tx.get("_account_person"),
            "household_use": tx.get("_account_household_use"),
        }
    )


def apply_owner_set(account: dict[str, Any], owner: str, household: bool) -> dict[str, Any]:
    """``account`` with the owner set written. ``owner``: person name | "shared" | "".

    Raises ``ValueError`` for a combination outside the allowed sets: the
    household flag with "shared" (it already is) or without a person, i.e. any
    set of two persons or a person-less "also household".
    """
    out = dict(account)
    if owner == "shared":
        if household:
            raise ValueError("household_with_shared")
        out.update(type="shared", person="")
        out.pop("household_use", None)
    elif owner:
        out.update(type="personal", person=owner)
        out["household_use"] = bool(household)
    else:
        if household:
            raise ValueError("household_without_person")
        out.update(type="personal", person="")
        out.pop("household_use", None)
    return out


def owner_set_label(account: dict[str, Any]) -> dict[str, Any]:
    """``{owner, household}`` in the /assignments wire shape."""
    kind = account_kind(account)
    if kind == KIND_HOUSEHOLD:
        return {"owner": "shared", "household": False}
    return {
        "owner": str(account.get("person") or ""),
        "household": kind == KIND_PERSON_HOUSEHOLD,
    }


def _norm(owner: str) -> str:
    # The memory stores a shared answer as "shared", the plan as OWNER_SHARED.
    return OWNER_SHARED if owner in ("shared", OWNER_SHARED) else owner


def resolve_owner_detail(  # noqa: PLR0911
    tx: dict[str, Any], position: Any | None = None, correction: str | None = None
) -> tuple[str, str, int]:
    """``(owner, source, confidence)`` of one expense; owner is a person,
    ``OWNER_SHARED`` or ``open``. See the module doc for the chain.

    Reads the stamps the derive step puts on the booking: ``_owner_override``
    (+ ``_owner_scope``), ``_series_owner``, ``_ai_tendency``,
    ``_household_categories``, ``_account_type|person|household_use``.
    """
    if correction:
        return _norm(str(correction)), SOURCE_CORRECTION, CONFIDENCE[SOURCE_CORRECTION]
    override = str(tx.get("_owner_override") or "")
    if override:
        if tx.get("_owner_scope") == SCOPE_BOOKING:
            return _norm(override), SOURCE_CORRECTION, CONFIDENCE[SOURCE_CORRECTION]
        return _norm(override), SOURCE_MERCHANT_RULE, CONFIDENCE[SOURCE_MERCHANT_RULE]
    if position is not None:
        return _norm(str(position.owner or OWNER_SHARED)), SOURCE_PLAN, CONFIDENCE[SOURCE_PLAN]
    kind = tx_kind(tx)
    person = str(tx.get("_account_person") or "")
    if kind == KIND_HOUSEHOLD:
        return OWNER_SHARED, SOURCE_ACCOUNT, 100
    if kind == KIND_PERSON:
        return person, SOURCE_ACCOUNT, 100
    if kind == KIND_OPEN:
        return OWNER_OPEN, SOURCE_ACCOUNT, 0
    series = str(tx.get("_series_owner") or "")
    if series:
        return _norm(series), SOURCE_SERIES, CONFIDENCE[SOURCE_SERIES]
    cats = tx.get("_household_categories")
    cats = DEFAULT_HOUSEHOLD_CATEGORIES if cats is None else cats
    if tx.get("category") in cats:
        return OWNER_SHARED, SOURCE_CATEGORY, CONFIDENCE[SOURCE_CATEGORY]
    tendency = tx.get("_ai_tendency")
    if tendency == "shared":
        return OWNER_SHARED, SOURCE_AI, CONFIDENCE[SOURCE_AI]
    if tendency == "personal":
        return person, SOURCE_AI, CONFIDENCE[SOURCE_AI]
    return person, SOURCE_ACCOUNT, CONFIDENCE_PERSON_DEFAULT
