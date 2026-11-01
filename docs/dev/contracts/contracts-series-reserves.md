# Contracts, series, reserves, pot coverage (Phase 4d) - handoff

Modules: `recurring.py` (`detect_series`), `contracts.py`, `pots.py` (`pot_coverage`, `Pot.account_key`), `api/contracts.py`.
Everything is cache-only; no bank call is added.

## Series (`recurring.detect_series(transactions, today=, amount_tolerance=0.20, date_tolerance_days=5, overrides=)`)
Intervals: weekly (>=4 payments), monthly, quarterly, half_yearly, yearly (>=2). Amounts in bank sign.
Payees are grouped by `text_norm.canonical_name` (encoding repaired, umlauts/accents, punctuation and legal forms removed), so
a bank changing "S.à r.l." to "S.Ã  r.l." or dropping "GmbH" does not split a series. Id (`resolve_series_id`): the stored
alias of the group (`ContractStore.aliases`, key `<canonical>|out|in`, names only), else a stored contract id of one of its
spellings, else `sha1(first-seen normalized name|direction)` - identical to the pre-alias id, so stored contracts never move.
Callers persist newly learned aliases with `ContractStore.async_save_if_changed()`.
One payee, several series (#108, `_series_parts`): a payee group is split by contract reference
(`contract_reference`: a number after a keyword such as Darlehen, Vertrag, Kd-Nr, Mandat, Police, Mitglieds-Nr - never a bare
order number) when two or more references each recur and run in parallel; a reference that only changes once is a successor.
Only when the whole group is no series, it is searched for amount bands (+-5 % around its most frequent amounts); a band counts only with >= 3
payments each within the date tolerance of the predicted date, finite instalments ("Teil 1/3", "Rate 2 von 6") never form
a band, and a band that continues where another stopped is joined (price step), so a real price step is never split. The part with the earliest payment keeps the payee id;
other parts get `sha1(name tag)`. Each part remembers its id under `alias_keys`: the payee key (earliest part), a
name-independent hashed reference key and a hashed band key - never a number or an amount in clear.
One price step is allowed, and with >= 4 payments one single outlier (a doubled instalment); anything noisier is rejected.
Pauses (#114): weekly and monthly series may skip whole periods (gaps of 2-4 periods) as long as at most a third of the
gaps are pauses; quarterly and longer gaps stay strict. Fields: `id`, `alias_key`, `alias_keys`,
`interval`, `next_expected`, `expected_amount`/`plan_amount`, `plan_mode` (`auto` default: the new price after a price step -
two payments at it, or one after a steady price that is below 1.8x - else the median, so a single catch-up never moves the
plan; explicit `highest` / `average` / `last` / `median` / `fixed`), `annual_cost` (always the full rhythm, pauses ignored),
`pauses` (skipped periods), `pauses_recent` (within the last 12 periods), `pause_pattern` (>= 3 recent; the question whether
to project with the pause rate belongs to the review flow #117), `pending_since` (#115: a pending debit of the payee at
least half a period after the last booked payment and within the amount tolerance of the plan counts as the next payment -
it moves `last_seen`, `next_expected` and the status, never the amounts; callers add `household_summary.pending_debits`
to the counted transactions), `status` (`active` / `missing` > date tolerance overdue / `ended` > 2 periods overdue),
`price_change {previous,last,change_pct,increase,date}`, `category`, `account_key`, `account_type`, `account_person`.
Confidence (#129, `series_confidence.score_series`): every series carries `confidence {score 0-100, reasons[]}` and
`candidate` (score < 50). Signals: contract reference / direct-debit marker (+), card-payment marker (-), contract keywords
(Abo, Beitrag, Miete, Abschlag ...) (+), stable amount or one price step (+) vs varying (-), >= 4 payments (+) vs only 2 for
weekly/monthly (-), day-of-month regularity on a 31-day circle, contract categories (+) vs everyday ones (food, health,
shopping) (-). Reasons are codes, never amounts or names. Review (#130): `Contract.review` = `contract` (confirmed, never a
candidate again) or `not_contract` (the series is dropped from `build_contracts` for good); any stored contract fields
also end the candidate status. The contracts page lists candidates for admins under "Prüfen" with the reason codes as a
tooltip; `PUT /contracts/{id}` with `{"review": "not_contract"}` answers `{"id", "dismissed": true}`. Own names (#109): a series to an
own account holder's name is dropped as a transfer, unless its text carries a contract word or number and the amount is
stable (`series_confidence.own_name_contract`) - then it is a candidate with the first reason `own_name`. Candidates are left out of reserves, plan prefill, notice
events and the contracts page list/totals; non-admin views carry `candidate` too.
`detect_recurring` (monthly, home screen) is unchanged. `recurring.add_months` is a public helper.

## Contract model (`contracts.Contract`, stored in `.storage/finance_dashboard_contracts`)
Fields (all optional, `null` = prefilled default): `start`, `min_term_months`, `renewal_months`, `notice_value`,
`notice_unit` (days/weeks/months), `notice_reference` (`end_of_term`/`end_of_month`), `owner`, `category`,
`plan_position_id`, `special_termination` (null = derive), `plan_mode`, `plan_fixed_amount`, `review` (#130), `kind` (#111).

### Kinds (#111, `contract_kind.py`)
`kind` is how binding a payment is, separate from its category: `contract` (term, renewal, notice), `subscription`
(cancelable monthly), `regular` (habit without contract), `irregular` (recurring but irregular). `detect_series` sets
`kind_suggested` and `kind_trait` (`telecom` from the payment text) on every read; the stored `Contract.kind` overrides
the suggestion, `null` follows it — nothing is migrated. Suggestion order: yearly/quarterly/half-yearly -> contract;
contract word or number -> contract; subscription word -> subscription; not monthly or an everyday category -> regular;
health -> irregular; contract category -> contract; fixed monthly price -> subscription; else regular.
Defaults by kind: subscription 1/1 + 0 days; contract by category (insurance 12/12 + 3 months, utilities/loans/housing
12/12 + 1/3/3 months, telecom trait 24/12 + 1 month, else 12/12 + 1 month). `regular` and `irregular` have no notice:
`next_deadline`, `effective_end`, `days_until_deadline` are `null`, `notice_due_soon` false, no notice event. The
payload carries `kind`, `kind_suggested`, `kind_trait` and `contract.defaults` / `contract.has_notice`.
`contracts.category_defaults` is kept for old callers.
Start falls back to the first seen payment. Deadline = (term end, or month end of it) - notice; rolls to the next renewal if passed.
Special termination prefill: last 3 payments, traits amount / booking day / gap; >=2 traits differing -> unchecked, else checked.
`special_termination_available` = latest price change is an increase and the (stored or prefilled) flag is checked.

## Endpoints
- `GET /api/finance_dashboard/contracts` - expense series + `contract` block + `next_deadline`, `effective_end`, `days_until_deadline`,
  `notice_due_soon`, `special_termination_available`, `monthly_equivalent`; sorted by next deadline. Admin full; non-admin only
  shared/own, reduced to aggregates (`aggregate_view`: no payment history). `totals` (#115, `contracts.contract_totals`):
  `{fixed, regular}` each `{monthly, yearly, count}` - fixed = contracts + subscriptions, regular = regular + irregular;
  candidates and ended series excluded; members get the totals of what they see.
- `PUT /api/finance_dashboard/contracts/{series_id}` (admin) partial edit; 400 `{error,detail}` on invalid, 404 `unknown_series`. Returns the updated contract.
- `GET /api/finance_dashboard/reserves` - `{reserves:{items,by_owner,total_monthly}, coverage}`; coverage is admin-only (`null` for others).
- `PUT /api/finance_dashboard/accounts/{key}/savings` `{savings: bool}` (admin) - sets `savings` on the account record via `async_set_accounts`; kept across `async_refresh_accounts`.

## Reserves and coverage
Reserve = every quarterly/half-yearly/yearly expense series (not `ended`): `annual_cost / 12`, grouped by owner.
Coverage: `Pot.account_key` (new optional field) names the account a `reserve`-kind pot sits on; per account
virtual total (pot `cycle_budget`) vs real balance (`pick_balance`) -> `covered` / `shortfall` (+`top_up`) / `unknown` (no cached balance).
Pots without `account_key` are counted in `unassigned_pots`. The pots endpoint may expose `account_key` via `Pot.to_dict`.

## Notice event hook for the setup agent
`await contracts.async_fire_notice_due(hass, get_effective_transactions(manager._transactions))` - call from the daily
refresh path after the ledger update. Fires `finance_dashboard_notice_due` (`series_id, creditor, deadline, effective_end, days_left, owner`; no amount)
for deadlines 0..30 days away, once per contract per deadline (markers persisted in the contract store). Returns the count.

## Open
- Views are registered in `api/__init__.py`; the hook call is NOT wired into the refresh path yet.
- No frontend; no strings/translations added (API returns codes only).
- Plan position link is stored only; no plan-vs-actual use yet.
