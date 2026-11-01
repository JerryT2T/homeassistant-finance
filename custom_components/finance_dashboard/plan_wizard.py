"""Household-plan wizard ("Haushaltsplan erstellen"): state, gate, income, result.

Everything here is a cache/config read - never a bank call. The wizard state
lives inside the setup-wizard Store (``state["plan_wizard"]``), so there is one
file and no extra reload trigger.

Plan vs. actual: all result figures are PLAN side, monthly, expense positive.
Bank expenses are converted with ``actual_amount_to_plan_sign``; income is
positive on both sides.

``setup_wizard`` imports this module for the state helpers, so the functions
that need ``setup_wizard`` (payday helpers) import it lazily.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from .budget_plan import actual_amount_to_plan_sign
from .const import OWNER_SHARED

STEPS = ("income", "fixed", "pots", "goals", "result")
SKIPPABLE = {"fixed", "pots", "goals"}
STATUSES = ("pending", "done", "skipped")
REQUIRED_CYCLES = 3
MAX_AMOUNT = 1_000_000


class PlanWizardError(ValueError):
    """Invalid plan-wizard input; ``code`` is the API error code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def default_state() -> dict[str, Any]:
    return {"steps": dict.fromkeys(STEPS, "pending"), "current_step": STEPS[0], "completed": False}


def merge_state(raw: Any) -> dict[str, Any]:
    state = default_state()
    if not isinstance(raw, dict):
        return state
    for step, status in (raw.get("steps") or {}).items():
        if step in state["steps"] and status in STATUSES:
            state["steps"][step] = status
    if raw.get("current_step") in STEPS:
        state["current_step"] = raw["current_step"]
    state["completed"] = bool(raw.get("completed"))
    return state


def first_open_step(state: dict[str, Any]) -> str:
    for step, status in state["steps"].items():
        if status == "pending":
            return step
    return STEPS[-1]


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    """GET payload: ``current_step`` is the stored one, ``result`` once completed."""
    pw = merge_state(state)
    current = STEPS[-1] if pw["completed"] else pw["current_step"]
    return {"current_step": current, "steps": dict(pw["steps"]), "completed": pw["completed"]}


def apply_update(state: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Validate ``body`` and return the new plan-wizard state."""
    new = merge_state(state)
    step = body.get("step")
    if step is not None:
        status = body.get("status", "done")
        if step not in new["steps"]:
            raise PlanWizardError("unknown_step", "Unknown plan wizard step")
        if status not in STATUSES:
            raise PlanWizardError("invalid_status", "Status must be pending, done or skipped")
        if status == "skipped" and step not in SKIPPABLE:
            raise PlanWizardError("not_skippable", "This step cannot be skipped")
        new["steps"][step] = status
        if status != "pending":
            new["current_step"] = first_open_step(new)
    if "current_step" in body:
        if body["current_step"] not in STEPS:
            raise PlanWizardError("unknown_step", "Unknown plan wizard step")
        new["current_step"] = body["current_step"]
    if "complete" in body:
        if not isinstance(body["complete"], bool):
            raise PlanWizardError("invalid_complete", "complete must be a boolean")
        new["completed"] = body["complete"]
    return new


# ---------------------------------------------------------------------------
# Payday cycles and the gate
# ---------------------------------------------------------------------------


def household_payday(persons: list[dict[str, Any]]) -> int:
    """First confirmed payday of the household; 1 (calendar month) without one."""
    from .setup_wizard import person_payday

    for p in persons:
        if (day := person_payday(p)) is not None:
            return day
    return 1


def _on(day: int, y: int, m: int) -> date:
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def cycle_boundaries(day: int, earliest: date, today: date) -> list[date]:
    """Payday dates from the first one on/after ``earliest`` up to ``today``.

    Consecutive boundaries delimit one full payday cycle. A boundary equal to
    ``today`` closes the cycle that ended yesterday.
    """
    out: list[date] = []
    y, m = earliest.year, earliest.month
    while True:
        b = _on(day, y, m)
        if b > today:
            return out
        if b >= earliest:
            out.append(b)
        y, m = y + (m == 12), m % 12 + 1


def full_cycles(day: int, earliest: date | None, today: date) -> list[tuple[date, date]]:
    """Complete payday cycles ``(start, end)`` between ``earliest`` and ``today``."""
    if earliest is None:
        return []
    b = cycle_boundaries(day, earliest, today)
    return [(b[i], b[i + 1] - timedelta(days=1)) for i in range(len(b) - 1)]


def _ready_from(day: int, earliest: date, required: int) -> date:
    """Payday on which the ``required``-th full cycle is closed."""
    y, m = earliest.year, earliest.month
    if _on(day, y, m) < earliest:
        y, m = y + (m == 12), m % 12 + 1
    total = m - 1 + required
    return _on(day, y + total // 12, total % 12 + 1)


def build_gate(earliest: date | None, today: date, day: int) -> dict[str, Any]:
    cycles = len(full_cycles(day, earliest, today))
    ready = cycles >= REQUIRED_CYCLES
    return {
        "ready": ready,
        "cycles": cycles,
        "required": REQUIRED_CYCLES,
        "earliest_booked": earliest.isoformat() if earliest else None,
        "ready_from": None
        if ready or earliest is None
        else _ready_from(day, earliest, REQUIRED_CYCLES).isoformat(),
    }


def _parse(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def earliest_booked_by_key(ledger: Any) -> dict[str, str | None]:
    """``{account key: earliest booked date}`` from the ledger (cache only)."""
    if ledger is None:
        return {}
    meta = getattr(ledger, "meta", None) or {}
    history = meta.get("history") if isinstance(meta, dict) else None
    out: dict[str, str | None] = {}
    for key in ledger.account_keys():
        first = ledger.first_booked_date(key)
        if not first and isinstance(history, dict):
            first = (history.get(key) or {}).get("earliest_booked")
        out[key] = str(first)[:10] if first else None
    return out


def earliest_booked(ledger: Any) -> date | None:
    dates = [d for v in earliest_booked_by_key(ledger).values() if (d := _parse(v))]
    return min(dates) if dates else None


# ---------------------------------------------------------------------------
# Income suggestions
# ---------------------------------------------------------------------------


def suggest_income(
    transactions: list[dict[str, Any]], persons: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Largest recurring credit on each person's own accounts, as net income."""
    from .const import CATEGORY_TRANSFERS
    from .recurring import detect_recurring
    from .setup_wizard import amount_of, tx_owner

    out = []
    for p in persons:
        name = str(p.get("name") or "")
        if not name:
            continue
        credits = [
            t
            for t in transactions
            if tx_owner(t) == name
            and t.get("_status", "booked") == "booked"
            and amount_of(t) > 0
            and t.get("category") != CATEGORY_TRANSFERS
        ]
        patterns = [x for x in detect_recurring(credits) if x["average_amount"] > 0]
        if not patterns:
            continue
        best = max(patterns, key=lambda x: x["average_amount"])
        out.append(
            {
                "person": name,
                "amount_net": round(best["average_amount"], 2),
                "source": best["creditor"],
                "samples": int(best.get("occurrences") or 0),
            }
        )
    return out


def validate_income(raw: Any, persons: set[str]) -> list[dict[str, Any]]:
    """``{"income": [{person, amount_net}]}`` -> income entry payloads."""
    items = raw.get("income") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        raise PlanWizardError("invalid_body", "income must be a non-empty list")
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise PlanWizardError("invalid_body", "Each income must be an object")
        person = str(item.get("person") or "")
        if person not in persons:
            raise PlanWizardError("unknown_person", "Unknown person")
        amount = item.get("amount_net")
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            raise PlanWizardError("invalid_amount", "amount_net must be a number")
        if amount != amount or not 0 <= float(amount) <= MAX_AMOUNT:
            raise PlanWizardError("invalid_amount", "amount_net out of range")
        out.append(
            {
                "person": person,
                "deposit": round(float(amount), 2),
                "insurance_mandatory": 0.0,
                "tax_adjustment": 0.0,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


def goal_monthly(goal: dict[str, Any], income_total: float, today: date) -> float:
    """Monthly set-aside a goal asks for (plan sign). Caps add nothing."""
    kind = goal.get("kind")
    if kind == "reserve_topup":
        return float(goal.get("monthly_amount") or 0)
    if kind == "savings_rate":
        return max(0.0, income_total) * float(goal.get("rate_percent") or 0) / 100
    if kind == "target_by_date":
        due = _parse(goal.get("target_date"))
        if due is None:
            return 0.0
        months = max(1, (due.year - today.year) * 12 + due.month - today.month)
        return float(goal.get("target_amount") or 0) / months
    return 0.0


def history_averages(
    transactions: list[dict[str, Any]], cycles: list[tuple[date, date]]
) -> dict[str, Any]:
    """Average income / spend / left over (plan sign) over the full cycles.

    ``transactions`` must already be the counted ones (no transfers).
    """
    from .household_summary import _day

    if not cycles:
        return {"months": 0, "avg_income": None, "avg_spent": None, "avg_left_over": None}
    income: dict[int, float] = defaultdict(float)
    spent: dict[int, float] = defaultdict(float)
    for tx in transactions:
        day = _day(tx)
        if day is None:
            continue
        try:
            bank = float((tx.get("transactionAmount") or {}).get("amount", 0) or 0)
        except (TypeError, ValueError):
            continue
        for i, (s, e) in enumerate(cycles):
            if s <= day <= e:
                if bank > 0 and tx.get("_refund_role") != "refund":
                    income[i] += bank
                else:
                    spent[i] += actual_amount_to_plan_sign(bank)
                break
    n = len(cycles)
    avg_in = sum(income.values()) / n
    avg_out = sum(spent.values()) / n
    return {
        "months": n,
        "avg_income": round(avg_in, 2),
        "avg_spent": round(avg_out, 2),
        "avg_left_over": round(avg_in - avg_out, 2),
    }


def build_result(
    plan: Any,
    pots: list[Any],
    goals: list[dict[str, Any]],
    today: date,
    history: dict[str, Any],
) -> dict[str, Any]:
    """Monthly balance of the plan: income - fixed - pots - goals = left over."""
    month, year = today.month, today.year
    income_total = plan.income_net_total()
    fixed_total = plan.cost_grand_total(month, year)
    pots_total = round(sum(p.cycle_budget for p in pots), 2)
    goal_amounts = [(g, goal_monthly(g, income_total, today)) for g in goals]
    goals_total = round(sum(a for _, a in goal_amounts), 2)
    left_over = round(income_total - fixed_total - pots_total - goals_total, 2)

    shared = (
        plan.cost_shared(month, year)
        + sum(p.cycle_budget for p in pots if p.owner == "shared")
        + sum(a for g, a in goal_amounts if g.get("owner", "shared") == "shared")
    )
    per_person = []
    for person in (p for p in plan.persons if p not in (OWNER_SHARED, "shared")):
        income = plan.income_net(person)
        share = plan.income_rel(person)
        own = (
            plan.cost_individual(person, month, year)
            + sum(p.cycle_budget for p in pots if p.owner == person)
            + sum(a for g, a in goal_amounts if g.get("owner") == person)
        )
        per_person.append(
            {
                "person": person,
                "income": round(income, 2),
                "share": round(share, 4),
                "pocket_money": round(income - shared * share - own, 2),
            }
        )
    return {
        "income_total": round(income_total, 2),
        "fixed_total": round(fixed_total, 2),
        "pots_total": pots_total,
        "goals_total": goals_total,
        "left_over": left_over,
        "balanced": left_over >= 0,
        "per_person": per_person,
        "history": history,
    }
