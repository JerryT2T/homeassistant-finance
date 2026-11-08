"""Budget plan — the migrated household spreadsheet model.

This module holds the PLAN side of the product: what the household expects to
earn and spend each month. Live banking data supplies the ACTUAL side; the two
are compared per position in the monthly summary.

It replaces a spreadsheet with three linked sheets:

- ``Breakdown Einkommen``  → :class:`IncomeEntry` per person
- ``Breakdown Kosten``     → :class:`CostPosition` list (the cost ledger)
- ``Breakdown Saldo``      → computed by :mod:`.household` from this plan

Sign convention (matches the spreadsheet, NOT the bank):
    A cost position's ``amount`` is POSITIVE for an expense and NEGATIVE for a
    reimbursement or credit (e.g. a shared subscription billed onward to a
    third party). ``cost_total`` therefore nets reimbursements out of the sum.
    Bank transactions use the opposite convention (expenses negative), so any
    plan-vs-actual comparison must flip the sign — see
    :func:`actual_amount_to_plan_sign`.

Ownership is a property of the POSITION, not of the account it is debited from.
"Google One" can exist twice — once shared, once personal — and a personal cost
may well be debited from the joint account. Deriving ownership from the account
cannot express that, so it is not derived from the account.

SECURITY: This module defines the model and its arithmetic only. Amounts are
persisted exclusively to HA's ``.storage/`` via :class:`BudgetPlanStore` and
must never be committed to git.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CATEGORY_OTHER,
    OWNER_SHARED,
    POSITION_KIND_BUFFER,
    POSITION_KIND_FIXED,
    STORAGE_KEY_BUDGET_PLAN,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify_position(name: str, owner: str) -> str:
    """Build a stable position id from its name and owner.

    The id must survive renames of unrelated positions and must not collide
    when the same position name exists for two different owners (the
    spreadsheet has "Google One" as both a shared and a personal position).
    """
    base = _SLUG_RE.sub("_", name.strip().lower()).strip("_") or "position"
    if owner == OWNER_SHARED:
        owner_part = "shared"
    else:
        owner_part = _SLUG_RE.sub("_", owner.strip().lower()).strip("_")
    return f"{base}__{owner_part}" if owner_part else base


def _parse_month_key(value: str | None) -> tuple[int, int] | None:
    """Parse a ``YYYY-MM`` validity bound into a sortable ``(year, month)``.

    Returns ``None`` for empty or malformed input, which callers treat as
    "unbounded" — a malformed bound must never silently hide a position.
    """
    if not value:
        return None
    parts = str(value).strip().split("-")
    if len(parts) < 2:
        return None
    try:
        year = int(parts[0])
        month = int(parts[1])
    except (TypeError, ValueError):
        return None
    if not 1 <= month <= 12:
        return None
    return (year, month)


def actual_amount_to_plan_sign(bank_amount: float) -> float:
    """Convert a bank transaction amount to the plan's sign convention.

    Bank: expense negative, income positive.
    Plan: expense positive, reimbursement negative.
    """
    return -float(bank_amount)


@dataclass
class CostPosition:
    """A single named cost position in the ledger.

    Attributes:
        id: Stable identifier, see :func:`slugify_position`.
        name: Human label as it appears in the household's own vocabulary.
        owner: A person's name, or :data:`OWNER_SHARED`.
        amount: Planned monthly EUR. Positive = expense, negative = credit.
            Ignored when ``kind`` is ``buffer`` (computed from the factors).
        kind: ``fixed`` (a recurring debit) or ``buffer`` (units x unit price).
        category: One of the ``CATEGORY_*`` constants, used for grouping,
            budget limits and benchmark numerators.
        buffer_units: For ``buffer`` positions, e.g. 4.5 weeks.
        buffer_unit_price: For ``buffer`` positions, e.g. 80 EUR per week.
        valid_from: Inclusive ``YYYY-MM`` lower bound, or None.
        valid_until: Inclusive ``YYYY-MM`` upper bound, or None.
        note: Free-form remark (the spreadsheet's comment column).
        debit_account: Account id this position is actually debited from, or
            None to use the default (shared positions from the joint account,
            individual positions from the owner's own account). Ownership and
            payment account are independent: the spreadsheet debits one
            person's mobile contract from the joint living-costs account while
            still counting it as that person's individual cost.
    """

    id: str
    name: str
    owner: str
    amount: float = 0.0
    kind: str = POSITION_KIND_FIXED
    category: str = CATEGORY_OTHER
    buffer_units: float | None = None
    buffer_unit_price: float | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    note: str = ""
    debit_account: str | None = None
    suspended: bool = False  # paused on purpose: the review does not expect a booking

    @property
    def is_shared(self) -> bool:
        """True when this position is a shared household cost."""
        return self.owner == OWNER_SHARED

    @property
    def planned_amount(self) -> float:
        """Planned monthly amount, ignoring validity.

        For buffer positions this is ``units * unit_price``; the spreadsheet
        writes these as formulas (``80*4.5``) precisely so the factors stay
        visible and adjustable.
        """
        if self.kind == POSITION_KIND_BUFFER:
            units = self.buffer_units or 0.0
            price = self.buffer_unit_price or 0.0
            return round(units * price, 2)
        return round(self.amount, 2)

    def is_active(self, month: int, year: int) -> bool:
        """Whether this position applies in the given calendar month.

        Bounds are inclusive, so a position marked "until April 2027" is still
        charged in April 2027 and drops out in May 2027.
        """
        current = (year, month)
        start = _parse_month_key(self.valid_from)
        end = _parse_month_key(self.valid_until)
        if start and current < start:
            return False
        if end and current > end:
            return False
        return True

    def effective_amount(self, month: int, year: int) -> float:
        """Planned amount for the given month, or 0.0 when out of validity."""
        return self.planned_amount if self.is_active(month, year) else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for .storage/ persistence."""
        return {
            "id": self.id,
            "name": self.name,
            "owner": self.owner,
            "amount": self.amount,
            "kind": self.kind,
            "category": self.category,
            "buffer_units": self.buffer_units,
            "buffer_unit_price": self.buffer_unit_price,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "note": self.note,
            "debit_account": self.debit_account,
            "suspended": self.suspended,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostPosition:
        """Rebuild a position from stored data, tolerating missing keys."""
        name = str(data.get("name", "")).strip()
        owner = str(data.get("owner", OWNER_SHARED))
        kind = data.get("kind", POSITION_KIND_FIXED)
        if kind not in (POSITION_KIND_FIXED, POSITION_KIND_BUFFER):
            kind = POSITION_KIND_FIXED
        return cls(
            id=str(data.get("id") or slugify_position(name, owner)),
            name=name,
            owner=owner,
            amount=float(data.get("amount") or 0.0),
            kind=kind,
            category=str(data.get("category") or CATEGORY_OTHER),
            buffer_units=(
                float(data["buffer_units"]) if data.get("buffer_units") is not None else None
            ),
            buffer_unit_price=(
                float(data["buffer_unit_price"])
                if data.get("buffer_unit_price") is not None
                else None
            ),
            valid_from=data.get("valid_from") or None,
            valid_until=data.get("valid_until") or None,
            note=str(data.get("note") or ""),
            debit_account=data.get("debit_account") or None,
            suspended=bool(data.get("suspended", False)),
        )


@dataclass
class IncomeEntry:
    """Planned monthly income for one person.

    Mirrors ``Breakdown Einkommen``: what lands on the account, minus legally
    required private insurance, plus/minus the tax-class settlement.

    A person may legitimately have a NEGATIVE net income — deposit 0 while
    insurance is still charged. Nothing downstream may assume net > 0.
    """

    person: str
    deposit: float = 0.0
    insurance_mandatory: float = 0.0
    tax_adjustment: float = 0.0

    @property
    def net(self) -> float:
        """Net income = deposit + insurance (negative) + tax adjustment."""
        return round(self.deposit + self.insurance_mandatory + self.tax_adjustment, 2)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for .storage/ persistence."""
        return {
            "person": self.person,
            "deposit": self.deposit,
            "insurance_mandatory": self.insurance_mandatory,
            "tax_adjustment": self.tax_adjustment,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IncomeEntry:
        """Rebuild an income entry from stored data."""
        return cls(
            person=str(data.get("person", "")),
            deposit=float(data.get("deposit") or 0.0),
            insurance_mandatory=float(data.get("insurance_mandatory") or 0.0),
            tax_adjustment=float(data.get("tax_adjustment") or 0.0),
        )


@dataclass
class BudgetPlan:
    """The complete plan: persons, their income, and the cost ledger."""

    persons: list[str] = field(default_factory=list)
    income: dict[str, IncomeEntry] = field(default_factory=dict)
    positions: list[CostPosition] = field(default_factory=list)
    source: str = ""  # provenance, e.g. "spreadsheet-import"

    # -- income ------------------------------------------------------------

    def income_net(self, person: str) -> float:
        """Net income for one person (0.0 when unknown)."""
        entry = self.income.get(person)
        return entry.net if entry else 0.0

    def income_net_total(self) -> float:
        """Pooled net income across all persons."""
        return round(sum(self.income_net(p) for p in self.persons), 2)

    def income_rel(self, person: str) -> float:
        """Share of pooled net income.

        Returns 0.0 when the pool is zero. The share may exceed 1.0 or go
        negative when another person's net income is negative — that is a
        faithful property of the model, not an error.
        """
        total = self.income_net_total()
        if total == 0:
            return 0.0
        return round(self.income_net(person) / total, 6)

    # -- costs -------------------------------------------------------------

    def active_positions(self, month: int, year: int) -> list[CostPosition]:
        """Positions that apply in the given month."""
        return [p for p in self.positions if p.is_active(month, year)]

    def positions_for(self, owner: str) -> list[CostPosition]:
        """All positions belonging to one owner (person name or shared)."""
        return [p for p in self.positions if p.owner == owner]

    def cost_total(self, owner: str, month: int, year: int) -> float:
        """Net planned cost for one owner in the given month.

        Reimbursements (negative positions) reduce the total, which is how the
        spreadsheet's column sums behave.
        """
        return round(
            sum(p.effective_amount(month, year) for p in self.positions if p.owner == owner),
            2,
        )

    def cost_shared(self, month: int, year: int) -> float:
        """Net planned shared cost for the given month."""
        return self.cost_total(OWNER_SHARED, month, year)

    def cost_individual(self, person: str, month: int, year: int) -> float:
        """Net planned individual cost for one person."""
        return self.cost_total(person, month, year)

    def cost_grand_total(self, month: int, year: int) -> float:
        """Shared plus all individual costs."""
        return round(
            sum(p.effective_amount(month, year) for p in self.positions),
            2,
        )

    def buffer_total(self, month: int, year: int, owner: str | None = None) -> float:
        """Planned buffer (variable) costs, optionally for one owner.

        The transfer choreography books buffers separately from fixed debits,
        so this has to be addressable on its own.
        """
        return round(
            sum(
                p.effective_amount(month, year)
                for p in self.positions
                if p.kind == POSITION_KIND_BUFFER and (owner is None or p.owner == owner)
            ),
            2,
        )

    def fixed_total(self, month: int, year: int, owner: str | None = None) -> float:
        """Planned fixed costs, optionally for one owner."""
        return round(
            sum(
                p.effective_amount(month, year)
                for p in self.positions
                if p.kind == POSITION_KIND_FIXED and (owner is None or p.owner == owner)
            ),
            2,
        )

    def category_totals(self, month: int, year: int, owner: str | None = None) -> dict[str, float]:
        """Planned cost per category for the given month."""
        totals: dict[str, float] = {}
        for p in self.positions:
            if owner is not None and p.owner != owner:
                continue
            amount = p.effective_amount(month, year)
            if amount == 0:
                continue
            totals[p.category] = round(totals.get(p.category, 0.0) + amount, 2)
        return totals

    # -- mutation ----------------------------------------------------------

    def upsert_position(self, position: CostPosition) -> CostPosition:
        """Insert or replace a position by id, keeping list order stable."""
        for idx, existing in enumerate(self.positions):
            if existing.id == position.id:
                self.positions[idx] = position
                return position
        self.positions.append(position)
        self._ensure_person(position.owner)
        return position

    def remove_position(self, position_id: str) -> bool:
        """Remove a position by id. Returns True when something was removed."""
        before = len(self.positions)
        self.positions = [p for p in self.positions if p.id != position_id]
        return len(self.positions) < before

    def set_income(self, entry: IncomeEntry) -> None:
        """Set or replace a person's income entry."""
        self.income[entry.person] = entry
        self._ensure_person(entry.person)

    def _ensure_person(self, owner: str) -> None:
        """Register a person referenced by a position or income entry."""
        if owner and owner != OWNER_SHARED and owner not in self.persons:
            self.persons.append(owner)

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the whole plan for .storage/ persistence."""
        return {
            "persons": self.persons,
            "income": [e.to_dict() for e in self.income.values()],
            "positions": [p.to_dict() for p in self.positions],
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BudgetPlan:
        """Rebuild a plan from stored data. Missing/short data yields an empty plan."""
        if not data:
            return cls()
        income = {}
        for raw in data.get("income", []) or []:
            entry = IncomeEntry.from_dict(raw)
            if entry.person:
                income[entry.person] = entry
        positions = [
            CostPosition.from_dict(raw) for raw in (data.get("positions") or []) if raw.get("name")
        ]
        persons = [str(p) for p in (data.get("persons") or []) if p]
        # Heal a plan whose person list drifted from its income/position owners.
        for name in list(income) + [p.owner for p in positions]:
            if name and name != OWNER_SHARED and name not in persons:
                persons.append(name)
        return cls(
            persons=persons,
            income=income,
            positions=positions,
            source=str(data.get("source") or ""),
        )

    def is_empty(self) -> bool:
        """True when nothing has been planned yet."""
        return not self.positions and not self.income


class BudgetPlanStore:
    """Persists the budget plan in HA's ``.storage/``.

    SECURITY: the plan contains real amounts. It lives only in ``.storage/``,
    never in the repository, and is never sent anywhere externally.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY_BUDGET_PLAN)
        self._plan: BudgetPlan | None = None

    async def async_load(self) -> BudgetPlan:
        """Load the plan, falling back to an empty plan on any read error."""
        if self._plan is not None:
            return self._plan
        try:
            raw = await self._store.async_load()
        except Exception:
            _LOGGER.exception("Budget plan load failed — starting from an empty plan")
            raw = None
        self._plan = BudgetPlan.from_dict(raw)
        if not self._plan.is_empty():
            _LOGGER.info(
                "Budget plan loaded: %d positions, %d persons (source: %s)",
                len(self._plan.positions),
                len(self._plan.persons),
                self._plan.source or "manual",
            )
        return self._plan

    async def async_save(self, plan: BudgetPlan) -> None:
        """Persist the plan."""
        self._plan = plan
        await self._store.async_save(plan.to_dict())

    @property
    def plan(self) -> BudgetPlan:
        """The in-memory plan (empty until :meth:`async_load` has run)."""
        return self._plan if self._plan is not None else BudgetPlan()
