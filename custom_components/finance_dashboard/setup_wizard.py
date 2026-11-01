"""Setup-wizard state, payday suggestions and pot suggestions from history.

Everything here is a cache/config read except the state Store. No bank call.

State lives in its own HA ``Store`` (not in the config entry) so wizard
progress never triggers an entry update/reload. Paydays are the exception:
they belong to a person, so they are stored on the person record in
``entry.data["persons"][i]["payday"] = {"day": int, "confirmed": bool}``.

Payday and the cycle rule: ``payday_cycle`` turns a confirmed payday day into
a cycle window. ``home.py`` can use it as the *preferred* start when a person
has a confirmed payday and fall back to ``cycle.person_cycle`` (detected
salary) otherwise; today nothing changes for persons without a payday.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CATEGORY_INCOME, CATEGORY_OTHER, CATEGORY_TRANSFERS, DOMAIN
from .cycle import cycle_windows, salary_starts
from . import plan_wizard
from .recurring import detect_recurring

STORAGE_KEY = f"{DOMAIN}.setup_wizard"
STORAGE_VERSION = 1

STEPS = (
    "persons", "accounts", "payday", "region", "notifications", "ai", "points", "done",
)
SKIPPABLE = {"payday", "region", "notifications", "ai", "points"}
STATUSES = ("pending", "done", "skipped")

DEFAULT_NOTIFICATIONS: dict[str, Any] = {
    "enabled": True,
    "large_debit": True,
    "large_debit_factor": 3.0,
    "large_debit_threshold": 500.0,  # absolute EUR; 0 disables the absolute rule
    "double_charge": True,
    "missing_salary": True,
    "consent_expiring": True,
    "digest_enabled": True,
}

# Fixed costs belong in the plan, not in variable-spend pots.
_NOT_VARIABLE = {"housing", "insurance", "loans", "subscriptions"}
_SKIP = {CATEGORY_INCOME, CATEGORY_TRANSFERS, CATEGORY_OTHER}
POT_ROUNDING = 10
MIN_SAMPLES = 2
CYCLES_BACK = 3


class SetupError(ValueError):
    """Invalid wizard input; ``code`` is the API error code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def default_state() -> dict[str, Any]:
    return {
        "steps": {s: "pending" for s in STEPS if s != "done"},
        "plan_wizard": plan_wizard.default_state(),
        "completed": False,
        "ai_opt_in": False,
        "points_target": "",
        "notifications": dict(DEFAULT_NOTIFICATIONS),
        "notified": {},
        "last_digest_week": "",
    }


def _store(hass: HomeAssistant) -> Store:
    data = hass.data.setdefault(DOMAIN, {})
    store = data.get("_setup_wizard_store")
    if store is None:
        store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        data["_setup_wizard_store"] = store
    return store


def _merge_state(raw: Any) -> dict[str, Any]:
    state = default_state()
    if not isinstance(raw, dict):
        return state
    for step, status in (raw.get("steps") or {}).items():
        if step in state["steps"] and status in STATUSES:
            state["steps"][step] = status
    state["plan_wizard"] = plan_wizard.merge_state(raw.get("plan_wizard"))
    state["completed"] = bool(raw.get("completed"))
    state["ai_opt_in"] = bool(raw.get("ai_opt_in"))
    state["points_target"] = str(raw.get("points_target") or "")
    state["notifications"].update(
        {k: v for k, v in (raw.get("notifications") or {}).items() if k in DEFAULT_NOTIFICATIONS}
    )
    notified = raw.get("notified")
    state["notified"] = dict(notified) if isinstance(notified, dict) else {}
    state["last_digest_week"] = str(raw.get("last_digest_week") or "")
    return state


async def async_load_state(hass: HomeAssistant) -> dict[str, Any]:
    try:
        raw = await _store(hass).async_load()
    except Exception:  # noqa: BLE001 - a broken file must not block the wizard
        raw = None
    return _merge_state(raw)


async def async_save_state(hass: HomeAssistant, state: dict[str, Any]) -> None:
    await _store(hass).async_save(state)


def effective_steps(state: dict[str, Any], hints: dict[str, bool]) -> dict[str, str]:
    """Stored status, upgraded to ``done`` when the data already proves it."""
    out = {}
    for step, status in state["steps"].items():
        out[step] = "done" if status == "pending" and hints.get(step) else status
    return out


def current_step(state: dict[str, Any], hints: dict[str, bool]) -> str:
    """First unresolved step; ``done`` once completed or everything is resolved."""
    if state.get("completed"):
        return "done"
    for step, status in effective_steps(state, hints).items():
        if status == "pending":
            return step
    return "done"


def apply_update(state: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Validate ``body`` and return the new state. Raises :class:`SetupError`."""
    new = _merge_state(state)
    step = body.get("step")
    if step is not None:
        status = body.get("status", "done")
        if step not in new["steps"]:
            raise SetupError("unknown_step", "Unknown wizard step")
        if status not in STATUSES:
            raise SetupError("invalid_status", "Status must be pending, done or skipped")
        if status == "skipped" and step not in SKIPPABLE:
            raise SetupError("not_skippable", "This step cannot be skipped")
        new["steps"][step] = status
    if "ai_opt_in" in body:
        if not isinstance(body["ai_opt_in"], bool):
            raise SetupError("invalid_ai_opt_in", "ai_opt_in must be a boolean")
        new["ai_opt_in"] = body["ai_opt_in"]
    if "notifications" in body:
        new["notifications"].update(validate_notifications(body["notifications"]))
    if "complete" in body:
        if not isinstance(body["complete"], bool):
            raise SetupError("invalid_complete", "complete must be a boolean")
        new["completed"] = body["complete"]
    return new


def validate_notifications(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SetupError("invalid_notifications", "notifications must be an object")
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in DEFAULT_NOTIFICATIONS:
            raise SetupError("unknown_notification_setting", f"Unknown setting {key}")
        if isinstance(DEFAULT_NOTIFICATIONS[key], bool):
            if not isinstance(value, bool):
                raise SetupError("invalid_notifications", f"{key} must be a boolean")
        else:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise SetupError("invalid_notifications", f"{key} must be a number")
            if not 0 <= float(value) <= 1_000_000:
                raise SetupError("invalid_notifications", f"{key} out of range")
            if key == "large_debit_factor" and float(value) < 1:
                raise SetupError("invalid_notifications", "factor must be >= 1")
            value = float(value)
        out[key] = value
    return out


def data_hints(
    persons: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    pots: int = 0,  # noqa: ARG001 - kept for callers; pots left the setup wizard
    *,
    region: bool = False,
    points: bool = False,
) -> dict[str, bool]:
    """Which steps the existing data already satisfies (resume support)."""
    assigned = bool(accounts) and all(
        a.get("type") == "shared" or str(a.get("person") or "") for a in accounts
    )
    return {
        "persons": bool(persons),
        "accounts": assigned,
        "payday": bool(persons) and all(person_payday(p) for p in persons),
        "region": region,
        "points": points,
    }


# ---------------------------------------------------------------------------
# Payday
# ---------------------------------------------------------------------------


def person_payday(person: dict[str, Any]) -> int | None:
    """Confirmed payday day-of-month of a person record, else None."""
    pd = person.get("payday")
    if isinstance(pd, dict) and pd.get("confirmed"):
        try:
            day = int(pd.get("day"))
        except (TypeError, ValueError):
            return None
        return day if 1 <= day <= 31 else None
    return None


def validate_paydays(raw: Any, persons: list[dict[str, Any]]) -> dict[str, int]:
    """``[{"person", "day"}]`` -> ``{person: day}``. Raises :class:`SetupError`."""
    if not isinstance(raw, list):
        raise SetupError("invalid_paydays", "paydays must be a list")
    names = {str(p.get("name")) for p in persons}
    out: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise SetupError("invalid_paydays", "Each payday must be an object")
        name = str(item.get("person") or "")
        if name not in names:
            raise SetupError("unknown_person", "Unknown person")
        day = item.get("day")
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
            raise SetupError("invalid_payday", "day must be an integer 1-31")
        out[name] = day
    return out


def apply_paydays(persons: list[dict[str, Any]], paydays: dict[str, int]) -> list[dict[str, Any]]:
    """Return new person records with the confirmed paydays set."""
    out = []
    for p in persons:
        p = dict(p)
        if p.get("name") in paydays:
            p["payday"] = {"day": paydays[p["name"]], "confirmed": True}
        out.append(p)
    return out


def payday_cycle(day: int, today: date) -> tuple[date, date]:
    """Cycle ``(start, end)`` for a payday day-of-month containing ``today``.

    A payday past the month's end (31 in a short month) lands on the last day.
    """

    def _on(y: int, m: int) -> date:
        return date(y, m, min(day, calendar.monthrange(y, m)[1]))

    this = _on(today.year, today.month)
    if this <= today:
        ny, nm = today.year + (today.month == 12), today.month % 12 + 1
        return this, _on(ny, nm) - timedelta(days=1)
    py, pm = today.year - (today.month == 1), (today.month - 2) % 12 + 1
    return _on(py, pm), this - timedelta(days=1)


def amount_of(tx: dict[str, Any]) -> float:
    try:
        return float((tx.get("transactionAmount") or {}).get("amount", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def day_of(tx: dict[str, Any]) -> date | None:
    raw = str(tx.get("bookingDate") or tx.get("valueDate") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def tx_owner(tx: dict[str, Any]) -> str:
    if tx.get("_account_type") == "shared":
        return "shared"
    return str(tx.get("_account_person") or "") or "shared"


def suggest_paydays(
    transactions: list[dict[str, Any]], persons: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Largest recurring credit on each person's accounts and its usual day."""
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
        entry: dict[str, Any] = {
            "person": name,
            "confirmed_day": person_payday(p),
            "suggested_day": None,
            "source": None,
            "amount": None,
        }
        if patterns:
            best = max(patterns, key=lambda x: x["average_amount"])
            entry.update(
                suggested_day=int(best["expected_day"]),
                source=best["creditor"],
                amount=round(best["average_amount"], 2),
            )
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Pots from history
# ---------------------------------------------------------------------------


def _history_windows(transactions: list[dict[str, Any]], today: date) -> list[tuple[date, date]]:
    incomes = [
        (d, a)
        for t in transactions
        if (a := amount_of(t)) > 0
        and t.get("category") != CATEGORY_TRANSFERS
        and t.get("_status", "booked") == "booked"
        and (d := day_of(t)) is not None
    ]
    windows = [w for w in cycle_windows(salary_starts(incomes)) if w[1] < today]
    windows = windows[-CYCLES_BACK:]
    if len(windows) >= MIN_SAMPLES and all(10 <= (e - s).days + 1 <= 45 for s, e in windows):
        return windows
    out = []
    y, m = today.year, today.month
    for _ in range(CYCLES_BACK):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append((date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])))
    return list(reversed(out))


def suggest_pots(
    transactions: list[dict[str, Any]],
    existing: list[Any],
    today: date,
) -> list[dict[str, Any]]:
    """Per owner + variable category: median spend of the last cycles, rounded to 10."""
    windows = _history_windows(transactions, today)
    spent: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0] * len(windows))
    for t in transactions:
        amount = amount_of(t)
        cat = str(t.get("category") or CATEGORY_OTHER)
        day = day_of(t)
        if amount >= 0 or day is None or cat in _SKIP or cat in _NOT_VARIABLE:
            continue
        if t.get("_status", "booked") != "booked":
            continue
        for i, (s, e) in enumerate(windows):
            if s <= day <= e:
                spent[(tx_owner(t), cat)][i] += -amount
    covered = {(p.owner, k) for p in existing for k in p.category_keys}
    out = []
    for (owner, cat), values in sorted(spent.items()):
        samples = [v for v in values if v > 0]
        if len(samples) < MIN_SAMPLES or (owner, cat) in covered:
            continue
        budget = max(POT_ROUNDING, round(median(samples) / POT_ROUNDING) * POT_ROUNDING)
        out.append(
            {
                "owner": owner,
                "category": cat,
                "name": cat.replace("_", " ").title(),
                "cycle_budget": float(budget),
                "samples": len(samples),
            }
        )
    return out


def validate_pot_acceptance(
    raw: Any, known_account_keys: set[str] | None = None
) -> list[dict[str, Any]]:
    """Body of the accept call -> pot payloads for ``manager.async_save_pot``."""
    items = raw.get("accept") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        raise SetupError("invalid_body", "accept must be a non-empty list")
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("category"):
            raise SetupError("invalid_body", "Each item needs a category")
        payload = {
            "name": str(item.get("name") or str(item["category"]).title()),
            "owner": str(item.get("owner") or "shared"),
            "cycle_budget": item.get("cycle_budget", 0),
            "category_keys": [str(item["category"])],
        }
        if item.get("account_keys") is not None:
            keys = item["account_keys"]
            if not isinstance(keys, list):
                raise SetupError("invalid_body", "account_keys must be a list or null")
            if known_account_keys is not None and any(str(k) not in known_account_keys for k in keys):
                raise SetupError("unknown_account", "account_keys contains an unknown account")
            payload["account_keys"] = keys
        out.append(payload)
    return out


# Nicknames: ``name`` is the stable key (accounts, pots, plan, rules reference
# it); ``display_name`` is display-only and can change freely.
MAX_NICKNAME = 40


def validate_nicknames(raw: Any, persons: list[dict[str, Any]]) -> dict[str, str]:
    """``[{"person", "display_name"}]`` -> ``{person: nickname}`` ("" clears)."""
    if not isinstance(raw, list):
        raise SetupError("invalid_nicknames", "nicknames must be a list")
    names = {str(p.get("name")) for p in persons}
    out: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise SetupError("invalid_nicknames", "Each nickname must be an object")
        person = str(item.get("person") or "")
        if person not in names:
            raise SetupError("unknown_person", "Unknown person")
        nick = item.get("display_name")
        if nick is None:
            nick = ""
        if not isinstance(nick, str) or len(nick.strip()) > MAX_NICKNAME:
            raise SetupError("invalid_display_name", "display_name must be at most 40 characters")
        out[person] = nick.strip()
    return out


def apply_nicknames(
    persons: list[dict[str, Any]], nicknames: dict[str, str]
) -> list[dict[str, Any]]:
    """New person records with nicknames set; an empty or identical one is removed."""
    out = []
    for p in persons:
        p = dict(p)
        name = p.get("name")
        if name in nicknames:
            nick = nicknames[name]
            if nick and nick != name:
                p["display_name"] = nick
            else:
                p.pop("display_name", None)
        out.append(p)
    return out


def iso_week(day: date | datetime) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"
