# Architecture

Read this before touching the manager, storage, config flow, API or frontend.

## Layout

```
custom_components/finance_dashboard/
├── __init__.py            # Setup, services, restart handling, daily scheduled refresh
├── config_flow.py         # `user` (application id + key), BankSubentryFlow, reconfigure, options
├── connect.py             # Bank connect: PSU redirect via my.home-assistant.io, code exchange
├── const.py               # All constants, categories, service names
├── runtime.py             # Per-entry runtime data
├── manager/               # Orchestrator: __init__ (cache reads), _refresh, _persistence, _banks
├── fetch_budget.py        # Per-bank fetch budget (pure logic, injectable time)
├── data_store.py          # Encrypted two-layer storage (raw archive + ledger)
├── balances.py / balance_statistics.py   # Balance series, long-term statistics import
├── account_identity.py    # IBAN-based account key (see CLAUDE.md hard rule)
├── enablebanking_client.py, credential_manager.py   # API client (JWT RS256), Fernet + audit
├── coordinator.py         # DataUpdateCoordinator, cache-only reads
├── entity.py, sensor.py, button.py, number.py, select.py   # Entities and devices
├── diagnostics.py, repairs.py, events.py, panel.py
├── counted.py (the one counting rule), own_accounts.py, plan_match.py, tx_dates.py
├── categorizer.py, recurring.py, transfer_detector.py
├── budget_plan.py, spreadsheet_import.py, sheet_source.py, transfer_plan.py, household.py, benchmark.py
├── api/                   # HTTP views: data, plan, refresh, demo, _helpers
└── frontend/              # One web-component kit, panel + cards
```

## Config flow

1. `user`: Enable Banking application id + RSA private key, validated live.
2. Banks are added as **config subentries** (`BankSubentryFlow`, `connect.py`): ASPSP choice, PSU
   redirect through `my.home-assistant.io`, code exchange, test call, account assignment
   (personal vs. shared).
3. Reconfigure flow (credentials) and options flow (daily refresh, `show_household`, retention, ...).

## Refresh and rate limit (per bank)

`fetch_budget.py` holds the budget per bank (ASPSP), never global:
- Background calls (no PSU headers) are counted per account per UTC day; the scheduled daily
  refresh may use at most `SCHEDULED_BACKGROUND_SHARE` of the limit.
- Attended calls (PSU headers from a real request) are uncapped, never gated on a block, only
  debounced (`ATTENDED_DEBOUNCE_SECONDS`).
- A 429 blocks that bank's background access for `RATE_LIMIT_BACKOFF_HOURS` (6h); other banks are
  unaffected. State is persisted across restarts.

Flow: "Neu importieren" button / service -> `POST /api/finance_dashboard/refresh` ->
`manager.async_refresh_transactions()` (lock-guarded) -> balances + transactions per bank in one
round -> stats written to cache -> coordinator pushes to entities -> endpoint returns
`{ok, status}`. Cache-read endpoints (`/balances`, `/transactions`, `/summary`, `/refresh_status`)
never hit the bank.

### Fetch triggers

Imports are rate limited, so page views and re-processing must never cost a call. The server
enforces this; the frontend is not trusted to behave.

| Trigger | Calls the bank? | Notes |
|---|---|---|
| "Neu importieren" (`POST /refresh` with body `{"trigger": "user_import"}`, admin) | yes, attended | A POST without that body is rejected with HTTP 400 `explicit_trigger_required` before any client is built |
| `refresh_transactions` / `refresh_accounts` service, refresh button entity | yes | Explicit user/automation action; no PSU IP -> background, capped |
| Setup bootstrap (config flow, setup wizard) | yes, attended | Part of connecting a bank |
| Scheduled daily refresh (`daily_refresh_*`) | yes, background | Exactly one per day |
| Panel open, page views, every HTTP GET | never | Cache reads only |
| "Aktualisieren" (`POST /reprocess`, `reprocess_data` service) | never | Replays stored raw data |
| Coordinator refresh / entity updates | never | Cache reads only |

`refresh_status` still carries `auto_refresh_on_open` (always `false`) and
`auto_refresh_max_age_seconds` (always `0`) for older frontends; the options were removed.
`tests/test_fetch_triggers.py` pins this, including an AST check that only the known trigger
modules reference the live-fetch methods.

## Storage

`data_store.py`: every store is HA `Store` with a Fernet-encrypted payload (key from the credential
manager), versioned with a migrate hook.
- **Raw layer**: every bank response unaltered, immutable snapshots, one store per month. Kept
  forever by default (option `raw_retention_days`, 0 = lifelong). Each snapshot carries replay
  metadata (`account_key`, `fetch_id`, `date_from`); a `transactions_window` snapshot closes a fetch
  with its `truncated` flag.
- **Ledger layer**: processed, deduplicated per-account transactions and balance time series,
  lifelong (no pruning, no cap). Categories, summaries and splits are derived, never stored here.
  A fetch is evidence only for the span the bank reported: a bank that answers a long request
  with less history never erases older ledger entries.
- **Reprocessing** (`reprocess.py`): `PROCESSING_VERSION` (const) versions the raw → ledger
  processing. Bump it with every change to normalisation, ingest or transaction identity. On
  start, a ledger written by another version is rebuilt by replaying the raw archive through the
  live code path (no bank call); the old ledger is saved to `…_ledger_backup_v<old>` first, history
  the archive does not cover is carried over, and an unreadable archive aborts the rebuild.
  Service `reprocess_data` forces it.
- **History backfill**: the first attended fetch of an account per bank session requests
  `HISTORY_BACKFILL_DAYS` (3650 → 730 → 365 → 90, stepping down on HTTP 400/422). Background fetches
  never backfill (each rejected window would spend the 4/day cap). Later fetches are incremental.

## Entities and devices

One device per bank and per account (`entity.py`). Per account: balance, available balance,
last-update sensors (`sensor.py`). Per bank: consent valid-until, consent state, budget used,
blocked-until, last error, plus a refresh button (`button.py`). Aggregates: total balance, monthly
summary. Balance history is imported as long-term statistics (`balance_statistics.py`).
`diagnostics.py` redacts financial data. See `entities-and-services.md`.

## Frontend

One kit (`finance-dashboard-kit.js`, `fd-*` components), see `docs/ARCHITECTURE-FRONTEND.md`.
- Sidebar panel via `panel_custom`, admin-only (`panel.py`).
- Cards auto-loaded through `frontend.add_extra_js_url`, no manual resource entry.
- Panel tabs: facts **Overview**, and **Household** (only when option `show_household` is on).

## Distribution

HACS only (`hacs.json`). There is no companion add-on and no payload sync.

## Frontend dev harness

`scripts/dev/panel_harness.py` (stdlib only, never loaded by the integration) serves `custom_components/finance_dashboard/frontend/` and answers `/api/finance_dashboard/*` from `demo.py` (`home`, `review`, `review/report`, `benchmark`; other reads `{}`, writes `{"ok": true}`). It needs the repo venv (Home Assistant importable); on Windows `fcntl`/`resource` are stubbed.

```
python scripts/dev/panel_harness.py --port 8765
http://localhost:8765/?el=fd-home&width=375&theme=dark&lang=en&admin=1
```

The bar on top toggles the element (`fd-home`, `fd-benchmark`, ...), admin/member, de/en, light/dark and the stage width (375 / 768 / 1100); the same keys work as URL parameters. `fd-navigate`, `fd-toast` and `fd-demo-toggle` are shown in the bar. The Jahr tab (`Start` > `Jahr`) renders from `GET /home?horizon=year`; the demo has no settlement balances, set `d._data.settlement` in the console to see the Ausgleich card.
