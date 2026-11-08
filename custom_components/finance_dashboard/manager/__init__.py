"""Finance Manager — core business logic orchestrator.

Coordinates between:
- Enable Banking API client (banking data via PSD2)
- Credential Manager (secure storage)
- Transaction Categorizer (auto-classification)
- Two-layer storage: raw bank-response archive + processed ledger

SECURITY: Transaction data lives in HA's .storage/ directory as Fernet
ciphertext (key held by the credential manager): the ledger
(``finance_dashboard_ledger``) and the monthly raw archive
(``finance_dashboard_raw_YYYY_MM``).  The pre-ledger plaintext cache is
migrated into the ledger on first start and then deleted.  Categories,
monthly summaries and household splits are derived from the ledger and never
stored.  No financial data is ever written to logs or git.

CACHE vs LIVE FETCH CONTRACT:
- ``get_cached_*`` / ``async_get_balance`` / ``get_bank_status`` return
  in-memory cache only — zero API calls, unbounded calls allowed.
- ``async_refresh_*`` hits the Enable Banking API and updates the cache —
  ONLY called from explicit user-triggered paths (service call, refresh
  button, setup-complete bootstrap) plus the single scheduled daily refresh.
  The 4/day cap is tracked per bank and applies to background (non-PSU)
  calls only; attended calls are uncapped but debounced.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..account_identity import account_key, normalize_iban
from ..budget_plan import BudgetPlan, BudgetPlanStore, CostPosition
from ..const import (
    BENCHMARK_METRIC_SOURCES,
    DEFAULT_SPLIT_MODEL,
    DEFAULT_WATER_BENCHMARK,
    DOMAIN,
    ENABLEBANKING_RATE_LIMIT_DAILY,
    OPT_BENCHMARK_POSTCODE,
    OPT_BENCHMARK_STATE,
    OPT_WATER_RATIO,
    OWNER_SHARED,
    STORAGE_KEY_LEDGER,
    STORAGE_KEY_TRANSFER_OVERRIDES,
)
from ..data_store import Ledger, StorageDecryptError
from ..fetch_budget import FetchBudget
from ..household import HouseholdMember, HouseholdModel, model_from_plan
from ..pots import Pot, PotStore
from ..counted import counted_transactions, is_income_line, movement_reasons, net_counted
from ..household_summary import (
    Classifier,
    cycle_windows,
    figures,
    month_of_window,
    plan_persons,
    window_of_month,
)
from ..labels import apply_contract_categories, contract_categories
from ..ownership import account_kind, apply_owner_set, owner_set_label
from ..plan_match import assign_positions
from ..tx_dates import effective_date_str, effective_day
from ..transfer_detector import (
    apply_overrides,
)
from ..transfer_plan import build_transfer_plan
from ._banks import BankMixin
from ._ownership import OwnershipMixin
from ._persistence import PersistenceMixin
from ._questions import QuestionsMixin
from ._refresh import RefreshMixin

_LOGGER = logging.getLogger(__name__)


def _refund_allocations(manager: Any) -> dict[str, dict[str, float]]:
    analysis = getattr(manager, "get_refund_analysis", None)  # a host without refunds has none
    return analysis()["allocations"] if analysis is not None else {}

TRANSACTION_CACHE_KEY = f"{DOMAIN}_transactions"
TRANSACTION_CACHE_VERSION = 1

# OAuth state token TTL in seconds (10 minutes) — kept here for test imports
_OAUTH_STATE_TTL = 600


class AssignmentError(ValueError):
    """Invalid persons/accounts assignment; ``code`` is the API error code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class FinanceDashboardManager(
    RefreshMixin, BankMixin, PersistenceMixin, QuestionsMixin, OwnershipMixin
):
    """Central orchestrator for the Finance integration.

    Inherits from:
    - RefreshMixin   (_refresh.py) — all live-fetch + OAuth methods
    - BankMixin      (_banks.py) — bank subentries, consent expiry, status
    - PersistenceMixin (_persistence.py) — ledger read/write
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._entry = entry
        self._credential_manager = None
        self._banking_client = None
        self._categorizer = None
        # LEGACY plaintext cache — read once for migration, then deleted.
        self._transaction_store = Store(hass, TRANSACTION_CACHE_VERSION, TRANSACTION_CACHE_KEY)
        # Two-layer storage: processed ledger + raw bank-response archive.
        # Attached to the credential manager's key in async_initialize().
        self._ledger = Ledger(None)
        self._raw = None
        self._ledger_writable = True
        # Per-bank fetch budget (attended vs background, 429 per bank).
        self._budget = FetchBudget(tz=dt_util.get_default_time_zone())
        self._bank_info: dict[str, dict[str, Any]] = {}
        self._consent_errors: dict[str, str] = {}
        self._accounts: list[dict[str, Any]] = entry.data.get("accounts", [])
        # Per-account transaction cache: account_id → list[tx].
        # Partial refresh failures only affect the failed account's slice —
        # other accounts keep their last-known data (R5 fix).
        self._tx_by_account: dict[str, list[dict[str, Any]]] = {}
        # Flat view (legacy + internal use) — kept in sync with _tx_by_account.
        self._transactions: list[dict[str, Any]] = []
        self._balances: dict[str, Any] = {}
        self._last_refresh: datetime | None = None
        self._rate_limited_until: datetime | None = None
        self._transfer_override_store = Store(hass, 1, STORAGE_KEY_TRANSFER_OVERRIDES)
        self._transfer_overrides: dict[str, bool] = {}
        self._contract_categories: dict[str, str] = {}
        self._memory = None  # MerchantMemory, created in async_initialize
        self._recurring_patterns: list[dict[str, Any]] = []
        self._previous_balances: dict[str, float] = {}
        self._demo_mode: bool = False
        # Last user-triggered refresh statistics — surfaced to the UI so
        # the user sees exactly what happened on the last "Aktualisieren"
        # click (accounts hit, transactions loaded, duration, outcome).
        # Structure: {"outcome": str, "accounts": int, "transactions": int,
        #   "new": int, "duration_ms": int, "started_at": ISO,
        #   "finished_at": ISO, "errors": list[str]}
        self._last_refresh_stats: dict[str, Any] = {}
        # Serialises concurrent refresh requests (double-click guard,
        # parallel service calls). In-flight state is also surfaced via
        # ``is_refreshing`` so the frontend can poll for completion.
        self._refresh_lock = asyncio.Lock()
        self._refresh_in_flight: bool = False
        # OAuth state tokens: {state_str: created_iso} — one-time-use, 10min TTL
        self._oauth_states: dict[str, str] = {}
        # The PLAN side: the migrated household spreadsheet (cost positions +
        # per-person income). Live bank data supplies the ACTUAL side; the two
        # are compared per position in the monthly summary.
        self._plan_store = BudgetPlanStore(hass)
        # Pots (budget envelopes) - plan data stored next to the plan.
        self._pot_store = PotStore(hass)
        # Lazily created on first benchmark request — it reads .storage/ and
        # nothing needs it during setup.
        self._benchmark_provider = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def rate_limited_until(self) -> datetime | None:
        """Until when background access is blocked for EVERY linked bank.

        Per-bank blocks live in the fetch budget.  With several banks, one
        blocked bank does not stop the others, so this is only set when all
        of them are blocked (the latest ``blocked_until``).  Callers that gate
        on it must keep exempting attended calls.
        """
        budget = getattr(self, "_budget", None)
        bank_ids = list(getattr(self, "_bank_info", {}) or {})
        if budget is not None and bank_ids:
            untils = [budget.blocked_until(b) for b in bank_ids]
            if all(untils):
                return max(untils)
            return None
        if self._rate_limited_until and dt_util.now() < self._rate_limited_until:
            return self._rate_limited_until
        return None

    @property
    def is_refreshing(self) -> bool:
        """True while a user-triggered refresh is in flight."""
        return self._refresh_in_flight

    @property
    def last_refresh(self) -> datetime | None:
        """Timestamp of the last successful transaction refresh, if any."""
        return self._last_refresh

    @property
    def last_refresh_stats(self) -> dict[str, Any]:
        """Structured stats from the most recent refresh attempt."""
        return dict(self._last_refresh_stats)

    @property
    def demo_mode(self) -> bool:
        """Return whether demo mode is active."""
        return self._demo_mode

    # ------------------------------------------------------------------
    # Demo mode
    # ------------------------------------------------------------------

    def set_demo_mode(self, enabled: bool) -> None:
        """Toggle demo mode on or off.

        When enabled, loads synthetic demo data into the manager's state.
        When disabled, clears demo data and reverts to real cached data.
        """
        self._demo_mode = enabled
        if enabled:
            from ..demo import generate_demo_data

            data = generate_demo_data()
            self._accounts = data["_demo_accounts"]
            self._transactions = data["_demo_transactions"]
            self._balances = data["_demo_balances"]
            self._last_refresh = dt_util.now()
            self._recurring_patterns = data.get("recurring", [])
            self._last_refresh_stats = self._build_stats(
                outcome="demo",
                started=self._last_refresh,
                duration_ms=0,
                accounts=len(self._accounts),
                transactions=len(self._transactions),
                new=0,
                errors=[],
            )
            _LOGGER.info("Demo mode enabled — loaded synthetic data")
        else:
            # Clear demo data — real data reloads on next manual refresh
            self._accounts = self._entry.data.get("accounts", [])
            self._transactions = []
            self._balances = {}
            self._last_refresh = None
            self._recurring_patterns = []
            _LOGGER.info("Demo mode disabled — cleared synthetic data")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_initialize(self) -> None:  # noqa: PLR0915
        """Initialize all sub-components."""
        from ..categorizer import TransactionCategorizer
        from ..credential_manager import CredentialManager

        self._credential_manager = CredentialManager(self._hass)
        await self._credential_manager.async_initialize()

        from ..merchants import MerchantMemory

        self._memory = MerchantMemory(self._hass)
        try:
            await self._memory.async_load()
        except Exception:
            _LOGGER.exception("Merchant memory unreadable — starting empty")
        self._categorizer = TransactionCategorizer(memory=self._memory)

        # Load the budget plan. A read failure must not block startup — the
        # store falls back to an empty plan and the UI prompts for an import.
        await self._plan_store.async_load()
        await self._pot_store.async_load()

        # Two-layer storage, encrypted with the credential manager's key.
        from ..data_store import RawArchive

        if self._ledger._store is None:
            self._ledger = Ledger.create(self._credential_manager)
        self._raw = RawArchive(
            self._hass, self._credential_manager, self._raw_retention_days
        )
        # R8: a corrupt or undecryptable store must not crash HA startup.
        try:
            await self._ledger.async_load()
        except StorageDecryptError as exc:
            # Key lost or file damaged: the content is unrecoverable, so
            # starting afresh (and overwriting) is the only way forward.
            _LOGGER.error("Ledger cannot be decrypted (%s) — starting empty", exc)
            self._raise_storage_corrupt_issue(STORAGE_KEY_LEDGER, "StorageDecryptError")
        except Exception as exc:
            # Unknown failure: keep the file untouched rather than overwrite it.
            _LOGGER.error("Ledger load failed (%s) — running without persistence", type(exc).__name__)
            self._ledger_writable = False
            self._raise_storage_corrupt_issue(STORAGE_KEY_LEDGER, type(exc).__name__)

        # Legacy plaintext cache -> encrypted ledger, then delete the plaintext.
        legacy = None
        try:
            legacy = await self._transaction_store.async_load()
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            _LOGGER.error(
                "Transaction cache corrupt (%s) — starting with empty state",
                type(exc).__name__,
            )
            self._raise_storage_corrupt_issue(TRANSACTION_CACHE_KEY, type(exc).__name__)
        if legacy and ("transactions" in legacy or "tx_by_account" in legacy):
            await self._migrate_plaintext_cache(legacy)

        await self._async_migrate_ledger_ids()

        # Processing changed since the ledger was written -> rebuild it from
        # the raw archive (no bank call).  Failure keeps the old ledger.
        try:
            await self.async_reprocess()
        except Exception:
            _LOGGER.exception("Ledger rebuild from raw archive failed — keeping current ledger")

        self._load_state_from_ledger()
        overrides: dict[str, bool] = {}
        try:
            overrides = await self._async_load_transfer_overrides()
        except Exception:
            _LOGGER.debug("Transfer overrides unavailable at startup", exc_info=True)
        self._derive_from_ledger(overrides)
        await self._async_refresh_contract_categories()
        _LOGGER.info(
            "Loaded %d ledger transactions (last refresh: %s, balances: %d)",
            len(self._transactions),
            self._last_refresh,
            len(self._balances),
        )

        _LOGGER.info("Finance Manager initialized")

    async def _migrate_plaintext_cache(self, cached: dict[str, Any]) -> None:
        """Move the pre-ledger plaintext transaction cache into the ledger."""
        from ..account_identity import account_key

        uid_to_key = {a.get("id"): account_key(a) for a in self._accounts if a.get("id")}
        by_uid = cached.get("tx_by_account")
        if not isinstance(by_uid, dict):
            by_uid = {}
            for tx in cached.get("transactions", []) or []:
                by_uid.setdefault(tx.get("_account_id", "__unknown__"), []).append(tx)
        for uid, txs in by_uid.items():
            self._ledger.import_legacy(uid_to_key.get(uid, uid), list(txs))

        meta = self._ledger.meta
        for field in ("balances", "last_refresh", "last_refresh_stats"):
            if cached.get(field) and not meta.get(field):
                meta[field] = cached[field]

        if not self._ledger_writable:
            return
        try:
            await self._ledger.async_save()
            await self._transaction_store.async_remove()
            _LOGGER.info("Plaintext transaction cache migrated to the encrypted ledger and removed")
        except Exception:
            _LOGGER.exception("Cache migration incomplete — plaintext kept until it succeeds")

    def _load_state_from_ledger(self) -> None:
        """Restore refresh stamps, cached balances and budget state."""
        meta = self._ledger.meta
        last_refresh = meta.get("last_refresh")
        if last_refresh:
            try:
                self._last_refresh = datetime.fromisoformat(last_refresh)
            except ValueError:
                self._last_refresh = None
        # Cached balances survive restart so the UI shows something at once.
        self._balances = meta.get("balances") or {}
        # Rebuild the balance-change baseline, otherwise the first refresh
        # after every restart fires fd_balance_changed for every account.
        for acc_id, data in self._balances.items():
            raw = data.get("balances") if isinstance(data, dict) else None
            if not raw:
                continue
            try:
                self._previous_balances[acc_id] = float(
                    raw[0].get("balanceAmount", {}).get("amount", 0)
                )
            except (TypeError, ValueError, IndexError, AttributeError):
                continue
        stats = meta.get("last_refresh_stats")
        if isinstance(stats, dict):
            self._last_refresh_stats = stats
        # Budget counters and per-bank blocks must survive a restart —
        # otherwise bouncing HA would reset the day's background budget.
        self._budget.load(meta.get("bank_budget"))

    async def async_shutdown(self) -> None:
        """Clean shutdown — persist cache, clear sensitive data from memory."""
        # Only persist real transactions — never overwrite cache with demo data
        if not self._demo_mode:
            await self._persist_transactions()
        self._banking_client = None
        self._balances.clear()
        _LOGGER.info("Finance Manager shut down")

    # ------------------------------------------------------------------
    # Account management
    # ------------------------------------------------------------------

    def async_set_accounts(self, accounts: list[dict[str, Any]]) -> None:
        """Update the in-memory account list (encapsulated write path).

        Validates that *accounts* is a list; persists immediately to the
        config-entry data so the new assignments survive an HA restart.
        """
        if not isinstance(accounts, list):
            raise TypeError(f"async_set_accounts: expected list, got {type(accounts).__name__}")
        self._accounts = accounts
        # Mirror to config-entry data so accounts survive HA restart
        try:
            new_data = {**self._entry.data, "accounts": accounts}
            self._hass.config_entries.async_update_entry(self._entry, data=new_data)
        except Exception:
            _LOGGER.warning(
                "async_set_accounts: failed to persist to config entry",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Account refresh
    # ------------------------------------------------------------------

    async def async_refresh_accounts(self) -> list[dict[str, Any]]:
        """Refresh account list from Enable Banking."""
        if self._demo_mode:
            return self._accounts
        client = await self._async_get_client()
        if not client:
            return []

        refreshed = []
        for account in self._accounts:
            acc_id = account.get("id")
            if not acc_id:
                continue
            try:
                details = await client.async_get_account_details(acc_id)
                acc_data = details.get("account", {})
                acc_data["id"] = acc_id
                # Preserve assignment info from config
                acc_data["type"] = account.get("type", "personal")
                acc_data["person"] = account.get("person", "")
                acc_data["household_use"] = bool(account.get("household_use"))
                acc_data["ha_users"] = account.get("ha_users", [])
                acc_data["custom_name"] = account.get("custom_name", "")
                acc_data["savings"] = bool(account.get("savings"))
                acc_data["institution"] = account.get("institution", "")
                acc_data["logo"] = account.get("logo", "")
                refreshed.append(acc_data)
            except Exception:
                _LOGGER.warning("Failed to refresh account %s", acc_id)
                refreshed.append(account)

        self._accounts = refreshed
        await self._credential_manager._audit_log("accounts_refreshed")
        return self._accounts

    # ------------------------------------------------------------------
    # Cache read endpoints (no API calls)
    # ------------------------------------------------------------------

    async def async_get_balance(self) -> dict[str, Any]:
        """Return cached balances — NEVER hits the banking API.

        This is the read path used by the HTTP balance endpoint and the
        coordinator's state queries. Safe for unbounded reads. Live
        updates happen inside ``async_refresh_transactions`` which is
        only invoked from user-triggered refresh paths.
        """
        return dict(self._balances)

    def get_cached_balances(self) -> dict[str, Any]:
        """Synchronous alias for ``async_get_balance`` — cache only."""
        return dict(self._balances)

    def _counted_view(self, *, include_pending: bool = False) -> list[dict[str, Any]]:
        """The bookings every total is made of: counted and refunds netted (``counted.py``)."""
        return net_counted(
            counted_transactions(
                self._transactions, self._accounts, include_pending=include_pending
            ),
            _refund_allocations(self),
        )

    def _period(
        self,
        txs: list[dict[str, Any]],
        month: int | None = None,
        year: int | None = None,
    ) -> tuple[tuple[date, date], int, int, dict[str, Any]]:
        """``(window, month, year, period)``: the same income cycle the panel shows.

        No selection is the current cycle; a month stands for the cycle holding
        its 15th. ``month`` / ``year`` name the plan month that goes with it.
        """
        now = dt_util.now()
        if month and not 1 <= month <= 12:  # noqa: PLR2004
            month = None
        if month:
            windows, rule, anchor = window_of_month(txs, month, year or now.year, self.persons)
        else:
            windows, rule, anchor = cycle_windows(txs, now.date(), self.persons)
        window = windows[0]
        label_month, label_year = month_of_window(window)
        return (
            window,
            month or label_month,
            (year or now.year) if month else label_year,
            {
                "start": window[0].isoformat(),
                "end": window[1].isoformat(),
                "rule": rule,
                "anchor": anchor,
            },
        )

    def _classifier(self) -> Classifier:
        return Classifier(
            self.budget_plan,
            self._recurring_patterns,
            None,
            plan_persons(self.budget_plan, self._accounts),
        )

    async def async_get_monthly_summary(
        self, month: int | None = None, year: int | None = None
    ) -> dict[str, Any]:
        """Spending summary of an income cycle with category breakdown.

        The figures come from the function behind the household summary, so
        sensors, automations and the panel read the same numbers (#169).
        """
        effective = await self._net_matched_refunds()
        window, target_month, target_year, period = self._period(effective, month, year)
        start, end = window

        def in_window(txn: dict[str, Any]) -> bool:
            day = effective_day(txn)
            return day is not None and start <= day <= end

        monthly_txns = [txn for txn in effective if in_window(txn)]
        movement = movement_reasons(self._transactions, self._accounts)
        excluded_chain_txns = [
            txn
            for txn in self._transactions
            if id(txn) in movement and txn.get("_status", "booked") == "booked" and in_window(txn)
        ]
        excluded_amount = sum(
            abs(float(t.get("transactionAmount", {}).get("amount", 0))) for t in excluded_chain_txns
        )

        result = figures(effective, window, self._classifier())
        total_income = result["income"]
        total_expenses = result["expenses"]

        # Bank sign per category: income positive, expenses negative
        category_totals: dict[str, float] = dict(result["income_categories"])
        for (_owner, category), spent in result["categories"].items():
            category_totals[category] = category_totals.get(category, 0) - spent

        # Build household split data from per-person accounts
        # Graceful degradation: household features must never crash the coordinator
        household = None
        try:
            household = self._compute_household(
                monthly_txns, total_expenses, target_month, target_year
            )
        except Exception:
            _LOGGER.exception("Household computation failed — skipping")

        # Recurring patterns (already detected during refresh)
        recurring_top = self._recurring_patterns[:10]

        # Fixed vs variable costs
        fixed_total = result["fixed"]
        variable_total = result["variable"]

        # Budget exceeded check — must not crash the coordinator
        try:
            self._check_budget_limits(category_totals)
        except Exception:
            _LOGGER.exception("Budget limit check failed — skipping")

        return {
            "month": target_month,
            "year": target_year,
            "period": period,
            "total_income": round(total_income, 2),
            "total_expenses": round(total_expenses, 2),
            "balance": round(total_income - total_expenses, 2),
            "categories": {k: round(v, 2) for k, v in category_totals.items()},
            "transaction_count": len(monthly_txns),
            "excluded_transfers": {
                "chain_count": len(
                    {
                        t.get("_transfer_chain_id")
                        for t in excluded_chain_txns
                        if t.get("_transfer_chain_id")
                    }
                ),
                "excluded_amount": round(excluded_amount, 2),
                "excluded_txn_count": len(excluded_chain_txns),
            },
            "household": household,
            "recurring": [
                {
                    "creditor": p.get("creditor", ""),
                    "average_amount": p.get("average_amount", 0),
                    "frequency": p.get("frequency", "monthly"),
                    "category": p.get("category", "other"),
                    "occurrences": p.get("occurrences", 0),
                    "expected_day": p.get("expected_day", 1),
                }
                for p in recurring_top
            ],
            "fixed_costs": round(fixed_total, 2),
            "variable_costs": round(variable_total, 2),
            "last_refresh": (self._last_refresh.isoformat() if self._last_refresh else None),
            "rate_limited_until": (
                self._rate_limited_until.isoformat() if self.rate_limited_until else None
            ),
            "last_refresh_stats": dict(self._last_refresh_stats),
            "is_refreshing": self._refresh_in_flight,
        }

    def remember_contract_categories(self, contracts: list[dict[str, Any]]) -> None:
        """Contract views changed: their categories are what the bookings count under."""
        self._contract_categories = contract_categories(contracts)
        apply_contract_categories(self._transactions, self._contract_categories)

    async def _async_refresh_contract_categories(self) -> None:
        """Rebuild the booking -> contract category map (cache only, #177)."""
        from ..contracts import async_get_store, build_contracts, own_account_names
        from ..household_summary import pending_debits

        try:
            store = await async_get_store(self._hass)
            txns = counted_transactions(self._transactions, self._accounts)
            txns += pending_debits(self._transactions)
            contracts = build_contracts(txns, store, own_names=own_account_names(self._accounts))
            await store.async_save_if_changed()
            self.remember_contract_categories(contracts)
        except Exception:  # noqa: BLE001 - totals fall back to the bookings' own categories
            _LOGGER.debug("Contract categories unavailable", exc_info=True)

    async def async_categorize_transactions(self) -> None:
        """Re-run auto-categorization on all cached transactions."""
        if self._demo_mode or not self._categorizer:
            return
        # Categories are derived, not stored: recompute from the ledger.
        self._derive_from_ledger(self._transfer_overrides)
        await self._async_refresh_contract_categories()
        _LOGGER.info("Re-categorized %d transactions", len(self._transactions))

    async def async_set_budget_limit(self, category: str, limit: float) -> None:
        """Set a budget limit for a category via the Number entity."""
        entity_id = f"number.fd_budget_{category}"
        state = self._hass.states.get(entity_id)
        if state is not None:
            await self._hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": entity_id, "value": limit},
            )
            _LOGGER.info("Budget limit for %s set to %.2f", category, limit)
        else:
            _LOGGER.warning("Budget entity %s not found", entity_id)

    async def async_export_csv(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        categories: list[str] | None = None,
    ) -> str:
        """Export transactions as CSV file."""
        from ..export import async_export_csv

        return await async_export_csv(
            self._hass,
            self._transactions,
            date_from=date_from,
            date_to=date_to,
            categories=categories,
        )

    def get_cached_transactions(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get cached transactions (no API call).

        Returns sanitized transactions for API responses.
        Full details only — caller must check admin status.
        """
        return self._transactions[:limit]

    # Cache staleness threshold — matches the coordinator constant.
    # Cache is considered stale when older than this value.
    _CACHE_STALE_THRESHOLD_SECONDS: int = 6 * 3600  # 6 hours

    def get_refresh_status(self) -> dict[str, Any]:
        """Return a compact status snapshot for the UI status endpoint.

        Pure cache read — NEVER touches the banking API. Safe for
        unbounded polling while a refresh is in flight.
        """
        now = dt_util.now()
        cache_age_seconds: int | None = None
        cache_is_stale: bool = False
        if self._last_refresh:
            cache_age_seconds = int((now - self._last_refresh).total_seconds())
            cache_is_stale = cache_age_seconds > self._CACHE_STALE_THRESHOLD_SECONDS
        return {
            "is_refreshing": self._refresh_in_flight,
            "last_refresh": (self._last_refresh.isoformat() if self._last_refresh else None),
            "cache_age_seconds": cache_age_seconds,
            "cache_is_stale": cache_is_stale,
            "rate_limited_until": (
                self._rate_limited_until.isoformat() if self.rate_limited_until else None
            ),
            "stats": dict(self._last_refresh_stats),
            "account_count": len(self._accounts),
            "transaction_count": len(self._transactions),
            "has_cache": bool(self._transactions) or bool(self._balances),
            "demo_mode": self._demo_mode,
            # Expose the daily rate-limit cap so the frontend can render
            # the "4/day" label dynamically instead of hardcoding it.
            "rate_limit_per_day": ENABLEBANKING_RATE_LIMIT_DAILY,
            # Retired compatibility fields: opening the panel never fetches
            # (only the explicit import, setup and the daily schedule do).
            # Kept as constants so an older frontend simply skips auto-refresh.
            "auto_refresh_on_open": False,
            "auto_refresh_max_age_seconds": 0,
        }

    # ------------------------------------------------------------------
    # Budget plan — the migrated spreadsheet model
    # ------------------------------------------------------------------

    @property
    def budget_plan(self) -> BudgetPlan:
        """The current budget plan (empty until imported or entered)."""
        return self._plan_store.plan

    def _split_options(self) -> tuple[str, str, dict[str, float]]:
        """Split configuration from the config entry options."""
        return (
            self._entry.options.get("split_model", DEFAULT_SPLIT_MODEL),
            self._entry.options.get("remainder_mode", "none"),
            self._entry.options.get("custom_ratios", {}) or {},
        )

    async def async_import_spreadsheet(self, path: str) -> dict[str, Any]:
        """Import a household workbook into the budget plan.

        Runs the blocking openpyxl parse in an executor so the event loop is
        never held. Replaces the plan wholesale — an import is a migration, not
        a merge, so a partially parsed workbook cannot leave a hybrid plan.

        Returns the import report (counts and warnings only, never amounts).
        """
        return await self._async_import_workbook(path)

    async def async_import_spreadsheet_bytes(self, data: bytes) -> dict[str, Any]:
        """Import a household workbook from raw ``.xlsx`` bytes.

        Used by the upload and the Google Sheets import — the bytes are parsed
        in memory and never written to disk.
        """
        return await self._async_import_workbook(data)

    async def _async_import_workbook(self, source: str | bytes) -> dict[str, Any]:
        """Parse a workbook in the executor and replace the plan with it."""
        from ..spreadsheet_import import parse_workbook

        plan, report = await self._hass.async_add_executor_job(parse_workbook, source)
        await self._plan_store.async_save(plan)
        _LOGGER.info(
            "Budget plan replaced by spreadsheet import: %d positions, %d persons",
            len(plan.positions),
            len(plan.persons),
        )
        return report.to_dict()

    async def async_set_cost_position(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a single cost position."""
        plan = await self._plan_store.async_load()
        position = CostPosition.from_dict(data)
        if not position.name:
            raise ValueError("A cost position needs a name")
        plan.upsert_position(position)
        await self._plan_store.async_save(plan)
        return position.to_dict()

    async def async_delete_cost_position(self, position_id: str) -> bool:
        """Delete a cost position by id."""
        plan = await self._plan_store.async_load()
        removed = plan.remove_position(position_id)
        if removed:
            await self._plan_store.async_save(plan)
        return removed

    async def async_set_income(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create or update one person's income entry.

        Fields missing from ``data`` keep their stored value, so the plan
        wizard can set the deposit without wiping insurance or tax adjustments.
        """
        from ..budget_plan import IncomeEntry

        plan = await self._plan_store.async_load()
        current = plan.income.get(str(data.get("person") or ""))
        entry = IncomeEntry.from_dict({**(current.to_dict() if current else {}), **data})
        if not entry.person:
            raise ValueError("An income entry needs a person")
        plan.set_income(entry)
        await self._plan_store.async_save(plan)
        return entry.to_dict()

    # ------------------------------------------------------------------
    # Pots + home screen (cache reads only)
    # ------------------------------------------------------------------

    @property
    def pots(self) -> list[Pot]:
        """All pots (empty until loaded)."""
        return self._pot_store.pots

    def resolve_person(self, user: Any) -> str | None:
        """Person the logged-in HA user maps to (via account ``ha_users``)."""
        from ..home import resolve_person

        return resolve_person(user, self._accounts, self.persons)

    @property
    def persons(self) -> list[dict[str, Any]]:
        """Configured persons (``name`` + ``ha_users``) from the config entry."""
        return list(self._entry.data.get("persons", []) or [])

    def get_assignments(self, users: list[Any]) -> dict[str, Any]:
        """Persons, HA users and account owners for the settings screen (cache only).

        Never exposes more than the last four IBAN digits.
        """
        persons = [
            {
                "name": str(p.get("name") or ""),
                "display_name": str(p.get("display_name") or "") or str(p.get("name") or ""),
                "ha_users": [str(i) for i in p.get("ha_users") or []],
            }
            for p in self.persons
        ]
        mapped = {i for p in persons for i in p["ha_users"]}
        # Device and service logins (MQTT, a wall tablet) are ordinary active
        # users to HA.  When the install has person entities, only users
        # linked to one are people; without any, every active user may be.
        person_users = {
            str(s.attributes.get("user_id"))
            for s in self._hass.states.async_all("person")
            if s.attributes.get("user_id")
        }
        ha_users = []
        for u in users:
            uid = str(getattr(u, "id", "") or "")
            if getattr(u, "system_generated", False):
                suggested, reason = False, "system"
            elif not getattr(u, "is_active", True):
                suggested, reason = False, "inactive"
            elif uid in mapped:
                suggested, reason = True, "person"
            elif person_users and uid not in person_users:
                suggested, reason = False, "no_person"
            else:
                suggested, reason = True, "active_user"
            ha_users.append(
                {
                    "id": uid,
                    "name": str(getattr(u, "name", "") or ""),
                    "is_admin": bool(getattr(u, "is_admin", False)),
                    "suggested": suggested,
                    "reason": reason,
                }
            )
        accounts = []
        for acc in self._accounts:
            iban = normalize_iban(acc.get("iban"))
            institution = str(acc.get("institution") or "")
            owner_set = owner_set_label(acc)
            accounts.append(
                {
                    "key": account_key(acc),
                    "name": str(acc.get("custom_name") or acc.get("name") or institution),
                    "institution": institution,
                    "iban_last4": iban[-4:] if iban else "",
                    "owner": owner_set["owner"],
                    "household": owner_set["household"],
                    "owner_kind": account_kind(acc),
                }
            )
        return {
            "persons": persons,
            "ha_users": ha_users,
            "accounts": accounts,
            "plan_persons": list(self.budget_plan.persons),
        }

    def async_set_assignments(self, data: dict[str, Any], users: list[Any]) -> bool:
        """Validate and persist persons + account owner sets. Raises ``AssignmentError``.

        An account's owner set is ``owner`` (person | "shared" | "") plus the
        optional ``household`` flag, which only a person may carry
        ({person}, {person, household}, {household}, nothing -- no other set).
        Returns True when an owner set changed: the caller then re-derives the
        stored bookings (:meth:`async_apply_owner_change`, no bank call).
        """
        if self._demo_mode:
            raise AssignmentError("demo_mode", "Not available in demo mode")
        known_users = {str(getattr(u, "id", "")) for u in users}
        raw_persons = data.get("persons")
        raw_accounts = data.get("accounts")
        if not isinstance(raw_persons, list) or not isinstance(raw_accounts, list):
            raise AssignmentError("invalid_body", "persons and accounts must be lists")

        persons: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        seen_users: set[str] = set()
        for item in raw_persons:
            if not isinstance(item, dict):
                raise AssignmentError("invalid_person", "Person must be an object")
            name = str(item.get("name") or "").strip()
            if not name or len(name) > 40:
                raise AssignmentError("invalid_person_name", "Name must be 1-40 characters")
            if name.lower() == "shared" or name.lower() in seen_names:
                raise AssignmentError("duplicate_person", "Duplicate or reserved person name")
            seen_names.add(name.lower())
            ids = item.get("ha_users") or []
            if not isinstance(ids, list):
                raise AssignmentError("invalid_ha_users", "ha_users must be a list")
            clean: list[str] = []
            for uid in (str(i) for i in ids):
                if uid not in known_users:
                    raise AssignmentError("unknown_ha_user", "Unknown HA user id")
                if uid in seen_users:
                    raise AssignmentError("ha_user_reused", "A user maps to one person only")
                seen_users.add(uid)
                clean.append(uid)
            record: dict[str, Any] = {"name": name, "ha_users": clean}
            # ``name`` is the stable key everywhere; the nickname is display only.
            kept_nick = next((p for p in self.persons if p.get("name") == name), {})
            nick = item.get("display_name", kept_nick.get("display_name"))
            nick = str(nick or "").strip()
            if len(nick) > 40:
                raise AssignmentError("invalid_display_name", "Nickname must be at most 40 characters")
            if nick and nick != name:
                record["display_name"] = nick
            # The wizard's confirmed payday belongs to the person; keep it.
            kept = next((p for p in self.persons if p.get("name") == name and p.get("payday")), None)
            if kept:
                record["payday"] = kept["payday"]
            persons.append(record)
        by_name = {p["name"]: p for p in persons}

        base = self._entry.data.get("accounts", []) or []
        keys = {account_key(a) for a in base}
        owners: dict[str, tuple[str, bool]] = {}
        for item in raw_accounts:
            if not isinstance(item, dict):
                raise AssignmentError("invalid_account", "Account must be an object")
            key = str(item.get("key") or "")
            owner = str(item.get("owner") or "").strip()
            if key not in keys:
                raise AssignmentError("unknown_account", "Unknown account key")
            if owner not in ("", "shared") and owner not in by_name:
                raise AssignmentError("unknown_owner", "Owner must be shared or a person")
            household = item.get("household", False)
            if not isinstance(household, bool):
                raise AssignmentError("invalid_household", "household must be a boolean")
            if household and owner in ("", "shared"):
                raise AssignmentError(
                    "invalid_owner_set",
                    "Allowed: one person, one person + household, or household only",
                )
            owners[key] = (owner, household)

        new_accounts = []
        changed = False
        for acc in base:
            acc = dict(acc)
            key = account_key(acc)
            if key in owners:
                owner, household = owners[key]
                before = (account_kind(acc), acc.get("person") or "")
                acc = apply_owner_set(acc, owner, household)
                if owner and owner != "shared":
                    acc["ha_users"] = list(by_name[owner]["ha_users"])
                changed = changed or before != (account_kind(acc), acc.get("person") or "")
            new_accounts.append(acc)

        self._hass.config_entries.async_update_entry(
            self._entry, data={**self._entry.data, "persons": persons, "accounts": new_accounts}
        )
        self._accounts = new_accounts
        return changed

    async def async_apply_owner_change(self) -> None:
        """Re-derive every stored booking after an owner set changed (C5).

        Replays the ledger through the derive step -- never a bank call. Rules
        and corrections live in the merchant memory and so stay untouched.
        """
        if not getattr(self, "_ledger", None):
            return
        self._derive_from_ledger(self._transfer_overrides)
        refresh = getattr(self, "_async_refresh_contract_categories", None)
        if refresh is not None:
            await refresh()
        await self._push_coordinator()

    async def async_save_pot(self, data: dict[str, Any], *, replace: bool) -> dict[str, Any]:
        """Create (``replace=False``) or replace a pot. Raises ``ValueError``/``KeyError``."""
        # Server-side id on create, never client-chosen.
        pot = Pot.from_dict({**data, "id": data.get("id") if replace else ""})
        saved = await self._pot_store.async_upsert(pot, replace_existing=replace)
        return saved.to_dict()

    async def async_set_pot_carry(self, pot_id: str, action: str) -> dict[str, Any] | None:
        """Accept or drop the current week's carry-over of a pot (idempotent per week).

        Returns the decision (``week_start``, ``action``) or ``None`` for an unknown pot.
        """
        from ..pots import week_bounds

        week_start = week_bounds(dt_util.now().date())[0]
        if not await self._pot_store.async_set_carry_decision(pot_id, week_start, action):
            return None
        return {"pot_id": pot_id, "week_start": week_start.isoformat(), "action": action}

    async def async_delete_pot(self, pot_id: str) -> bool:
        """Delete a pot by id."""
        return await self._pot_store.async_delete(pot_id)

    def get_home(
        self,
        *,
        person: str | None,
        view: str,
        horizon: str,
        demo: bool = False,
        include_questions: bool = False,
        include_recent: bool = False,
    ) -> dict[str, Any]:
        """Home-screen payload from cached data. Never contacts a bank."""
        from ..home import build_home

        now = dt_util.now()
        if demo or self._demo_mode:
            from ..demo import generate_demo_home

            return generate_demo_home(
                person=person, view=view, horizon=horizon, now=now, include_recent=include_recent
            )
        banks = self.get_bank_status()
        return build_home(
            **(self._question_kwargs() if hasattr(self, "_question_kwargs") else {}),
            include_questions=include_questions,
            include_recent=include_recent,
            accounts=self._accounts,
            persons=self.persons,
            transactions=self._transactions,
            refund_allocations=_refund_allocations(self),
            plan=self.budget_plan,
            pots=self.pots,
            recurring=self._recurring_patterns,
            banks=banks,
            as_of=self._last_refresh,
            now=now,
            person=person,
            view=view,
            horizon=horizon,
        )

    def get_household_summary(
        self, *, cycle: str = "current", person: str | None = None, is_admin: bool = False
    ) -> dict[str, Any]:
        """Per-cycle household figures from cached data. Never contacts a bank."""
        from ..household_summary import build_household_summary

        return build_household_summary(
            accounts=self._accounts,
            transactions=self._transactions,
            plan=self.budget_plan,
            recurring=self._recurring_patterns,
            now=dt_util.now(),
            cycle=cycle,
            viewer_person=person,
            is_admin=is_admin,
            refund_allocations=_refund_allocations(self),
            as_of=self._last_refresh,
            persons=self.persons,
        )

    async def _net_matched_refunds(
        self, txns: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """``txns`` (default: all counted) with every refund netted into its expense."""
        from ..labels import async_get_label_store
        from ..refund_store import async_get_refund_store

        try:
            await async_get_refund_store(self._hass)
            await async_get_label_store(self._hass)
        except Exception:  # noqa: BLE001 - the summary must not depend on the refund hint
            _LOGGER.debug("Refund inputs unavailable", exc_info=True)
        if txns is None:
            return self._counted_view()
        return net_counted(txns, _refund_allocations(self))

    def get_refund_analysis(self) -> dict[str, Any]:
        """Refund matches (#119) from cache and the stores the API views loaded.

        Pure computation, never a bank call; a failure leaves the figures as
        they were rather than breaking the summary.
        """
        from ..refund_matcher import analyse

        data = self._hass.data.get(DOMAIN, {})
        refunds, labels = data.get("_refund_store"), data.get("_label_store")
        try:
            # A PayPal mirror or chain leg never counts, so it must not attract a refund.
            return analyse(
                counted_transactions(self._transactions, getattr(self, "_accounts", None) or []),
                manual=refunds.manual if refunds else None,
                labels=labels.bookings if labels else None,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Refund matching failed", exc_info=True)
            return {"allocations": {}, "proposals": [], "confidence": {}}

    def get_budget_plan_view(
        self, month: int | None = None, year: int | None = None
    ) -> dict[str, Any]:
        """Full plan snapshot for the given month — pure cache read.

        This is the API shape behind the ledger, income and split cards. It
        mirrors the three spreadsheet sheets: income breakdown, cost ledger,
        and the resulting split.
        """
        now = dt_util.now()
        target_month = month or now.month
        target_year = year or now.year
        plan = self.budget_plan

        split_mode, remainder_mode, custom_ratios = self._split_options()
        model, shared_costs = model_from_plan(
            plan,
            target_month,
            target_year,
            split_mode=split_mode,
            remainder_mode=remainder_mode,
            custom_ratios=custom_ratios,
        )
        results = model.calculate_split(shared_costs)

        return {
            "month": target_month,
            "year": target_year,
            "source": plan.source,
            "is_empty": plan.is_empty(),
            "persons": plan.persons,
            "income": [
                {
                    "person": person,
                    "deposit": plan.income[person].deposit if person in plan.income else 0.0,
                    "insurance_mandatory": (
                        plan.income[person].insurance_mandatory if person in plan.income else 0.0
                    ),
                    "tax_adjustment": (
                        plan.income[person].tax_adjustment if person in plan.income else 0.0
                    ),
                    "net": plan.income_net(person),
                    "share": round(plan.income_rel(person) * 100, 2),
                }
                for person in plan.persons
            ],
            "income_net_total": plan.income_net_total(),
            "positions": [
                {
                    **position.to_dict(),
                    "planned_amount": position.planned_amount,
                    "effective_amount": position.effective_amount(target_month, target_year),
                    "is_active": position.is_active(target_month, target_year),
                }
                for position in plan.positions
            ],
            "costs": {
                "shared": plan.cost_shared(target_month, target_year),
                "individual": {
                    person: plan.cost_individual(person, target_month, target_year)
                    for person in plan.persons
                },
                "grand_total": plan.cost_grand_total(target_month, target_year),
                "shared_fixed": plan.fixed_total(target_month, target_year, OWNER_SHARED),
                "shared_buffer": plan.buffer_total(target_month, target_year, OWNER_SHARED),
                "by_category": plan.category_totals(target_month, target_year),
            },
            "split": {
                "model": split_mode,
                "members": [
                    {
                        "person": r.person,
                        "net_income": r.net_income,
                        "income_share": round(r.income_ratio * 100, 2),
                        "shared_costs_share": r.shared_costs_share,
                        "remainder_share": r.remainder_share,
                        "individual_costs": r.individual_costs,
                        "spielgeld": r.spielgeld,
                    }
                    for r in results
                ],
                "spielgeld_total": round(sum(r.spielgeld for r in results), 2),
            },
        }

    def get_transfer_plan(
        self, month: int | None = None, year: int | None = None
    ) -> dict[str, Any]:
        """The monthly transfer choreography — pure cache read.

        Reproduces the spreadsheet's account-by-account transfer ledger and
        reports whether every pass-through account nets to zero.
        """
        now = dt_util.now()
        target_month = month or now.month
        target_year = year or now.year
        plan = self.budget_plan

        split_mode, remainder_mode, custom_ratios = self._split_options()
        model, shared_costs = model_from_plan(
            plan,
            target_month,
            target_year,
            split_mode=split_mode,
            remainder_mode=remainder_mode,
            custom_ratios=custom_ratios,
        )
        results = model.calculate_split(shared_costs)

        return build_transfer_plan(
            plan,
            self._accounts,
            target_month,
            target_year,
            split_results=results,
        ).to_dict()

    def get_plan_vs_actual(
        self, month: int | None = None, year: int | None = None
    ) -> dict[str, Any]:
        """Compare planned positions against what the bank actually booked.

        Matching happens on two levels because neither alone is reliable:

        - **per category**, which always adds up but is coarse
        - **per position**, by matching the distinctive words of a position
          name against the transaction text; unmatched positions are reported
          as such rather than silently showing 0

        Amounts are normalised to the plan's sign convention (expense
        positive), so plan and actual are directly comparable.
        """
        from ..budget_plan import actual_amount_to_plan_sign

        plan = self.budget_plan
        counted = self._counted_view()
        window, target_month, target_year, period = self._period(counted, month, year)
        start, end = window

        # The same bookings as every other total: movement and income never
        # reach a cost row, a credit nets inside its category.
        booked = [
            txn
            for txn in counted
            if (day := effective_day(txn)) is not None
            and start <= day <= end
            and not is_income_line(txn)
        ]

        actual_by_category: dict[str, float] = {}
        for txn in booked:
            amount = actual_amount_to_plan_sign(
                float(txn.get("transactionAmount", {}).get("amount", 0) or 0)
            )
            category = txn.get("category", "other")
            actual_by_category[category] = round(actual_by_category.get(category, 0.0) + amount, 2)

        planned_by_category = plan.category_totals(target_month, target_year)

        active = plan.active_positions(target_month, target_year)
        assigned = assign_positions(booked, active, plan_persons(plan, self._accounts))

        positions: list[dict[str, Any]] = []
        for position in active:
            matched = assigned.get(position.id, [])
            actual = round(
                sum(
                    actual_amount_to_plan_sign(
                        float(t.get("transactionAmount", {}).get("amount", 0) or 0)
                    )
                    for t in matched
                ),
                2,
            )
            planned = position.effective_amount(target_month, target_year)
            positions.append(
                {
                    "id": position.id,
                    "name": position.name,
                    "owner": position.owner,
                    "category": position.category,
                    "planned": planned,
                    "actual": actual if matched else None,
                    "delta": round(actual - planned, 2) if matched else None,
                    "match_count": len(matched),
                }
            )

        categories = sorted(set(planned_by_category) | set(actual_by_category))
        return {
            "month": target_month,
            "year": target_year,
            "period": period,
            "has_actuals": bool(booked),
            "categories": [
                {
                    "category": category,
                    "planned": planned_by_category.get(category, 0.0),
                    "actual": actual_by_category.get(category, 0.0),
                    "delta": round(
                        actual_by_category.get(category, 0.0)
                        - planned_by_category.get(category, 0.0),
                        2,
                    ),
                }
                for category in categories
            ],
            "positions": positions,
            "unmatched_positions": sum(1 for p in positions if p["actual"] is None),
        }

    async def async_get_benchmarks(
        self, month: int | None = None, year: int | None = None
    ) -> dict[str, Any]:
        """Compare our own plan against the bundled German benchmark dataset.

        The spreadsheet compared four hand-maintained figures against values
        copied out of Destatis/Statista once. Here the "ours" side is computed
        from the plan and the reference side comes from
        :class:`~.benchmark.BenchmarkProvider`, which reads the versioned dataset
        shipped with the integration (no runtime fetch). Location (state,
        postcode) comes from the options, household size from the plan persons -
        each value falls back to the finest level the dataset carries.

        Percentage metrics are expressed as a share of pooled net income, which
        is the basis the spreadsheet used. Absolute metrics (EUR) are compared
        directly. Metrics whose numerator is zero are omitted rather than shown
        as "0% — better than average".
        """
        from ..benchmark import BenchmarkProvider

        if self._benchmark_provider is None:
            provider = BenchmarkProvider(self._hass)
            await provider.async_initialize()
            self._benchmark_provider = provider
        provider = self._benchmark_provider

        now = dt_util.now()
        target_month = month or now.month
        target_year = year or now.year
        plan = self.budget_plan
        income = plan.income_net_total()
        by_category = plan.category_totals(target_month, target_year)
        options = self._entry.options
        location = dict(
            state=options.get(OPT_BENCHMARK_STATE),
            postcode=options.get(OPT_BENCHMARK_POSTCODE),
            household_size=len(plan.persons) or None,
        )

        comparisons: list[dict[str, Any]] = []
        for metric_category, source_categories in BENCHMARK_METRIC_SOURCES.items():
            numerator = round(sum(by_category.get(c, 0.0) for c in source_categories), 2)
            if numerator <= 0:
                continue
            benchmark = provider.get_benchmark_for_category(metric_category, **location)
            if not benchmark:
                continue
            if benchmark.get("unit") == "%":
                if income <= 0:
                    continue
                our_value = round(numerator / income * 100, 2)
            else:
                our_value = numerator
            result = provider.compare(metric_category, our_value, **location)
            if result:
                result["our_amount"] = numerator
                result["source_categories"] = source_categories
                comparisons.append(result)

        # Consumption metrics cannot be derived from banking data — the utility
        # statement is the only source. Kept as an explicit option so the
        # spreadsheet's water comparison survives the migration instead of
        # being silently dropped.
        water_ratio = self._entry.options.get(OPT_WATER_RATIO)
        if water_ratio:
            try:
                value = float(water_ratio)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                comparisons.append(
                    {
                        "label": "Kaltwasser",
                        "category": "water",
                        "user_value": value,
                        "benchmark_value": DEFAULT_WATER_BENCHMARK,
                        "difference": round(value - DEFAULT_WATER_BENCHMARK, 2),
                        "better": value < DEFAULT_WATER_BENCHMARK,
                        "unit": "x Ø",
                        "statistic": "manual",
                        "source": "Nebenkostenabrechnung (manuell gepflegt)",
                        "survey_year": target_year,
                        "fetch_date": "manual",
                        "text": (
                            f"Kaltwasser: {value:.2f}x "
                            f"(DE Ø {DEFAULT_WATER_BENCHMARK:.2f}x, Nebenkostenabrechnung)"
                        ),
                        "manual": True,
                    }
                )

        return {
            "month": target_month,
            "year": target_year,
            "income_net_total": income,
            "comparisons": comparisons,
            "references": provider.references(**location),
            "unavailable": provider.unavailable(),
            "dataset": provider.dataset_info(),
            "location": location,
            "has_plan": not plan.is_empty(),
        }

    # ------------------------------------------------------------------
    # Transfer chain management
    # ------------------------------------------------------------------

    async def async_confirm_transfer_chain(self, chain_id: str, confirmed: bool) -> None:
        """Confirm or reject a detected transfer chain.

        Args:
            chain_id: The chain UUID to confirm/reject
            confirmed: True = user agrees it's a chain, False = reject
        """
        self._transfer_overrides[chain_id] = confirmed
        await self._transfer_override_store.async_save(self._transfer_overrides)
        # Apply to in-memory transactions immediately
        apply_overrides(self._transactions, self._transfer_overrides)
        _LOGGER.info(
            "Transfer chain %s %s",
            chain_id,
            "confirmed" if confirmed else "rejected",
        )

    def get_transfer_chains(self) -> list[dict[str, Any]]:
        """Return detected transfer chains for API/frontend display."""
        chains: dict[str, dict[str, Any]] = {}
        for txn in self._transactions:
            chain_id = txn.get("_transfer_chain_id")
            if not chain_id:
                continue

            if chain_id not in chains:
                chains[chain_id] = {
                    "chain_id": chain_id,
                    "confidence": txn.get("_transfer_confidence", 0),
                    "confirmed": txn.get("_transfer_confirmed"),
                    "transactions": [],
                }

            amount = float(txn.get("transactionAmount", {}).get("amount", 0))
            chains[chain_id]["transactions"].append(
                {
                    "transactionId": txn.get("transactionId", ""),
                    "role": txn.get("_transfer_role", ""),
                    "account_name": txn.get("_account_name", ""),
                    "amount": amount,
                    "date": effective_date_str(txn),
                    "creditor": txn.get("creditorName", ""),
                    "description": txn.get("remittanceInformationUnstructured", ""),
                }
            )

        return list(chains.values())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_household(
        self,
        monthly_txns: list[dict[str, Any]],
        total_expenses: float,
        month: int | None = None,
        year: int | None = None,
    ) -> dict[str, Any] | None:
        """Build household split data for the monthly summary.

        Prefers the budget PLAN when one exists: the plan states each person's
        income and each position's owner explicitly, which the transaction
        stream cannot. Deriving ownership from "which account was debited"
        mis-assigns every position whose payment account differs from its owner
        — a shared subscription billed onward, or one person's contract paid
        from the joint account.

        Falls back to the transaction-derived estimate only when no plan has
        been imported yet, so a fresh install still shows something.
        """
        plan = self.budget_plan
        if not plan.is_empty() and plan.persons:
            now = dt_util.now()
            target_month = month or now.month
            target_year = year or now.year
            split_mode, remainder_mode, custom_ratios = self._split_options()
            model, shared_costs = model_from_plan(
                plan,
                target_month,
                target_year,
                split_mode=split_mode,
                remainder_mode=remainder_mode,
                custom_ratios=custom_ratios,
            )
            results = model.calculate_split(shared_costs)
            return {
                "members": [
                    {
                        "person": r.person,
                        "gross_income": round(r.gross_income, 2),
                        "net_income": round(r.net_income, 2),
                        "income_ratio": round(r.income_ratio * 100, 1),
                        "shared_costs_share": round(r.shared_costs_share, 2),
                        "remainder_share": round(r.remainder_share, 2),
                        "individual_costs": round(r.individual_costs, 2),
                        "spielgeld": round(r.spielgeld, 2),
                        "bonus_amount": round(r.bonus_amount, 2),
                    }
                    for r in results
                ],
                "split_model": split_mode,
                "remainder_mode": remainder_mode,
                "total_shared_costs": round(shared_costs, 2),
                "spielgeld_total": round(sum(r.spielgeld for r in results), 2),
                "source": "plan",
            }

        return self._household_from_transactions(monthly_txns)

    def _household_from_transactions(
        self,
        monthly_txns: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Estimate the household split from transactions alone.

        Used only before a budget plan exists. Ownership is inferred from the
        debited account, which is an approximation — the plan replaces it.
        """
        # Build person map from account config
        persons: dict[str, dict[str, Any]] = {}
        for acc in self._accounts:
            person = acc.get("person", "")
            if not person:
                continue
            if person not in persons:
                persons[person] = {
                    "income": 0.0,
                    "individual_costs": 0.0,
                    "account_ids": [],
                    "acc_type": acc.get("type", "personal"),
                }
            persons[person]["account_ids"].append(acc.get("id", ""))

        if not persons:
            return None

        # Sum income and costs per person from their transactions
        shared_costs = 0.0
        shared_cost_items: list[dict[str, Any]] = []

        for txn in monthly_txns:
            amount = float(txn.get("transactionAmount", {}).get("amount", 0))
            acc_type = txn.get("_account_type", "personal")
            person = txn.get("_account_person", "")
            category = txn.get("category", "other")

            if acc_type == "shared":
                # Shared account — costs are split among all members
                if amount < 0:
                    shared_costs += abs(amount)
                    shared_cost_items.append(
                        {
                            "category": category,
                            "amount": amount,
                        }
                    )
            elif person and person in persons:
                if amount > 0:
                    persons[person]["income"] += amount
                else:
                    persons[person]["individual_costs"] += abs(amount)

        # Build HouseholdMembers
        members = []
        for name, data in persons.items():
            members.append(
                HouseholdMember(
                    name=name,
                    net_income=data["income"],
                    gross_income=data["income"],
                    individual_costs=data["individual_costs"],
                    account_ids=data["account_ids"],
                )
            )

        split_mode, remainder_mode, custom_ratios = self._split_options()

        model = HouseholdModel(
            members=members,
            split_mode=split_mode,
            remainder_mode=remainder_mode,
            custom_ratios=custom_ratios,
        )

        results = model.calculate_split(shared_costs, shared_cost_items or None)

        return {
            "members": [
                {
                    "person": r.person,
                    "gross_income": round(r.gross_income, 2),
                    "net_income": round(r.net_income, 2),
                    "income_ratio": round(r.income_ratio * 100, 1),
                    "shared_costs_share": round(r.shared_costs_share, 2),
                    "individual_costs": round(r.individual_costs, 2),
                    "spielgeld": round(r.spielgeld, 2),
                    "bonus_amount": round(r.bonus_amount, 2),
                }
                for r in results
            ],
            "split_model": split_mode,
            "remainder_mode": remainder_mode,
            "total_shared_costs": round(shared_costs, 2),
            "spielgeld_total": round(sum(r.spielgeld for r in results), 2),
            "source": "transactions",
        }

    def _check_budget_limits(self, category_totals: dict[str, float]) -> None:
        """Check if any category exceeds its budget limit and fire events."""
        from ..events import fire_budget_exceeded

        for category, amount in category_totals.items():
            if amount >= 0:
                continue  # Only check expense categories
            actual = abs(amount)
            entity_id = f"number.fd_budget_{category}"
            state = self._hass.states.get(entity_id)
            if state is None:
                continue
            try:
                limit = float(state.state)
            except (ValueError, TypeError):
                continue
            if limit > 0 and actual > limit:
                fire_budget_exceeded(
                    self._hass,
                    category=category,
                    limit=limit,
                    actual=actual,
                )
