"""Finance Dashboard — Home Assistant Integration.

Provides a secure finance overview with live banking data via the Enable
Banking PSD2 Open Banking API (JWT-signed RS256). Tracks accounts,
transactions, and household budgets.

SECURITY: No financial data is ever stored in git or logs.
All credentials and tokens are stored in HA's encrypted .storage/ directory.
Live banking calls happen on explicit user-triggered paths (refresh button,
service call, setup bootstrap) plus exactly ONE scheduled refresh per day.
That spends a quarter of Enable Banking's 4/day/ASPSP budget and keeps the
data at most a day old; anything more frequent remains forbidden.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change

from .const import (
    DEFAULT_DAILY_REFRESH,
    DEFAULT_DAILY_REFRESH_HOUR,
    DEFAULT_DAILY_REFRESH_MINUTE,
    DOMAIN,
    OPT_DAILY_REFRESH,
    OPT_DAILY_REFRESH_HOUR,
    OPT_DAILY_REFRESH_MINUTE,
    SERVICE_TOGGLE_DEMO,
)
from .runtime import FinanceDashboardData

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
]

_LOGGER = logging.getLogger(__name__)

type FinanceDashboardConfigEntry = ConfigEntry[FinanceDashboardData]


def _structure_signature(entry: ConfigEntry) -> tuple:
    """What forces a reload: the set of banks and accounts, not the options."""
    import json

    from .account_identity import account_key

    subs = getattr(entry, "subentries", None) or {}
    banks = tuple(
        sorted(
            (sid, json.dumps(dict(sub.data), sort_keys=True, default=str))
            for sid, sub in subs.items()
        )
    )
    accounts = tuple(sorted(account_key(a) for a in entry.data.get("accounts", [])))
    return (banks, accounts)


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Finance Dashboard integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FinanceDashboardConfigEntry) -> bool:
    """Set up Finance Dashboard from a config entry."""
    # Initialize the manager (core business logic)
    from .manager import FinanceDashboardManager
    from .taxonomy_migration import async_migrate_taxonomy

    # Legacy category slugs -> life areas (#112), once, before any store loads.
    try:
        await async_migrate_taxonomy(hass, entry.entry_id)
    except Exception:  # noqa: BLE001 - a failed migration must not block setup
        _LOGGER.exception("Category migration failed; legacy slugs kept")

    manager = FinanceDashboardManager(hass, entry)
    await manager.async_initialize()

    # Installs that predate bank subentries: turn the single stored session
    # into one bank subentry.  Never blocks setup — the virtual legacy bank
    # keeps working if this cannot run.
    try:
        await manager.async_migrate_legacy_session()
        manager.async_adopt_subentry_accounts()
        await manager.async_prune_orphan_sessions()
        await manager.async_update_consent_issues()
    except Exception:
        _LOGGER.exception("Bank migration / consent check failed — continuing setup")

    # Create the coordinator — single source of truth for all entities.
    # Entities read from coordinator.data instead of calling the API directly.
    from .coordinator import FinanceDashboardCoordinator

    coordinator = FinanceDashboardCoordinator(hass, manager, entry)

    # Initialize demo mode from options
    if entry.options.get("demo_mode", False):
        manager.set_demo_mode(True)

    entry.runtime_data = FinanceDashboardData(manager=manager, coordinator=coordinator)
    # The HTTP views still resolve the manager through hass.data.
    hass.data[DOMAIN][entry.entry_id] = manager
    hass.data[DOMAIN][f"{entry.entry_id}_coordinator"] = coordinator
    hass.data[DOMAIN]["entry"] = entry

    # Register services (pass coordinator so refresh service can push updates)
    await _async_register_services(hass, manager, coordinator)

    # Register frontend: static mount, sidebar panel, auto-loaded cards
    from .panel import async_register_panel

    await async_register_panel(hass)

    # Register HTTP endpoints
    from .api import async_register_api

    await async_register_api(hass)

    # Reconcile the entity registry BEFORE platforms register entities:
    # migrate uid-derived unique_ids to the stable account key and drop
    # balance entities left behind by earlier re-links.  Doing this after
    # forwarding would race the platform into recreating them.
    from .account_identity import async_reconcile_account_entities

    try:
        stats = await async_reconcile_account_entities(hass, entry, DOMAIN)
        if stats["migrated"] or stats["removed"]:
            _LOGGER.info(
                "Account entities reconciled — %d migrated, %d duplicates removed",
                stats["migrated"],
                stats["removed"],
            )
    except Exception:
        # Never block setup over registry housekeeping.
        _LOGGER.exception("Account entity reconciliation failed — continuing setup")

    # Forward platform setup — sensors/numbers/selects will register themselves
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Load cached data into coordinator — NO external API calls.
    # Entities are populated immediately from the transaction cache
    # that was loaded in manager.async_initialize(). The user must
    # click "Aktualisieren" to trigger real banking API calls.
    # Run for ALL entry states (configured / pending / demo) so sensors
    # always have a valid coordinator snapshot — without this,
    # half-configured setups leave entities permanently "unavailable"
    # until a full HA restart.
    async def _initial_load() -> None:
        try:
            await coordinator.async_load_cached()
            _LOGGER.info("Initial cached data loaded (no API calls)")
        except Exception:
            _LOGGER.exception("Initial cached data load failed")

    if hass.is_running:
        hass.async_create_task(_initial_load())
    else:
        # The listener MUST be a coroutine function. A sync lambda calling
        # hass.async_create_task is invoked from a worker thread, which trips
        # HA's thread-safety guard: the guard raises, the coroutine is never
        # awaited, and the cache is never loaded — leaving every entity empty
        # after each restart until a manual refresh. HA awaits async listeners
        # itself, so no task creation is needed.
        async def _on_hass_started(_event) -> None:
            await _initial_load()

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_hass_started)

    _register_daily_refresh(hass, entry, manager, coordinator)

    # Banks / accounts added, removed or re-linked change which devices and
    # entities exist; options changes (selects write them) must not reload.
    signature = _structure_signature(entry)

    async def _reload_on_structure_change(hass_: HomeAssistant, updated: ConfigEntry) -> None:
        if _structure_signature(updated) != signature:
            _LOGGER.info("Banks or accounts changed — reloading Finance Dashboard")
            hass_.config_entries.async_schedule_reload(updated.entry_id)

    entry.async_on_unload(entry.add_update_listener(_reload_on_structure_change))

    _LOGGER.info("Finance Dashboard v%s loaded", entry.version)
    return True


def _register_daily_refresh(
    hass: HomeAssistant,
    entry: FinanceDashboardConfigEntry,
    manager,
    coordinator,
) -> None:
    """Schedule exactly one live refresh per day.

    Enable Banking allows 4 calls per day per ASPSP. One scheduled refresh
    spends a quarter of that budget and leaves three for manual refreshes,
    which keeps the data at most a day old without ever polling. Anything more
    frequent is still forbidden.

    The schedule is skipped entirely in demo mode and while the entry is not
    fully configured, and a failure is logged without disturbing the entry.
    """
    if not entry.options.get(OPT_DAILY_REFRESH, DEFAULT_DAILY_REFRESH):
        _LOGGER.debug("Daily refresh disabled by options")
        return

    hour = int(entry.options.get(OPT_DAILY_REFRESH_HOUR, DEFAULT_DAILY_REFRESH_HOUR))
    minute = int(entry.options.get(OPT_DAILY_REFRESH_MINUTE, DEFAULT_DAILY_REFRESH_MINUTE))
    hour = min(max(hour, 0), 23)
    minute = min(max(minute, 0), 59)

    async def _daily_refresh(now) -> None:
        if manager.demo_mode:
            _LOGGER.debug("Daily refresh skipped — demo mode active")
            return
        # No global rate-limit gate: the budget is per bank, and the
        # scheduled fetch (background, no PSU headers) may use at most one of
        # a bank's four daily slots — a blocked or spent bank is skipped
        # inside the refresh, the others still run.
        try:
            await manager.async_refresh_transactions(scheduled=True)
            stats = manager.last_refresh_stats
            await coordinator.async_refresh()
            await manager.async_update_consent_issues()
            from .notify import async_after_refresh

            await async_after_refresh(hass, manager)  # exceptions + weekly digest
            _LOGGER.info(
                "Daily refresh done: outcome=%s accounts=%s transactions=%s new=%s",
                stats.get("outcome"),
                stats.get("accounts"),
                stats.get("transactions"),
                stats.get("new"),
            )
        except Exception:
            _LOGGER.exception("Daily refresh failed — cache left untouched")

    entry.async_on_unload(
        async_track_time_change(hass, _daily_refresh, hour=hour, minute=minute, second=0)
    )
    _LOGGER.info("Daily live refresh scheduled for %02d:%02d local time", hour, minute)


async def async_unload_entry(hass: HomeAssistant, entry: FinanceDashboardConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        manager = hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_coordinator", None)
        if manager:
            await manager.async_shutdown()
        # Last entry gone -> take the frontend down so a reload re-registers
        # cleanly and a removed integration leaves no dead sidebar item.
        if not any(
            e.entry_id != entry.entry_id and e.state is ConfigEntryState.LOADED
            for e in hass.config_entries.async_entries(DOMAIN)
        ):
            from .panel import async_unregister_panel

            await async_unregister_panel(hass)
        # Clean up entry reference if it matches
        if hass.data.get(DOMAIN, {}).get("entry") is entry:
            hass.data[DOMAIN].pop("entry", None)
    return unload_ok


async def _async_register_services(hass: HomeAssistant, manager, coordinator) -> None:
    """Register integration services."""
    from .const import (
        SERVICE_CATEGORIZE,
        SERVICE_EXPORT_CSV,
        SERVICE_GET_BALANCE,
        SERVICE_GET_SUMMARY,
        SERVICE_GET_TRANSFER_PLAN,
        SERVICE_IMPORT_SPREADSHEET,
        SERVICE_REFRESH_ACCOUNTS,
        SERVICE_REFRESH_TRANSACTIONS,
        SERVICE_REPROCESS_DATA,
        SERVICE_SET_BUDGET_LIMIT,
    )

    async def handle_refresh_accounts(call) -> dict:
        await manager.async_refresh_accounts()
        # Keep entity state in lockstep with the account metadata we
        # just refreshed — otherwise the next dashboard render reads
        # stale account data from the coordinator and the user sees
        # no change despite a successful service call.
        try:
            await coordinator.async_refresh()
        except Exception:
            _LOGGER.exception("Coordinator refresh after refresh_accounts failed")
        return manager.get_refresh_status()

    async def handle_refresh_transactions(call) -> dict:
        """User-triggered refresh — returns stats so automations and
        the frontend can surface "5 Konten, 243 Tx, 2 neu" instead
        of a silent OK.

        The documented ``days`` field is honoured. It used to be advertised in
        services.yaml and then ignored, so a caller asking for a year of history
        silently got the default window.
        """
        days = call.data.get("days")
        if days:
            await manager.async_refresh_transactions(days=int(days))
        else:
            await manager.async_refresh_transactions()
        # Push fresh data to all entities via coordinator
        await coordinator.async_refresh()
        return manager.get_refresh_status()

    async def handle_get_balance(call) -> dict:
        return await manager.async_get_balance()

    async def handle_get_summary(call) -> dict:
        return await manager.async_get_monthly_summary(
            call.data.get("month"),
            call.data.get("year"),
        )

    async def handle_categorize(call) -> None:
        await manager.async_categorize_transactions()

    async def handle_set_budget_limit(call) -> None:
        category = call.data.get("category")
        limit = call.data.get("limit")
        if category and limit is not None:
            await manager.async_set_budget_limit(category, float(limit))

    async def handle_export_csv(call) -> dict:
        path = await manager.async_export_csv(
            date_from=call.data.get("date_from"),
            date_to=call.data.get("date_to"),
            categories=call.data.get("categories"),
        )
        return {"path": path}

    async def handle_toggle_demo(call) -> None:
        # R14: admin-only gate — toggling demo mode modifies global state
        # and replaces cached transaction data.
        from homeassistant.exceptions import HomeAssistantError

        if not call.context or not call.context.user_id:
            raise HomeAssistantError("admin_required")
        user = await hass.auth.async_get_user(call.context.user_id)
        if user is None or not user.is_admin:
            raise HomeAssistantError("admin_required")

        enabled = not manager.demo_mode
        if enabled:
            # Back up real data before overwriting with demo
            manager._demo_backup_transactions = list(manager._transactions)
            manager._demo_backup_tx_by_account = dict(manager._tx_by_account)
            manager._demo_backup_balances = dict(manager._balances)
            manager._demo_backup_last_refresh = manager._last_refresh
        # Restore real data when disabling demo
        elif hasattr(manager, "_demo_backup_transactions"):
            manager._transactions = manager._demo_backup_transactions
            manager._tx_by_account = manager._demo_backup_tx_by_account
            manager._balances = manager._demo_backup_balances
            manager._last_refresh = manager._demo_backup_last_refresh
        manager.set_demo_mode(enabled)
        await coordinator.async_refresh()

    async def handle_import_spreadsheet(call) -> dict:
        """Import a household workbook into the budget plan.

        Admin-only: an import replaces the entire plan. The path is validated
        against Home Assistant's allowlist so the service cannot be used to
        read arbitrary files off the host.
        """
        from homeassistant.exceptions import HomeAssistantError

        if not call.context or not call.context.user_id:
            raise HomeAssistantError("admin_required")
        user = await hass.auth.async_get_user(call.context.user_id)
        if user is None or not user.is_admin:
            raise HomeAssistantError("admin_required")

        path = str(call.data.get("path") or "").strip()
        if not path:
            raise HomeAssistantError("A 'path' to the .xlsx file is required")
        if not hass.config.is_allowed_path(path):
            raise HomeAssistantError(
                "Path not allowed. Add its directory to allowlist_external_dirs "
                "in configuration.yaml, or place the file in the config directory."
            )

        try:
            report = await manager.async_import_spreadsheet(path)
        except FileNotFoundError as err:
            raise HomeAssistantError(f"File not found: {path}") from err
        except (ImportError, ValueError) as err:
            raise HomeAssistantError(str(err)) from err

        await coordinator.async_refresh()
        return report

    async def handle_reprocess_data(call) -> dict:
        """Rebuild the ledger from the raw archive (admin-only, no bank call)."""
        from homeassistant.exceptions import HomeAssistantError

        if not call.context or not call.context.user_id:
            raise HomeAssistantError("admin_required")
        user = await hass.auth.async_get_user(call.context.user_id)
        if user is None or not user.is_admin:
            raise HomeAssistantError("admin_required")

        async with manager._refresh_lock:
            result = await manager.async_reprocess(force=True)
            overrides = await manager._async_load_transfer_overrides()
            manager._derive_from_ledger(overrides)
        await coordinator.async_refresh()
        return result

    async def handle_get_transfer_plan(call) -> dict:
        """Return the monthly transfer choreography (cache read)."""
        return manager.get_transfer_plan(
            call.data.get("month"),
            call.data.get("year"),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_SPREADSHEET,
        handle_import_spreadsheet,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_TRANSFER_PLAN,
        handle_get_transfer_plan,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_ACCOUNTS,
        handle_refresh_accounts,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_TRANSACTIONS,
        handle_refresh_transactions,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_GET_BALANCE, handle_get_balance)
    hass.services.async_register(DOMAIN, SERVICE_GET_SUMMARY, handle_get_summary)
    hass.services.async_register(DOMAIN, SERVICE_CATEGORIZE, handle_categorize)
    hass.services.async_register(DOMAIN, SERVICE_SET_BUDGET_LIMIT, handle_set_budget_limit)
    hass.services.async_register(DOMAIN, SERVICE_EXPORT_CSV, handle_export_csv)
    hass.services.async_register(DOMAIN, SERVICE_TOGGLE_DEMO, handle_toggle_demo)
    hass.services.async_register(
        DOMAIN,
        SERVICE_REPROCESS_DATA,
        handle_reprocess_data,
        supports_response=SupportsResponse.OPTIONAL,
    )
