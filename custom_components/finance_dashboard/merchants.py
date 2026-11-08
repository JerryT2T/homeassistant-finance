"""Merchant normalisation and learned merchant memory.

A bank booking names its counterparty in many shapes: DKB card payments carry
``Globus.Markthalle/Koblenz`` with a remittance ``VISA Debitkartenumsatz vom
27.10.2026``, PayPal prefixes ``PAYPAL...BOOKINGKIT/3060985033``, SumUp
terminals ``SumUp...The.Studio/Koblenz``.  :func:`merchant_key` reduces all of
them to one stable, lowercase key so one answered question teaches every
future (and past) booking of that merchant.

The memory stores only merchant keys, categories and an optional owner plus
bookings' ledger ids and counters -- never amounts, IBANs or dates.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .text_norm import is_processor_only, processor_merchant_text

STORAGE_KEY_MERCHANTS = f"{DOMAIN}_merchants"
STORAGE_VERSION = 1
POINT_EVERY = 7  # answered questions per point (product-concept § Points)
MAX_BOOKING_RULES = 5000

# Payment-processor prefixes that hide the real merchant.
_PROCESSOR_PREFIXES = ("paypal", "pp", "sumup", "sq", "zettle", "payone", "ssp", "lsp")
_LEGAL = {
    "gmbh", "mbh", "se", "ag", "kg", "ohg", "ug", "co", "eg", "ev", "inc",
    "ltd", "llc", "sarl", "bv", "gbr", "kgaa", "und",
}
_NOISE_WORDS = {
    "visa", "debitkartenumsatz", "kartenzahlung", "girocard", "kartenumsatz", "vom",
    "mastercard", "lastschrift", "sepa", "dankt", "danke", "vielen", "online",
    "payment", "zahlung", "debitkarte", "kreditkarte", "karte", "folgenr", "verfalld",
}
_CARD_NOISE = re.compile(
    r"(visa|mastercard|girocard|maestro)?\s*(debit|kredit)?kartenumsatz(\s+vom\s+[\d.]+)?"
    r"|kartenzahlung|\bvom\s+\d{1,2}\.\d{1,2}\.\d{2,4}",
    re.IGNORECASE,
)
_TRANS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _clean(raw: str) -> list[str]:
    """Raw counterparty text -> list of meaningful lowercase tokens."""
    text = _CARD_NOISE.sub(" ", raw.lower()).translate(_TRANS)
    # DKB card creditors: "Name/City" -- the part after the slash is city or a reference.
    text = text.split("/", 1)[0]
    text = re.sub(r"pp\.\d+\.pp", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text).strip()
    tokens = text.split()
    while len(tokens) > 1 and tokens[0] in _PROCESSOR_PREFIXES:
        tokens.pop(0)
    out = []
    for tok in tokens:
        if tok in _LEGAL or tok in _NOISE_WORDS:
            continue
        # Reference numbers: pure digits or long mixed alphanumerics with digits.
        if tok.isdigit() or (len(tok) >= 6 and any(c.isdigit() for c in tok)):
            continue
        out.append(tok)
    return out


def _counterparty(tx: dict[str, Any]) -> str:
    try:
        amount = float((tx.get("transactionAmount") or {}).get("amount", 0) or 0)
    except (TypeError, ValueError):
        amount = 0.0
    first, second = (
        (tx.get("creditorName"), tx.get("debtorName"))
        if amount <= 0
        else (tx.get("debtorName"), tx.get("creditorName"))
    )
    return str(first or second or "")


def _remittance(tx: dict[str, Any]) -> str:
    remit = str(tx.get("remittanceInformationUnstructured") or "")
    if not remit:
        arr = tx.get("remittanceInformationUnstructuredArray") or []
        remit = str(arr[0]) if arr else ""
    return remit


def merchant_key(tx: dict[str, Any]) -> str:
    """Stable merchant key of a transaction ('' when nothing usable).

    A line whose counterparty is a payment processor itself ("PayPal Europe
    S.a r.l. et Cie") takes the merchant from the remittance text; otherwise
    every purchase through that processor would share one key and one answer.
    """
    counterparty = _counterparty(tx)
    if is_processor_only(counterparty):
        merchant = processor_merchant_text(_remittance(tx))
        tokens = _clean(merchant) if merchant else _clean(_remittance(tx))[:3]
        return " ".join(tokens[:4])
    tokens = _clean(counterparty)
    if not tokens:
        tokens = _clean(_remittance(tx))[:3]
    return " ".join(tokens[:4])


def display_name(tx: dict[str, Any]) -> str:
    """Human-readable merchant name (title-cased key)."""
    key = merchant_key(tx)
    return key.title() if key else ""


def week_id(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


class MerchantMemory:
    """Persisted learning: merchant -> category/owner, one-off booking answers."""

    def __init__(self, hass: Any | None = None, store: Any | None = None) -> None:
        self._store = (
            store if store is not None else Store(hass, STORAGE_VERSION, STORAGE_KEY_MERCHANTS)
        )
        self._data: dict[str, Any] = self._empty()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"merchants": {}, "bookings": {}, "answered": 0, "points": 0,
                "week": "", "week_answered": 0,
                # owner decided once for a recurring series: id -> {owner, ledger_ids}
                "series": {},
                # AI tendency per merchant key: "shared" | "personal"
                "tendencies": {},
                # None = the defaults of ownership.DEFAULT_HOUSEHOLD_CATEGORIES
                "household_categories": None,
                # reconciliation review: confirmed group ids, reviewed_at, snapshots
                "review": {}}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self._data = self._empty()
        if isinstance(data, dict):
            for k in self._data:
                if k in data and isinstance(data[k], type(self._data[k])):
                    self._data[k] = data[k]
            hc = data.get("household_categories")
            if isinstance(hc, list):
                self._data["household_categories"] = [str(c) for c in hc]

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    # --- lookups (used inside the categorisation chain) -------------------
    def booking_rule(self, tx: dict[str, Any]) -> dict[str, Any] | None:
        lid = tx.get("_ledger_id")
        return self._data["bookings"].get(lid) if lid else None

    def merchant_rule(self, tx: dict[str, Any]) -> dict[str, Any] | None:
        key = merchant_key(tx)
        return self._data["merchants"].get(key) if key else None

    def resolve(self, tx: dict[str, Any]) -> dict[str, Any] | None:
        """Correction for ``tx``: one-off booking answer beats merchant memory."""
        return self.booking_rule(tx) or self.merchant_rule(tx)

    # --- learning ---------------------------------------------------------
    def learn_merchant(
        self, key: str, category: str, owner: str | None = None, *, source: str | None = None
    ) -> None:
        """Store a merchant rule; ``source="ai"`` marks an AI suggestion.

        A user answer calls this without ``source`` and so always replaces an
        AI entry; the AI never replaces an existing entry (see
        :meth:`learn_ai_merchant`).
        """
        rule: dict[str, Any] = {"category": category}
        if owner:
            rule["owner"] = owner
        if source:
            rule["source"] = source
        # Re-insert so the merchant moves to the end: insertion order is the history order.
        self._data["merchants"].pop(key, None)
        self._data["merchants"][key] = rule

    def learn_ai_merchant(self, key: str, category: str) -> bool:
        """Learn an AI-sourced merchant category unless a rule already exists."""
        existing = self._data["merchants"].get(key)
        if existing is not None:
            if existing.get("category"):
                return False
            # an owner-only rule (a user's ownership answer) gains the AI category
            existing.update(category=category, source="ai")
            return True
        self.learn_merchant(key, category, source="ai")
        return True

    def set_merchant_owner(self, key: str, owner: str | None) -> None:
        """Owner of a merchant ("für alle von X merken"); category/source stay.

        ``None`` removes the owner; a rule left with nothing is dropped.
        """
        rules = self._data["merchants"]
        rule = rules.get(key)
        if owner:
            if rule is None:
                rules[key] = {"category": None, "owner": owner}
            else:
                rule["owner"] = owner
            return
        if rule is not None:
            rule.pop("owner", None)
            if not rule.get("category"):
                rules.pop(key, None)

    def set_booking_owner(self, ledger_id: str, owner: str | None, category: str) -> None:
        """One-off owner of a booking; the booking keeps its current ``category``."""
        bookings = self._data["bookings"]
        if owner:
            rule = bookings.get(ledger_id)
            if rule is None:
                self.learn_booking(ledger_id, category, owner)
            else:
                rule["owner"] = owner
        elif ledger_id in bookings:
            bookings[ledger_id].pop("owner", None)

    def learn_booking(self, ledger_id: str, category: str, owner: str | None = None) -> None:
        bookings = self._data["bookings"]
        if len(bookings) >= MAX_BOOKING_RULES and ledger_id not in bookings:
            bookings.pop(next(iter(bookings)))
        rule: dict[str, Any] = {"category": category}
        if owner:
            rule["owner"] = owner
        bookings[ledger_id] = rule

    def rename_bookings(self, renames: dict[str, str]) -> bool:
        """One-off answers follow a booking whose ledger id changed."""
        bookings = self._data["bookings"]
        moved = [lid for lid in bookings if lid in renames]
        for lid in moved:
            bookings[renames[lid]] = bookings.pop(lid)
        return bool(moved)

    # --- ownership signals (series decision, AI tendency, category default) --
    def learn_series_owner(
        self, series_id: str, owner: str, ledger_ids: list[str] | None = None
    ) -> None:
        """A recurring series decided once: ``owner`` applies to all its bookings.

        ``ledger_ids`` are the series' bookings as ``"<account_key>|<ledger_id>"``
        (what ``recurring`` reports), so variants of the series are reached too.
        """
        self._data["series"][series_id] = {
            "owner": owner,
            "ledger_ids": sorted({str(i) for i in ledger_ids or []})[:2000],
        }

    def forget_series_owner(self, series_id: str) -> bool:
        return self._data["series"].pop(series_id, None) is not None

    def series_owner(self, tx: dict[str, Any], sid: str = "") -> str | None:
        """Decided owner of the series ``tx`` belongs to (by id or by member booking)."""
        series = self._data["series"]
        if not series:
            return None
        if sid and sid in series:
            return series[sid].get("owner") or None
        lid = tx.get("_ledger_id")
        if lid:
            ref = f"{tx.get('_account_key') or ''}|{lid}"
            for rule in series.values():
                if ref in rule.get("ledger_ids", ()):
                    return rule.get("owner") or None
        # a booking not yet in any stored member list: the series of its payee
        from .recurring import series_id

        name = str(tx.get("creditorName") or tx.get("debtorName") or "")
        try:
            negative = float((tx.get("transactionAmount") or {}).get("amount", 0) or 0) < 0
        except (TypeError, ValueError):
            return None
        rule = series.get(series_id(name, negative)) if name else None
        return (rule or {}).get("owner") or None

    def series_decisions(self) -> dict[str, dict[str, Any]]:
        return dict(self._data["series"])

    def learn_tendency(self, key: str, tendency: str) -> bool:
        if tendency not in ("shared", "personal") or not key:
            return False
        if self._data["tendencies"].get(key) == tendency:
            return False
        self._data["tendencies"][key] = tendency
        return True

    def tendency(self, tx: dict[str, Any]) -> str | None:
        key = merchant_key(tx)
        return self._data["tendencies"].get(key) if key else None

    def household_categories(self) -> tuple[str, ...]:
        from .ownership import DEFAULT_HOUSEHOLD_CATEGORIES

        cats = self._data["household_categories"]
        return tuple(cats) if cats is not None else DEFAULT_HOUSEHOLD_CATEGORIES

    def set_household_categories(self, categories: list[str] | None) -> None:
        """``None`` restores the defaults."""
        self._data["household_categories"] = None if categories is None else list(categories)

    def review_state(self) -> dict[str, Any]:
        """The reconciliation review's persisted state (live dict)."""
        return self._data["review"]

    def forget_merchant(self, key: str) -> bool:
        return self._data["merchants"].pop(key, None) is not None

    def record_answer(self, today: date) -> bool:
        """Count one answered question; True when it earns a point."""
        wid = week_id(today)
        if self._data["week"] != wid:
            self._data["week"], self._data["week_answered"] = wid, 0
        self._data["answered"] += 1
        self._data["week_answered"] += 1
        if self._data["answered"] % POINT_EVERY == 0:
            self._data["points"] += 1
            return True
        return False

    def week_answered(self, today: date) -> int:
        return self._data["week_answered"] if self._data["week"] == week_id(today) else 0

    @property
    def answered(self) -> int:
        return int(self._data["answered"])

    @property
    def points(self) -> int:
        return int(self._data["points"])

    def known_merchants(self) -> dict[str, dict[str, Any]]:
        return dict(self._data["merchants"])

    def history(self, limit: int = 500) -> dict[str, Any]:
        """Learned merchant categories, newest first, plus per-source counts."""
        merchants = self._data["merchants"]
        items = [
            {
                "merchant": key,
                "category": rule.get("category"),
                "owner": rule.get("owner"),
                "source": "ai" if rule.get("source") == "ai" else "user",
            }
            for key, rule in reversed(merchants.items())
        ]
        ai = sum(1 for i in items if i["source"] == "ai")
        return {
            "items": items[:limit],
            "total": len(items),
            "by_user": len(items) - ai,
            "by_ai": ai,
            "bookings": len(self._data["bookings"]),
        }
