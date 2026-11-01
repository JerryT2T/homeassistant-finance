"""Plan prefill: propose budget-plan cost positions from detected contracts.

Cache read only - the proposals are derived from ``contracts.build_contracts``
output, never from a bank call. The plan side is positive-expense, so the
proposed amount is the contract's ``monthly_equivalent`` (already positive and
already honouring the contract's ``plan_mode``).

Owner chain: the series' account owner is only the default; the accepted
position carries the owner the user confirmed.
"""

from __future__ import annotations

from typing import Any

from .budget_plan import CostPosition, slugify_position
from .const import CATEGORY_OTHER, OWNER_SHARED

MAX_ACCEPT = 200
_ENDED = "ended"


class PrefillError(ValueError):
    """Invalid prefill input; ``code`` is the API error code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


def to_plan_owner(owner: str) -> str:
    """API owner (``shared`` / person key / empty) -> plan owner."""
    return OWNER_SHARED if owner in ("", "shared", OWNER_SHARED) else owner


def from_plan_owner(owner: str) -> str:
    return "shared" if owner == OWNER_SHARED else owner


def propose_positions(
    contracts: list[dict[str, Any]], existing: list[CostPosition]
) -> list[dict[str, Any]]:
    """One proposal per live contract, biggest monthly cost first."""
    taken = {p.id for p in existing}
    out = []
    for c in contracts:
        if c.get("status") == _ENDED or c.get("candidate"):
            continue
        monthly = round(float(c.get("monthly_equivalent") or 0.0), 2)
        if monthly <= 0:
            continue
        owner = to_plan_owner(str(c.get("owner") or ""))
        name = str(c.get("display_name") or c.get("creditor") or "").strip()
        if not name:
            continue
        contract = c.get("contract") or {}
        link = contract.get("plan_position_id")
        pid = slugify_position(name, owner)
        out.append(
            {
                "series_id": c["id"],
                "name": name,
                "owner": from_plan_owner(owner),
                "category": str(c.get("category") or CATEGORY_OTHER),
                "interval": c.get("interval"),
                "amount": monthly,
                "plan_mode": (contract.get("stored") or {}).get("plan_mode"),
                "already_in_plan": pid in taken or bool(link and link in taken),
            }
        )
    out.sort(key=lambda p: p["amount"], reverse=True)
    return out


def validate_acceptance(
    raw: Any, proposals: list[dict[str, Any]], valid_owners: set[str]
) -> list[CostPosition]:
    """Body ``{accept: [{series_id, name?, owner?, amount?, category?}]}`` -> positions.

    Only series that were proposed can be accepted; edits override the proposal.
    """
    items = raw.get("accept") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        raise PrefillError("invalid_body", "accept must be a non-empty list")
    if len(items) > MAX_ACCEPT:
        raise PrefillError("too_many", "Too many positions")
    by_id = {p["series_id"]: p for p in proposals}
    out: list[CostPosition] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise PrefillError("invalid_body", "Each item must be an object")
        base = by_id.get(str(item.get("series_id") or ""))
        if base is None:
            raise PrefillError("unknown_series", "Series is not a proposal")
        owner = str(item["owner"]).strip() if "owner" in item else base["owner"]
        if to_plan_owner(owner) != OWNER_SHARED and owner not in valid_owners:
            raise PrefillError("unknown_owner", "Owner must be shared or a person")
        amount = item.get("amount", base["amount"])
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            raise PrefillError("invalid_amount", "amount must be a number")
        if not 0 < float(amount) <= 1_000_000:
            raise PrefillError("invalid_amount", "amount out of range")
        name = str(item.get("name") or base["name"]).strip()[:80]
        if not name:
            raise PrefillError("invalid_name", "name must not be empty")
        category = str(item.get("category") or base["category"]).strip()[:32]
        pos = CostPosition.from_dict(
            {
                "name": name,
                "owner": to_plan_owner(owner),
                "amount": round(float(amount), 2),
                "category": category,
                "note": "prefilled from detected contract",
            }
        )
        if pos.id in seen:
            raise PrefillError("duplicate", "Two accepted items map to one position")
        seen.add(pos.id)
        out.append(pos)
    return out
