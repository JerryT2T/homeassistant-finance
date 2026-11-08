"""Two-layer, encrypted data storage.

* **Raw layer** (:class:`RawArchive`) — every bank response, unaltered, as an
  immutable snapshot.  Chunked one Store per month so no single file grows
  without bound; pruned by retention on every write.  It is the audit trail
  and the source for re-deriving anything later.
* **Ledger layer** (:class:`Ledger`) — the processed, deduplicated
  per-account transaction list and balance time series.  Categories, monthly
  summaries and household splits are *derived* from it and never stored here.

Both layers live in :class:`EncryptedStore` files: HA's atomic ``Store`` with
the payload Fernet-encrypted by the credential manager's key, so financial
data is genuinely encrypted at rest.  Every store is versioned
(``version`` / ``minor_version``) with an ``async_migrate_func`` hook.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.helpers.storage import Store

from .tx_dates import (
    effective_date_str,
    effective_day,
    fingerprint_date,
    only_transaction_date,
)
from .const import (
    DEFAULT_RAW_RETENTION_DAYS,
    LEDGER_STORAGE_MINOR_VERSION,
    LEDGER_STORAGE_VERSION,
    RAW_STORAGE_MINOR_VERSION,
    RAW_STORAGE_VERSION,
    STORAGE_KEY_LEDGER,
    STORAGE_KEY_RAW_INDEX,
    STORAGE_KEY_RAW_PREFIX,
)

_LOGGER = logging.getLogger(__name__)

MigrateFunc = Callable[[int, int, Any], Awaitable[Any]]

# Keys that are derived (from rules / user settings), never ledger data.
_DERIVED_PREFIXES = ("_account_", "_transfer", "_refund_")
_DERIVED_KEYS = ("category", "_own_category", "_owner_override", "_owner_scope", "_series_owner",
                 "_ai_tendency", "_household_categories", "_net_expense")
PENDING_MATCH_DAYS = 3
SHORT_ANSWER_DAYS = 31
_STRING_FIELDS = (
    "transactionId",
    "bookingDate",
    "bookingDateTime",
    "valueDate",
    "transactionDate",
    "creditorName",
    "debtorName",
    "remittanceInformationUnstructured",
)


class StorageDecryptError(Exception):
    """An encrypted store could not be decrypted (key lost or file damaged)."""


# ---------------------------------------------------------------------------
# Encrypted, versioned Store
# ---------------------------------------------------------------------------


class _EnvelopeStore(Store):
    """HA Store whose payload is ``{"enc": <fernet token>}``.

    HA calls ``_async_migrate_func`` when the on-disk version differs; the
    override decrypts, hands the plaintext to the user's migrate function and
    re-encrypts, so migrations never see ciphertext.
    """

    def __init__(self, hass, owner: EncryptedStore, key, version, minor_version) -> None:
        super().__init__(hass, version, key, minor_version=minor_version)
        self._owner = owner

    async def _async_migrate_func(self, old_major_version, old_minor_version, old_data):
        return await self._owner.async_migrate_envelope(old_major_version, old_minor_version, old_data)


class EncryptedStore:
    """Versioned Store whose content is Fernet-encrypted."""

    def __init__(
        self,
        hass,
        cred,
        key: str,
        version: int,
        minor_version: int = 1,
        migrate: MigrateFunc | None = None,
    ) -> None:
        self._cred = cred
        self._key = key
        self._migrate = migrate
        self._store = _EnvelopeStore(hass, self, key, version, minor_version)

    @property
    def key(self) -> str:
        return self._key

    async def async_migrate_envelope(self, old_major: int, old_minor: int, envelope: Any) -> Any:
        """Migrate an old on-disk envelope (decrypt → migrate → encrypt)."""
        payload = self._decrypt(envelope)
        if self._migrate is not None:
            payload = await self._migrate(old_major, old_minor, payload)
        return {"enc": self._cred.encrypt_json(payload)}

    def _decrypt(self, envelope: Any) -> Any:
        if not isinstance(envelope, dict) or "enc" not in envelope:
            raise StorageDecryptError(f"{self._key}: not an encrypted envelope")
        try:
            return self._cred.decrypt_json(envelope["enc"])
        except Exception as exc:
            raise StorageDecryptError(f"{self._key}: {type(exc).__name__}") from None

    async def async_load(self) -> Any | None:
        """Load and decrypt; None when the file does not exist."""
        envelope = await self._store.async_load()
        if envelope is None:
            return None
        return self._decrypt(envelope)

    async def async_save(self, payload: Any) -> None:
        """Encrypt and write atomically (HA Store)."""
        await self._store.async_save({"enc": self._cred.encrypt_json(payload)})

    async def async_remove(self) -> None:
        await self._store.async_remove()


# ---------------------------------------------------------------------------
# Transaction identity
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _counterparty(tx: dict[str, Any]) -> str:
    return _norm(tx.get("creditorName") or tx.get("debtorName"))


def fingerprint(tx: dict[str, Any], *, with_date: bool = True) -> str:
    """Stable hash of what makes a transaction itself.

    (date, amount, currency, counterparty, remittance).  Without the date it
    is the key pending→booked matching uses, since a pending entry's date is a
    guess.
    """
    amount = tx.get("transactionAmount") or {}
    try:
        amt = f"{float(amount.get('amount', 0)):.2f}"
    except (TypeError, ValueError):
        amt = "0.00"
    parts = [
        fingerprint_date(tx) if with_date else "",
        amt,
        _norm(amount.get("currency")),
        _counterparty(tx),
        _norm(tx.get("remittanceInformationUnstructured")),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _parse_date(value: Any):
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (TypeError, ValueError):
        return None


def is_pending_match(
    pending: dict[str, Any], booked: dict[str, Any], *, today: date | None = None
) -> bool:
    """Whether a booked transaction is the settled form of a pending one.

    Same fingerprint minus date, dates within ±3 days.  A pending row without
    any date is dated by the fetch (``today``): it must not swallow a booked
    row of the same payee and amount from months ago.
    """
    if fingerprint(pending, with_date=False) != fingerprint(booked, with_date=False):
        return False
    d1 = effective_day(pending) or today
    d2 = effective_day(booked)
    if d1 is None or d2 is None:
        return False
    return abs((d1 - d2).days) <= PENDING_MATCH_DAYS


def reported_from(date_from: str | None, booked: list[dict[str, Any]]) -> str | None:
    """Start of the span a fetch is evidence for.

    The requested ``date_from`` — unless the earliest booked date the bank
    returned lies more than ``SHORT_ANSWER_DAYS`` later, which means the bank
    served less history than asked (a ten-year request answered with 90
    days).  Then the span starts at that earliest date, so the years before
    are not mistaken for reversals.  An ordinary incremental window keeps its
    full span and with it reversal detection.  An empty answer covers the
    whole requested window.
    """
    dates = [d for t in booked if (d := effective_date_str(t))]
    if not dates:
        return date_from
    earliest = min(dates)
    if not date_from:
        return earliest
    start, first = _parse_date(date_from), _parse_date(earliest)
    if start and first and (first - start).days > SHORT_ANSWER_DAYS:
        return earliest
    return date_from


def strip_derived(tx: dict[str, Any]) -> dict[str, Any]:
    """Copy of *tx* without derived fields (category, account tags, transfer flags)."""
    return {
        k: v
        for k, v in tx.items()
        if k not in _DERIVED_KEYS and not k.startswith(_DERIVED_PREFIXES)
    }


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


async def _migrate_ledger(old_major: int, old_minor: int, payload: Any) -> Any:
    """Ledger schema migrations.  v1 is the first schema — nothing to do yet."""
    return payload


IMPORT_MATCH_DAYS = 2


def _amount_cents(tx: dict[str, Any]) -> int | None:
    try:
        return round(float((tx.get("transactionAmount") or {}).get("amount")) * 100)
    except (TypeError, ValueError):
        return None


def _covered_imports(txs: list[dict[str, Any]]) -> set[int]:
    """``id()`` of imported rows that a bank row on the same account covers."""
    bank: dict[tuple[int, str], list[Any]] = {}
    for t in txs:
        if t.get("_source") or t.get("_status") != "booked":
            continue
        cents, party, day = _amount_cents(t), _counterparty(t), effective_day(t)
        if cents is not None and party and day:
            bank.setdefault((cents, party), []).append(day)
    gone: set[int] = set()
    for t in txs:
        if not t.get("_source"):
            continue
        cents, party, day = _amount_cents(t), _counterparty(t), effective_day(t)
        days = bank.get((cents, party)) if cents is not None and party and day else None
        if not days:
            continue
        hit = next((i for i, d in enumerate(days) if abs((d - day).days) <= IMPORT_MATCH_DAYS), None)
        if hit is not None:
            days.pop(hit)
            gone.add(id(t))
    return gone


class Ledger:
    """Per-account deduplicated transactions + balance time series.

    ``data`` layout::

        {"accounts": {account_key: {"transactions": [tx...],
                                    "balances": [point...]}},
         "meta": {...}}   # refresh stamps + per-bank budget state
    """

    def __init__(self, store: EncryptedStore | None) -> None:
        self._store = store
        self.data: dict[str, Any] = {"accounts": {}, "meta": {}}

    @classmethod
    def create(cls, cred) -> Ledger:
        return cls(
            cred.encrypted_store(
                STORAGE_KEY_LEDGER,
                LEDGER_STORAGE_VERSION,
                LEDGER_STORAGE_MINOR_VERSION,
                _migrate_ledger,
            )
        )

    async def async_load(self) -> bool:
        """Load from disk.  Returns False when no ledger exists yet."""
        loaded = await self._store.async_load() if self._store else None
        if not isinstance(loaded, dict):
            return False
        self.data = {
            "accounts": dict(loaded.get("accounts") or {}),
            "meta": dict(loaded.get("meta") or {}),
        }
        # Ledgers written before PROCESSING_VERSION 2 can hold explicit nulls
        # where every consumer expects a string.
        for acct in self.data["accounts"].values():
            for tx in acct.get("transactions") or []:
                for field in _STRING_FIELDS:
                    if field in tx and tx[field] is None:
                        tx[field] = ""
        return True

    async def async_save(self) -> None:
        if self._store:
            await self._store.async_save(self.data)

    # -- accessors ---------------------------------------------------------

    @property
    def meta(self) -> dict[str, Any]:
        return self.data.setdefault("meta", {})

    def account_keys(self) -> list[str]:
        return list(self.data.get("accounts", {}))

    def _acct(self, key: str) -> dict[str, Any]:
        return self.data.setdefault("accounts", {}).setdefault(
            key, {"transactions": [], "balances": []}
        )

    def transactions(self, key: str) -> list[dict[str, Any]]:
        """Copies of an account's ledger transactions (no derived fields)."""
        return [dict(t) for t in self.data.get("accounts", {}).get(key, {}).get("transactions", [])]

    def balance_series(self, key: str) -> list[dict[str, Any]]:
        return [dict(p) for p in self.data.get("accounts", {}).get(key, {}).get("balances", [])]

    def last_booked_date(self, key: str) -> str | None:
        """Latest booked date the bank delivered (imported history does not count)."""
        # A value date in the future must not push the next fetch window past it.
        today = datetime.now(UTC).date().isoformat()
        dates = [d for d in self._bank_dates(key) if d <= today]
        return max(dates) if dates else None

    def _bank_dates(self, key: str) -> list[str]:
        return [
            day
            for t in self.data.get("accounts", {}).get(key, {}).get("transactions", [])
            if t.get("_status") == "booked" and not t.get("_source") and (day := effective_date_str(t))
        ]

    # -- mutation ----------------------------------------------------------

    def import_legacy(self, key: str, txs: list[dict[str, Any]]) -> None:
        """Seed an account from a legacy plaintext cache (already tagged)."""
        booked = [t for t in txs if t.get("_status", "booked") == "booked"]
        pending = [t for t in txs if t.get("_status") == "pending"]
        for t in booked:
            t.setdefault("_status", "booked")
        self.ingest(key, booked, pending, date_from=None, truncated=True)

    def ingest(
        self,
        key: str,
        booked: list[dict[str, Any]],
        pending: list[dict[str, Any]],
        *,
        date_from: str | None,
        truncated: bool = False,
    ) -> list[dict[str, Any]]:
        """Merge a fetched window into an account's ledger.

        * Fresh data is authoritative inside the span the bank actually
          reported (:func:`reported_from`): a cached booked transaction there
          that the bank no longer reports is dropped (reversal) — unless the
          fetch was truncated, when absence proves nothing.  A bank that
          answers a ten-year request with 90 days must not erase older
          history.
        * Pending entries are replaced wholesale by the fresh pending set and
          by their booked counterpart (``is_pending_match``).
        * IDs: the bank's ``transactionId`` when present, else a fingerprint;
          identical fingerprints inside one batch get an occurrence suffix so
          two genuine same-day same-amount payments are not collapsed.

        Returns the list of newly added booked transactions.
        """
        acct = self._acct(key)
        existing = {t["_ledger_id"]: t for t in acct["transactions"] if t.get("_ledger_id")}

        def prepare(batch: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
            seen: dict[str, int] = {}
            ids: set[str] = set()
            out = []
            for raw in batch:
                tx = strip_derived(raw)
                tx["_status"] = status
                tid = str(tx.get("transactionId") or "")
                if tid:
                    lid = f"id:{tid}"
                else:
                    fp = fingerprint(tx)
                    n = seen.get(fp, 0)
                    seen[fp] = n + 1
                    lid = f"fp:{fp}" + (f"#{n}" if n else "")
                if lid in ids:
                    continue  # duplicate id inside one batch
                ids.add(lid)
                tx["_ledger_id"] = lid
                out.append(tx)
            return out

        fresh_booked = prepare(booked, "booked")
        fresh_pending = prepare(pending, "pending")
        fresh_ids = {t["_ledger_id"] for t in fresh_booked}
        authoritative_from = reported_from(date_from, fresh_booked)
        earliest_fresh = min((d for t in fresh_booked if (d := effective_date_str(t))), default="")

        kept: list[dict[str, Any]] = []
        for tx in acct["transactions"]:
            if tx.get("_status") != "booked":
                continue  # pending is volatile — replaced below
            if tx["_ledger_id"] in fresh_ids:
                continue
            if tx.get("_source"):
                kept.append(tx)  # imported history is never a reversal candidate (#121)
                continue
            bdate = effective_date_str(tx)
            if only_transaction_date(tx) and (not earliest_fresh or bdate < earliest_fresh):
                kept.append(tx)  # such a source answers thinly: absence below its answer is no proof
                continue
            if not truncated and authoritative_from and bdate and bdate >= authoritative_from:
                continue
            kept.append(tx)

        new = [t for t in fresh_booked if t["_ledger_id"] not in existing]
        fetched_on = datetime.now(UTC).date()
        fresh_pending = [
            p
            for p in fresh_pending
            if not any(is_pending_match(p, b, today=fetched_on) for b in fresh_booked)
        ]
        merged = kept + fresh_booked + fresh_pending
        merged.sort(key=effective_date_str, reverse=True)
        acct["transactions"] = merged
        self.reconcile_imports(key)
        return new

    # -- imported history (#121) -------------------------------------------

    def import_batches(self) -> list[dict[str, Any]]:
        """Imported batches, newest first (ids, dates, counts - no booking values)."""
        return [dict(b) for b in reversed(self.meta.get("import_batches") or [])]

    def add_import_batch(
        self, key: str, batch_id: str, txs: list[dict[str, Any]], info: dict[str, Any]
    ) -> int:
        """Add imported bookings tagged ``_source = import:<id>`` as one batch.

        The rows are plain ledger entries, so detection treats them like bank
        rows.  They never replace a row the ledger already has (``_ledger_id``
        wins), and a later bank fetch that covers their span supersedes them
        through the normal ``ingest`` rules.  Returns how many were added.
        """
        acct = self._acct(key)
        have = {t.get("_ledger_id") for t in acct["transactions"]}
        fresh = [t for t in txs if t.get("_ledger_id") not in have]
        acct["transactions"] = sorted(
            acct["transactions"] + fresh, key=effective_date_str, reverse=True
        )
        batches = self.meta.setdefault("import_batches", [])
        batches.append({**info, "id": batch_id, "account_key": key, "count": len(fresh)})
        return len(fresh)

    def reconcile_imports(self, key: str | None = None) -> int:
        """Bank wins after the fact: drop imported rows a bank row now covers.

        A bank row covers an imported one on the same account when the booking
        date is within ``IMPORT_MATCH_DAYS``, the amount is equal and the
        normalised counterparty is the same (one bank row covers one imported
        row).  The batch keeps its books straight: ``count`` falls and
        ``removed_by_bank`` rises.  Returns how many imported rows were dropped.
        """
        dropped_total = 0
        accounts = self.data.get("accounts", {})
        for akey in [key] if key else list(accounts):
            acct = accounts.get(akey)
            if not acct:
                continue
            txs = acct.get("transactions") or []
            gone = _covered_imports(txs)
            if not gone:
                continue
            acct["transactions"] = [t for t in txs if id(t) not in gone]
            by_batch: dict[str, int] = {}
            for t in txs:
                if id(t) in gone:
                    batch = str(t["_source"]).split(":", 1)[1]
                    by_batch[batch] = by_batch.get(batch, 0) + 1
            for b in self.meta.get("import_batches") or []:
                n = by_batch.get(b.get("id"), 0)
                if n:
                    b["count"] = max(0, int(b.get("count") or 0) - n)
                    b["removed_by_bank"] = int(b.get("removed_by_bank") or 0) + n
            dropped_total += len(gone)
        return dropped_total

    def remove_import_batch(self, batch_id: str) -> int:
        """Undo one import as a whole.  Returns how many bookings were removed."""
        tag = f"import:{batch_id}"
        removed = 0
        for acct in self.data.get("accounts", {}).values():
            keep = [t for t in acct.get("transactions") or [] if t.get("_source") != tag]
            removed += len(acct.get("transactions") or []) - len(keep)
            acct["transactions"] = keep
        self.meta["import_batches"] = [
            b for b in self.meta.get("import_batches") or [] if b.get("id") != batch_id
        ]
        return removed

    def migrate_fingerprint_ids(self) -> dict[str, dict[str, str]]:
        """Give rows with only a transaction date their new identity (#168).

        Their fingerprint used to carry no date at all, so equal payments
        collapsed into one row.  ``{account key: {old id: new id}}``; whatever
        stores a booking by its ledger id follows the map, or a one-off answer
        on such a row would be lost.  Idempotent: a new id maps to itself and
        is not reported.
        """
        renames: dict[str, dict[str, str]] = {}
        for key, acct in self.data.get("accounts", {}).items():
            txs = acct.get("transactions") or []
            taken = {t.get("_ledger_id") for t in txs}
            for tx in txs:
                lid = str(tx.get("_ledger_id") or "")
                if not lid.startswith("fp:") or tx.get("transactionId") or tx.get("_source"):
                    continue
                if not only_transaction_date(tx):
                    continue
                base = f"fp:{fingerprint(tx)}"
                if lid == base or lid.startswith(f"{base}#"):
                    continue
                new, n = base, 0
                while new in taken:
                    n += 1
                    new = f"{base}#{n}"
                taken.add(new)
                renames.setdefault(key, {})[lid] = new
                tx["_ledger_id"] = new
        return renames

    def first_booked_date(self, key: str) -> str | None:
        """Earliest booked date the bank delivered (imported history does not count)."""
        dates = self._bank_dates(key)
        return min(dates) if dates else None

    def add_balances(self, key: str, balances: list[dict[str, Any]], at: str) -> None:
        """Append one point per balance type for this fetch.

        The series is lifelong: no retention, no cap.  A few fetches a day
        add a few thousand small points per year.
        """
        acct = self._acct(key)
        series = acct["balances"]
        for bal in balances:
            amount = bal.get("balanceAmount") or {}
            series.append(
                {
                    "at": at,
                    "type": bal.get("balanceType", ""),
                    "amount": amount.get("amount"),
                    "currency": amount.get("currency", ""),
                }
            )


# ---------------------------------------------------------------------------
# Raw archive
# ---------------------------------------------------------------------------


async def _migrate_raw(old_major: int, old_minor: int, payload: Any) -> Any:
    return payload


class RawArchive:
    """Immutable snapshots of bank responses, one encrypted Store per month.

    ``retention_days == 0`` keeps everything forever (the default): the
    archive is what the ledger is rebuilt from when processing changes.
    """

    def __init__(self, hass, cred, retention_days: int = DEFAULT_RAW_RETENTION_DAYS) -> None:
        self._hass = hass
        self._cred = cred
        self.retention_days = max(int(retention_days or 0), 0)
        self._pending: list[dict[str, Any]] = []
        self._stores: dict[str, EncryptedStore] = {}
        from homeassistant.helpers.storage import Store as _Store

        self._index_store = _Store(hass, 1, STORAGE_KEY_RAW_INDEX)

    def _month_store(self, month: str) -> EncryptedStore:
        if month not in self._stores:
            self._stores[month] = EncryptedStore(
                self._hass,
                self._cred,
                f"{STORAGE_KEY_RAW_PREFIX}{month}",
                RAW_STORAGE_VERSION,
                RAW_STORAGE_MINOR_VERSION,
                _migrate_raw,
            )
        return self._stores[month]

    @staticmethod
    def make_snapshot(
        *,
        bank: str,
        account: str,
        kind: str,
        attended: bool,
        http_status: int,
        response: Any,
        fetched_at: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One archived response.

        ``meta`` carries what a replay needs beyond the body: ``account_key``
        (the uid changes per bank session), ``fetch_id`` (groups the pages
        of one transaction fetch), ``date_from`` / ``date_to``.  A
        ``transactions_window`` snapshot closes a fetch with ``truncated``.
        """
        snap = {
            "fetched_at": fetched_at or datetime.now(UTC).isoformat(),
            "bank": bank,
            "account": account,
            "kind": kind,
            "attended": attended,
            "http_status": http_status,
            "response": response,
        }
        if meta:
            snap["meta"] = dict(meta)
        return snap

    def record(self, snapshot: dict[str, Any]) -> None:
        """Queue a snapshot; written by :meth:`async_flush` at end of a refresh."""
        self._pending.append(snapshot)

    async def async_flush(self, now: datetime | None = None) -> int:
        """Write queued snapshots into their month files and prune. Returns count."""
        if not self._pending:
            await self.async_prune(now)
            return 0
        batch, self._pending = self._pending, []
        by_month: dict[str, list[dict[str, Any]]] = {}
        for snap in batch:
            by_month.setdefault(snap["fetched_at"][:7].replace("-", "_"), []).append(snap)

        index = await self._load_index()
        for month, snaps in by_month.items():
            store = self._month_store(month)
            try:
                existing = await store.async_load() or {"snapshots": []}
            except StorageDecryptError:
                _LOGGER.error("Raw archive %s unreadable — starting that month afresh", month)
                existing = {"snapshots": []}
            existing["snapshots"].extend(snaps)
            await store.async_save(existing)
            if month not in index:
                index.append(month)
        await self._index_store.async_save({"months": sorted(index)})
        await self.async_prune(now)
        return len(batch)

    async def _load_index(self) -> list[str]:
        data = await self._index_store.async_load() or {}
        return list(data.get("months", []))

    async def async_prune(self, now: datetime | None = None) -> int:
        """Drop months wholly older than retention; trim the boundary month."""
        if not self.retention_days:
            return 0  # lifelong
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=self.retention_days)
        cutoff_month = cutoff.strftime("%Y_%m")
        index = await self._load_index()
        removed = 0
        keep = []
        for month in index:
            if month < cutoff_month:
                await self._month_store(month).async_remove()
                self._stores.pop(month, None)
                removed += 1
            else:
                keep.append(month)
        if cutoff_month in keep:
            store = self._month_store(cutoff_month)
            try:
                data = await store.async_load()
            except StorageDecryptError:
                data = None
            if data:
                iso = cutoff.isoformat()
                trimmed = [s for s in data["snapshots"] if s["fetched_at"] >= iso]
                if len(trimmed) != len(data["snapshots"]):
                    data["snapshots"] = trimmed
                    await store.async_save(data)
        if removed:
            await self._index_store.async_save({"months": keep})
        return removed

    async def async_read_month(self, month: str) -> list[dict[str, Any]]:
        """Snapshots of one month (``YYYY_MM``)."""
        data = await self._month_store(month).async_load()
        return list((data or {}).get("snapshots", []))

    async def async_read_all(self) -> list[dict[str, Any]]:
        """Every archived snapshot, oldest first, including unflushed ones.

        Raises :class:`StorageDecryptError` when any month is unreadable — a
        rebuild from a partial archive would silently lose history.
        """
        snapshots: list[dict[str, Any]] = []
        for month in sorted(await self._load_index()):
            snapshots.extend(await self.async_read_month(month))
        snapshots.extend(self._pending)
        snapshots.sort(key=lambda s: str(s.get("fetched_at") or ""))
        return snapshots
