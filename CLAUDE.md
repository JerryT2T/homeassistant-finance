# Finance — Home Assistant Integration

## Project Overview

A secure Home Assistant integration (HACS only) for personal finance management. Pulls live banking data via the Enable Banking PSD2 Open Banking API (JWT-signed), auto-categorizes transactions, and provides household budget tracking with configurable multi-person split models.

**Hard rule — cache vs. live fetch**: Cache reads (HTTP endpoints, sensor attributes, coordinator state) are unbounded. Live Enable-Banking calls are allowed from explicit user-triggered paths (the "Neu importieren" button / `POST /refresh` with `{"trigger": "user_import"}`, the `refresh_transactions` service, the refresh button entity, setup bootstrap) **plus exactly one scheduled refresh per day** at a configurable time (default 06:30, `daily_refresh_enabled` / `daily_refresh_hour`). Panel open, page views, "Aktualisieren" (reprocess of stored raw data), coordinator refresh and every HTTP GET **never** call the bank; `POST /refresh` rejects a request without the explicit trigger (HTTP 400) server-side. Polling — any interval-based or coordinator-driven fetch — remains forbidden.

**Hard rule — attended vs. background**: The 4/day cap is the *bank's*, and PSD2 RTS Art. 36(5)(b) applies it only to requests made while the user is **not** in session. A call carrying PSU headers (`Psu-Ip-Address` / `Psu-User-Agent`, derived from a real HTTP request) is *attended* and not capped; a call without them is *background* and is. The budget is tracked per bank (`fetch_budget.py`). Consequences that must not be re-broken:
- Never gate an attended path on a block (`blocked_until`) — that refuses a call the bank permits. Only the scheduled fetch is background. Attended calls are only debounced.
- Never invent PSU header values. No request context means background, and background means the cap applies.
- The `/aspsps` catalog is served by Enable Banking, not by a bank: it neither spends nor is bound by the quota. Gating it locked rate-limited users out of connecting any bank at all.
- A 429 backs off 6h (`RATE_LIMIT_BACKOFF_HOURS`), not until midnight — a 07:00 rate limit must not cost the whole day.

**Hard rule — account identity**: Enable Banking issues a fresh account uid per PSU session, so the uid is not an identity. The IBAN is. Everything account-scoped (entity `unique_id`, config-entry merge on re-link) goes through `account_identity.py`; using the raw uid duplicates every entity on each re-link.

**Hard rule — plan vs. actual**: The product has two sides that must not be conflated.
- The **plan** (`budget_plan.py`) is what the household budgeted: cost positions with an explicit owner, income per person. It exists independently of any bank link.
- The **actual** is live bank data.
Ownership resolves in a fixed chain: the account's owner (person or shared) is only the *default*; a matched plan position overrides it, and a user correction (one-off or saved as a rule) overrides both — a shared subscription can be billed onward, and one person's contract can be paid from the joint account. Sign conventions are opposite on the two sides (plan: expense positive; bank: expense negative); convert with `actual_amount_to_plan_sign`.

**Hard rule — one counting rule**: Every total reads the same bookings: `counted.counted_transactions` (no chain leg, no `transfers`, no PayPal mirror, booked and dated), then `counted.net_counted` (refunds netted into the expense's category). Period figures come from `household_summary.figures` inside the window from `household_summary.cycle_windows`. A view must not filter bookings or pick a period by itself: five rules for one ledger is what showed saving as spending. Dates go through `tx_dates` (a test forbids a direct `bookingDate` read), owners through `plan_match.resolve_owner`, a chain's id is a hash of its member bookings.

## Security Model

**CRITICAL — banking-grade:**
1. **No financial data in git**: no balances, transactions, account numbers or tokens, ever. `.gitignore` enforces this.
2. **Encrypted storage**: credentials and bank data (raw snapshots + ledger) are Fernet-encrypted on top of HA's `.storage/`.
3. **JWT auth**: short-lived (60s) RS256 JWTs per request; RSA key only in memory. PSU session max 180 days, forced re-auth after 90 by policy.
4. **Session timeout** 30 min; **audit trail** logs event type + timestamp only, never values.
5. **IBAN masking** (last 4 digits) in API responses; endpoints require HA auth; individual transactions are admin-only.
6. **No external calls** except the Enable Banking API and the user's opt-in AI categorisation (HA AI functions first; otherwise the user's own API key against exactly one of api.x.ai, api.anthropic.com or api.openai.com, a user-set monthly budget of calls (default 100, hard cap 1000), key Fernet-encrypted, results cached per merchant; payload merchant + remittance text only, never amount, IBAN, date or a person's name; the answer is the category plus a shared/personal tendency for that merchant (same call, cached with the category; the consent for this purpose was widened for it and is asked again once); the one other payload is the names of budget-sheet positions that local matching could not place — name only, never an amount; and, only for the optional booking-history import (purpose `history_import`), the rows of a user-uploaded statement file that the local CSV/XLSX reader could not map — here amounts and dates ARE part of the payload, IBANs and long account numbers are masked locally first, it is sent only after that purpose's own one-time consent and counts against the user's monthly AI budget, one call per 100 lines; and, only for the optional AI search in the contracts tab (purpose `contract_query`), the question the user types plus the names of the categories, labels and persons (and the fixed allowed filter values) so the AI can answer with a filter spec only — never amounts, IBANs, dates, bookings or contract names; it counts as one call per question against the same monthly budget and is sent only after that purpose's recurring consent). **AI consent is per purpose**: each purpose (categorisation = recurring, sheet analysis = once, history import = once, contract query = recurring) is asked where it is needed, states once vs. recurring and at most 3 advantages and 3 risks, and is revocable on its own; without that purpose's consent nothing leaves HA. The one further exception is the user-triggered budget-plan import from a Google Sheets link: only the xlsx export of that sheet id is downloaded from `docs.google.com` (`sheet_source.py`, URL built from the id, never the pasted URL), nothing is sent. No telemetry, no runtime benchmark fetch.

**Before every commit, verify:** `git diff --cached` has zero financial data (account numbers, balances, tokens); no `.storage/` files staged; no `credentials.json` / `tokens.json` staged.

## Versions

`manifest.json` `version` and `const.py` `VERSION` must stay aligned (`python scripts/bump_versions.py --check`). After every BUILDLOG entry run `python scripts/sync_changelog.py`.

## Tech Stack

Python 3.12+ (integration), vanilla Web Components (frontend), `cryptography` (Fernet, RSA), GitHub Actions CI.

## Deeper docs (read on demand)

- Read `docs/dev/architecture.md` when touching the manager, config flow, refresh/rate limit, storage, API or frontend wiring.
- Read `docs/dev/household-model.md` when touching split logic, month cycles, income or bonus detection.
- Read `docs/dev/entities-and-services.md` when adding or changing entities, services, events or endpoints; `docs/dev/setup-and-plan-wizards.md` when touching the setup (Einrichtung) or plan wizard.
- Read `docs/dev/product-concept.md` (what Finance is for, decided interactions) and `docs/dev/roadmap.md` before planning new work; Phase 4/5 are gated on user approval.
- Read `docs/dev/release.md` when bumping versions, writing BUILDLOG/CHANGELOG or validating.
- Read `docs/dev/labels.md` when creating issues or PRs.
- Read `docs/ARCHITECTURE-FRONTEND.md` for frontend component details.
