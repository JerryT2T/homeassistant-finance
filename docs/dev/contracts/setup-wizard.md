# Contract: setup wizard, payday, pot suggestions, exceptions, member access

Modules: `setup_wizard.py` (state + pure logic), `api/setup.py` (endpoints), `notify.py`
(exceptions + digest), `api/_helpers.py` (`is_admin`, `admin_denied`, `visible_account_ids`),
`panel.py`. Everything is a cache/config read; no bank call.

## Wizard state

Own HA Store `finance_dashboard.setup_wizard` (no config-entry update, no reload). Setup
(Einrichtung) steps: `persons, accounts, payday, region, notifications, ai, points, done`. Status
per step: `pending|done|skipped`. Skippable: payday, region, notifications, ai, points. Pots,
plan and goals left the setup; stored entries for `pots`/`plan`/`goals` from older versions are
ignored on load. A `pending` step is reported `done` when the data already proves it (persons
exist; all accounts assigned; every person has a confirmed payday; region state set; points
target set) - that is the resume rule. `current_step`
is the first unresolved step, `done` once `complete: true` was stored.

`GET /api/finance_dashboard/setup` (admin) ->
`{current_step, steps{}, completed, ai_opt_in, notifications{}, persons[{name, payday}]}`

`PUT /api/finance_dashboard/setup` (admin), all keys optional:
`{step, status, complete, ai_opt_in, notifications{...}, paydays[{person, day 1-31}]}` ->
same payload as GET. Errors 400 `{error, detail}`: `unknown_step, invalid_status,
not_skippable, invalid_ai_opt_in, unknown_notification_setting, invalid_notifications,
invalid_complete, invalid_paydays, unknown_person, invalid_payday`.
`ai_opt_in` is kept for compatibility and routed through `ai_consent` (read:
`async_granted(hass, "categorize")`, write: `async_set(hass, "categorize", value)`); the legacy
state flag is only the fallback while that module is absent.

Notification settings (defaults): `enabled true, large_debit true, large_debit_factor 3.0,
large_debit_threshold 500.0 (0 = absolute rule off), double_charge true, missing_salary true,
consent_expiring true, digest_enabled true`.

## Payday

Stored on the person record: `entry.data["persons"][i]["payday"] = {"day": int, "confirmed": true}`.
`manager.async_set_assignments` now carries an existing payday over (one small edit) so saving
assignments never drops it.

`GET /setup/payday_suggestions` (admin) -> `{suggestions: [{person, confirmed_day,
suggested_day, source, amount}]}`: largest recurring credit (via `detect_recurring`) on the
person's own accounts. The user confirms via `PUT /setup {paydays: [...]}`.

Cycle rule (not changed, `home.py` is not mine): `setup_wizard.person_payday(person)` returns the
confirmed day or None; `setup_wizard.payday_cycle(day, today)` returns the window containing
today (day clamped to month length). Intended use in `home.build_home` person view: if the
person has a confirmed payday use `payday_cycle`, else keep `person_cycle(incomes)` and the
calendar fallback. Persons without payday behave exactly as before. `notify.detect_missing_salary`
already prefers the confirmed payday.

## Pots from history

`GET /setup/pot_suggestions` (admin) -> `{suggestions: [{owner, category, name, cycle_budget,
samples}]}`. Per owner x category: median of the last 3 completed cycles (salary-start windows,
falling back to the 3 previous calendar months), only cycles with spend count, >= 2 samples,
rounded to 10 EUR (min 10). Excluded: income, transfers, other, and fixed-cost categories
(housing, insurance, loans, subscriptions - those belong in the plan), and owner+category pairs
already covered by an existing pot.

`POST /setup/pot_suggestions` (admin) body `{accept: [{category, owner, cycle_budget, name?,
account_keys?}]}` -> 201 `{ok, pots}`; creates pots via `manager.async_save_pot` (all validated
first). Extra error `unknown_account` (an `account_keys` entry is not a known account key).

Pot account binding: every pot dict (`/pots` POST/PUT, `/home`) carries `account_keys: string[] |
null`. `null` (or `[]`) = all accounts; otherwise only bookings from those account identity keys
(`account_identity.account_key`, never raw uids) count as the pot's spending (`pots.pot_accepts_account`,
applied in `home._pot_bookings` and `pots._matching`). Bookings carry `account_key`; projected
upcoming bookings without a key are kept.

## Exceptions and digest

Run from the daily refresh (`__init__._register_daily_refresh`, after the consent-issue update)
through `notify.async_after_refresh`; never raises; skipped in demo mode and when
`notifications.enabled` is false. Each exception is delivered once (hashed id kept 60 days).

Event `finance_dashboard_exception`: `{kind, person, merchant, amount, date}`.
`kind`: `large_debit | double_charge | missing_salary | consent_expiring | consent_expired`.
`person` = account owner or `"shared"` (automations route on it). `amount` is rounded absolute
(null for consent) - allowed because `events.py` events carry amounts. No IBAN/account number.
The `persistent_notification` is visible to all HA users, so it is generic: kind + person, and
the merchant only for shared items; never amounts.

Event `finance_dashboard_weekly_digest`: `{week, status, top_changes[{category, delta}],
questions_open, text}` once per ISO week + persistent notification `finance_dashboard_digest_<week>`.
Household level only. Text is English.

## Endpoint visibility (panel is now `require_admin=False`)

| Endpoint | Admin | Non-admin member |
|---|---|---|
| `GET /home` | yes | 200, own person view (person from the login) / household with other persons as totals |
| `/pots` POST/PUT/DELETE | any | own personal pots only (existing) |
| `GET /transactions` | full | 200 aggregates only (existing) |
| `GET /summary` | yes | yes (monthly category aggregates, no merchants) |
| `GET /balances` | all accounts | own + shared accounts only (NEW: `visible_account_ids`); unmapped member: shared only; unassigned accounts hidden |
| `GET /bank_status`, `/refresh_status`, `/settings` | yes | yes (no IBAN, no values) |
| `GET /budget_plan` | full | shared positions only (existing, `restricted: true`) |
| `GET /plan_vs_actual` | full | 200 `restricted` stub (existing) |
| `/budget_plan/position`, `/income`, `/import` | yes | 403 (existing) |
| `GET /transfer_plan`, `GET /benchmark` | yes | 403 (NEW gate, per-person plan data) |
| `/transfer_chains` GET/POST | yes | 403 (existing) |
| `/assignments` GET/PUT | yes | 403 (existing) |
| `/refresh` POST, `/demo/toggle` | yes | 403 (existing) |
| `/demo/data` | yes | yes (synthetic data) |
| `/setup`, `/setup/payday_suggestions`, `/setup/pot_suggestions` | yes | 403 |

## Open points

- `GET /budget_plan` for members still returns whatever else is in the view besides `positions`
  (e.g. per-person income totals); not audited in depth - another agent owns the plan model.
- `home.py` does not yet consume `payday_cycle` (not my file).
- The frontend must tolerate 403 on `/transfer_plan` and `/benchmark` for members (check `/settings.is_admin`).

## Region (benchmark comparison)

`GET /setup` also returns `region: {state, postcode}` (from the entry options
`benchmark_state` / `benchmark_postcode`). `PUT /setup` accepts
`{"region": {"state": "DE-RP" | "RP", "postcode": "56179"}}` — state is a
two-letter code with optional `DE-` prefix, postcode optional and 5 digits;
anything else returns `400 invalid_region`. The frontend shows Region as its own
screen between Zahltag and Töpfe; it has no backend step status.

## Backend additions (plan prefill, goals, points, AI, nicknames)

All admin only, cache/config only. Errors are 400 `{error, detail}` unless noted.

- `GET /setup` and `PUT /setup` now also carry `points_target` and `persons[].display_name`
  (falls back to `name`). `PUT /setup {nicknames: [{person, display_name}]}`; empty clears.
  `name` stays the stable key (accounts, pots, plan, rules); only the display text changes.
  `/assignments` GET returns `persons[].display_name`; PUT accepts `display_name` per person and keeps
  the stored one when omitted. Errors: `unknown_person`, `invalid_display_name`, `invalid_nicknames`.
- `GET /setup/plan_prefill` -> `{proposals: [{series_id, name, owner, category, interval, amount,
  plan_mode, already_in_plan}]}` (amount = monthly equivalent, plan sign, owner `shared` or a person).
  `POST` `{accept: [{series_id, name?, owner?, amount?, category?}]}` -> 201 `{ok, created, skipped}`;
  existing plan positions are never overwritten (`skipped` ids). Errors: `invalid_body, unknown_series,
  unknown_owner, invalid_amount, invalid_name, duplicate, too_many`, `demo_mode`.
- `GET /setup/goals` -> `{goals}`; `POST` goal -> 201 `{ok, goal}`; `DELETE /setup/goals/{id}` -> `{ok}` / 404.
  Goal kinds: `target_by_date {target_amount, target_date}`, `category_cap {category, cap_amount}`,
  `savings_rate {rate_percent}`, `reserve_topup {reserve_id, monthly_amount}`; all take `name`, `owner`.
  Readers: `savings_goals.async_get_goals(hass)`.
- `GET/PUT /setup/points` `{entity_id}` (`counter.*` / `input_number.*`, "" clears) -> `{entity_id, event,
  every, answered_total}`. Errors `invalid_entity, unknown_entity`. Finance keeps no points ledger.
- `GET/PUT /setup/ai`: PUT any of `provider (ha|xai|anthropic|openai), model, ha_agent, budget_cap (0-1000, default 100),
  api_key (write-only, "" removes), ai_opt_in`. Response: `{opt_in, provider, model, effective_model, ha_agent,
  has_key, budget {month, calls, cap, hard_cap, remaining}, cached_merchants, providers[]}`. The key is
  Fernet-encrypted (credential manager) in the `finance_dashboard.ai_provider` store and never returned.
  `ai_provider.async_categorize(...)` is the entry point for the categoriser (not wired into the pipeline yet).

## Einrichtung additions

`GET /assignments` accounts[] gain (additive) `earliest_booked` (`"YYYY-MM-DD"|null`, ledger first
booked date, meta `history[akey].earliest_booked` as fallback) and `account_type` (bank
`cash_account_type`, e.g. `CACC|SVGS|CARD`, `null` when unknown).

## Plan wizard (Haushaltsplan erstellen)

Module `plan_wizard.py` (state, gate, income, result) + `api/plan_wizard.py`. State is the
`plan_wizard` section of the same Store. All admin only, cache/config only, never a bank call.
Plan sign everywhere (expense positive); income positive.

- `GET /plan_wizard` -> `{current_step, steps{income,fixed,pots,goals,result: pending|done|skipped}, completed}`
  (`current_step` is `result` once completed).
- `PUT /plan_wizard` body (all optional) `{step, status (default done), current_step, complete}` -> same
  payload. Marking a step done/skipped moves `current_step` to the first pending step. Skippable:
  fixed, pots, goals. Errors 400 `unknown_step, invalid_status, not_skippable, invalid_complete`.
  - `{restart: true}` (rebuild): removes all plan positions and all income entries, resets all steps
    to pending, `completed=false`, `current_step="income"`; pots and goals untouched. Returns the normal
    GET payload. Admin only; 400 `demo_mode` in demo mode.
  - `{complete: true}` additionally upserts one pot "Taschengeld" per person (`owner` = person,
    `cycle_budget` = `max(0, pocket_money)`, `auto: "remainder"`). An existing auto pot of the person
    is updated, never duplicated; a manual pot named "Taschengeld" is left alone; pocket money <= 0
    sets the auto pot to 0 (kept). The response adds `remainder_pots: [{person, pot_id, cycle_budget}]`.
    Pots/goals use `"shared"` as shared owner, the plan `__shared__`. Pots carry optional `auto`
    (`null` | `"remainder"`) in every pot dict.
- `GET /plan_wizard/gate` -> `{ready, cycles, required: 3, earliest_booked, ready_from}`. Full payday
  cycles between the earliest booked date (min over all ledger accounts) and today. Household payday =
  first confirmed person payday, else day 1 (calendar month); day clamped to month length. The partial
  cycle before the first payday does not count. `ready_from` = payday on which the 3rd cycle closes
  (`null` when ready or without data).
- `GET /plan_wizard/income_suggestions` -> `{suggestions: [{person, amount_net, source, samples}]}`:
  largest recurring credit on the person's own accounts (`detect_recurring`, as the payday
  suggestion). Persons without a recognised salary are omitted.
- `PUT /plan_wizard/income` body `{income: [{person, amount_net}]}` -> `{ok, income: [entry]}`. Stores via
  `manager.async_set_income` (the budget plan's income entry; `deposit = amount_net`, insurance and
  tax adjustment 0). Errors `invalid_body, unknown_person, invalid_amount`, `demo_mode`.
- `GET/POST /plan_wizard/fixed`: same as `GET/POST /setup/plan_prefill` (both stay).
- `GET /plan_wizard/result` -> `{income_total, fixed_total, pots_total, goals_total, left_over, balanced,
  per_person[{person, income, share, pocket_money}], history{months, avg_income, avg_spent,
  avg_left_over}, remainder{total, per_person[{person, amount}]}}`, monthly. `remainder` = `left_over`
  split as `pocket_money` (negative allowed = "es fehlen X EUR"); auto-remainder pots are excluded from
  `pots_total` and the remainder so re-running never shrinks it. `fixed_total` = all active plan positions (fixed + buffer, reimbursements
  net); `pots_total` = sum of pot `cycle_budget`; `goals_total` = `reserve_topup.monthly_amount` +
  `savings_rate` % of `income_total` + `target_by_date` amount / months left (min 1); `category_cap`
  adds nothing. `left_over = income - fixed - pots - goals`, `balanced = left_over >= 0`.
  `share` = income share; `pocket_money = income - shared_total * share - own_total` (own = the person's
  positions, pots and goals). `history` averages the full payday cycles of the gate with counted
  transactions (no transfers); `months: 0` and `null` averages without a full cycle.
