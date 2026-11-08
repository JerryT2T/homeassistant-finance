# Entities, services, events

Read this before adding or changing entities, services, events or HTTP endpoints.

## Entities

- Devices: one per bank, one per account (`entity.py`).
- Sensors per account: balance (with bank logo, IBAN masked), available balance, last update.
- Sensors per bank: consent valid-until, consent state, budget used, blocked-until, last error.
- Button per bank: refresh (attended path).
- Aggregates: `total_balance` (optional), `monthly_summary`; per-person budget sensors.
- Number per category: budget limit. Select: split model.
- Unique ids go through `account_identity.py` (IBAN-based), never the raw uid.
- Balance history is imported as long-term statistics (`balance_statistics.py`).

## Services (see `services.yaml`)

`refresh_accounts`, `refresh_transactions` (both return refresh stats via
`SupportsResponse.OPTIONAL`), `get_balance`, `get_monthly_summary`, `categorize_transactions`,
`set_budget_limit`, `export_csv`, `toggle_demo`, `import_spreadsheet` (admin-only, path checked
against `allowlist_external_dirs`), `get_transfer_plan`, `set_cost_position`,
`delete_cost_position`, `reprocess_data` (admin-only; rebuilds the ledger from the raw archive, no
bank call, returns rebuild stats). `refresh_transactions` is the only live-fetch entry point and
updates balances + transactions + recurring in one round.

## Events

`fd_transaction_new`, `fd_balance_changed`, `fd_budget_exceeded`, `fd_recurring_detected`.

## HTTP endpoints (`api/`, all require HA auth)

Cache reads: `/balances`, `/transactions`, `/summary`, `/refresh_status`, bank status, settings.
Live: `/refresh`. Plan: `/budget_plan`, `/transfer_plan`, `/plan_vs_actual`, `/benchmark`, plan
position/income/import, `/budget_plan/upload` (admin; base64 `.xlsx`, max 5 MB, parsed in memory)
and `/budget_plan/import_url` (admin; Google Sheets link shared "anyone with the link" — only the
sheet id is taken, the export URL on `docs.google.com` is built in `sheet_source.py`). Demo: toggle + data. IBANs are truncated to the last 4 digits.

Home screen (`api/home.py`, `home.py`, `pots.py`, `cycle.py`):

- `GET /home?horizon=today|week|cycle|year&view=person|household[&demo=1]` - cache read only, never a
  bank call. The person comes from the logged-in HA user (account `ha_users`), never from a
  parameter; without a mapping `view=person` degrades to `household`. Household view shows shared
  pots in full and every person only as totals (`persons[]`). Contract: see
  `docs/concepts/20261027-2210-finance-visual-round/briefs/home-api-contract.md`.
  Identity fields, present on every view: `person` = `{id, name, display_name}` | null (`id`/`name`
  is the stable key, `display_name` the nickname from the persons config, falling back to `name`);
  `viewer_person` = the calling HA user's person key or null, **also in the household view** (and
  when `view=person` degraded to household), so the UI can always offer the person/household toggle.
  Person view only: `person_budget {budget, spent, remaining, source}` = the person's own Spielraum
  for the current cycle, plan sign, own items only. `source: "plan"` when the plan has income or
  positions for the person: `budget` = own net plan income - own fixed costs, `spent` = own booked
  expenses in the cycle except categories an own fixed position already covers. `source: "history"`
  otherwise: `budget` = own income booked in the cycle (previous cycle if none yet), `spent` = all
  own booked expenses. `remaining = budget - spent`; transfers, chain bookings and pending items
  are excluded. The key is absent in the household view. (Demo payloads do not carry the new
  fields yet.)
- `POST|PUT|DELETE /pots` - pot CRUD. Admins manage every pot; other users only their own
  personal pots (also checked against the existing owner on update/delete, so a pot cannot be
  taken over). Ids are server-generated on create. Pots are stored in `.storage/finance_dashboard_pots`.
- `GET|PUT /assignments` (`api/assignments.py`, admin only, 403 `admin_required`) - the "Personen & Konten"
  settings. GET returns `persons` (name + `ha_users`), `ha_users` (id, name, is_admin, `suggested`,
  `reason` person|active_user|system|inactive), `accounts` (`key`, name, institution, `iban_last4`,
  `owner` person|shared|"", `household` bool, `owner_kind` open|person|person_household|household,
  `card_owners` `{last 4 digits: person}`, only kept for `shared` accounts)
  and `plan_persons`. PUT takes `{persons, accounts:[{key, owner, household?, card_owners?}]}` (`card_owners`: keys exactly 4 digits and values existing persons, else 400 `invalid_card_suffix`/`unknown_card_person`/`invalid_card_owners`; dropped when the account is not household-only) (`household: true` only
  with a person; `shared`/"" + household, or a non-boolean, is 400 `invalid_owner_set`/`invalid_household`),
  validates (unique names <= 40 chars, existing HA users, one person per user, owner shared or a
  person, known account keys; else 400 `{error, detail}`), stores `persons` in the config entry and
  writes `type`/`person`/`household_use`/`ha_users` onto the accounts (user-owned fields, kept on bank
  re-link) and, when an owner set changed, re-derives the stored bookings from the ledger (no bank call).
  `/home` carries `setup {persons, user_mapped, accounts_total, accounts_assigned, pots}`.
- Demo mode (`manager.demo_mode`, or `demo=1`) serves the same payload from invented data
  (`demo.generate_demo_home`).

Contracts (`api/contracts.py`, details in `docs/dev/contracts/contracts-series-reserves.md`):
`GET /contracts`, `POST /contracts` (admin, add by hand, #117 D), `PUT|DELETE /contracts/{id}`
(admin; DELETE only for manual contracts), `POST /contract_overrides` (admin; merge / split /
booking assignment, #117 E/F), `GET /reserves`, `PUT /accounts/{key}/savings`.
`GET /contracts` also answers `viewer: {me, persons}` (resolves the owner filters "me" / "partner").
Search and filters (#118): `contract_filter.py` (spec, `validate_spec`, `apply`, totals) is mirrored by
`frontend/fd-contract-filter.js`; both run `tests/fixtures/contract_filter_cases.json`.
`GET /contracts/query` -> `{available, usable, consented, remaining}` (offer the AI search? non-admins get `available: false`);
`POST /contracts/query` `{question}` -> `{spec, errors}` (admin only: 403 `admin_required`; purpose `contract_query` consent
required: 403 `consent_required`; `no_provider` / `budget_exhausted` 400; provider failure 502). The AI
returns a filter spec only; it is validated against the schema, valid parts are kept and dropped parts
are listed in `errors` (an unreadable answer gives `[{field: "_", reason: "unparsable"}]` and an empty
spec). The prompt holds the question plus allowed names only. Series carry `remittance` (up to 3 recent
purpose texts) for the search; non-admins get the reduced aggregate view without it.
Counted figures: `/summary`, `/plan_vs_actual` and the `get_monthly_summary` service report one
income cycle (`period: {start, end, rule, anchor}`; `month`/`year` name the plan month it goes by;
a requested month means the cycle holding its 15th). `/transactions` returns the effective date for
every row, `counted` and `movement` (reason) per row and `totals: {income, expenses}` over the
filtered rows by the same rule; `category` is what the booking counts under (a contract's category
wins, `own_category` keeps its own).

Questions (`api/questions.py`): pairs of a debit and a credit that match on amount and date only
are never linked but asked (`kind: "transfer"`, `id: "transfer:<chain id>"`, at most 5, newest
first, `choice: confirm|no`). Answering `category: "transfers"` for a merchant marks the
counterparty as an own account; it applies retroactively on every derive.
`GET /questions` puts contract and price-change cards (#117 B/G)
in front of the merchant cards (shared weekly quota); `POST /questions/answer` takes
`{id, type: "contract"|"price", answer}` besides the merchant answer.

Ownership (`api/ownership.py`, all admin only, 403 `admin_required`; cache and merchant memory, never a
bank call; errors are 400 `{error, detail}`):
- `POST /ownership/correct` `{ledger_id, owner, reach}` - `owner` a person name, `"shared"` or `null`
  (undo); `reach` `"booking"` (this booking) or `"merchant"` (every booking of its merchant, "für alle
  von X merken"). Works for a booking of any category. Answers `{ledger_id, reach, owner, merchant}`.
  Errors `invalid_id`, `invalid_reach`, `invalid_owner`, `unknown_booking`, `no_merchant`.
- `POST /ownership/series` `{series_id, owner, ledger_ids?}` - decides a recurring series once
  (`ledger_ids` as `"<account_key>|<ledger_id>"`); `owner: null` forgets it.
- `GET|PUT /ownership/household-categories` - `{categories, defaults, available}`; PUT `{categories}`
  (`null` = defaults) sets the categories treated as household on a `{P,H}` account.
- `POST /ownership/ai-review` `{merchants: [merchant keys]}` - category + shared/personal tendency for
  those merchants in the monthly AI budget and only with the categorisation consent; answers
  `{asked, categorized, tendencies, skipped_budget, reason}` (`reason` `no_consent` |
  `provider_unusable` | `unavailable` | null). An AI category never replaces a user rule.

Year view and benchmark (cache only, `year_view.py`, `benchmark.py`):
- `GET /home?horizon=year` (both views) -> `year`: `cycles[12]` `{month, year, start, end, current, future,
  before_history, spent, income, budget (that month's plan, null without a plan), status, spent_shared}`
  (a cycle belongs to the month of its 15th); `balance` `{income, expenses, saved, savings_rate, fixed,
  variable, through, cycles_counted}` year to date; `categories` top 8 `{category, amount, share,
  delta_prev?}` (`delta_prev` only with a complete prior year; `categories_scope` `own` | `shared`);
  `fixed_year` `{yearly, monthly, count, link: "contracts", items}`; `split` `{shared, persons: {name: total},
  open?, own?: {person, total, shared_share}}` (other persons as totals only); `outliers` `{count, total,
  items}` (items admin only, each with `ledger_id`, `owner`, `owner_source`, `owner_confidence`);
  `vs_last_year` `{through, spent, spent_last_year, delta, delta_pct, income(_last_year), saved(_last_year)}`
  **only present** when every counted account has bookings from before the prior-year window opens;
  `benchmark_teaser` (admin, top 3 deviations), `reviewed_at`, `review_hint` `{open_groups, open_amount}`
  (admin, only when new unreviewed groups sum to >= 100 EUR or > 2 % of the year's expenses).
  Household cycle/year payloads also carry `settlement` `{start, end, balances: {person: {owes_household,
  household_owes, net}}}` (net > 0: the person owes the household).
- `GET /benchmark` (admin): `comparisons` ordered by relative deviation, each with the dataset labels
  (`statistic`, `source`, `survey_year`, `level`) plus `basis` (`actual` | `plan`), `user_value`, `actual_value`,
  `plan_value`, `deviation_pct`, `position` (0..1, 0.5 typical), `band` (`below` | `typical` | `above`, +-10 %),
  `extrapolated`, `months_covered`; top-level `basis` `{year, months_covered, extrapolated, has_actual}`, `teaser`.

Reconciliation review (`review.py`, `api/review.py`, admin only, cache only; `?demo=1` answers from the demo
household and stores nothing):
- `GET /review[?since=last]` -> `{steps: [acc, links, fixed, owner, cat, check], start_step, window, reviewed_at,
  threshold}`; a step is `{id, open_count, auto_count, new_count, open_amount, group_ids, groups}`; a group is
  `{group_id "<kind>:<key>", kind series|merchant|category|account|chain|position|link, label, amount, count,
  owner, source, confidence, reason, auto (confidence >= 85), confirmed, category, bookings[<=20 with ledger_id,
  owner, owner_source, owner_confidence]}`. `check` carries `criteria` `accounts, open_ownership (>50 EUR),
  transfers, reconcile (difference to the cent + group ids), plan (shortfalls)` and `ok`.
- `POST /review/start` stores the before-snapshot (idempotent); `POST /review/confirm` `{group_id, kind, owner?,
  category?, confirmed? (chain), suspended? (position)}` writes the rule (merchant rule / series decision /
  booking owners) and marks the group done at 95; `POST /review/ai` `{group_ids}` runs the AI review pass for
  those groups' merchants (consent + monthly budget; `reason` when refused) and returns `{..., groups}`;
  `POST /review/complete` stores `reviewed_at` and the seen groups.
- `GET /review/report` -> `{hh_year, hh_cycle (plan vs actual per position), p_year, p_cycle (full detail for the
  viewer, totals for others), settle {cycle, year}, diff (before/after/delta), reviewed_at}`.
- `GET /transactions` (admin) rows carry `ledger_id` (`"<account_key>|<id>"`, accepted by `/ownership/correct`),
  `owner` (`"shared"` | person | `""`), `owner_source`, `owner_confidence`.

## AI consent and spreadsheet ideas

AI consent is per purpose (`ai_consent.py`, own store `finance_dashboard.ai_consent`; first load
migrates the legacy wizard flag `ai_opt_in` into `categorize`). Purposes: `categorize`
(`recurring`: merchant + remittance text of unclassified transactions, stays granted; the answer is the
category plus a shared/personal tendency per merchant, same call; the purpose has `version: 2`, so an
older grant reads `granted: false, reconsent: true` until the user grants it again) and
`history_import` (`once`: see below), `contract_query` (`recurring`: the contracts-search question plus names of
categories, labels and persons, never amounts, IBANs, dates or bookings) and
`sheet_analysis` (`once`: names of budget-sheet positions local matching could not place; consumed
by the first analysis that gets a real AI answer). `manager/_questions.py` gates the categorisation
pass on `async_granted(hass, "categorize")`.

- `GET /setup/ai/consents` (admin) -> `{consents: {purpose: {granted, mode, granted_at, used_at}},
  purposes: {purpose: {mode, pros: [i18n key x<=3], risks: [i18n key x<=3]}}}`.
- `PUT /setup/ai/consents` (admin) body `{purpose, granted: bool}` -> same payload; unknown purpose
  or non-boolean -> 400 `invalid_body`.
- `POST /plan_wizard/sheet_ideas` (admin) body `{content_base64}` or `{url}` (Google Sheets, URL
  built from the sheet id only). Reads position **names** only (amounts ignored), matches them
  locally against recurring series (`recurring.detect_series`) and category names/spend in the
  cached ledger, never a bank call, never writes the plan. Response
  `{ideas: [{name, matched: "series"|"category"|"ai"|null, series_id, category, amount (monthly,
  plan sign, from ledger data only, else null), kind: "fixed"|"pot"|"reserve"|null}],
  needs_consent, ai_used}`. Unmatched names go to the AI only with `sheet_analysis` consent (names
  only, one batched call, counts against the monthly budget); without it `needs_consent` is true
  and no call is made.

## Booking-history import (#121)

Optional, admin only, never a bank call. `history_import.py` (pure: reader, column guess, validation,
duplicate check, AI prompt/answer parsing), `api/history_import.py` (endpoints), `Ledger.add_import_batch`
/ `remove_import_batch` (`data_store.py`), manager methods in `manager/_persistence.py`.

- Local first: CSV (`;,	|` sniffed, cp1252/UTF-8) and XLSX (first sheet) are mapped by header synonyms
  (de/en, preamble lines skipped, `Soll`/`Haben` or a signed `Betrag`). PDF statements (#147): text
  extracted locally with `pypdf` (layout mode, empty-password encryption opened, max 300 pages, no OCR);
  `rows_from_pdf_lines` takes every line that starts with a booking date (year-less `01.03.` gets the year
  from the statement's latest full date) and ends with an amount (a running balance after it is ignored),
  the next up to 3 lines are its purpose; balance/carry-over lines are skipped. A PDF whose amounts carry
  no debit marker (`-`, trailing `-`, `S`) is not guessed: it counts as unreadable and goes the AI way
  below. Errors `pdf_encrypted`, `pdf_no_text` (scan), `pdf_unavailable`. Only a file with no
  recognisable columns or booking lines can go to the AI: purpose
  `history_import` (`once`), IBAN/long numbers masked by `mask_sensitive`, one call per 100 lines
  (max 12), refused up front when the monthly budget cannot cover all calls. The AI returns a JSON
  array of `{date, amount (expense negative), counterparty, text, currency}`; local and AI rows pass the
  same `validate_rows`. Invalid rows are listed with line + reason, never dropped silently.
- `GET /history_import` -> `{allowed, accounts[{key,name,iban_masked}], batches[{id,at,method,count,first,last,account_key}], ai{usable,consented,remaining}}`.
- `POST /history_import/preview` `{content_base64, account_key, use_ai?}` -> `{preview_id, method, summary{new,duplicate,overlap,invalid,total,window_start}, rows[{line,date,amount,counterparty,text,currency,status}], invalid[{line,reason,raw}]}`;
  or `{needs_ai: true, calls, ai}` when the layout is unreadable and `use_ai` is not set. Rows wait in memory
  (30 min, max 3 previews), nothing is stored. Errors: `pdf_encrypted`, `pdf_no_text`, `too_large`, `unreadable`,
  `consent_required`, `no_provider`, `budget_exhausted`, `unparsable`, `unknown_account`, `import_unavailable` (demo).
- Row status: `duplicate` = same date + amount + counterparty already in the ledger (one-to-one);
  `overlap` = inside the bank fetch window (last 90 days, `fetch_window_start`), so the bank's data wins; `new` = older. Only `new` is stored, re-classified against the ledger at commit.
- `POST /history_import/commit` `{preview_id}` -> `{batch_id, added}`. Rows become ledger entries tagged
  `_source = "import:<batch_id>"`, `_ledger_id = imp:<batch>:<n>`; the ledger meta keeps `import_batches`.
  Imported rows survive `ingest` and the raw-archive rebuild (`merge_uncovered`) unless the bank wins afterwards: `Ledger.reconcile_imports` drops an imported row that a bank row covers (date +-2 days, equal amount, same normalised counterparty; batch `count` falls, `removed_by_bank` rises). They do not move
  `last_booked_date` / `first_booked_date` (fetch window, backfill, plan wizard). Parsing runs in the executor; the one-time consent is spent before the AI call.
- `POST /history_import/undo` `{batch_id}` removes the whole batch.
- Frontend: `fd-history-import.js`, embedded as settings section `history`.

Options flow (`init`): `raw_retention_days`, `show_household`, `demo_mode`,
`enable_total_balance_sensor`. There is no refresh interval (no polling); the split model is the
`select.fd_split_model` entity (a stored `split_model` option stays its default).
