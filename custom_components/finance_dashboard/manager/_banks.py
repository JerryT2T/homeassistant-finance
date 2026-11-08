"""BankMixin — per-bank targets, consent expiry, status and ledger derivation.

Banks are config SUBENTRIES of type ``"bank"``::

    data = {"aspsp_name", "aspsp_country", "valid_until",
            "accounts": [{"uid", "identity_key"}]}

Each bank's Enable Banking session lives in the credential store under the
subentry id.  Installs that predate subentries run as one virtual ``legacy``
bank until :meth:`async_migrate_legacy_session` turns it into a real one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

from homeassistant.util import dt as dt_util

from ..const import (
    CONSENT_EXPIRY_WARN_DAYS,
    DOMAIN,
    LEGACY_BANK_ID,
    SUBENTRY_TYPE_BANK,
)
from ..ownership import card_person
from ..tx_dates import effective_date_str

_LOGGER = logging.getLogger(__name__)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class BankMixin:
    """Bank subentry handling for FinanceDashboardManager."""

    # ------------------------------------------------------------------
    # Targets
    # ------------------------------------------------------------------

    def _bank_subentries(self) -> list[Any]:
        subs = getattr(self._entry, "subentries", None) or {}
        return [s for s in subs.values() if getattr(s, "subentry_type", None) == SUBENTRY_TYPE_BANK]

    def _accounts_for(self, listed: list[dict[str, Any]], title: str) -> list[dict[str, Any]]:
        """The bank's account records, one per subentry ref.

        A ref without a stored record (a bank linked by 0.16.0/0.16.1, which
        wrote the subentry but not the entry's ``accounts``) still yields a
        minimal record keyed by its identity, so the bank is fetched instead
        of silently reaching no account.
        """
        from ..account_identity import account_key

        by_uid = {a.get("id"): a for a in self._accounts if a.get("id")}
        by_key = {account_key(a): a for a in self._accounts}
        result: list[dict[str, Any]] = []
        for ref in listed:
            record = by_uid.get(ref.get("uid")) or by_key.get(ref.get("identity_key"))
            if record is None and ref.get("uid"):
                record = {
                    "id": ref["uid"],
                    "key": ref.get("identity_key") or ref["uid"],
                    "name": f"{title} {len(result) + 1}",
                    "institution": title,
                }
            if record is not None and record not in result:
                result.append(record)
        return result

    def async_adopt_subentry_accounts(self) -> int:
        """Store the accounts a bank subentry references but the entry lacks.

        Banks linked by 0.16.0/0.16.1 wrote only the subentry refs.  Fetching
        still worked through the minimal records of :meth:`_accounts_for`, but
        everything that reads ``_accounts`` (account keys in the API, person
        and owner assignment, transfer detection) saw no account at all.
        Runs on setup, before the update listener exists, so persisting does
        not reload the entry.  Returns the number of adopted accounts.
        """
        from ..account_identity import account_key

        known = {account_key(a) for a in self._accounts}
        adopted: list[dict[str, Any]] = []
        for sub in self._bank_subentries():
            data = dict(sub.data)
            title = data.get("aspsp_name") or sub.title
            for record in self._accounts_for(data.get("accounts") or [], title):
                key = account_key(record)
                if key not in known:
                    known.add(key)
                    adopted.append(record)
        if not adopted:
            return 0
        self.async_set_accounts([*self._accounts, *adopted])
        _LOGGER.info("Adopted %d bank account(s) from subentries", len(adopted))
        return len(adopted)

    async def _async_bank_targets(self) -> list[dict[str, Any]]:
        """Banks to fetch, each with its accounts and consent expiry."""
        targets: list[dict[str, Any]] = []
        subs = self._bank_subentries()
        for sub in subs:
            data = dict(sub.data)
            listed = data.get("accounts") or []
            accounts = self._accounts_for(listed, data.get("aspsp_name") or sub.title)
            session = await self._credential_manager.async_get_bank_session(sub.subentry_id)
            valid_until = (session or {}).get("valid_until") or data.get("valid_until")
            targets.append(
                {
                    "bank_id": sub.subentry_id,
                    "title": data.get("aspsp_name") or sub.title,
                    "accounts": accounts,
                    "valid_until": valid_until,
                }
            )
        if not subs and self._accounts:
            legacy = await self._credential_manager.async_get_session(include_expired=True)
            targets.append(
                {
                    "bank_id": LEGACY_BANK_ID,
                    "title": (self._accounts[0].get("institution") or "Bank"),
                    "accounts": list(self._accounts),
                    "valid_until": (legacy or {}).get("valid_until"),
                }
            )
        self._bank_info = {t["bank_id"]: t for t in targets}
        return targets

    # ------------------------------------------------------------------
    # Status (consumed by entities)
    # ------------------------------------------------------------------

    def get_bank_status(self) -> list[dict[str, Any]]:
        """Per-bank budget and health.  Pure cache read, never hits a bank.

        Each dict: ``bank_id``, ``title``, ``budget_used_today`` (background
        calls today for the busiest account), ``budget_limit`` (4),
        ``blocked_until`` (ISO or None), ``last_success``, ``last_error``
        (class-level text), ``last_attended_at`` (last uncapped fetch the
        user started), ``consent_valid_until``, ``consent_state``
        (ok / expiring / expired).
        """
        info = dict(getattr(self, "_bank_info", {}) or {})
        for sub in self._bank_subentries():
            info.setdefault(
                sub.subentry_id,
                {
                    "title": dict(sub.data).get("aspsp_name") or sub.title,
                    "valid_until": dict(sub.data).get("valid_until"),
                },
            )
        out = []
        for bank_id, bank in info.items():
            status = self._budget.status(bank_id, consent_valid_until=bank.get("valid_until"))
            status["title"] = bank.get("title", "")
            status["consent_state"] = self._consent_state(bank.get("valid_until"))
            out.append(status)
        return out

    # ------------------------------------------------------------------
    # Consent expiry
    # ------------------------------------------------------------------

    @staticmethod
    def _consent_state(valid_until: Any, now: datetime | None = None) -> str:
        """``ok`` | ``expiring`` (<= 14 days left) | ``expired``."""
        until = _parse_dt(valid_until)
        if until is None:
            return "ok"  # unknown expiry is not a reason to refuse
        now = now or datetime.now(UTC)
        if now >= until:
            return "expired"
        if until - now <= timedelta(days=CONSENT_EXPIRY_WARN_DAYS):
            return "expiring"
        return "ok"

    def _mark_consent_error(self, bank_id: str, valid_until: Any) -> None:
        """Remember a 401/403 for the consent valid at that time.

        Keyed by ``valid_until``: once the session is renewed the value
        changes and the error no longer applies.
        """
        self._consent_errors[bank_id] = str(valid_until or "")

    async def async_update_consent_issues(self) -> None:
        """Create/delete ``consent_expiring_<id>`` / ``consent_expired_<id>`` issues.

        Called with the daily refresh, after every refresh and on setup.
        Issues are fixable (the subentry reconfigure flow renews the session)
        and disappear on their own once the session is renewed.
        """
        from homeassistant.helpers import issue_registry as ir

        if self._demo_mode:
            return
        targets = await self._async_bank_targets()
        for bank in targets:
            bank_id = bank["bank_id"]
            if bank_id == LEGACY_BANK_ID:
                continue  # no subentry to fix yet
            valid_until = bank["valid_until"]
            state = self._consent_state(valid_until)
            if self._consent_errors.get(bank_id) == str(valid_until or ""):
                state = "expired"  # the bank itself rejected the session

            placeholders = {"bank": bank["title"] or "Bank"}
            expiring_id = f"consent_expiring_{bank_id}"
            expired_id = f"consent_expired_{bank_id}"
            if state == "expired":
                ir.async_delete_issue(self._hass, DOMAIN, expiring_id)
                ir.async_create_issue(
                    self._hass,
                    DOMAIN,
                    expired_id,
                    is_fixable=True,
                    is_persistent=True,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="consent_expired",
                    translation_placeholders=placeholders,
                    data={"subentry_id": bank_id},
                )
            elif state == "expiring":
                ir.async_delete_issue(self._hass, DOMAIN, expired_id)
                ir.async_create_issue(
                    self._hass,
                    DOMAIN,
                    expiring_id,
                    is_fixable=True,
                    is_persistent=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="consent_expiring",
                    translation_placeholders=placeholders,
                    data={"subentry_id": bank_id},
                )
            else:
                ir.async_delete_issue(self._hass, DOMAIN, expiring_id)
                ir.async_delete_issue(self._hass, DOMAIN, expired_id)

    async def async_prune_orphan_sessions(self) -> list[str]:
        """Remove sessions of bank subentries that no longer exist.

        HA has no per-subentry removal hook, so the set of known bank ids is
        kept in the ledger meta and diffed against ``entry.subentries`` on
        every setup/reload.  Returns the ids whose session was removed.
        """
        current = {s.subentry_id for s in self._bank_subentries()}
        meta = self._ledger.meta
        known = set(meta.get("known_banks") or [])
        removed = sorted(known - current)
        for bank_id in removed:
            await self._credential_manager.async_remove_bank_session(bank_id)
            self._consent_errors.pop(bank_id, None)
        if removed or known != current:
            meta["known_banks"] = sorted(current)
            await self._persist_transactions()
        return removed

    # ------------------------------------------------------------------
    # Legacy single-session -> bank subentry
    # ------------------------------------------------------------------

    async def async_migrate_legacy_session(self) -> str | None:
        """Turn a legacy single session into one bank subentry.

        Runs on setup.  No-op when bank subentries exist, when there is no
        legacy session or no accounts, or when this Home Assistant has no
        config subentries (< 2025.3) — the virtual ``legacy`` bank then keeps
        the install working.  The legacy session record is left in place so a
        rollback still finds it.

        Returns the new subentry id, or None.
        """
        if self._bank_subentries() or not self._accounts:
            return None
        try:
            from homeassistant.config_entries import ConfigSubentry
        except ImportError:
            _LOGGER.info("Config subentries unavailable — staying on the legacy bank")
            return None

        session = await self._credential_manager.async_get_session(include_expired=True)
        if not session:
            return None

        from ..account_identity import account_key

        first = self._accounts[0]
        name = first.get("institution") or "Bank"
        data = {
            "aspsp_name": name,
            "aspsp_country": self._entry.data.get("country", "DE"),
            "valid_until": session["valid_until"],
            "accounts": [
                {"uid": a.get("id", ""), "identity_key": account_key(a)} for a in self._accounts
            ],
        }
        subentry = ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=SUBENTRY_TYPE_BANK,
            title=name,
            unique_id=None,
        )
        # Session first: adding the subentry may reload the entry.
        await self._credential_manager.async_store_bank_session(
            subentry.subentry_id, session["session_id"], session["valid_until"]
        )
        self._hass.config_entries.async_add_subentry(self._entry, subentry)
        _LOGGER.info("Migrated legacy bank session to a bank subentry")
        return subentry.subentry_id

    # ------------------------------------------------------------------
    # Ledger -> derived views
    # ------------------------------------------------------------------

    def _derive_from_ledger(self, overrides: dict[str, bool] | None = None) -> list[dict[str, Any]]:
        """Rebuild every derived view from the ledger.

        Account tags, categories and transfer-chain enrichment are computed
        here and never stored in the ledger.  Fills ``_tx_by_account`` (keyed
        by the current session uid, as the rest of the code expects) and
        ``_transactions``.
        """
        from ..account_identity import account_key
        from ..labels import apply_contract_categories
        from ..own_accounts import OwnAccounts
        from ..transfer_detector import (
            apply_overrides,
            detect_transfer_chains,
            enrich_transactions,
        )

        by_uid = {a.get("id"): a for a in self._accounts if a.get("id")}
        uid_for_key = {account_key(a): uid for uid, a in by_uid.items()}
        categorizer = self._categorizer
        memory = getattr(self, "_memory", None)
        if categorizer and hasattr(categorizer, "set_own_accounts"):
            categorizer.set_own_accounts(OwnAccounts.of(self._accounts))

        hh_categories = memory.household_categories() if memory else None
        tx_by_account: dict[str, list[dict[str, Any]]] = {}
        for akey in self._ledger.account_keys():
            uid = uid_for_key.get(akey, akey)
            account = by_uid.get(uid, {})
            display = account.get("custom_name") or account.get("name", "")
            txs = self._ledger.transactions(akey)
            for tx in txs:
                tx["_account_key"] = akey
                tx["_account_id"] = uid
                tx["_account_name"] = display
                tx["_account_type"] = account.get("type", "personal")
                tx["_account_person"] = account.get("person", "")
                tx["_account_household_use"] = bool(account.get("household_use"))
                tx["_card_person"] = (
                    card_person(tx, account.get("card_owners")) if tx["_account_type"] == "shared" else ""
                )
                tx["_account_ha_users"] = account.get("ha_users", [])
                tx["category"] = categorizer.categorize(tx) if categorizer else "other"
                # a booking answer without an owner must not hide the merchant's owner
                brule = (memory.booking_rule(tx) if memory else None) or {}
                mrule = (memory.merchant_rule(tx) if memory else None) or {}
                tx["_owner_override"] = brule.get("owner") or mrule.get("owner")
                tx["_owner_scope"] = "booking" if brule.get("owner") else "merchant"
                tx["_series_owner"] = memory.series_owner(tx) if memory else None
                tx["_ai_tendency"] = memory.tendency(tx) if memory else None
                tx["_household_categories"] = hh_categories
            tx_by_account[uid] = txs

        flat = [tx for txs in tx_by_account.values() for tx in txs]
        flat.sort(key=effective_date_str, reverse=True)
        try:
            chains, refunds = detect_transfer_chains(flat, self._accounts, overrides=overrides)
            flat = enrich_transactions(flat, chains, refunds)
            apply_overrides(flat, overrides or {})
        except Exception:
            _LOGGER.exception("Transfer detection failed — using unenriched transactions")

        # A contract's category is what its bookings count under (#177).
        apply_contract_categories(flat, getattr(self, "_contract_categories", None))

        self._tx_by_account = tx_by_account
        self._transactions = flat
        return flat

    def get_ledger_transactions(self, account_key_: str | None = None) -> list[dict[str, Any]]:
        """Ledger transactions (no derived fields); one account or all.

        Cache read.  ``account_key_`` is the IBAN-based key from
        ``account_identity.account_key``.
        """
        keys = [account_key_] if account_key_ else self._ledger.account_keys()
        return [tx for k in keys for tx in self._ledger.transactions(k)]

    def get_balance_history(self, account_key_: str) -> list[dict[str, Any]]:
        """Balance time series: one point per fetch per balance type."""
        return self._ledger.balance_series(account_key_)

    @property
    def _raw_retention_days(self) -> int:
        from ..const import DEFAULT_RAW_RETENTION_DAYS, OPT_RAW_RETENTION_DAYS

        options = getattr(self._entry, "options", {}) or {}
        try:
            # 0 = keep forever
            return max(int(options.get(OPT_RAW_RETENTION_DAYS, DEFAULT_RAW_RETENTION_DAYS)), 0)
        except (TypeError, ValueError):
            return DEFAULT_RAW_RETENTION_DAYS

    @staticmethod
    def _now_utc() -> datetime:
        return dt_util.utcnow()
