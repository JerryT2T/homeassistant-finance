"""Contracts, reserves and pot coverage (Phase 4d).

A *series* (``recurring.detect_series``) is what the bank shows: payments that
repeat. A *contract* is what the user knows about it: start, minimum term,
renewal and notice period. Contract fields are persisted per series id and
user-editable; everything else (next notice deadline, special-termination
right, monthly reserve) is derived on every read.

Notice deadline model
---------------------
``term_end`` = ``start`` + ``min_term_months``, rolled forward by
``renewal_months`` until it lies ahead. With reference ``end_of_month`` the
contract can only end at the last day of the month containing ``term_end``.
``deadline`` = effective end - notice period. If that deadline has passed, the
next renewal period is taken, so the result is always the next *actionable*
deadline.

SECURITY: contracts hold payee names and amounts. They live only in HA's
``.storage/`` and must never be committed. The notice event carries no amount.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .account_identity import account_key
from .const import DOMAIN, STORAGE_VERSION
from .labels import LabelError, clean_ids
from .contract_kind import CATEGORY_DEFAULTS as KIND_CATEGORY_DEFAULTS
from .contract_kind import (
    KIND_CONTRACT,
    KIND_IRREGULAR,
    KIND_REGULAR,
    KIND_SUBSCRIPTION,
    KINDS,
    NO_NOTICE_KINDS,
    SUBSCRIPTION_DEFAULTS,
    kind_defaults,
)
from .recurring import (
    INTERVALS,
    IRREGULAR_INTERVALS,
    PLAN_MODE_FIXED,
    PLAN_MODES,
    add_months,
    detect_series,
)
from .series_confidence import REASON_OWN_NAME, own_name_contract
from .settlement import MAX_MANUAL as MAX_MANUAL_SETTLEMENTS
from .settlement import TRAIT_USAGE_BASED
from .settlement import expected as expected_settlement

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY_CONTRACTS = f"{DOMAIN}_contracts"
EVENT_NOTICE_DUE = f"{DOMAIN}_notice_due"
NOTICE_EVENT_WINDOW_DAYS = 30
_STORE_KEY = "_contract_store"

NOTICE_UNITS = ("days", "weeks", "months")
REF_END_OF_TERM = "end_of_term"
REF_END_OF_MONTH = "end_of_month"
NOTICE_REFERENCES = (REF_END_OF_TERM, REF_END_OF_MONTH)

# Legacy per-category table; the kind (#111) decides the defaults now.
CATEGORY_DEFAULTS: dict[str, tuple[int, int, int, str]] = {
    **KIND_CATEGORY_DEFAULTS,
    "media": SUBSCRIPTION_DEFAULTS,
}
_FALLBACK_DEFAULTS = SUBSCRIPTION_DEFAULTS


# Fields a bad stored value of must never cost the contract terms (QA #113, Codex #116).
_ADD_ONS = ("labels", "settlements", "usage_based")

REVIEW_CONTRACT = "contract"
REVIEW_NOT_CONTRACT = "not_contract"
REVIEW_ANSWERS = (REVIEW_CONTRACT, REVIEW_NOT_CONTRACT)


class ContractError(Exception):
    """Invalid contract input (``code`` is machine-readable)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def category_defaults(category: str) -> dict[str, Any]:
    term, renewal, notice, unit = CATEGORY_DEFAULTS.get(category, _FALLBACK_DEFAULTS)
    return {
        "min_term_months": term,
        "renewal_months": renewal,
        "notice_value": notice,
        "notice_unit": unit,
        "notice_reference": REF_END_OF_TERM,
    }


@dataclass
class Contract:
    """User-owned contract fields; ``None`` means "use the prefilled default"."""

    series_id: str
    start: str | None = None
    min_term_months: int | None = None
    renewal_months: int | None = None
    notice_value: int | None = None
    notice_unit: str | None = None
    notice_reference: str | None = None
    owner: str | None = None
    category: str | None = None
    plan_position_id: str | None = None
    special_termination: bool | None = None  # None = derive from the pattern
    plan_mode: str | None = None
    plan_fixed_amount: float | None = None
    review: str | None = None  # the user's answer to a candidate (#130)
    kind: str | None = None  # None = follow the detector's suggestion (#111)
    labels: list[str] | None = None  # passed on to every booking of the series (#113)
    usage_based: bool | None = None  # None = follow the detected trait (#116)
    settlements: list[str] | None = None  # booking keys assigned by hand as settlements

    _FIELDS = (
        "start",
        "min_term_months",
        "renewal_months",
        "notice_value",
        "notice_unit",
        "notice_reference",
        "owner",
        "category",
        "plan_position_id",
        "special_termination",
        "plan_mode",
        "plan_fixed_amount",
        "review",
        "kind",
        "labels",
        "usage_based",
        "settlements",
    )

    def to_dict(self) -> dict[str, Any]:
        out = {f: getattr(self, f) for f in self._FIELDS}
        out["labels"] = list(self.labels) if self.labels else None
        out["settlements"] = list(self.settlements) if self.settlements else None
        return out

    def apply(self, data: dict[str, Any]) -> None:
        """Validate and apply a partial update. Raises ``ContractError``."""
        unknown = set(data) - set(self._FIELDS)
        if unknown:
            raise ContractError("unknown_field", "Unknown contract field")
        new = self.to_dict()
        new.update(data)
        _validate(new)
        for f in self._FIELDS:
            setattr(self, f, new[f])

    @classmethod
    def from_dict(cls, sid: str, data: dict[str, Any]) -> Contract:
        c = cls(series_id=sid)
        fields = {k: v for k, v in data.items() if k in cls._FIELDS}
        try:
            c.apply(fields)
        except ContractError:
            try:  # add-ons: never lose the contract terms over them
                c.apply(
                    {k: v for k, v in fields.items() if k not in _ADD_ONS}
                )
            except ContractError:
                _LOGGER.warning("Skipping unreadable contract fields")
        return c


def _int_in(value: Any, lo: int, hi: int, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        raise ContractError("invalid_" + name, f"{name} must be a whole number")
    if not lo <= int(value) <= hi:
        raise ContractError("invalid_" + name, f"{name} out of range")
    return int(value)


def _validate(d: dict[str, Any]) -> None:
    if d["start"] is not None:
        try:
            date.fromisoformat(str(d["start"]))
        except ValueError as err:
            raise ContractError("invalid_start", "start must be YYYY-MM-DD") from err
        d["start"] = str(d["start"])
    d["min_term_months"] = _int_in(d["min_term_months"], 0, 240, "min_term_months")
    d["renewal_months"] = _int_in(d["renewal_months"], 1, 240, "renewal_months")
    d["notice_value"] = _int_in(d["notice_value"], 0, 3650, "notice_value")
    if d["notice_unit"] is not None and d["notice_unit"] not in NOTICE_UNITS:
        raise ContractError("invalid_notice_unit", "Unknown notice unit")
    if d["notice_reference"] is not None and d["notice_reference"] not in NOTICE_REFERENCES:
        raise ContractError("invalid_notice_reference", "Unknown notice reference")
    for name in ("owner", "category", "plan_position_id"):
        v = d[name]
        if v is not None:
            if not isinstance(v, str) or len(v) > 80:
                raise ContractError("invalid_" + name, f"{name} must be a short string")
            d[name] = v.strip() or None
    if d["special_termination"] is not None and not isinstance(d["special_termination"], bool):
        raise ContractError("invalid_special_termination", "Must be a boolean or null")
    if d["plan_mode"] is not None and d["plan_mode"] not in PLAN_MODES:
        raise ContractError("invalid_plan_mode", "Unknown plan mode")
    fixed = d["plan_fixed_amount"]
    if fixed is not None:
        if isinstance(fixed, bool) or not isinstance(fixed, int | float) or fixed != fixed:
            raise ContractError("invalid_plan_fixed_amount", "Must be a number")
        if not 0 <= fixed <= 1_000_000:
            raise ContractError("invalid_plan_fixed_amount", "Out of range")
        d["plan_fixed_amount"] = round(float(fixed), 2)
    if d["review"] is not None and d["review"] not in REVIEW_ANSWERS:
        raise ContractError("invalid_review", "Unknown review answer")
    if d["kind"] is not None and d["kind"] not in KINDS:
        raise ContractError("invalid_kind", "Unknown contract kind")
    try:
        d["labels"] = clean_ids(d["labels"]) or None
    except LabelError as err:
        raise ContractError(err.code, err.detail) from err
    if d["usage_based"] is not None and not isinstance(d["usage_based"], bool):
        raise ContractError("invalid_usage_based", "Must be a boolean or null")
    keys = d["settlements"]
    if keys is not None:
        if (
            not isinstance(keys, list)
            or len(keys) > MAX_MANUAL_SETTLEMENTS
            or any(not isinstance(k, str) or not 0 < len(k) <= 200 for k in keys)
        ):
            raise ContractError("invalid_settlements", "Must be a list of booking keys")
        d["settlements"] = list(dict.fromkeys(keys)) or None
    if d["plan_mode"] == PLAN_MODE_FIXED and d["plan_fixed_amount"] is None:
        raise ContractError("invalid_plan_fixed_amount", "Fixed mode needs an amount")


class ContractStore:
    """Persists contract fields and the already-notified deadlines."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY_CONTRACTS)
        self.contracts: dict[str, Contract] = {}
        self.notified: set[str] = set()
        # canonical payee name -> series id; keeps ids stable across spellings
        self.aliases: dict[str, str] = {}
        self._aliases_changed = False
        self._loaded = False

    async def async_load(self) -> None:
        try:
            raw = await self._store.async_load()
        except Exception:
            _LOGGER.exception("Contract load failed - starting empty")
            raw = None
        if isinstance(raw, dict):
            for sid, item in (raw.get("contracts") or {}).items():
                if isinstance(item, dict):
                    self.contracts[str(sid)] = Contract.from_dict(str(sid), item)
            self.notified = {str(n) for n in raw.get("notified") or []}
            self.aliases = {
                str(k): str(v) for k, v in (raw.get("aliases") or {}).items() if k and v
            }
        self._loaded = True

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "contracts": {sid: c.to_dict() for sid, c in self.contracts.items()},
                "notified": sorted(self.notified),
                "aliases": dict(sorted(self.aliases.items())),
            }
        )
        self._aliases_changed = False

    def learn_alias(self, key: str, sid: str) -> None:
        """Remember which series id a payee name maps to (names only, no amounts)."""
        if key and self.aliases.get(key) != sid:
            self.aliases[key] = sid
            self._aliases_changed = True

    async def async_save_if_changed(self) -> None:
        """Persist aliases learned during a detection pass."""
        if self._aliases_changed:
            await self.async_save()

    def get(self, sid: str) -> Contract:
        return self.contracts.get(sid) or Contract(series_id=sid)

    def overrides(self) -> dict[str, dict[str, Any]]:
        return {
            sid: {
                "plan_mode": c.plan_mode,
                "plan_fixed_amount": c.plan_fixed_amount,
                "settlements": list(c.settlements or ()),
            }
            for sid, c in self.contracts.items()
            if c.plan_mode or c.settlements
        }


async def async_get_store(hass: HomeAssistant) -> ContractStore:
    """Lazily created, loaded store shared by the API and the daily hook."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    store = domain_data.get(_STORE_KEY)
    if store is None:
        store = ContractStore(hass)
        domain_data[_STORE_KEY] = store
        await store.async_load()
    return store


# ---------------------------------------------------------------------------
# Derivations (pure)
# ---------------------------------------------------------------------------


def _notice_delta_apply(day: date, value: int, unit: str) -> date:
    if unit == "months":
        return add_months(day, -value)
    if unit == "weeks":
        return day - timedelta(weeks=value)
    return day - timedelta(days=value)


def _end_of_month(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def next_notice_deadline(
    start: date, term_months: int, renewal_months: int, notice_value: int, notice_unit: str,
    reference: str, today: date,
) -> tuple[date, date]:
    """Return ``(deadline, effective_end)`` of the next actionable notice."""
    renewal = max(1, renewal_months)
    end = add_months(start, max(term_months, 0)) if term_months else add_months(start, renewal)
    for _ in range(1200):
        effective = _end_of_month(end) if reference == REF_END_OF_MONTH else end
        deadline = _notice_delta_apply(effective, notice_value, notice_unit)
        if deadline >= today:
            return deadline, effective
        end = add_months(end, renewal)
    return deadline, effective


def special_termination_default(series: dict[str, Any]) -> bool:
    """Prefill for the special-termination right after a price increase.

    Looks at the last three payments and three traits: amount, booking day and
    gap. Even payments (at most one trait differs) -> a contractual price that
    changed -> checked. Differing in two or more of the three -> usage-based or
    irregular billing, not a fixed contract price -> unchecked. The single
    price step itself does not count as an amount difference.
    """
    dates = [date.fromisoformat(d) for d in series.get("dates", [])][-3:]
    amounts = [round(abs(a), 2) for a in series.get("amounts", [])][-3:]
    if len(dates) < 3:
        return True
    differing = 0
    if len(set(amounts)) > 2:
        differing += 1
    if max(d.day for d in dates) - min(d.day for d in dates) > 3:
        differing += 1
    gaps = [(dates[i + 1] - dates[i]).days for i in range(2)]
    if abs(gaps[0] - gaps[1]) > 3:
        differing += 1
    return differing < 2


def _owner_of(series: dict[str, Any], contract: Contract) -> str:
    if contract.owner:
        return contract.owner
    if series.get("account_type") == "shared":
        return "shared"
    return str(series.get("account_person") or "")


def build_contracts(
    transactions: list[dict[str, Any]],
    store: ContractStore,
    *,
    today: date | None = None,
    own_names: set[str] | frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Expense series with contract fields and derived deadlines.

    Sorted by next notice deadline (soonest first); contracts without a
    deadline come last. ``own_names`` are the household's account holder
    names (normalised): a payment to one of them is an own transfer the
    chain detector missed, never a contract.
    """
    today = today or date.today()
    series_list = detect_series(
        transactions,
        today=today,
        overrides=store.overrides(),
        aliases=store.aliases,
        known_ids=set(store.contracts),
    )
    out: list[dict[str, Any]] = []
    for s in series_list:
        for key in s.get("alias_keys") or [s["alias_key"]]:
            store.learn_alias(key, s["id"])
        if s["direction"] != "out":
            continue
        if is_own_name(s["creditor"], own_names):
            # usually a savings transfer; a contract word makes it a question (#109)
            if not own_name_contract(s.get("confidence") or {}):
                continue
            conf = s.get("confidence") or {"score": 0, "reasons": []}
            s = {
                **s,
                "candidate": True,
                "confidence": {**conf, "reasons": [REASON_OWN_NAME, *conf["reasons"]]},
            }
        stored = store.contracts.get(s["id"])
        if stored is not None and stored.review == REVIEW_NOT_CONTRACT:
            continue  # "Kein Vertrag": never shown again (#130)
        if s.get("candidate") and stored is not None:
            # confirmed, or edited by the user: a contract, whatever the score says
            s = {**s, "candidate": False}
        out.append(_contract_view(s, store.get(s["id"]), today))
    out.sort(key=lambda c: (c["next_deadline"] is None, c["next_deadline"] or ""))
    return out


def _contract_view(s: dict[str, Any], c: Contract, today: date) -> dict[str, Any]:
    category = c.category or s["category"]
    suggested = s.get("kind_suggested") or KIND_CONTRACT
    kind = c.kind or suggested
    trait = s.get("kind_trait") or ""
    has_notice = kind not in NO_NOTICE_KINDS
    # Kinds without notice keep the contract terms only for a later switch back.
    defaults = kind_defaults(kind, category, trait) or kind_defaults(KIND_CONTRACT, category, trait)

    def eff(name: str) -> Any:
        v = getattr(c, name)
        return defaults[name] if v is None else v

    pc = s["price_change"]
    detected_usage = trait == TRAIT_USAGE_BASED
    usage_based = detected_usage if c.usage_based is None else c.usage_based
    history = s.get("settlements") or []
    exp = (
        expected_settlement(
            history, s.get("advance_at_settlement"), s["last_amount"],
            INTERVALS[s["interval"]][1], today,
        )
        if usage_based
        else None
    )
    # a back-payment adds to the yearly cost, a refund lowers it
    annual_total = round(s["annual_cost"] + (exp["amount"] if exp else 0.0), 2)
    special_default = special_termination_default(s)
    special_checked = special_default if c.special_termination is None else c.special_termination
    deadline = effective = None
    days_left = None
    if has_notice:  # no notice deadline for regular or irregular spending
        start = date.fromisoformat(c.start or s["first_seen"])
        deadline, effective = next_notice_deadline(
            start,
            eff("min_term_months"),
            eff("renewal_months"),
            eff("notice_value"),
            eff("notice_unit"),
            eff("notice_reference"),
            today,
        )
        days_left = (deadline - today).days
    return {
        **s,
        "category": category,
        "kind": kind,
        "kind_suggested": suggested,
        "kind_trait": trait,
        "owner": _owner_of(s, c),
        "contract": {
            "start": c.start,
            "min_term_months": eff("min_term_months"),
            "renewal_months": eff("renewal_months"),
            "notice_value": eff("notice_value"),
            "notice_unit": eff("notice_unit"),
            "notice_reference": eff("notice_reference"),
            "plan_position_id": c.plan_position_id,
            "special_termination": special_checked,
            "special_termination_prefilled": c.special_termination is None,
            "defaults": defaults,
            "defaults_by_kind": {k: kind_defaults(k, category, trait) for k in KINDS},
            "has_notice": has_notice,
            "stored": c.to_dict(),
        },
        "labels": list(c.labels or []),
        "settlement": {
            "usage_based": usage_based,
            "usage_based_detected": detected_usage,
            "history": history,
            "expected": exp,
            "candidates": s.get("settlement_candidates") or [],
        },
        "annual_total": annual_total,
        "next_deadline": deadline.isoformat() if deadline else None,
        "effective_end": effective.isoformat() if effective else None,
        "days_until_deadline": days_left,
        "notice_due_soon": days_left is not None and 0 <= days_left <= NOTICE_EVENT_WINDOW_DAYS,
        "special_termination_available": bool(
            has_notice and pc and pc["increase"] and special_checked
        ),
        "monthly_equivalent": round(s["annual_cost"] / 12, 2),
    }


TOTAL_FIXED = "fixed"
TOTAL_REGULAR = "regular"
_TOTAL_GROUP = {
    KIND_CONTRACT: TOTAL_FIXED,
    KIND_SUBSCRIPTION: TOTAL_FIXED,
    KIND_REGULAR: TOTAL_REGULAR,
    KIND_IRREGULAR: TOTAL_REGULAR,
}


def contract_totals(contracts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Monthly and yearly sums per group (#115).

    ``fixed`` = contracts and subscriptions, ``regular`` = regular and
    irregular spending. Unconfirmed candidates and ended series never count.
    """
    out = {g: {"monthly": 0.0, "yearly": 0.0, "count": 0} for g in (TOTAL_FIXED, TOTAL_REGULAR)}
    for c in contracts:
        if c.get("candidate") or c.get("status") == "ended":
            continue
        group = out[_TOTAL_GROUP.get(c.get("kind") or KIND_CONTRACT, TOTAL_FIXED)]
        yearly = c.get("annual_total", c.get("annual_cost"))
        group["yearly"] = round(group["yearly"] + float(yearly or 0), 2)
        group["count"] += 1
    for group in out.values():
        group["monthly"] = round(group["yearly"] / 12, 2)
    return out


def aggregate_view(item: dict[str, Any]) -> dict[str, Any]:
    """Reduced view for non-admins: no payment history, no amounts per payment."""
    keep = (
        "id",
        "creditor",
        "display_name",
        "interval",
        "status",
        "category",
        "kind",
        "owner",
        "annual_cost",
        "annual_total",
        "monthly_equivalent",
        "next_expected",
        "last_seen",
        "pending_since",
        "next_deadline",
        "effective_end",
        "days_until_deadline",
        "notice_due_soon",
        "special_termination_available",
        "labels",
    )
    return {
        **{k: item[k] for k in keep},
        "candidate": bool(item.get("candidate")),
        "confidence": item.get("confidence"),
    }


def visible_to(item: dict[str, Any], person: str | None) -> bool:
    return item["owner"] == "shared" or (bool(person) and item["owner"] == person)


# ---------------------------------------------------------------------------
# Reserves
# ---------------------------------------------------------------------------


def build_reserves(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    """Monthly reserve for every annual/irregular expense series, plus the
    expected back-payment of a usage-based contract (#116)."""
    items = []
    by_owner: dict[str, float] = {}
    for c in contracts:
        if c["status"] == "ended" or c.get("candidate"):  # no reserve for a guess (#129)
            continue
        exp = (c.get("settlement") or {}).get("expected")
        if exp and exp["monthly_reserve"] > 0:
            items.append(
                {
                    "series_id": c["id"],
                    "type": "settlement",
                    "creditor": c["creditor"],
                    "display_name": c.get("display_name", c["creditor"]),
                    "category": c["category"],
                    "owner": c["owner"],
                    "interval": "yearly",
                    "amount": exp["amount"],
                    "next_due": exp["next_due"],
                    "monthly_reserve": exp["monthly_reserve"],
                    "annual_cost": exp["amount"],
                }
            )
            by_owner[c["owner"]] = round(by_owner.get(c["owner"], 0.0) + exp["monthly_reserve"], 2)
        if c["interval"] not in IRREGULAR_INTERVALS:
            continue
        monthly = round(c["annual_cost"] / 12, 2)
        items.append(
            {
                "series_id": c["id"],
                "creditor": c["creditor"],
                "display_name": c.get("display_name", c["creditor"]),
                "category": c["category"],
                "owner": c["owner"],
                "interval": c["interval"],
                "amount": abs(c["plan_amount"]),
                "next_due": c["next_expected"],
                "monthly_reserve": monthly,
                "annual_cost": c["annual_cost"],
            }
        )
        by_owner[c["owner"]] = round(by_owner.get(c["owner"], 0.0) + monthly, 2)
    items.sort(key=lambda i: i["next_due"])
    return {
        "items": items,
        "by_owner": by_owner,
        "total_monthly": round(sum(by_owner.values()), 2),
    }


# ---------------------------------------------------------------------------
# Notice-due event hook
# ---------------------------------------------------------------------------


async def async_fire_notice_due(
    hass: HomeAssistant,
    transactions: list[dict[str, Any]],
    *,
    today: date | None = None,
    own_names: set[str] | frozenset[str] = frozenset(),
) -> int:
    """Fire ``finance_dashboard_notice_due`` for deadlines within 30 days.

    Once per contract per deadline. Call from the daily refresh path after the
    ledger is updated: ``await async_fire_notice_due(hass, effective_txns)``.
    Cache-only: never talks to the bank. Returns the number of events fired.
    """
    store = await async_get_store(hass)
    fired = 0
    for c in build_contracts(transactions, store, today=today, own_names=own_names):
        if not c["notice_due_soon"] or c["status"] == "ended" or c.get("candidate"):
            continue
        marker = f"{c['id']}|{c['next_deadline']}"
        if marker in store.notified:
            continue
        hass.bus.async_fire(
            EVENT_NOTICE_DUE,
            {
                "series_id": c["id"],
                "creditor": c["creditor"],
                "display_name": c.get("display_name", c["creditor"]),
                "deadline": c["next_deadline"],
                "effective_end": c["effective_end"],
                "days_left": c["days_until_deadline"],
                "owner": c["owner"],
            },
        )
        store.notified.add(marker)
        fired += 1
    if fired:
        # forget markers of deadlines long gone so the set cannot grow forever
        cutoff = (today or date.today()).isoformat()
        store.notified = {m for m in store.notified if m.split("|")[-1] >= cutoff}
        await store.async_save()
    else:
        await store.async_save_if_changed()
    return fired


# ---------------------------------------------------------------------------
# Savings accounts
# ---------------------------------------------------------------------------


def is_own_name(creditor: str, own_names: set[str] | frozenset[str]) -> bool:
    """Every word of an own name appears in the creditor ("Jeremy Tim Treder")."""
    words = set(creditor.replace(",", " ").split())
    return any(name and set(name.split()) <= words for name in own_names)


def own_account_names(accounts: list[dict[str, Any]]) -> frozenset[str]:
    """Normalised account holder names ("Jeremy Treder und X" -> both parts)."""
    names: set[str] = set()
    for acc in accounts or []:
        raw = " ".join(str(acc.get("name") or acc.get("account_name") or "").lower().split())
        for part in raw.replace(" und ", ",").replace(" & ", ",").split(","):
            part = part.strip()
            if len(part.split()) >= 2:  # a full name, never a bare bank or product word
                names.add(part)
    return frozenset(names)


def set_account_savings(manager: Any, key: str, savings: bool) -> bool:
    """Flag/unflag an account as savings account. False when the key is unknown."""
    accounts = [dict(a) for a in manager._accounts]  # noqa: SLF001 - same package
    found = False
    for acc in accounts:
        if account_key(acc) == key:
            acc["savings"] = bool(savings)
            found = True
    if found:
        manager.async_set_accounts(accounts)
    return found

