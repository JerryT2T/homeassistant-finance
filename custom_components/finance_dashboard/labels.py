"""Labels: non-exclusive tags across categories (#113).

A category is exclusive (one life area per euro); a label is not: "Energie",
"Erstattungsfähig" or "Beruflich" cut across areas. Labels live in three places:

- the **catalogue**: the starter labels plus the household's own ones,
- a **contract** (``Contract.labels``): every booking of its series inherits
  them, together with the contract's category, at read time - nothing is
  copied per booking, so fixing the contract fixes all its bookings,
- a **booking** (by ``_ledger_id``): extra labels of its own.

Automatic labels (payment channel, price increase, special termination) are
computed on every read and cannot be edited. Label names are the user's own
text and never leave HA.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION

STORAGE_KEY_LABELS = f"{DOMAIN}_labels"
MAX_CUSTOM = 100
MAX_PER_ITEM = 20
MAX_NAME = 40
_SLUG = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# Starter catalogue; names are translated in the frontend (label.<id>).
STARTER_LABELS: tuple[str, ...] = (
    "energy",
    "communication",
    "streaming_media",
    "software_cloud_ai",
    "insurance",
    "credit_rate",
    "fees_interest",
    "membership",
    "settlement_refund",
    "refundable",
    "business_expense",
    "household_service",
    "family_child",
    "optimizable",
    "taxes_levies",
)

AUTO_PAYPAL = "auto_paypal"
AUTO_BNPL = "auto_bnpl"
AUTO_CARD = "auto_card"
AUTO_DIRECT_DEBIT = "auto_direct_debit"
AUTO_PRICE_INCREASED = "auto_price_increased"
AUTO_SPECIAL_TERMINATION = "auto_special_termination"
AUTO_LABELS: tuple[str, ...] = (
    AUTO_PAYPAL,
    AUTO_BNPL,
    AUTO_CARD,
    AUTO_DIRECT_DEBIT,
    AUTO_PRICE_INCREASED,
    AUTO_SPECIAL_TERMINATION,
)

_PAYPAL = re.compile(r"paypal", re.IGNORECASE)
_BNPL = re.compile(r"\b(klarna|afterpay|ratepay|riverty|scalapay|paypal ratenzahlung"
                   r"|später bezahlen|spaeter bezahlen)\b", re.IGNORECASE)
_CARD = re.compile(
    r"\b(visa ?(debit|card|karte)|mastercard|maestro|debitkarte|kreditkarte|girocard|ec[- ]?karte"
    r"|kartenzahlung|apple ?pay|google ?pay|card payment)\b",
    re.IGNORECASE,
)
_DIRECT_DEBIT = re.compile(r"\b(lastschrift|sepa[- ]?basis\w*|mandat\w*|mref|direct debit)\b",
                           re.IGNORECASE)


class LabelError(ValueError):
    """Invalid label request; ``code`` goes to the API response."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


def _text(txn: dict[str, Any]) -> str:
    parts = [
        txn.get("remittanceInformationUnstructured") or "",
        " ".join(str(a) for a in txn.get("remittanceInformationUnstructuredArray") or []),
        txn.get("creditorName") or "",
        txn.get("debtorName") or "",
        txn.get("bankTransactionCode") or "",
        txn.get("proprietaryBankTransactionCode") or "",
    ]
    return " ".join(str(p) for p in parts if p)


def booking_key(txn: dict[str, Any]) -> str | None:
    """Stable booking key: the ledger id is unique per account only (QA #113)."""
    lid = txn.get("_ledger_id")
    return f"{txn.get('_account_key') or ''}|{lid}" if lid else None


def booking_auto_labels(txn: dict[str, Any]) -> list[str]:
    """Payment channel of one booking; at most one, most specific first."""
    text = _text(txn)
    if _BNPL.search(text):
        return [AUTO_BNPL]
    if _PAYPAL.search(text):
        return [AUTO_PAYPAL]
    if _CARD.search(text):
        return [AUTO_CARD]
    if _DIRECT_DEBIT.search(text):
        return [AUTO_DIRECT_DEBIT]
    return []


def contract_auto_labels(item: dict[str, Any]) -> list[str]:
    """Automatic labels of a contract view (``contracts._contract_view``)."""
    out = []
    if (item.get("price_change") or {}).get("increase"):
        out.append(AUTO_PRICE_INCREASED)
    if item.get("special_termination_available"):
        out.append(AUTO_SPECIAL_TERMINATION)
    return out


def slugify(name: str) -> str:
    """A label id from a user-given name ("Kita & Schule" -> "kita_schule")."""
    text = unicodedata.normalize("NFKD", name.lower().replace("ß", "ss"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if not text or not text[0].isalpha():
        text = "l_" + text
    return text[:MAX_NAME]


def clean_ids(value: Any, known: set[str] | frozenset[str] | None = None) -> list[str]:
    """Validated, de-duplicated label ids; raises ``LabelError``."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_PER_ITEM:
        raise LabelError("invalid_labels", f"labels must be a list of at most {MAX_PER_ITEM}")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _SLUG.match(item) or item in AUTO_LABELS:
            raise LabelError("invalid_labels", "label ids are slugs; automatic labels are read-only")
        if known is not None and item not in known:
            raise LabelError("unknown_label", "label is not in the catalogue")
        if item not in out:
            out.append(item)
    return out


class LabelStore:
    """Custom labels and per-booking labels (``.storage/finance_dashboard_labels``)."""

    def __init__(self, hass: HomeAssistant | None, store: Any | None = None) -> None:
        self._store = store if store is not None else Store(hass, STORAGE_VERSION, STORAGE_KEY_LABELS)
        self.custom: dict[str, str] = {}
        self.bookings: dict[str, list[str]] = {}

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        raw = raw if isinstance(raw, dict) else {}
        custom = raw.get("custom") if isinstance(raw.get("custom"), dict) else {}
        self.custom = {
            k: str(v)[:MAX_NAME] for k, v in custom.items() if isinstance(k, str) and _SLUG.match(k)
        }
        bookings = raw.get("bookings") if isinstance(raw.get("bookings"), dict) else {}
        self.bookings = {
            str(lid): [i for i in ids if isinstance(i, str) and _SLUG.match(i)][:MAX_PER_ITEM]
            for lid, ids in bookings.items()
            if isinstance(ids, list) and ids
        }

    async def async_save(self) -> None:
        await self._store.async_save({"custom": self.custom, "bookings": self.bookings})

    # --- catalogue --------------------------------------------------------
    def known(self) -> frozenset[str]:
        return frozenset((*STARTER_LABELS, *self.custom))

    def catalogue(self) -> list[dict[str, Any]]:
        starter = [{"id": i, "name": None, "kind": "starter"} for i in STARTER_LABELS]
        custom = [{"id": i, "name": n, "kind": "custom"} for i, n in sorted(self.custom.items())]
        auto = [{"id": i, "name": None, "kind": "auto"} for i in AUTO_LABELS]
        return starter + custom + auto

    def add(self, name: Any) -> str:
        name = name.strip() if isinstance(name, str) else ""
        if not name or len(name) > MAX_NAME:
            raise LabelError("invalid_name", f"name must be 1-{MAX_NAME} characters")
        if len(self.custom) >= MAX_CUSTOM:
            raise LabelError("too_many_labels", f"at most {MAX_CUSTOM} own labels")
        base = slugify(name)
        lid, n = base, 2
        while lid in self.known() or lid in AUTO_LABELS:
            lid = f"{base[: MAX_NAME - 3]}_{n}"
            n += 1
        self.custom[lid] = name
        return lid

    def rename(self, lid: str, name: Any) -> None:
        if lid not in self.custom:
            raise LabelError("unknown_label", "only own labels can be renamed")
        name = name.strip() if isinstance(name, str) else ""
        if not name or len(name) > MAX_NAME:
            raise LabelError("invalid_name", f"name must be 1-{MAX_NAME} characters")
        self.custom[lid] = name

    def remove(self, lid: str) -> None:
        """Delete an own label and drop it from every booking."""
        if lid not in self.custom:
            raise LabelError("unknown_label", "only own labels can be deleted")
        del self.custom[lid]
        for key in list(self.bookings):
            kept = [i for i in self.bookings[key] if i != lid]
            if kept:
                self.bookings[key] = kept
            else:
                del self.bookings[key]

    # --- bookings ---------------------------------------------------------
    def set_booking(self, ledger_id: str, ids: Any) -> list[str]:
        if not isinstance(ledger_id, str) or not ledger_id or len(ledger_id) > 200:
            raise LabelError("invalid_id", "unknown booking")
        clean = clean_ids(ids, self.known())
        if clean:
            self.bookings[ledger_id] = clean
        else:
            self.bookings.pop(ledger_id, None)
        return clean


async def async_get_label_store(hass: HomeAssistant) -> LabelStore:
    """The loaded label store, cached in ``hass.data``."""
    data = hass.data.setdefault(DOMAIN, {})
    store = data.get("_label_store")
    if store is None:
        store = LabelStore(hass)
        await store.async_load()
        data["_label_store"] = store
    return store


def resolve_bookings(
    transactions: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
    booking_labels: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    """Per ledger id: the contract it belongs to and what it inherits.

    ``contracts`` are contract views (``build_contracts``) carrying
    ``ledger_ids`` (booking keys, see ``booking_key``). A booking of a contract takes the contract's category
    (``category_source = "contract"``) and its labels as ``inherited``;
    its own labels stay separate, the automatic channel label is added.
    """
    by_ledger: dict[str, dict[str, Any]] = {}
    for item in contracts:
        if item.get("candidate"):
            continue  # an uncertain detection never passes anything on
        stored = (item.get("contract") or {}).get("stored") or {}
        for lid in item.get("ledger_ids") or []:
            by_ledger[lid] = {
                "contract_id": item["id"],
                "contract_name": item.get("display_name") or item.get("creditor"),
                "category": item.get("category"),
                "inherited": list(stored.get("labels") or []),
            }
    out: dict[str, dict[str, Any]] = {}
    for txn in transactions:
        lid = booking_key(txn)
        if not lid:
            continue
        link = by_ledger.get(lid)
        out[lid] = {
            "contract_id": link["contract_id"] if link else None,
            "contract_name": link["contract_name"] if link else None,
            "category": link["category"] if link else txn.get("category", "other"),
            "category_source": "contract" if link else "own",
            "labels_inherited": link["inherited"] if link else [],
            "labels_own": list(booking_labels.get(lid) or []),
            "labels_auto": booking_auto_labels(txn),
        }
    return out
