"""Home-screen payload (``GET /api/finance_dashboard/home``).

Pure assembly from cached data - no I/O, no clock, never a bank call. The
manager hands in accounts, transactions, plan, pots and bank status; this
module turns them into the contract the frontend renders.

Ownership and privacy (decided rules):

- An account belongs to a person (``type`` personal) or to the household
  (``type`` shared). Personal pots are fed only from the owner's accounts,
  shared pots only from shared accounts.
- **Person view**: only that person's own pots, bookings and items.
- **Household view**: shared pots in full; every person only as a *total*
  (budget / spent / status) - never a pot name, merchant or booking of a
  person, not even the viewer's own.
- There is no way to ask for another person's person view: the person comes
  from the logged-in HA user (:func:`resolve_person`).

Sign convention: plan sign (expense positive) throughout, converted with
``actual_amount_to_plan_sign``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from .budget_plan import BudgetPlan, actual_amount_to_plan_sign
from .const import POSITION_KIND_FIXED
from .contracts import is_own_name, own_account_names
from .cycle import (
    calendar_cycle,
    cycle_windows,
    household_cycle,
    household_starts,
    person_cycle,
    salary_starts,
)
from .merchants import display_name, merchant_key
from .pots import (
    POT_KIND_RESERVE,
    POT_KIND_SPEND,
    POT_OWNER_SHARED,
    Pot,
    cycle_days,
    pot_accepts_account,
    pot_cycle_history,
    pot_status,
    status_for,
    week_bounds,
    week_status,
)
from .questions import merchant_history, select_questions  # noqa: E402

HORIZONS = ("today", "week", "cycle", "year")
VIEWS = ("person", "household")
FRESH_SECONDS = 6 * 3600
NEXT_TOP_N = 3
YEAR_CYCLES = 12
DID_YOU_KNOW_MIN_SHARE = 0.30
RECENT_DAYS = 14
RECENT_MAX = 30

_SKIP_CATEGORIES = {"income", "income_work", "income_state", "income_capital", "income_refund", "income_private", "transfers"}


def account_owner(account: dict[str, Any]) -> str:
    """Owner of an account: the person, or ``"shared"``."""
    if account.get("type") == "shared":
        return POT_OWNER_SHARED
    return str(account.get("person") or "") or POT_OWNER_SHARED


def resolve_person(
    user: Any,
    accounts: list[dict[str, Any]],
    persons: list[dict[str, Any]] | None = None,
) -> str | None:
    """Map the logged-in HA user to a person.

    First through the configured persons (``entry.data["persons"]``, which work
    before any account is assigned), then - as fallback - through the accounts'
    ``ha_users``.
    """
    if user is None:
        return None
    ids = {str(getattr(user, "id", "") or "")} - {""}
    names = {str(getattr(user, "name", "") or "").lower()} - {""}
    for cfg in persons or []:
        name = str(cfg.get("name") or "")
        if name and ids & {str(i) for i in cfg.get("ha_users") or []}:
            return name
    for acc in accounts:
        person = str(acc.get("person") or "")
        if not person or acc.get("type") == "shared":
            continue
        for entry in acc.get("ha_users") or []:
            if isinstance(entry, dict):
                eid = str(entry.get("id") or entry.get("user_id") or "")
                ename = str(entry.get("name") or "").lower()
            else:
                eid, ename = str(entry), str(entry).lower()
            if (eid and eid in ids) or (ename and ename in names):
                return person
    return None


def setup_block(
    accounts: list[dict[str, Any]],
    persons: list[dict[str, Any]] | None,
    pots: int,
    *,
    user_mapped: bool,
) -> dict[str, Any]:
    """Cheap onboarding status: are persons and accounts set up?"""
    names = {str(p.get("name") or "") for p in persons or []} - {""}
    names |= {
        str(a.get("person") or "")
        for a in accounts
        if a.get("type") != "shared" and a.get("person")
    }
    assigned = sum(1 for a in accounts if a.get("type") == "shared" or str(a.get("person") or ""))
    return {
        "persons": len(names),
        "user_mapped": user_mapped,
        "accounts_total": len(accounts),
        "accounts_assigned": assigned,
        "pots": pots,
    }


def _to_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _booking(tx: dict[str, Any], today: date) -> dict[str, Any] | None:
    """Transaction -> internal booking (plan sign) or None when not usable."""
    try:
        amount = float((tx.get("transactionAmount") or {}).get("amount", 0) or 0)
    except (TypeError, ValueError):
        return None
    day = (
        _to_date(tx.get("bookingDate"))
        or _to_date(tx.get("valueDate"))
        or _to_date(tx.get("transactionDate"))
    )
    if day is None:
        return None
    pending = tx.get("_status") == "pending"
    owner = (
        POT_OWNER_SHARED
        if tx.get("_account_type") == "shared"
        else str(tx.get("_account_person") or "") or POT_OWNER_SHARED
    )
    # A learned merchant owner (user answer) overrides the account default.
    owner = str(tx.get("_owner_override") or owner)
    return {
        "lid": str(tx.get("_ledger_id") or ""),
        "merchant": merchant_key(tx),
        "display": display_name(tx),
        "in_chain": bool(tx.get("_transfer_chain_id")),
        "date": max(day, today) if pending else day,
        "amount": actual_amount_to_plan_sign(amount),
        "bank_amount": amount,
        "category": str(tx.get("category") or "other"),
        "pending": pending,
        "label": str(tx.get("creditorName") or tx.get("debtorName") or "")
        or str(tx.get("remittanceInformationUnstructured") or "")[:40],
        "owner": owner,
        "account": str(tx.get("_account_name") or ""),
        "account_key": str(tx.get("_account_key") or ""),
        "counterparty": _counterparty_name(tx, amount),
        "counter_iban": _counter_iban_last4(tx, amount),
        "text": _remittance(tx),
    }


def _counterparty_name(tx: dict[str, Any], amount: float) -> str:
    """The other side of the booking: the creditor of a debit, the debtor of a credit."""
    first, second = ("creditorName", "debtorName") if amount < 0 else ("debtorName", "creditorName")
    return str(tx.get(first) or tx.get(second) or "")


def _counter_iban_last4(tx: dict[str, Any], amount: float) -> str:
    """Last four IBAN digits of the counterparty, never more (IBAN masking rule)."""
    key = "creditorAccount" if amount < 0 else "debtorAccount"
    iban = str((tx.get(key) or {}).get("iban") or "").replace(" ", "")
    return iban[-4:] if len(iban) >= 4 else ""


def _remittance(tx: dict[str, Any]) -> str:
    text = str(tx.get("remittanceInformationUnstructured") or "")
    if not text:
        text = " ".join(str(x) for x in tx.get("remittanceInformationUnstructuredArray") or [])
    return " ".join(text.split())[:140]


def _incomes(bookings: list[dict[str, Any]], owner: str | None) -> list[tuple[date, float]]:
    return [
        (b["date"], b["bank_amount"])
        for b in bookings
        if b["bank_amount"] > 0
        and not b["pending"]
        and b["category"] != "transfers"
        and (owner is None or b["owner"] == owner)
    ]


def _expense(b: dict[str, Any]) -> bool:
    return b["bank_amount"] < 0 and b["category"] not in _SKIP_CATEGORIES


def _upcoming_recurring(
    patterns: list[dict[str, Any]],
    owner_by_creditor: dict[str, str],
    today: date,
    end: date,
) -> list[dict[str, Any]]:
    """Monthly recurring costs expected between ``today`` and ``end`` and not seen yet."""
    out: list[dict[str, Any]] = []
    for p in patterns or []:
        try:
            amount = actual_amount_to_plan_sign(float(p.get("average_amount", 0)))
            day = int(p.get("expected_day", 0))
        except (TypeError, ValueError):
            continue
        creditor = str(p.get("creditor") or "")
        if amount <= 0 or not 1 <= day <= 28:
            continue
        last_seen = _to_date(p.get("last_seen"))
        for offset in (0, 1):
            month = today.month + offset
            year = today.year + (month - 1) // 12
            due = date(year, (month - 1) % 12 + 1, day)
            if today <= due <= end and (last_seen is None or last_seen < due - timedelta(days=15)):
                out.append(
                    {
                        "date": due,
                        "amount": amount,
                        "category": str(p.get("category") or "other"),
                        "pending": False,
                        "upcoming": True,
                        "label": creditor,
                        "owner": owner_by_creditor.get(creditor.strip().lower(), POT_OWNER_SHARED),
                    }
                )
    return out


def _pot_bookings(pot: Pot, bookings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        b
        for b in bookings
        if b["owner"] == pot.owner
        and _expense_or_upcoming(b)
        and pot_accepts_account(pot, b.get("account_key"))
    ]


def _recent(bookings: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Newest bookings of the last RECENT_DAYS for the cycle ledger.

    Sanitised like ``/transactions``: no IBAN, no remittance text, bank sign
    (debit negative). The caller decides who may see them (admin only).
    """
    since = today - timedelta(days=RECENT_DAYS)
    rows = sorted(
        (b for b in bookings if since <= b["date"] <= today),
        key=lambda b: (b["date"], not b["pending"]),
        reverse=True,
    )
    return [
        {
            "date": b["date"].isoformat(),
            "label": b["label"] or b["display"] or b["counterparty"],
            "category": b["category"],
            "amount": round(b["bank_amount"], 2),
            "pending": bool(b["pending"]),
            "owner": b["owner"],
        }
        for b in rows[:RECENT_MAX]
    ]


def _expense_or_upcoming(b: dict[str, Any]) -> bool:
    return b.get("upcoming") or _expense(b)


def _freshness(as_of: datetime | None, now: datetime, banks: list[dict[str, Any]]) -> dict:
    status = "stale"
    if as_of is not None and (now - as_of).total_seconds() < FRESH_SECONDS:
        status = "fresh"
    if any(b.get("last_error") for b in banks) or any(
        b.get("consent_state") == "expired" for b in banks
    ):
        status = "error"
    return {"as_of": as_of.isoformat() if as_of else None, "status": status}


def _alerts(banks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in banks:
        bid = str(b.get("bank_id") or "")
        title = str(b.get("title") or "")
        if b.get("consent_state") in ("expiring", "expired"):
            out.append(
                {
                    "id": f"consent:{bid}",
                    "severity": "warn",
                    "kind": f"consent_{b['consent_state']}",
                    "title": title,
                    "actions": [{"id": "renew_consent", "bank_id": bid}],
                }
            )
        elif b.get("last_error"):
            out.append(
                {
                    "id": f"error:{bid}",
                    "severity": "warn",
                    "kind": "bank_error",
                    "title": title,
                    "actions": [{"id": "open_bank_status", "bank_id": bid}],
                }
            )
        elif b.get("blocked_until"):
            out.append(
                {
                    "id": f"blocked:{bid}",
                    "severity": "info",
                    "kind": "bank_limit",
                    "title": title,
                    "actions": [],
                }
            )
    return out


def _agg(statuses: list[dict[str, Any]]) -> dict[str, Any]:
    spent = sum(s["spent"] for s in statuses)
    linear = sum(s["linear_to_date"] for s in statuses)
    return {
        "spent": round(spent, 2),
        "linear_to_date": round(linear, 2),
        "balance": round(sum(s["balance"] for s in statuses), 2),
        "budget": round(sum(s["cycle_budget"] for s in statuses), 2),
        "per_day": round(sum(s["per_day_typical"] for s in statuses), 2),
        "status": status_for(spent, linear),
    }


def _spent_between(pots: list[Pot], bookings: list[dict[str, Any]], a: date, b: date) -> float:
    total = 0.0
    for pot in pots:
        keys = set(pot.category_keys)
        total += sum(
            x["amount"]
            for x in _pot_bookings(pot, bookings)
            if x["category"] in keys and not x["pending"] and a <= x["date"] <= b
        )
    return total


def _year_block(
    spend: list[Pot],
    bookings: list[dict[str, Any]],
    starts: list[date],
    cycle: tuple[date, date],
    today: date,
) -> dict[str, Any]:
    windows = cycle_windows(starts)[-(YEAR_CYCLES - 1) :] + [cycle]
    budget = sum(p.cycle_budget for p in spend)
    cycles = []
    for a, b in windows:
        spent = _spent_between(spend, bookings, a, b)
        full = budget if budget else 0.0
        cycles.append(
            {
                "start": a.isoformat(),
                "end": b.isoformat(),
                "status": status_for(spent, full),
                "current": (a, b) == cycle,
            }
        )
    try:
        ly_start = cycle[0].replace(year=cycle[0].year - 1)
        ly_today = today.replace(year=today.year - 1)
    except ValueError:  # 29 Feb
        ly_start, ly_today = cycle[0] - timedelta(days=365), today - timedelta(days=365)
    has_history = any(b["date"] <= ly_today and b["date"] >= ly_start for b in bookings)
    spent_now = _spent_between(spend, bookings, cycle[0], today)
    spent_then = _spent_between(spend, bookings, ly_start, ly_today)
    return {
        "cycles": cycles,
        "vs_last_year": {
            "available": has_history,
            "spent": round(spent_now, 2),
            "spent_last_year": round(spent_then, 2) if has_history else None,
            "delta": round(spent_now - spent_then, 2) if has_history else None,
        },
        # Inflation / purchasing-power comparison needs the bundled benchmark
        # dataset (roadmap phase 4e); never a runtime fetch.
        "benchmark": {"available": False, "reason": "not_implemented"},
    }


def _did_you_know(scope_bookings: list[dict[str, Any]], cycle: tuple[date, date], today: date):
    by_cat: dict[str, float] = defaultdict(float)
    for b in scope_bookings:
        # "other" is the absence of a category -- never a headline fact.
        if (
            _expense(b)
            and not b["pending"]
            and b["category"] != "other"
            and cycle[0] <= b["date"] <= today
        ):
            by_cat[b["category"]] += b["amount"]
    total = sum(by_cat.values())
    if total <= 0:
        return None
    cat, amount = max(by_cat.items(), key=lambda kv: kv[1])
    share = amount / total
    if share < DID_YOU_KNOW_MIN_SHARE:
        return None
    return {
        "key": "top_category",
        "params": {"category": cat, "share": round(share, 2)},
        "text": f"{round(share * 100)} % of your spending this cycle went to {cat}.",
    }


def _display_name(person: str, persons: list[dict[str, Any]] | None) -> str:
    """Nickname of a person (``display_name``), falling back to the stable ``name``."""
    for cfg in persons or []:
        if str(cfg.get("name") or "") == person:
            return str(cfg.get("display_name") or "").strip() or person
    return person


def _person_budget(
    person: str,
    scope: list[dict[str, Any]],
    plan: BudgetPlan | None,
    cycle: tuple[date, date],
    today: date,
) -> dict[str, Any]:
    """The person's own Spielraum for the cycle (own items only, plan sign).

    ``plan``: own plan income minus own fixed costs; ``spent`` skips bookings in
    categories an own fixed position already covers (they are inside the fixed
    costs, counting them again would eat the Spielraum twice).
    ``history``: own income received in the cycle (previous cycle when none yet)
    against all own spending.
    """
    start, end = cycle
    skip_always = set(_SKIP_CATEGORIES)

    def _own_spent(skip: set[str]) -> float:
        return sum(
            b["amount"]
            for b in scope
            if b["owner"] == person and _expense(b) and not b["pending"] and not b["in_chain"]
            and b["category"] not in skip_always | skip and start <= b["date"] <= end
        )

    def _result(budget: float, spent: float, source: str) -> dict[str, Any]:
        return {
            "budget": round(budget, 2),
            "spent": round(spent, 2),
            "remaining": round(budget - spent, 2),
            "source": source,
        }

    if plan is not None and not plan.is_empty():
        own = plan.positions_for(person)
        income = plan.income_net(person)
        if income > 0 or own:
            fixed = {
                p.category
                for p in own
                if p.kind == POSITION_KIND_FIXED and p.is_active(today.month, today.year)
            }
            budget = income - plan.fixed_total(today.month, today.year, owner=person)
            return _result(budget, _own_spent(fixed), "plan")

    span = (end - start).days + 1
    prev = (start - timedelta(days=span), start - timedelta(days=1))
    own_income = _incomes(scope, person)
    budget = sum(a for d, a in own_income if start <= d <= end)
    if budget <= 0:
        budget = sum(a for d, a in own_income if prev[0] <= d <= prev[1])
    return _result(budget, _own_spent(set()), "history")


HISTORY_CYCLES = 6


def _past_cycles(
    cycle_at: Any, current: tuple[date, date], booking_dates: list[date]
) -> list[tuple[date, date]]:
    """Up to ``HISTORY_CYCLES`` finished cycles before ``current``, ascending.

    Walks back with the same rule as the current cycle and stops where the rule
    stops being contiguous or where the cached bookings begin.
    """
    if not booking_dates:
        return []
    earliest = min(booking_dates)
    out: list[tuple[date, date]] = []
    nxt_start = current[0]
    for _ in range(HISTORY_CYCLES):
        s, e = cycle_at(nxt_start - timedelta(days=1))
        if e != nxt_start - timedelta(days=1) or s >= nxt_start or e < earliest:
            break
        out.append((s, e))
        nxt_start = s
    out.reverse()
    return out


def build_home(  # noqa: PLR0912, PLR0915
    *,
    accounts: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    plan: BudgetPlan | None,
    pots: list[Pot],
    recurring: list[dict[str, Any]] | None,
    banks: list[dict[str, Any]] | None,
    as_of: datetime | None,
    now: datetime,
    person: str | None,
    view: str,
    horizon: str,
    persons: list[dict[str, Any]] | None = None,
    week_answered: int = 0,
    suggest: Any = None,
    include_questions: bool = False,
    include_recent: bool = False,
) -> dict[str, Any]:
    """Assemble the home contract. ``view`` degrades to household without a person."""
    today = now.date()
    user_mapped = bool(person)
    persons_cfg = persons
    banks = banks or []
    if horizon not in HORIZONS:
        horizon = "cycle"
    viewer_person = person or None  # the caller's person, kept for every view
    if view != "person" or not person:
        view, person = "household", None

    all_bookings = [b for tx in transactions if (b := _booking(tx, today))]
    scope_owner = person  # None = whole household
    scope = [b for b in all_bookings if scope_owner is None or b["owner"] == scope_owner]

    # --- cycle ---------------------------------------------------------
    # One rule for the current cycle and for the history: ``cycle_at(day)`` is
    # the cycle containing ``day``.
    anchor: str | None
    by_person: dict[str, list] = defaultdict(list)
    if view == "person":
        incomes = _incomes(all_bookings, person)
        starts = salary_starts(incomes)
        anchor = person if starts else None
        rule = "person_highest_income" if starts else "calendar_fallback"
    else:
        for b in all_bookings:
            if b["owner"] != POT_OWNER_SHARED:
                by_person[b["owner"]].extend(_incomes([b], b["owner"]))
        _s, _e, anchor = household_cycle(dict(by_person), today)
        starts = [s for s, _ in household_starts(dict(by_person))]
        rule = "household_7_day" if starts else "calendar_fallback"

    payday_days: list[date] = []
    if not starts:
        # No salary seen in the bookings yet: a payday the user confirmed in
        # the setup wizard is the next best anchor (the person's own, or the
        # earliest confirmed one for the household).
        from .setup_wizard import person_payday

        payday_days = [
            d
            for p in persons or []
            if (view != "person" or p.get("name") == person) and (d := person_payday(p))
        ]
        if payday_days:
            rule = "payday_confirmed"

    def cycle_at(day: date) -> tuple[date, date]:
        if starts:
            if view == "person":
                return person_cycle(incomes, day)
            s, e, _a = household_cycle(dict(by_person), day)
            return s, e
        if payday_days:
            from .setup_wizard import payday_cycle

            return payday_cycle(min(payday_days), day)
        return calendar_cycle(day)

    start, end = cycle_at(today)
    cycle = (start, end)

    # --- pots ----------------------------------------------------------
    if view == "person":
        visible = [p for p in pots if p.owner == person]
    else:
        visible = [p for p in pots if p.is_shared]
    past_cycles = _past_cycles(cycle_at, cycle, [b["date"] for b in scope])
    status_by_id = {p.id: pot_status(p, _pot_bookings(p, scope), cycle, today) for p in pots}
    pot_rows = [
        {
            "id": p.id,
            "name": p.name,
            "owner": p.owner,
            "balance": status_by_id[p.id]["balance"],
            "per_day": status_by_id[p.id]["per_day_typical"],
            "status": status_by_id[p.id]["status"],
            "kind": p.kind,
            "cycle_budget": status_by_id[p.id]["cycle_budget"],
            "spent": status_by_id[p.id]["spent"],
            "carry_in_week": status_by_id[p.id]["carry_in_week"],
            "carry_decision": status_by_id[p.id]["carry_decision"],
            "week_start": week_bounds(today)[0].isoformat(),
            "history": pot_cycle_history(p, _pot_bookings(p, scope), past_cycles),
            "category_keys": list(p.category_keys),
        }
        for p in visible
        if p.kind == POT_KIND_SPEND
    ]
    reserves = [
        {
            "id": p.id,
            "name": p.name,
            "owner": p.owner,
            "balance": status_by_id[p.id]["balance"],
            "per_day": status_by_id[p.id]["per_day_typical"],
            "cycle_budget": status_by_id[p.id]["cycle_budget"],
            "kind": POT_KIND_RESERVE,
        }
        for p in visible
        if p.kind == POT_KIND_RESERVE
    ]

    # Scope pots feeding the headline numbers (household: everybody's, as totals).
    scope_pots = [p for p in pots if scope_owner is None or p.owner == scope_owner]
    scope_spend = [p for p in scope_pots if p.kind == POT_KIND_SPEND]
    head = _agg([status_by_id[p.id] for p in scope_spend])

    # A payment to an account holder's own name is an own transfer, never a
    # question (same middle-name tolerant rule contracts use since 0.20.2).
    own_names = own_account_names(accounts)
    candidates = [
        {"merchant": b["merchant"], "display": b["display"], "amount": b["bank_amount"],
         "date": b["date"], "lid": b["lid"], "account": b["account"],
         "counterparty": b["counterparty"], "counter_iban": b["counter_iban"], "text": b["text"]}
        for b in scope
        if _expense(b) and not b["pending"] and b["category"] == "other"
        and not b["in_chain"] and cycle[0] <= b["date"] <= cycle[1]
        and not is_own_name(str(b["counterparty"]).lower(), own_names)
    ]
    questions, questions_total = select_questions(
        candidates, week_answered=week_answered, suggest=suggest,
        history=merchant_history([b for b in scope if _expense(b) and not b["pending"]]),
    )

    out: dict[str, Any] = {
        "view": view,
        "person": (
            {"id": person, "name": person, "display_name": _display_name(person, persons_cfg)}
            if person
            else None
        ),
        "viewer_person": viewer_person,
        "horizon": horizon,
        "freshness": _freshness(as_of, now, banks),
        "alerts": _alerts(banks),
        "questions_open": len(questions),
        "questions_total": questions_total,
        "cycle": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": cycle_days(cycle),
            "day": min(max((today - start).days + 1, 0), cycle_days(cycle)),
            "anchor": anchor,
            "rule": rule,
        },
        "status": head["status"],
        "remaining": head["balance"],
        "pots": pot_rows,
    }

    if include_questions:
        out["questions"] = questions  # internal: admin question list, not in the public home view

    if view == "person" and person:
        out["person_budget"] = _person_budget(person, scope, plan, cycle, today)

    out["setup"] = setup_block(accounts, persons_cfg, len(pots), user_mapped=user_mapped)

    if view == "household":
        persons = sorted({p.owner for p in pots if not p.is_shared})
        out["persons"] = [
            {
                "id": name,
                "name": name,
                **{
                    k: _agg([status_by_id[p.id] for p in pots if p.owner == name and p.kind == POT_KIND_SPEND])[k]
                    for k in ("budget", "spent", "balance", "status")
                },
            }
            for name in persons
        ]

    # Items still to come: pending bookings + expected recurring costs.
    owner_by_creditor: dict[str, str] = {}
    for tx in transactions:  # newest first: first hit is the latest
        name = str(tx.get("creditorName") or "").strip().lower()
        if name and name not in owner_by_creditor:
            b = _booking(tx, today)
            if b:
                owner_by_creditor[name] = b["owner"]
    future = [
        b
        for b in all_bookings
        if b["pending"] and _expense(b) and (scope_owner is None or b["owner"] == scope_owner)
    ]
    future += [
        r
        for r in _upcoming_recurring(recurring or [], owner_by_creditor, today, end)
        if scope_owner is None or r["owner"] == scope_owner
    ]
    if view == "household":
        # Other persons' items stay private: only shared ones carry a label.
        future = [b for b in future if b["owner"] == POT_OWNER_SHARED]
    future.sort(key=lambda b: (b["date"], b["label"]))

    def _item(b: dict[str, Any]) -> dict[str, Any]:
        return {
            "date": b["date"].isoformat(),
            "label": b["label"],
            "amount": round(b["amount"], 2),
            "pending": bool(b["pending"]),
        }

    if include_recent and horizon == "cycle":
        out["recent"] = _recent(scope if view == "person" else
                                [b for b in scope if b["owner"] == POT_OWNER_SHARED], today)

    if horizon == "today":
        spent_today = sum(
            b["amount"]
            for b in scope
            if _expense(b) and not b["pending"] and b["date"] == today
            and any(
                b["category"] in p.category_keys and p.owner == b["owner"] for p in scope_spend
            )
        )
        out["today"] = {
            "spent": round(spent_today, 2),
            "daily_budget": head["per_day"],
            "can_spend": max(0.0, head["balance"]),
        }

    if horizon == "week":
        week_bookings: list[dict[str, Any]] = []
        seen: set[int] = set()
        for p in scope_spend:
            for b in _pot_bookings(p, scope):
                if not b["pending"] and id(b) not in seen:
                    seen.add(id(b))
                    week_bookings.append(b)
        week_bookings += [b for b in future if week_bounds(today)[0] <= b["date"] <= week_bounds(today)[1]]
        out["week"] = week_status(scope_spend, week_bookings, cycle, today)

    if horizon in ("cycle", "year"):
        out["next"] = [_item(b) for b in future if b["date"] <= end][:NEXT_TOP_N]
        out["next_total"] = len([b for b in future if b["date"] <= end])
        out["next_all"] = [_item(b) for b in future if b["date"] <= end][:30]
        out["did_you_know"] = _did_you_know(scope if view == "person" else
                                            [b for b in scope if b["owner"] == POT_OWNER_SHARED],
                                            cycle, today)
        out["reserves"] = reserves
        covered: bool | None = None
        if plan is not None and not plan.is_empty():
            fixed = plan.fixed_total(today.month, today.year, owner=person)
            income = sum(a for d, a in _incomes(scope, None) if cycle[0] <= d <= cycle[1])
            if income <= 0:
                income = plan.income_net(person) if person else plan.income_net_total()
            covered = income >= fixed
        out["fixed_costs_covered"] = covered

    if horizon == "year":
        out["year"] = _year_block(scope_spend, scope, starts, cycle, today)

    return out
