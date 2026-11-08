"""The reconciliation review (Abgleich): groups, steps, final check, report.

Pure functions over cached data -- no I/O, no clock, never a bank call.

One counting rule: ``txs`` are the counted, refund-netted bookings
(:mod:`counted`); owners, sources and confidences come from the one chain
(``Classifier.classify_detail`` -> ``ownership.resolve_owner_detail``), the
settlement from :mod:`household_settle`. The review only *groups* and
*explains* what the numbers are made of.

Unit = group by euro impact: a recurring **series**, else a **merchant**, else
a **category**. A group with confidence >= ``CONFIDENCE_AUTO`` (85) is done
automatically; a lower one is a guess ("Vermutung") with its reason. A group
the user confirmed is done at 95 whatever the chain says (the confirmation
also wrote a rule where the chain can use one).

Steps, in order: ``acc`` accounts, ``links`` transfers / PayPal / refunds,
``fixed`` series against the plan, ``owner`` household or person, ``cat``
largest "other" groups, ``check`` the final criteria.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from .budget_plan import BudgetPlan
from .const import OWNER_SHARED
from .counted import (
    MOVEMENT_PAYPAL,
    amount_of,
    is_income_line,
    movement_reasons,
)
from .household_settle import settlement_balances
from .household_summary import Classifier, OWNER_OPEN, owner_fields
from .labels import booking_key
from .merchants import merchant_key
from .ownership import CONFIDENCE_AUTO, KIND_OPEN, account_kind
from .plan_match import assign_positions, best_position
from .tx_dates import effective_day

STEPS = ("acc", "links", "fixed", "owner", "cat", "check")
CONFIRMED_CONFIDENCE = 95
OPEN_OWNERSHIP_LIMIT = 50.0  # EUR: above this an unassigned amount fails the check
MAX_OPEN_GROUPS = 50
MAX_AUTO_GROUPS = 10
MAX_BOOKINGS = 20
HINT_MIN_EUR = 100.0
HINT_MIN_SHARE = 0.02

KIND_SERIES, KIND_MERCHANT, KIND_CATEGORY = "series", "merchant", "category"
KIND_ACCOUNT, KIND_CHAIN, KIND_POSITION, KIND_LINK = "account", "chain", "position", "link"


def ref_of(tx: dict[str, Any]) -> str:
    return f"{tx.get('_account_key') or ''}|{tx.get('_ledger_id') or ''}"


def group_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def series_index(series: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Booking ref (``"<account_key>|<ledger_id>"``) -> its series."""
    out: dict[str, dict[str, Any]] = {}
    for s in series or []:
        if s.get("candidate") or s.get("status") == "ended":
            continue
        for ref in s.get("ledger_ids") or []:
            out[ref] = s
    return out


def _booking(tx: dict[str, Any], clf: Classifier) -> dict[str, Any]:
    day = effective_day(tx)
    return {
        "ledger_id": booking_key(tx) or "",
        **owner_fields(clf, tx),
        "date": day.isoformat() if day else None,
        "label": str(tx.get("creditorName") or tx.get("debtorName") or "")
        or str(tx.get("remittanceInformationUnstructured") or "")[:40],
        "amount": round(amount_of(tx), 2),
        "category": str(tx.get("category") or "other"),
    }


def expense_groups(
    txs: list[dict[str, Any]],
    clf: Classifier,
    window: tuple[date, date],
    series: dict[str, dict[str, Any]],
    state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every expense of ``window`` grouped by series / merchant / category (G3)."""
    confirmed = (state or {}).get("confirmed") or {}
    acc: dict[str, dict[str, Any]] = {}
    for tx in txs:
        day = effective_day(tx)
        if day is None or not window[0] <= day <= window[1] or is_income_line(tx):
            continue
        spent = -amount_of(tx)
        if not spent:
            continue
        owner, _fixed, source, conf = clf.classify_detail(tx, day)
        s = series.get(ref_of(tx))
        mkey = merchant_key(tx)
        if s is not None:
            kind, key, label = KIND_SERIES, str(s["id"]), str(s.get("display_name") or s.get("creditor") or "")
        elif mkey:
            kind, key, label = KIND_MERCHANT, mkey, str(tx.get("creditorName") or tx.get("debtorName") or mkey)
        else:
            cat = str(tx.get("category") or "other")
            kind, key, label = KIND_CATEGORY, cat, cat
        gid = group_id(kind, key)
        g = acc.setdefault(
            gid,
            {
                "group_id": gid, "kind": kind, "key": key, "label": label, "amount": 0.0,
                "count": 0, "owners": defaultdict(float), "cats": defaultdict(float),
                "confidence": 100, "source": "account", "bookings": [], "ledger_ids": [],
            },
        )
        g["amount"] += spent
        g["count"] += 1
        g["owners"][owner] += abs(spent)
        g["cats"][str(tx.get("category") or "other")] += abs(spent)
        if conf < g["confidence"]:
            g["confidence"], g["source"] = conf, source
        g["bookings"].append((day, _booking(tx, clf)))
        if tx.get("_ledger_id"):
            g["ledger_ids"].append(ref_of(tx))
    out = []
    for g in acc.values():
        owner = max(g["owners"].items(), key=lambda kv: kv[1])[0]
        category = max(g["cats"].items(), key=lambda kv: kv[1])[0]
        done = g["group_id"] in confirmed
        confidence = CONFIRMED_CONFIDENCE if done else g["confidence"]
        bookings = [b for _d, b in sorted(g.pop("bookings"), key=lambda p: p[0], reverse=True)]
        out.append(
            {
                "group_id": g["group_id"], "kind": g["kind"], "key": g["key"],
                "label": g["label"], "amount": round(g["amount"], 2), "count": g["count"],
                "owner": owner, "mixed_owner": len(g["owners"]) > 1,
                "source": "confirmed" if done else g["source"],
                "confidence": confidence, "reason": "confirmed" if done else g["source"],
                "reason_category": category, "category": category,
                "auto": confidence >= CONFIDENCE_AUTO, "confirmed": done,
                "bookings": bookings[:MAX_BOOKINGS],
                "ledger_refs": g["ledger_ids"],
            }
        )
    out.sort(key=lambda r: -abs(r["amount"]))
    return out


def _step(step_id: str, groups: list[dict[str, Any]], seen: set[str]) -> dict[str, Any]:
    open_ = [g for g in groups if not g["auto"]]
    auto = [g for g in groups if g["auto"]]
    shown = open_[:MAX_OPEN_GROUPS] + auto[:MAX_AUTO_GROUPS]
    return {
        "id": step_id,
        "group_ids": [g["group_id"] for g in groups],
        "open_count": len(open_),
        "auto_count": len(auto),
        "new_count": sum(1 for g in open_ if g["group_id"] not in seen),
        "open_amount": round(sum(abs(g["amount"]) for g in open_), 2),
        "groups": shown,
    }


def _strip(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for g in groups:
        g.pop("ledger_refs", None)
    return groups


def account_groups(
    accounts: list[dict[str, Any]], txs: list[dict[str, Any]], window: tuple[date, date]
) -> list[dict[str, Any]]:
    spent: dict[str, float] = defaultdict(float)
    for tx in txs:
        day = effective_day(tx)
        if day and window[0] <= day <= window[1] and not is_income_line(tx):
            spent[str(tx.get("_account_key") or "")] += -amount_of(tx)
    out = []
    for acc in accounts:
        from .account_identity import account_key

        key = account_key(acc)
        kind = account_kind(acc)
        owner = OWNER_SHARED if kind == "household" else str(acc.get("person") or OWNER_OPEN)
        iban = str(acc.get("iban") or "").replace(" ", "")
        out.append(
            {
                "group_id": group_id(KIND_ACCOUNT, key), "kind": KIND_ACCOUNT, "key": key,
                "label": str(acc.get("name") or acc.get("institution") or key),
                "iban_last4": iban[-4:] if len(iban) >= 4 else "",
                "amount": round(spent.get(key, 0.0), 2), "count": 0,
                "owner": owner, "owner_set": kind, "household": kind == "person_household",
                "source": "account", "confidence": 0 if kind == KIND_OPEN else 100,
                "reason": "no_owner" if kind == KIND_OPEN else "owner_set",
                "auto": kind != KIND_OPEN, "category": None, "bookings": [],
            }
        )
    return out


def link_groups(
    raw: list[dict[str, Any]], accounts: list[dict[str, Any]], state: dict[str, Any] | None,
    clf: Classifier,
) -> list[dict[str, Any]]:
    """Transfer chains (confirmable), PayPal mirrors and own transfers (informational)."""
    confirmed = (state or {}).get("confirmed") or {}
    chains: dict[str, dict[str, Any]] = {}
    for tx in raw:
        cid = tx.get("_transfer_chain_id")
        if not cid:
            continue
        c = chains.setdefault(cid, {"conf": tx.get("_transfer_confidence") or 0, "decided": tx.get("_transfer_confirmed"), "amount": 0.0, "n": 0, "bookings": []})
        c["amount"] = max(c["amount"], abs(amount_of(tx)))
        c["n"] += 1
        c["bookings"].append(_booking(tx, clf))
    out = []
    for cid, c in chains.items():
        pct = c["conf"] * 100 if c["conf"] <= 1 else c["conf"]
        decided = c["decided"] is not None or group_id(KIND_CHAIN, cid) in confirmed
        auto = decided or pct >= CONFIDENCE_AUTO
        out.append(
            {
                "group_id": group_id(KIND_CHAIN, cid), "kind": KIND_CHAIN, "key": cid,
                "label": "transfer_chain", "amount": round(c["amount"], 2), "count": c["n"],
                "owner": None, "source": "transfer_detector", "confidence": round(pct),
                "reason": "confirmed" if decided else "detected", "auto": auto,
                "confirmed": decided, "rejected": c["decided"] is False, "category": None,
                "bookings": c["bookings"][:MAX_BOOKINGS],
            }
        )
    reasons = movement_reasons(raw, accounts)
    mirrors = [t for t in raw if reasons.get(id(t)) == MOVEMENT_PAYPAL]
    if mirrors:
        out.append(_info_group("paypal", mirrors, clf))
    own = [t for t in raw if str(t.get("category") or "") == "transfers" and not t.get("_transfer_chain_id")]
    if own:
        out.append(_info_group("own_transfers", own, clf))
    refunds = [t for t in raw if t.get("_refund_role") == "refund"]
    if refunds:
        out.append(_info_group("refunds", refunds, clf))
    out.sort(key=lambda g: (g["auto"], -g["amount"]))
    return out


def _info_group(name: str, txs: list[dict[str, Any]], clf: Classifier) -> dict[str, Any]:
    return {
        "group_id": group_id(KIND_LINK, name), "kind": KIND_LINK, "key": name, "label": name,
        "amount": round(sum(abs(amount_of(t)) for t in txs), 2), "count": len(txs),
        "owner": None, "source": "counted", "confidence": 100, "reason": "counted_rule",
        "auto": True, "confirmed": False, "category": None,
        "bookings": [_booking(t, clf) for t in txs[:MAX_BOOKINGS]],
    }


def fixed_groups(
    series_list: list[dict[str, Any]] | None,
    txs: list[dict[str, Any]],
    plan: BudgetPlan | None,
    clf: Classifier,
    persons: list[str],
    today: date,
    state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Contracts / recurring series against the plan positions (matched / unmatched)."""
    confirmed = (state or {}).get("confirmed") or {}
    by_ref = {ref_of(t): t for t in txs if t.get("_ledger_id")}
    active = plan.active_positions(today.month, today.year) if plan and not plan.is_empty() else []
    out: list[dict[str, Any]] = []
    matched_positions: set[str] = set()
    for s in series_list or []:
        if s.get("candidate") or s.get("status") == "ended":
            continue
        members = [by_ref[r] for r in s.get("ledger_ids") or [] if r in by_ref]
        if not members:
            continue
        latest = max(members, key=lambda t: effective_day(t) or date.min)
        day = effective_day(latest) or today
        pos = best_position(latest, active, persons) if active else None
        owner, _f, source, conf = clf.classify_detail(latest, day)
        gid = group_id(KIND_SERIES, str(s["id"]))
        done = gid in confirmed
        if pos is not None:
            matched_positions.add(pos.id)
        matched = pos is not None
        confidence = CONFIRMED_CONFIDENCE if done else (conf if matched else min(conf, 50))
        out.append(
            {
                "group_id": gid, "kind": KIND_SERIES, "key": str(s["id"]),
                "label": str(s.get("display_name") or s.get("creditor") or ""),
                "amount": round(float(s.get("annual_cost") or 0), 2), "count": len(members),
                "owner": owner, "source": "confirmed" if done else ("plan" if matched else source),
                "confidence": confidence,
                "reason": "confirmed" if done else ("plan_match" if matched else "no_plan_position"),
                "plan_position": {"id": pos.id, "name": pos.name} if pos else None,
                "category": str(s.get("category") or "other"),
                "auto": confidence >= CONFIDENCE_AUTO, "confirmed": done,
                "bookings": [_booking(t, clf) for t in members[-MAX_BOOKINGS:]],
            }
        )
    for p in active:
        if p.id in matched_positions or p.kind != "fixed":
            continue
        gid = group_id(KIND_POSITION, p.id)
        done = gid in confirmed or bool(getattr(p, "suspended", False))
        out.append(
            {
                "group_id": gid, "kind": KIND_POSITION, "key": p.id, "label": p.name,
                "amount": round(p.effective_amount(today.month, today.year) * 12, 2), "count": 0,
                "owner": p.owner, "source": "plan", "confidence": 95 if done else 40,
                "reason": "suspended" if getattr(p, "suspended", False) else "no_series",
                "category": p.category, "auto": done, "confirmed": done,
                "suspended": bool(getattr(p, "suspended", False)), "bookings": [],
            }
        )
    out.sort(key=lambda g: (g["auto"], -abs(g["amount"])))
    return out


def unreviewed(groups: list[dict[str, Any]], seen: set[str]) -> list[dict[str, Any]]:
    return [g for g in groups if not g["auto"] and g["group_id"] not in seen]


def build_review(  # noqa: PLR0913, PLR0914
    *,
    raw: list[dict[str, Any]],
    txs: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    plan: BudgetPlan | None,
    clf: Classifier,
    persons: list[str],
    series_list: list[dict[str, Any]] | None,
    state: dict[str, Any] | None,
    today: date,
    ai_merchants: dict[str, str] | None = None,
    ai: dict[str, Any] | None = None,
    since_last: bool = False,
) -> dict[str, Any]:
    """The ``GET /review`` payload: six steps with groups, plus the check."""
    state = state or {}
    seen = set(state.get("seen") or [])
    window = (date(today.year, 1, 1), today)
    sidx = series_index(series_list)
    egroups = expense_groups(txs, clf, window, sidx, state)
    # cat: "other" merchants/series by euro impact, plus AI-suggested categories
    ai_merchants = ai_merchants or {}
    cat_groups = []
    for g in egroups:
        if g["category"] == "other" or (g["kind"] == KIND_MERCHANT and g["key"] in ai_merchants):
            suggestion = ai_merchants.get(g["key"]) if g["kind"] == KIND_MERCHANT else None
            done = g["confirmed"]
            cat_groups.append(
                {
                    **g,
                    "reason": "confirmed" if done else ("ai" if suggestion else "no_category"),
                    "suggested_category": suggestion,
                    "confidence": CONFIRMED_CONFIDENCE if done else (60 if suggestion else 0),
                    "auto": done,
                }
            )
    owner_groups = egroups
    steps = {
        "acc": _step("acc", account_groups(accounts, txs, window), seen),
        "links": _step("links", link_groups(raw, accounts, state, clf), seen),
        "fixed": _step("fixed", fixed_groups(series_list, txs, plan, clf, persons, today, state), seen),
        "owner": _step("owner", owner_groups, seen),
        "cat": _step("cat", cat_groups, seen),
    }
    check = final_check(
        accounts=accounts, txs=txs, raw=raw, plan=plan, clf=clf, today=today, window=window,
        owner_groups=owner_groups, persons=persons,
    )
    steps["check"] = {
        "id": "check", "open_count": sum(1 for c in check["criteria"] if not c["ok"]),
        "auto_count": sum(1 for c in check["criteria"] if c["ok"]), "new_count": 0,
        "open_amount": 0.0, "groups": [], "criteria": check["criteria"], "ok": check["ok"],
    }
    ordered = [steps[s] for s in STEPS]
    start = next((s["id"] for s in ordered if s["id"] != "check" and s["new_count"]), None)
    if start is None:
        start = next((s["id"] for s in ordered if s["open_count"]), "check")
    for step in ordered:
        _strip(step["groups"])
    return {
        "steps": ordered,
        "start_step": start if since_last or state.get("reviewed_at") else ordered[0]["id"],
        "window": {"start": window[0].isoformat(), "end": window[1].isoformat()},
        "reviewed_at": state.get("reviewed_at"),
        "started": bool(state.get("started")),
        "ai": ai or {},
        "threshold": {"auto_confidence": CONFIDENCE_AUTO, "open_limit_eur": OPEN_OWNERSHIP_LIMIT},
    }


def final_check(  # noqa: PLR0913, PLR0914
    *,
    accounts: list[dict[str, Any]],
    txs: list[dict[str, Any]],
    raw: list[dict[str, Any]],
    plan: BudgetPlan | None,
    clf: Classifier,
    today: date,
    window: tuple[date, date],
    owner_groups: list[dict[str, Any]],
    persons: list[str],
) -> dict[str, Any]:
    """G5: the five criteria that make the numbers consistent."""
    open_accounts = [a.get("name") or a.get("institution") or "" for a in accounts if account_kind(a) == KIND_OPEN]
    open_groups = [g for g in owner_groups if g["owner"] == OWNER_OPEN]
    open_amount = round(sum(abs(g["amount"]) for g in open_groups), 2)
    # transfers: nothing that is movement may sit in the counted bookings
    leaked = [
        t for t in txs
        if (t.get("_transfer_chain_id") and t.get("_transfer_confirmed") is not False)
        or str(t.get("category") or "") == "transfers"
    ]
    # reconcile: the direct sum of the expenses against the sum of the owner buckets
    direct = buckets = 0.0
    by_owner: dict[str, float] = defaultdict(float)
    for tx in txs:
        day = effective_day(tx)
        if day is None or not window[0] <= day <= window[1] or is_income_line(tx):
            continue
        spent = -amount_of(tx)
        direct += spent
        by_owner[clf.classify_detail(tx, day)[0]] += spent
    known = {OWNER_SHARED, OWNER_OPEN, *persons}
    buckets = sum(v for o, v in by_owner.items() if o in known)
    diff_cents = round(direct * 100) - round(buckets * 100)
    offenders = sorted({g["group_id"] for g in owner_groups if g["owner"] not in known})
    # plan: every active fixed position has a booking in this period, or is suspended
    shortfalls: list[dict[str, Any]] = []
    if plan is not None and not plan.is_empty():
        active = plan.active_positions(today.month, today.year)
        in_period = [t for t in txs if (d := effective_day(t)) and window[0] <= d <= window[1]]
        got = assign_positions(in_period, active, persons)
        shortfalls = [
            {"position_id": p.id, "name": p.name, "planned": p.effective_amount(today.month, today.year)}
            for p in active
            if p.kind == "fixed" and not got.get(p.id) and not getattr(p, "suspended", False)
        ]
    criteria = [
        {"id": "accounts", "ok": not open_accounts, "open": open_accounts},
        {"id": "open_ownership", "ok": open_amount <= OPEN_OWNERSHIP_LIMIT, "amount": open_amount,
         "limit": OPEN_OWNERSHIP_LIMIT, "group_ids": [g["group_id"] for g in open_groups]},
        {"id": "transfers", "ok": not leaked, "count": len(leaked)},
        {"id": "reconcile", "ok": diff_cents == 0, "difference": round(diff_cents / 100, 2),
         "expenses": round(direct, 2), "shared": round(by_owner.get(OWNER_SHARED, 0.0), 2),
         "persons": round(sum(v for o, v in by_owner.items() if o not in (OWNER_SHARED, OWNER_OPEN)), 2),
         "open": round(by_owner.get(OWNER_OPEN, 0.0), 2), "group_ids": offenders},
        {"id": "plan", "ok": not shortfalls, "shortfalls": shortfalls},
    ]
    return {"criteria": criteria, "ok": all(c["ok"] for c in criteria)}


def hint(review: dict[str, Any], state: dict[str, Any], year_expenses: float) -> dict[str, Any] | None:
    """G7: ``{open_groups, open_amount}`` when new unreviewed groups move the year."""
    seen = set(state.get("seen") or [])
    fresh = [
        g for s in review["steps"] if s["id"] in ("fixed", "owner", "cat", "links")
        for g in s["groups"] if not g["auto"] and g["group_id"] not in seen
    ]
    amount = round(sum(abs(g["amount"]) for g in fresh), 2)
    if fresh and (amount >= HINT_MIN_EUR or amount > HINT_MIN_SHARE * max(year_expenses, 0.0)):
        return {"open_groups": len(fresh), "open_amount": amount}
    return None


# ---------------------------------------------------------------------------
# snapshot + report (G6)
# ---------------------------------------------------------------------------


def snapshot(
    txs: list[dict[str, Any]], clf: Classifier, window: tuple[date, date], review: dict[str, Any],
    cycle: tuple[date, date] | None = None,
) -> dict[str, Any]:
    """Key figures at one moment, to show what the review moved."""
    owners: dict[str, float] = defaultdict(float)
    for tx in txs:
        day = effective_day(tx)
        if day and window[0] <= day <= window[1] and not is_income_line(tx):
            owners[clf.classify_detail(tx, day)[0]] += -amount_of(tx)
    open_groups = [g for s in review["steps"] for g in s["groups"] if not g["auto"] and s["id"] != "check"]
    settle = settlement_balances(txs, clf, cycle or window)
    return {
        "owners": {k: round(v, 2) for k, v in owners.items()},
        "open_groups": sum(s["open_count"] for s in review["steps"] if s["id"] != "check"),
        "open_amount": round(sum(abs(g["amount"]) for g in open_groups), 2),
        "settle": {p: v["net"] for p, v in settle.items()},
    }


def diff(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any] | None:
    """Before / after / delta of every snapshot figure (None before the review started)."""
    if not before:
        return None

    def pair(b: float, a: float) -> dict[str, float]:
        return {"before": round(b, 2), "after": round(a, 2), "delta": round(a - b, 2)}

    names = sorted(set(before.get("owners", {})) | set(after["owners"]))
    people = sorted(set(before.get("settle", {})) | set(after["settle"]))
    return {
        "owners": {n: pair(before.get("owners", {}).get(n, 0.0), after["owners"].get(n, 0.0)) for n in names},
        "open_groups": pair(before.get("open_groups", 0), after["open_groups"]),
        "open_amount": pair(before.get("open_amount", 0.0), after["open_amount"]),
        "settle": {p: pair(before.get("settle", {}).get(p, 0.0), after["settle"].get(p, 0.0)) for p in people},
    }


def _plan_vs_actual(
    plan: BudgetPlan | None,
    txs: list[dict[str, Any]],
    window: tuple[date, date],
    persons: list[str],
    owner: str | None,
) -> list[dict[str, Any]]:
    """Plan position against its matched bookings in the window (plan sign)."""
    if plan is None or plan.is_empty():
        return []
    month, year = _month_of(window)
    active = [p for p in plan.active_positions(month, year) if owner is None or p.owner == owner]
    booked = [t for t in txs if (d := effective_day(t)) and window[0] <= d <= window[1] and not is_income_line(t)]
    got = assign_positions(booked, active, persons)
    rows = []
    for p in active:
        matched = got.get(p.id, [])
        actual = round(sum(-amount_of(t) for t in matched), 2)
        planned = p.effective_amount(month, year)
        rows.append(
            {
                "id": p.id, "name": p.name, "owner": p.owner, "category": p.category,
                "planned": planned, "actual": actual if matched else None,
                "delta": round(actual - planned, 2) if matched else None,
                "suspended": bool(getattr(p, "suspended", False)),
            }
        )
    return rows


def _month_of(window: tuple[date, date]) -> tuple[int, int]:
    from .household_summary import month_of_window

    return month_of_window(window)


def build_report(  # noqa: PLR0913, PLR0914
    *,
    txs: list[dict[str, Any]],
    plan: BudgetPlan | None,
    clf: Classifier,
    persons_cfg: list[dict[str, Any]],
    person_names: list[str],
    today: date,
    viewer_person: str | None,
    contracts: list[dict[str, Any]] | None,
    review: dict[str, Any],
    state: dict[str, Any],
    ledger_earliest: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """G6: ``hh_year``, ``hh_cycle``, ``p_year``, ``p_cycle``, ``settle``, ``diff``.

    Other persons appear as totals only (income, expenses, saved); the viewer's
    own person carries the full detail.
    """
    from .household_summary import cycle_windows, figures
    from .year_view import _shared_share, build_year

    booked = [t for t in txs if t.get("_status", "booked") == "booked"]
    cycle = cycle_windows(booked, today, persons_cfg)[0][0]
    hh_year = build_year(
        txs=booked, plan=plan, clf=clf, persons=persons_cfg, today=today, view="household",
        person=None, contracts=contracts, is_admin=False, ledger_earliest=ledger_earliest,
    )
    fig = figures(booked, cycle, clf)
    totals = {
        "income": round(fig["income"], 2), "expenses": round(fig["expenses"], 2),
        "saved": round(fig["income"] - fig["expenses"], 2),
        "fixed": round(fig["fixed"], 2), "variable": round(fig["variable"], 2),
    }
    hh_cycle = {
        "start": cycle[0].isoformat(), "end": cycle[1].isoformat(), **totals,
        "shared": round(fig["owners"].get(OWNER_SHARED, {}).get("expenses", 0.0), 2),
        "positions": _plan_vs_actual(plan, booked, cycle, person_names, None),
    }
    p_year: dict[str, Any] = {}
    p_cycle: dict[str, Any] = {}
    for name in person_names:
        full = name == viewer_person
        own = fig["owners"].get(name, {})
        inc, exp = round(own.get("income", 0.0), 2), round(own.get("expenses", 0.0), 2)
        # The person's income also carries their part of the shared spending.
        part = round(
            fig["owners"].get(OWNER_SHARED, {}).get("expenses", 0.0)
            * _shared_share(plan, name, list(person_names)),
            2,
        )
        p_cycle[name] = {
            "restricted": not full, "income": inc, "expenses": exp,
            "shared_share": part, "saved": round(inc - exp - part, 2),
        }
        yr = build_year(
            txs=booked, plan=plan, clf=clf, persons=persons_cfg, today=today, view="person",
            person=name, contracts=contracts, is_admin=False, ledger_earliest=ledger_earliest,
        )
        p_year[name] = {"restricted": not full, **{k: yr["balance"][k] for k in ("income", "expenses", "saved", "savings_rate")}}
        if full:
            p_cycle[name].update(
                fixed=round(own.get("fixed", 0.0), 2), variable=round(own.get("variable", 0.0), 2),
                positions=_plan_vs_actual(plan, booked, cycle, person_names, name),
            )
            p_year[name].update(categories=yr["categories"], split=yr["split"], cycles=yr["cycles"])
    year_window = (date(today.year, 1, 1), today)
    after = snapshot(booked, clf, year_window, review, cycle)
    return {
        "hh_year": hh_year,
        "hh_cycle": hh_cycle,
        "p_year": p_year,
        "p_cycle": p_cycle,
        "settle": {
            "cycle": {"start": cycle[0].isoformat(), "end": cycle[1].isoformat(),
                      "balances": settlement_balances(booked, clf, cycle)},
            "year": settlement_balances(booked, clf, year_window),
        },
        "diff": diff(state.get("started_snapshot") or state.get("last_before"), after),
        "reviewed_at": state.get("reviewed_at"),
    }
