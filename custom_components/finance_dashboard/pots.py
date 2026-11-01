"""Pots ("Töpfe") — household budget envelopes with cycle-aggregated balances.

A pot is part of the PLAN side: a cycle budget for a set of categories with an
explicit owner (a person, or ``"shared"``). The ACTUAL side (bank bookings)
only feeds the balance. Personal pots are fed from the owner's personal
accounts only; shared pots from shared accounts only.

Sign convention: everything here is in the PLAN sign (expense positive). The
caller converts bank amounts with ``actual_amount_to_plan_sign``.

Pending (vorgemerkte) bookings are not spent yet: they show up as upcoming only.

A *booking* in this module is a dict::

    {"date": date, "amount": float, "category": str, "pending": bool, "label": str}

Balance model: a pot earns ``cycle_budget / days_in_cycle`` every day of the
cycle. Money not spent on a day stays in the pot (carry-over), overspending
makes the balance negative. A new cycle starts from zero again - nothing is
carried across the cycle boundary.

Status (±10 % rule): spent up to the linear amount to date -> ``good``; up to
10 % above it -> ``knapp`` (still fine); above -> ``over``.

SECURITY: pots contain budget amounts. They live only in HA's ``.storage/`` and
must never be committed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY_POTS, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

POT_OWNER_SHARED = "shared"
POT_KIND_SPEND = "spend"
POT_KIND_RESERVE = "reserve"
POT_KINDS = (POT_KIND_SPEND, POT_KIND_RESERVE)

STATUS_GOOD = "good"
STATUS_KNAPP = "knapp"
STATUS_OVER = "over"
KNAPP_TOLERANCE = 0.10

UPCOMING_TOP_N = 3

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class Pot:
    """One budget envelope."""

    id: str
    name: str
    owner: str = POT_OWNER_SHARED
    cycle_budget: float = 0.0  # plan sign: positive
    category_keys: list[str] = field(default_factory=list)
    kind: str = POT_KIND_SPEND
    account_key: str = ""  # account the virtual pot sits on (coverage check)
    # Accounts whose bookings count as spending of this pot (account identity keys,
    # never raw uids). None = all accounts.
    account_keys: list[str] | None = None
    # week start (ISO Monday) -> "accept" | "drop": what the user decided about the
    # carry-over into that week. No entry = default (carry stays in the balance).
    carry_decisions: dict[str, str] = field(default_factory=dict)

    @property
    def is_shared(self) -> bool:
        return self.owner == POT_OWNER_SHARED

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "owner": self.owner,
            "cycle_budget": round(self.cycle_budget, 2),
            "category_keys": list(self.category_keys),
            "kind": self.kind,
            "account_key": self.account_key,
            "account_keys": None if self.account_keys is None else list(self.account_keys),
            "carry_decisions": dict(self.carry_decisions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pot:
        """Validate and build a pot. Raises ``ValueError`` on bad input."""
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("A pot needs a name")
        if len(name) > 60:
            raise ValueError("Pot name too long")
        owner = str(data.get("owner") or POT_OWNER_SHARED).strip()
        kind = str(data.get("kind") or POT_KIND_SPEND)
        if kind not in POT_KINDS:
            raise ValueError("Unknown pot kind")
        try:
            budget = float(data.get("cycle_budget", 0) or 0)
        except (TypeError, ValueError) as err:
            raise ValueError("cycle_budget must be a number") from err
        if budget != budget or budget < 0 or budget > 1_000_000:  # NaN, negative, absurd
            raise ValueError("cycle_budget out of range")
        raw_keys = data.get("category_keys") or []
        if not isinstance(raw_keys, list):
            raise ValueError("category_keys must be a list")
        keys = list(dict.fromkeys(str(k).strip() for k in raw_keys if str(k).strip()))
        pot_id = str(data.get("id") or "").strip() or slugify_pot(name, owner)
        return cls(
            id=pot_id,
            name=name,
            owner=owner,
            cycle_budget=budget,
            category_keys=keys,
            kind=kind,
            account_key=str(data.get("account_key") or "").strip()[:80],
            account_keys=_clean_account_keys(data.get("account_keys")),
            carry_decisions=_clean_decisions(data.get("carry_decisions")),
        )


MAX_ACCOUNT_KEYS = 20


def _clean_account_keys(raw: Any) -> list[str] | None:
    """``None``/empty -> all accounts; else a deduplicated list of identity keys."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("account_keys must be a list or null")
    keys = list(dict.fromkeys(str(k).strip()[:80] for k in raw if str(k).strip()))
    if len(keys) > MAX_ACCOUNT_KEYS:
        raise ValueError("too many account_keys")
    return keys or None


def pot_accepts_account(pot: Pot, key: Any) -> bool:
    """Whether a booking from account ``key`` counts for ``pot``.

    Unbound pots take everything; a booking without a key (a projected upcoming
    one) is unknown and therefore kept.
    """
    if pot.account_keys is None or not key:
        return True
    return str(key) in pot.account_keys


CARRY_ACCEPT = "accept"
CARRY_DROP = "drop"
CARRY_ACTIONS = (CARRY_ACCEPT, CARRY_DROP)
_MAX_DECISIONS = 8  # only recent weeks matter; older ones are pruned


def _clean_decisions(raw: Any) -> dict[str, str]:
    """Keep well-formed ``{iso monday: accept|drop}`` entries, newest few only."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        try:
            day = date.fromisoformat(str(k))
        except ValueError:
            continue
        if v in CARRY_ACTIONS and day.weekday() == 0:
            out[day.isoformat()] = v
    return dict(sorted(out.items())[-_MAX_DECISIONS:])


def slugify_pot(name: str, owner: str) -> str:
    base = _SLUG_RE.sub("_", name.strip().lower()).strip("_") or "pot"
    owner_part = _SLUG_RE.sub("_", owner.strip().lower()).strip("_") or "shared"
    return f"{base}__{owner_part}"


class PotStore:
    """Persists the pots in HA's ``.storage/`` (plan data, never in git)."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY_POTS)
        self._pots: list[Pot] = []

    async def async_load(self) -> list[Pot]:
        try:
            raw = await self._store.async_load()
        except Exception:
            _LOGGER.exception("Pot load failed - starting without pots")
            raw = None
        pots: list[Pot] = []
        for item in (raw or {}).get("pots", []) if isinstance(raw, dict) else []:
            try:
                pots.append(Pot.from_dict(item))
            except (ValueError, AttributeError):
                _LOGGER.warning("Skipping an unreadable pot entry")
        self._pots = pots
        return self._pots

    async def async_save(self) -> None:
        await self._store.async_save({"pots": [p.to_dict() for p in self._pots]})

    @property
    def pots(self) -> list[Pot]:
        return self._pots

    def get(self, pot_id: str) -> Pot | None:
        return next((p for p in self._pots if p.id == pot_id), None)

    async def async_upsert(self, pot: Pot, *, replace_existing: bool) -> Pot:
        """Insert (``replace_existing=False``: unique id enforced) or replace."""
        existing = self.get(pot.id)
        if replace_existing:
            if existing is None:
                raise KeyError(pot.id)
            if not pot.carry_decisions:  # PUT /pots from the sheet never carries them
                pot.carry_decisions = dict(existing.carry_decisions)
            self._pots[self._pots.index(existing)] = pot
        else:
            base, n = pot.id, 2
            while self.get(pot.id) is not None:
                pot.id = f"{base}_{n}"
                n += 1
            self._pots.append(pot)
        await self.async_save()
        return pot

    async def async_set_carry_decision(self, pot_id: str, week_start: date, action: str) -> bool:
        """Persist accept/drop of the carry into ``week_start`` (idempotent). False: unknown pot."""
        pot = self.get(pot_id)
        if pot is None:
            return False
        if action not in CARRY_ACTIONS:
            raise ValueError("Unknown carry action")
        key = week_start.isoformat()
        if pot.carry_decisions.get(key) != action:
            pot.carry_decisions[key] = action
            pot.carry_decisions = _clean_decisions(pot.carry_decisions)
            await self.async_save()
        return True

    async def async_delete(self, pot_id: str) -> bool:
        existing = self.get(pot_id)
        if existing is None:
            return False
        self._pots.remove(existing)
        await self.async_save()
        return True


# ---------------------------------------------------------------------------
# Pure status arithmetic
# ---------------------------------------------------------------------------


def cycle_days(cycle: tuple[date, date]) -> int:
    return max(1, (cycle[1] - cycle[0]).days + 1)


def status_for(spent: float, linear_to_date: float) -> str:
    """±10 % rule: good up to the linear amount, knapp up to +10 %, else over."""
    if spent <= linear_to_date + 1e-9:
        return STATUS_GOOD
    if spent <= linear_to_date * (1 + KNAPP_TOLERANCE) + 1e-9:
        return STATUS_KNAPP
    return STATUS_OVER


def _matching(pot: Pot, bookings: list[dict[str, Any]], cycle: tuple[date, date], upto: date):
    keys = set(pot.category_keys)
    for b in bookings:
        if (
            b["category"] in keys
            and pot_accepts_account(pot, b.get("account_key"))
            and not b.get("pending")
            and not b.get("upcoming")
            and cycle[0] <= b["date"] <= min(upto, cycle[1])
        ):
            yield b


def week_bounds(today: date) -> tuple[date, date]:
    """Monday to Sunday of the week containing ``today``."""
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def pot_status(
    pot: Pot,
    bookings_in_cycle: list[dict[str, Any]],
    cycle: tuple[date, date],
    today: date,
) -> dict[str, Any]:
    """Cycle-aggregated state of one pot.

    Returns ``balance`` (available now, unspent days carried forward inside the
    cycle), ``per_day_typical`` (the pot's daily allowance), ``spent``,
    ``linear_to_date``, ``status`` and ``carry_in_week`` (balance carried into
    the current week from earlier weeks of the same cycle - 0 in the first week)
    and ``carry_decision``. A ``drop`` decision for the current week removes the
    carry from the balance (the week starts fresh); ``carry_in_week`` still shows
    the raw amount so the UI can say what was dropped.
    """
    total_days = cycle_days(cycle)
    daily = pot.cycle_budget / total_days
    today_c = min(max(today, cycle[0] - timedelta(days=1)), cycle[1])
    elapsed = (today_c - cycle[0]).days + 1
    linear = daily * elapsed
    spent = sum(b["amount"] for b in _matching(pot, bookings_in_cycle, cycle, today))
    week_start, _ = week_bounds(today)
    before_week = week_start - timedelta(days=1)
    if before_week < cycle[0]:
        carry = 0.0
    else:
        days_before = (before_week - cycle[0]).days + 1
        carry = daily * days_before - sum(
            b["amount"] for b in _matching(pot, bookings_in_cycle, cycle, before_week)
        )
    decision = pot.carry_decisions.get(week_start.isoformat())
    dropped = decision == CARRY_DROP
    return {
        "balance": round(linear - spent - (carry if dropped else 0.0), 2),
        "per_day_typical": round(daily, 2),
        "spent": round(spent, 2),
        "linear_to_date": round(linear, 2),
        "status": status_for(spent, linear),
        "carry_in_week": round(carry, 2),
        "carry_decision": decision,
        "cycle_budget": round(pot.cycle_budget, 2),
    }


def pot_cycle_history(
    pot: Pot,
    bookings: list[dict[str, Any]],
    cycles: list[tuple[date, date]],
) -> list[dict[str, Any]]:
    """Per finished cycle: budget, spent and what was left (``carry``).

    Nothing crosses a cycle boundary, so ``carry`` is the pot's closing balance
    (``budget - spent``; negative = overspent). ``cycles`` ascending.
    """
    out = []
    for cyc in cycles:
        spent = sum(b["amount"] for b in _matching(pot, bookings, cyc, cyc[1]))
        out.append(
            {
                "start": cyc[0].isoformat(),
                "end": cyc[1].isoformat(),
                "budget": round(pot.cycle_budget, 2),
                "spent": round(spent, 2),
                "carry": round(pot.cycle_budget - spent, 2),
            }
        )
    return out


def _upcoming_items(
    bookings: list[dict[str, Any]], pots: list[Pot], start: date, end: date
) -> list[dict[str, Any]]:
    """Pending bookings (and known upcoming ones) between ``start`` and ``end``."""
    keys = {k for p in pots for k in p.category_keys}
    items = [
        {
            "date": b["date"].isoformat(),
            "label": b.get("label", ""),
            "amount": round(b["amount"], 2),
            "pending": bool(b.get("pending")),
            "category": b["category"],
        }
        for b in bookings
        if (b.get("pending") or b.get("upcoming"))
        and start <= b["date"] <= end
        and (not keys or b["category"] in keys)
    ]
    items.sort(key=lambda i: (i["date"], i["label"]))
    return items


def week_status(
    pots: list[Pot],
    bookings: list[dict[str, Any]],
    cycle: tuple[date, date],
    today: date,
) -> dict[str, Any]:
    """Daily budget vs. actual for the current week (Mon-Sun).

    - ``daily_budget``: sum of the spend pots' daily allowance.
    - ``carry_over``: what earlier weeks *of this cycle* left (+) or overspent
      (-). Never reaches back before the cycle start.
    - ``week_budget``: ``max(0, carry_over + daily_budget * days_in_week)``.
    - ``linear_line``: cumulative allowance per day with the carry-over spread
      evenly over the week's days.
    - ``zero_carry_line``: the same without carry-over; flat 0 when the carry
      is so negative that nothing is left this week.
    """
    spend = [p for p in pots if p.kind == POT_KIND_SPEND]
    total_days = cycle_days(cycle)
    daily = sum(p.cycle_budget for p in spend) / total_days
    keys = {k for p in spend for k in p.category_keys}
    week_start, week_end = week_bounds(today)
    real = [b for b in bookings if not b.get("upcoming") and not b.get("pending")]

    def _spent_on(day: date) -> float:
        return sum(b["amount"] for b in real if b["category"] in keys and b["date"] == day)

    days: list[dict[str, Any]] = []
    in_cycle_days = 0
    for i in range(7):
        day = week_start + timedelta(days=i)
        inside = cycle[0] <= day <= cycle[1]
        in_cycle_days += inside
        days.append(
            {
                "date": day.isoformat(),
                "budget": round(daily, 2) if inside else 0.0,
                "actual": round(_spent_on(day), 2) if inside and day <= today else 0.0,
                "future": day > today,
                "today": day == today,
                "in_cycle": inside,
            }
        )

    carry = 0.0
    if week_start > cycle[0]:
        d = cycle[0]
        while d < week_start:
            carry += daily - _spent_on(d)
            d += timedelta(days=1)

    if week_start > cycle[0]:
        for pot in spend:
            if pot.carry_decisions.get(week_start.isoformat()) != CARRY_DROP:
                continue
            pdaily = pot.cycle_budget / total_days
            pkeys = set(pot.category_keys)
            d = cycle[0]
            while d < week_start:
                carry -= pdaily - sum(
                    b["amount"] for b in real if b["category"] in pkeys and b["date"] == d
                )
                d += timedelta(days=1)

    week_budget = max(0.0, carry + daily * in_cycle_days)
    n = max(1, in_cycle_days)
    linear, zero_carry, running = [], [], 0
    for i, day in enumerate(days):
        running += 1 if day["in_cycle"] else 0
        linear.append(round(week_budget * running / n, 2))
        zero_carry.append(round(daily * running, 2) if week_budget > 0 else 0.0)

    spent = sum(d["actual"] for d in days)
    pending = _upcoming_items(bookings, spend, today, week_end)
    return {
        "start": week_start.isoformat(),
        "end": week_end.isoformat(),
        "daily_budget": round(daily, 2),
        "carry_over": round(carry, 2),
        "week_budget": round(week_budget, 2),
        "spent": round(spent, 2),
        "remaining": round(week_budget - spent, 2),
        "days": days,
        "linear_line": linear,
        "zero_carry_line": zero_carry,
        "upcoming": {
            "sum": round(sum(i["amount"] for i in pending), 2),
            "items": pending[:UPCOMING_TOP_N],
            "count": len(pending),
        },
    }


# ---------------------------------------------------------------------------
# Coverage: virtual pots vs. the real position of the accounts they sit on
# ---------------------------------------------------------------------------

COVERAGE_COVERED = "covered"
COVERAGE_SHORTFALL = "shortfall"


def pot_coverage(
    pots: list[Pot],
    accounts: list[dict[str, Any]],
    balances: dict[str, Any],
    *,
    amounts: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compare the sum of reserve pots per account with its real balance.

    Only ``reserve`` pots that name an ``account_key`` count; ``amounts`` may
    override a pot's virtual amount (default: its ``cycle_budget``). An account
    flagged ``savings`` is reported as such. ``top_up`` is the amount missing
    on the account (0 when covered). Accounts without a cached balance are
    reported with ``real_balance`` None and status ``unknown``.
    """
    from .account_identity import account_key
    from .balances import amount_of, pick_balance

    amounts = amounts or {}
    by_key = {account_key(a): a for a in accounts}
    virtual: dict[str, float] = {}
    pot_ids: dict[str, list[str]] = {}
    unassigned = 0
    for pot in pots:
        if pot.kind != POT_KIND_RESERVE:
            continue
        if not pot.account_key or pot.account_key not in by_key:
            unassigned += 1
            continue
        virtual[pot.account_key] = virtual.get(pot.account_key, 0.0) + float(
            amounts.get(pot.id, pot.cycle_budget)
        )
        pot_ids.setdefault(pot.account_key, []).append(pot.id)

    rows = []
    for key, total in virtual.items():
        acc = by_key[key]
        entry = balances.get(acc.get("id")) if acc.get("id") else None
        raw = entry.get("balances") if isinstance(entry, dict) else None
        real = amount_of(pick_balance(raw or []))
        if real is None:
            status, top_up = "unknown", 0.0
        elif real >= total:
            status, top_up = COVERAGE_COVERED, 0.0
        else:
            status, top_up = COVERAGE_SHORTFALL, round(total - real, 2)
        rows.append(
            {
                "account_key": key,
                "name": str(acc.get("custom_name") or acc.get("name") or ""),
                "savings": bool(acc.get("savings")),
                "pot_ids": pot_ids[key],
                "virtual_total": round(total, 2),
                "real_balance": None if real is None else round(real, 2),
                "status": status,
                "top_up": top_up,
            }
        )
    rows.sort(key=lambda r: r["name"])
    return {
        "accounts": rows,
        "unassigned_pots": unassigned,
        "total_top_up": round(sum(r["top_up"] for r in rows), 2),
        "status": COVERAGE_SHORTFALL
        if any(r["status"] == COVERAGE_SHORTFALL for r in rows)
        else COVERAGE_COVERED,
    }
