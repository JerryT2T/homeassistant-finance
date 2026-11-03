"""Exception notifications and the weekly digest.

Rhythm (product concept): the integration speaks only when something is off,
plus one calm digest per calendar week. Detection is pure (``detect_*``);
delivery runs from the daily refresh path (``async_after_refresh``) - never
from a poll.

Exceptions
----------
* ``large_debit``     a debit above ``factor`` x the merchant's median, or above
                      an absolute threshold
* ``double_charge``   same merchant + amount twice within 3 days
* ``missing_salary``  a recurring income more than 3 days overdue
* ``consent_expiring`` a bank consent that is expiring/expired (the repair issue
                      from ``manager/_banks.py`` stays the fix path)

Delivery
--------
* HA event ``finance_dashboard_exception``. Payload: ``kind``, ``person``
  (owner or ``"shared"``), ``merchant`` (display name), ``amount`` (rounded,
  allowed because ``events.py`` events carry amounts too), ``date``. Never an
  IBAN or account number.
* ``persistent_notification`` is visible to every HA user, so it is generic:
  kind + person, and the merchant only for shared items.
* Each exception is delivered once (hashed id in the wizard store, pruned).

Digest: ``finance_dashboard_weekly_digest`` event + persistent notification,
once per ISO week; household level only (cycle status, top category changes
week over week, open questions).
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CATEGORY_TRANSFERS, DOMAIN
from .life_areas import is_income
from .recurring import detect_recurring
from .setup_wizard import (
    amount_of,
    async_load_state,
    async_save_state,
    day_of,
    iso_week,
    person_payday,
    tx_owner,
)
from .counted import counted_transactions
from .tx_dates import effective_date_str

_LOGGER = logging.getLogger(__name__)

EVENT_EXCEPTION = f"{DOMAIN}_exception"
EVENT_WEEKLY_DIGEST = f"{DOMAIN}_weekly_digest"

LOOKBACK_DAYS = 7  # only transactions this fresh can raise an exception
DOUBLE_CHARGE_DAYS = 3
SALARY_OVERDUE_DAYS = 3
MIN_MERCHANT_HISTORY = 3
NOTIFIED_RETENTION_DAYS = 60


def merchant_of(tx: dict[str, Any]) -> str:
    """Display name of the counterparty (debit: creditor)."""
    name = tx.get("creditorName") if amount_of(tx) < 0 else tx.get("debtorName")
    name = name or tx.get("creditorName") or tx.get("debtorName") or ""
    return str(name).strip()


def _tx_id(tx: dict[str, Any]) -> str:
    base = str(tx.get("_ledger_id") or "") or "|".join(
        str(x)
        for x in (
            tx.get("_account_key"),
            effective_date_str(tx),
            tx.get("transactionAmount"),
            merchant_of(tx),
            str(tx.get("remittanceInformationUnstructured") or "")[:30],
        )
    )
    return hashlib.sha1(base.encode()).hexdigest()[:16]  # noqa: S324 - dedupe key only


def _exc(kind: str, ident: str, tx_owner_: str, merchant: str, amount: float, day: date) -> dict:
    key = hashlib.sha1(f"{kind}:{ident}".encode()).hexdigest()[:20]  # noqa: S324
    return {
        "id": key,
        "kind": kind,
        "person": tx_owner_,
        "merchant": merchant,
        "amount": round(abs(amount), 2),
        "date": day.isoformat(),
    }


def _debits(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        t
        for t in transactions
        if amount_of(t) < 0
        and t.get("_status", "booked") == "booked"
        and t.get("category") != CATEGORY_TRANSFERS
        and not is_income(t.get("category"))
        and merchant_of(t)
        and day_of(t) is not None
    ]


def detect_large_debits(
    transactions: list[dict[str, Any]], today: date, factor: float, threshold: float
) -> list[dict[str, Any]]:
    debits = _debits(transactions)
    history: dict[str, list[float]] = defaultdict(list)
    for t in debits:
        history[merchant_of(t).lower()].append(-amount_of(t))
    out = []
    for t in debits:
        day = day_of(t)
        if day is None or (today - day).days > LOOKBACK_DAYS or day > today:
            continue
        amount = -amount_of(t)
        past = list(history[merchant_of(t).lower()])
        past.remove(amount)  # the transaction itself is not its own baseline
        relative = len(past) >= MIN_MERCHANT_HISTORY and amount > factor * median(past)
        absolute = threshold > 0 and amount > threshold
        if relative or absolute:
            out.append(_exc("large_debit", _tx_id(t), tx_owner(t), merchant_of(t), amount, day))
    return out


def detect_double_charges(transactions: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    groups: dict[tuple[str, float], list[tuple[date, dict[str, Any]]]] = defaultdict(list)
    for t in _debits(transactions):
        day = day_of(t)
        groups[(merchant_of(t).lower(), round(amount_of(t), 2))].append((day, t))
    out = []
    for items in groups.values():
        items.sort(key=lambda x: x[0])
        for (d1, _), (d2, t2) in zip(items, items[1:], strict=False):
            if 0 <= (d2 - d1).days <= DOUBLE_CHARGE_DAYS and 0 <= (today - d2).days <= LOOKBACK_DAYS:
                out.append(
                    _exc("double_charge", _tx_id(t2), tx_owner(t2), merchant_of(t2),
                         amount_of(t2), d2)
                )
    return out


def _due_in_month(day: int, ref: date) -> date:
    import calendar

    return date(ref.year, ref.month, min(day, calendar.monthrange(ref.year, ref.month)[1]))


def detect_missing_salary(
    transactions: list[dict[str, Any]], persons: list[dict[str, Any]], today: date
) -> list[dict[str, Any]]:
    out = []
    for p in persons:
        name = str(p.get("name") or "")
        credits = [
            t
            for t in transactions
            if tx_owner(t) == name
            and amount_of(t) > 0
            and t.get("_status", "booked") == "booked"
            and t.get("category") != CATEGORY_TRANSFERS
        ]
        patterns = [x for x in detect_recurring(credits) if x["average_amount"] > 0]
        if not patterns:
            continue
        best = max(patterns, key=lambda x: x["average_amount"])
        day = person_payday(p) or int(best["expected_day"])  # a confirmed payday wins
        due = _due_in_month(day, today)
        try:
            last_seen = date.fromisoformat(best["last_seen"])
        except ValueError:
            continue
        if (today - due).days > SALARY_OVERDUE_DAYS and last_seen < due - timedelta(days=15):
            out.append(
                _exc("missing_salary", f"{name}:{due.isoformat()}", name, best["creditor"],
                     best["average_amount"], due)
            )
    return out


def detect_all(
    transactions: list[dict[str, Any]],
    persons: list[dict[str, Any]],
    today: date,
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if settings.get("large_debit"):
        found += detect_large_debits(
            transactions, today,
            float(settings["large_debit_factor"]), float(settings["large_debit_threshold"]),
        )
    if settings.get("double_charge"):
        found += detect_double_charges(transactions, today)
    if settings.get("missing_salary"):
        found += detect_missing_salary(transactions, persons, today)
    return found


def consent_exceptions(banks: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    out = []
    for b in banks:
        state = b.get("consent_state")
        if state in ("expiring", "expired"):
            valid = str(b.get("consent_valid_until") or "")[:10]
            out.append(
                {
                    "id": hashlib.sha1(f"consent:{b.get('bank_id')}:{state}:{valid}".encode())  # noqa: S324
                    .hexdigest()[:20],
                    "kind": f"consent_{state}",
                    "person": "shared",
                    "merchant": str(b.get("title") or ""),
                    "amount": None,
                    "date": today.isoformat(),
                }
            )
    return out


_CATEGORY_DE = {
    "housing_cold": "Wohnen kalt", "housing_warm": "Wohnen warm",
    "groceries": "Lebensmittel & Haushalt", "mobility": "Mobilität",
    "health": "Gesundheit & Absicherung", "leisure": "Freizeit",
    "media": "Medien & Kommunikation", "finance": "Finanzen & Verpflichtungen",
    "income_work": "Einkommen Arbeit", "income_state": "Einkommen Staat",
    "income_capital": "Kapitalerträge", "income_refund": "Erstattungen",
    "income_private": "Einnahmen privat", "transfers": "Umbuchungen", "other": "Sonstiges",
}
_KIND_DE = {
    "large_debit": "ungewöhnlich hohe Abbuchung",
    "double_charge": "mögliche Doppelbuchung",
    "missing_salary": "erwartetes Gehalt fehlt",
    "consent_expiring": "Bankzugang läuft bald ab",
    "consent_expired": "Bankzugang abgelaufen",
}


def build_digest(
    transactions: list[dict[str, Any]], today: date, home: dict[str, Any] | None
) -> dict[str, Any]:
    """Household-level weekly summary: status, top category changes, open questions."""
    this_start = today - timedelta(days=6)
    prev_start, prev_end = today - timedelta(days=13), today - timedelta(days=7)
    cur: dict[str, float] = defaultdict(float)
    prev: dict[str, float] = defaultdict(float)
    for t in _debits(transactions):
        day = day_of(t)
        cat = str(t.get("category") or "other")
        if this_start <= day <= today:
            cur[cat] += -amount_of(t)
        elif prev_start <= day <= prev_end:
            prev[cat] += -amount_of(t)
    changes = sorted(
        ({"category": c, "delta": round(cur[c] - prev[c], 2)} for c in set(cur) | set(prev)),
        key=lambda x: abs(x["delta"]),
        reverse=True,
    )[:3]
    home = home or {}
    status = home.get("status", "unknown")
    questions = int(home.get("questions_open") or 0)
    status_de = {"good": "passt", "near": "knapp", "over": "drüber"}.get(status, status)
    lines = [f"Zyklus: {status_de}."]
    if "remaining" in home:
        lines.append(f"Noch frei in diesem Zyklus: {home['remaining']:.0f} €.")
    for c in changes:
        label = _CATEGORY_DE.get(c["category"], c["category"])
        lines.append(f"{label}: {c['delta']:+.0f} € zur Vorwoche.")
    lines.append(f"Offene Fragen: {questions}.")
    return {
        "week": iso_week(today),
        "status": status,
        "top_changes": changes,
        "questions_open": questions,
        "text": " ".join(lines),
    }


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _persistent(hass: HomeAssistant, notification_id: str, title: str, message: str) -> None:
    from homeassistant.components import persistent_notification

    persistent_notification.async_create(
        hass, message, title=title, notification_id=f"{DOMAIN}_{notification_id}"
    )


def deliver_exception(hass: HomeAssistant, exc: dict[str, Any]) -> None:
    payload = {k: v for k, v in exc.items() if k != "id" and v is not None}
    hass.bus.async_fire(EVENT_EXCEPTION, payload)
    who = exc["person"] if exc["person"] != "shared" else "den Haushalt"
    detail = f" ({exc['merchant']})" if exc["person"] == "shared" and exc["merchant"] else ""
    _persistent(
        hass,
        exc["id"],
        "Finance",
        f"Bitte kurz ansehen für {who}: {_KIND_DE.get(exc['kind'], exc['kind'].replace('_', ' '))}{detail}.",
    )


async def async_after_refresh(hass: HomeAssistant, manager: Any, now: datetime | None = None) -> None:
    """Run exception checks + the weekly digest. Cache only; never raises."""
    try:
        await _run(hass, manager, now)
    except Exception:  # noqa: BLE001 - notifications must never break a refresh
        _LOGGER.exception("Exception notification run failed")


async def _run(hass: HomeAssistant, manager: Any, now: datetime | None) -> None:
    if getattr(manager, "demo_mode", False):
        return
    state = await async_load_state(hass)
    settings = state["notifications"]
    if not settings.get("enabled"):
        return
    now = now or dt_util.now()
    today = now.date()
    transactions = counted_transactions(
        manager._transactions,  # noqa: SLF001
        getattr(manager, "_accounts", None) or [],
        include_pending=True,
    )
    found = detect_all(transactions, manager.persons, today, settings)
    if settings.get("consent_expiring"):
        found += consent_exceptions(manager.get_bank_status(), today)

    notified = state["notified"]
    cutoff = (today - timedelta(days=NOTIFIED_RETENTION_DAYS)).isoformat()
    notified = {k: v for k, v in notified.items() if str(v) >= cutoff}
    for exc in found:
        if exc["id"] in notified:
            continue
        deliver_exception(hass, exc)
        notified[exc["id"]] = today.isoformat()
    state["notified"] = notified

    # Contract notice deadlines ≤30 days away (fires once per deadline).
    from .contracts import async_fire_notice_due, own_account_names

    accounts = getattr(manager, "_accounts", []) or []
    await async_fire_notice_due(
        hass,
        counted_transactions(manager._transactions, accounts),  # noqa: SLF001
        own_names=own_account_names(accounts),
    )

    week = iso_week(today)
    if settings.get("digest_enabled") and state["last_digest_week"] != week:
        home = None
        try:
            home = manager.get_home(person=None, view="household", horizon="cycle")
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Digest without home payload", exc_info=True)
        digest = build_digest(transactions, today, home)
        hass.bus.async_fire(EVENT_WEEKLY_DIGEST, digest)
        _persistent(hass, f"digest_{week}", "Finance – Wochenüberblick", digest["text"])
        state["last_digest_week"] = week
    await async_save_state(hass, state)
