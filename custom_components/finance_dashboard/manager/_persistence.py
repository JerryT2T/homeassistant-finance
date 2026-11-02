"""PersistenceMixin — storage read/write for FinanceDashboardManager.

Handles:
- Persisting transactions, balances, rate-limit state, and stats to
  HA's encrypted .storage/ directory.
- Loading per-account transfer-chain overrides.
- Surfacing Repair issues for corrupt storage files (R8).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


class PersistenceMixin:
    """Mixin that adds persistence methods to FinanceDashboardManager."""

    async def _persist_transactions(self) -> None:
        """Write the ledger (encrypted) with refresh stamps and budget state.

        Only the ledger layer is stored: transactions and balance series.
        Categories, account tags and transfer enrichment are derived on load
        and never persisted.  Demo data is never written.
        """
        if self._demo_mode or not self._ledger_writable:
            return
        meta = self._ledger.meta
        meta["balances"] = self._balances
        meta["last_refresh"] = self._last_refresh.isoformat() if self._last_refresh else None
        meta["last_refresh_stats"] = self._last_refresh_stats
        meta["account_count"] = len(self._accounts)
        meta["bank_budget"] = self._budget.to_dict()
        try:
            await self._ledger.async_save()
        except Exception:
            _LOGGER.exception("Ledger write failed — data stays in memory only")

    async def async_reprocess(self, *, force: bool = False) -> dict:
        """Rebuild the ledger from the raw archive and log the run (no bank call)."""
        import time

        from ..const import PROCESSING_VERSION
        from ..freshness import make_entry

        t0 = time.monotonic()
        result = await self._reprocess_core(force=force)
        if result.get("outcome") != "current":
            self._log_run(
                make_entry(
                    "reprocess" if force else "processing_upgrade",
                    at=self._utc_iso(),
                    total=int(result.get("transactions") or 0),
                    processing_version=PROCESSING_VERSION,
                    outcome=str(result.get("outcome")),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            )
        return result

    async def _reprocess_core(self, *, force: bool = False) -> dict:
        """Rebuild the ledger from the raw archive when processing changed.

        Runs when the ledger's ``processing_version`` differs from
        ``PROCESSING_VERSION`` (or on ``force``).  No bank call.  The previous
        ledger is saved to ``…_ledger_backup_v<old>`` first, history the
        archive does not cover is carried over, and an unreadable archive
        month aborts the rebuild (the old ledger stays as it is).
        """
        from datetime import UTC, datetime

        from ..account_identity import account_key
        from ..const import (
            LEDGER_STORAGE_MINOR_VERSION,
            LEDGER_STORAGE_VERSION,
            PROCESSING_VERSION,
            STORAGE_KEY_LEDGER_BACKUP,
        )
        from ..data_store import StorageDecryptError
        from ..reprocess import merge_uncovered, replay

        meta = self._ledger.meta
        old_version = int(meta.get("processing_version") or 0)
        if not force and old_version == PROCESSING_VERSION:
            return {"outcome": "current", "version": PROCESSING_VERSION}
        if self._raw is None or not self._ledger_writable:
            return {"outcome": "unavailable"}

        try:
            snapshots = await self._raw.async_read_all()
        except StorageDecryptError as exc:
            _LOGGER.error("Raw archive unreadable (%s) — ledger not rebuilt", exc)
            self._raise_storage_corrupt_issue("raw_archive", "StorageDecryptError")
            return {"outcome": "error", "reason": "raw_unreadable"}

        if not snapshots:
            meta["processing_version"] = PROCESSING_VERSION
            await self._ledger.async_save()
            return {"outcome": "empty", "version": PROCESSING_VERSION}

        backup = self._credential_manager.encrypted_store(
            f"{STORAGE_KEY_LEDGER_BACKUP}{old_version}",
            LEDGER_STORAGE_VERSION,
            LEDGER_STORAGE_MINOR_VERSION,
        )
        await backup.async_save(self._ledger.data)

        uid_to_key = {a["id"]: account_key(a) for a in self._accounts if a.get("id")}
        accounts, coverage, stats = replay(snapshots, uid_to_key)
        old_accounts = self._ledger.data.get("accounts", {})
        stats["carried"] = merge_uncovered(old_accounts, accounts, coverage)

        self._ledger.data["accounts"] = accounts
        # imported history the rebuilt bank rows now cover: the bank wins (#121)
        reconcile = getattr(self._ledger, "reconcile_imports", None)
        if reconcile is not None:
            stats["imports_covered"] = reconcile()
        meta["processing_version"] = PROCESSING_VERSION
        log = list(meta.get("reprocessed") or [])
        log.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "from": old_version,
                "to": PROCESSING_VERSION,
                **stats,
            }
        )
        meta["reprocessed"] = log[-20:]
        await self._ledger.async_save()
        _LOGGER.info(
            "Ledger rebuilt from %d raw snapshots (v%d → v%d, %d windows, %d carried over)",
            stats["snapshots"],
            old_version,
            PROCESSING_VERSION,
            stats["windows"],
            stats["carried"],
        )
        total = sum(len(a.get("transactions") or []) for a in accounts.values())
        return {"outcome": "rebuilt", "version": PROCESSING_VERSION, "transactions": total, **stats}

    @staticmethod
    def _utc_iso() -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).isoformat()

    def _log_run(self, entry: dict) -> None:
        """Append to the import log in the ledger meta (saved with the next ledger write)."""
        from ..freshness import append_log

        if self._demo_mode:
            return
        append_log(self._ledger.meta, entry)

    async def async_reprocess_and_derive(self) -> dict:
        """User-triggered "Aktualisieren": forced replay + full re-derivation.

        Never touches the bank or the fetch budget.  Serialised with live
        refreshes through ``_refresh_lock``.  The caller pushes the coordinator.
        """
        async with self._refresh_lock:
            result = await self.async_reprocess(force=True)
            overrides = await self._async_load_transfer_overrides()
            derived = self._derive_from_ledger(overrides)
            try:
                from ..recurring import detect_recurring

                self._recurring_patterns = detect_recurring(derived)
            except Exception:
                _LOGGER.exception("Recurring detection failed — skipping")
            await self._persist_transactions()  # also saves the log entry
        self.schedule_ai_categorization()
        return {**result, "transaction_count": len(derived)}

    # -- imported booking history (#121) ----------------------------------

    def history_accounts(self) -> list[dict]:
        """Accounts a history file can be imported into (key, name, IBAN tail)."""
        from ..account_identity import account_key

        out = []
        for a in self._accounts:
            iban = str(a.get("iban") or "")
            out.append(
                {
                    "key": account_key(a),
                    "name": a.get("custom_name") or a.get("name", ""),
                    "iban_masked": f"****{iban[-4:]}" if len(iban) >= 4 else "",
                }
            )
        return out

    def history_ledger_transactions(self, key: str) -> list[dict]:
        return self._ledger.transactions(key)

    def history_import_allowed(self) -> bool:
        return not self._demo_mode and self._ledger_writable

    async def _after_ledger_edit(self) -> None:
        overrides = await self._async_load_transfer_overrides()
        derived = self._derive_from_ledger(overrides)
        try:
            from ..recurring import detect_recurring

            self._recurring_patterns = detect_recurring(derived)
        except Exception:
            _LOGGER.exception("Recurring detection failed - skipping")
        await self._persist_transactions()

    async def async_commit_history_import(
        self, key: str, batch_id: str, txs: list[dict], info: dict
    ) -> int:
        """Store an import batch in the ledger and re-derive.  No bank call."""
        async with self._refresh_lock:
            added = self._ledger.add_import_batch(key, batch_id, txs, info)
            await self._after_ledger_edit()
        return added

    async def async_undo_history_import(self, batch_id: str) -> int:
        async with self._refresh_lock:
            removed = self._ledger.remove_import_batch(batch_id)
            await self._after_ledger_edit()
        return removed

    def history_batches(self) -> list[dict]:
        return self._ledger.import_batches()

    def get_freshness(self, *, admin: bool) -> dict:
        """Freshness payload (cache read only, no bank call)."""
        from datetime import date

        from ..account_identity import account_key
        from ..const import PROCESSING_VERSION
        from ..freshness import (
            LOG_KEY,
            build_freshness,
            derivation_check,
            monthly_validity,
            undated_accounts,
        )

        meta = self._ledger.meta
        log = list(meta.get(LOG_KEY) or [])
        as_of = self._last_refresh.isoformat() if self._last_refresh else self._utc_iso()
        validity: list = []
        check: dict = {}
        quality: list = []
        if admin:
            names = {
                account_key(a): a.get("custom_name") or a.get("name", "") for a in self._accounts
            }
            accounts = self._ledger.data.get("accounts", {})
            validity = monthly_validity(accounts, names, today=date.today())
            ledger_txs = [t for a in accounts.values() for t in a.get("transactions") or []]
            check = derivation_check(ledger_txs, self._transactions)
            quality = undated_accounts(accounts, names)
        return build_freshness(
            as_of=as_of,
            log=log,
            processing_version=int(meta.get("processing_version") or PROCESSING_VERSION),
            validity=validity,
            check=check,
            admin=admin,
            data_quality=quality,
            last_bank_success=max(
                (b["last_success"] for b in self.get_bank_status() if b.get("last_success")),
                default=None,
            ),
        )

    async def _async_load_transfer_overrides(
        self,
    ) -> dict[str, bool]:
        """Load user overrides for transfer chains from storage."""
        data = await self._transfer_override_store.async_load()
        if data and isinstance(data, dict):
            self._transfer_overrides = data
            return data
        return {}

    def _raise_storage_corrupt_issue(self, storage_key: str, error_class: str) -> None:
        """Raise a Repair issue for a corrupt .storage/ file (R8).

        Only the storage key name and Python exception class are included
        in the repair issue — never raw exception text or stack traces.

        Marked ``is_persistent=True`` — a corrupt cache file requires manual
        intervention (the user must delete the corrupt file or re-configure)
        and must remain visible across HA restarts.
        """
        try:
            from homeassistant.helpers import issue_registry as ir

            from ..const import DOMAIN

            ir.async_create_issue(
                self._hass,
                DOMAIN,
                f"storage_corrupt_{storage_key}",
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="storage_corrupt",
                translation_placeholders={
                    "storage_key": storage_key,
                    "error_class": error_class,
                },
            )
        except Exception:
            _LOGGER.debug("Could not create storage_corrupt repair issue", exc_info=True)
