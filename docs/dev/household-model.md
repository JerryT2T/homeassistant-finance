# Household model

Read this before touching split logic, month cycles, income or bonus detection.
Note: Phase 4 (see `roadmap.md`) replaces the hard-wired 2026 spreadsheet model with building
blocks; until then this is the implemented model.

## Split model

Four modes for cost distribution:
- **Pooled equal** (default, the household spreadsheet's model): shared costs are paid from the
  POOLED net income, the remainder is split equally, and each person then pays their own
  individual fixed costs out of their share. Two persons' pocket money differs *only* by their
  individual costs, and a person with negative net income is carried by the pool.
- **Equal**: shared costs split evenly, each person keeps their own income.
- **Proportional**: shared costs split by net income ratio.
- **Custom**: user sets percentages per person.

`remainder_mode` is ignored in pooled mode: the remainder is already split equally there, and
applying it again would flatten exactly the individual-cost differences the model preserves.

Additional: remainder split ("no split" or "equal distribution"); optional category-level override
of the split (not implemented yet).

## Account owner sets and who owns an expense (`ownership.py`)

An account has exactly one owner set: `{person}`, `{person, household}`, `{household}` or none yet
("open"). No other combination exists (two persons on one account is not allowed), so "not household"
always means the one person. Stored backward-compatibly: `type` (`personal`/`shared`), `person` and the
boolean `household_use` (only with a person; old configs lack it = `False`, same meaning as before).
`ownership.account_kind` reads it, `apply_owner_set` writes it and rejects other combinations. Changing
an owner set re-derives the stored bookings (`async_apply_owner_change`, ledger replay, no bank call);
corrections and rules live in the merchant memory and stay.

One resolver, `ownership.resolve_owner_detail(tx, position, correction) -> (owner, source, confidence)`;
`plan_match.resolve_owner` returns its first element and `Classifier.classify_detail` adds it to the
classification, so `figures` and `home.py` can never disagree. The chain:

| source | confidence | applies on |
|---|---|---|
| `correction` (this booking) | 100 | every account |
| `merchant_rule` ("für alle von X merken") | 95 | every account |
| `plan` (matched plan position's owner) | 90 | every account |
| `series` (a recurring series decided once) | 85 | `{P,H}` only |
| `category` (household categories; default housing_cold, housing_warm, groceries; configurable) | 70 | `{P,H}` only |
| `ai` (shared/personal tendency of the merchant) | 60 | `{P,H}` only |
| `account` default | 100 on `{P}`/`{H}`, 50 = the person on `{P,H}`, 0 = open | - |

A confidence of 85 or more counts as done without asking. The derive step stamps the inputs on each
booking (`_account_household_use`, `_owner_override` + `_owner_scope` booking|merchant,
`_series_owner`, `_ai_tendency`, `_household_categories`); the plan position is matched at read time.
The old card-suffix signal is not built: with at most one person per account it has nothing to decide.

Settlement (`household_settle.settlement_balances`): from the counted, netted bookings, personal spend
paid from a `{H}` account is owed to the household by that person; household spend paid from a `{P}` or
`{P,H}` account is owed by the household to the payer. `net` > 0: the person owes the household.

## Year, review and settlement

The year view (`year_view.py`) and the review (`review.py`) add no counting of their own: every figure is
`household_summary.figures` inside a cycle from `window_of_month` (the cycle holding the 15th of a month, one
cycle per month), owners from `Classifier.classify_detail`. A cycle before the first booking is
`before_history`, one after today `future`; the prior-year comparison needs every counted account to reach back
to the prior-year window start, else the whole `vs_last_year` block and every `delta_prev` are omitted. In the
household view only the shared bucket carries categories and outliers; persons appear as totals. A plan
position may be marked `suspended` (paused on purpose): the review's plan check then does not expect a booking.
`settlement_balances` is shown per household cycle and in the review report.

## Income cycle (`cycle.py`, used by every view)

No view uses the calendar month; home, household summary, monthly summary (and with it the sensors
and budget events) and plan vs actual use the income cycle from
`household_summary.cycle_windows`. Asked for a month, they mean the cycle holding its 15th; the
payload's `period` says which days that is.

- **Person**: from one salary to the next. Candidates are credits in an income category that are
  no refund and no own-account transfer. Per payer, amounts that come back in another month form
  a level (the level carrying the most money, so a yearly bonus does not replace the salary);
  credits within +-20 % of the payer's neighbouring credits are salary events, a higher one only on
  payday (at least 25 days after the last one). A one-off credit from anyone else moves nothing.
  Payers below 80 % of the top level are not salaries. Bookings within the +-5-day tolerance of
  each other are one salary event (the earliest marks the start). Only when nothing recurs yet does
  the largest credit stand in. Without any income: confirmed payday, else calendar month. If the
  next salary is overdue the cycle runs on until it arrives. A new employer counts from its second
  salary on.
- **Household**: the highest income of all persons sets the start, unless another person's salary
  falls within the 7 days *before* it (1-7 days; 8 does not count, same day does not move it) -
  then that earlier salary is the start and that person is the "anchor". The rule and "ab Gehalt X"
  are shown only behind the info button of the cycle card.
- Pots (`pots.py`) accrue `cycle_budget / days_in_cycle` per day inside this cycle; unspent days
  carry forward, nothing crosses the cycle boundary. Status uses the +-10 % rule.

## Income and bonus detection (planned)

- Salary tolerance window of +-5 days for income detection.
- Income >= 15% above the 3-month average triggers an HA notification for confirmation
  (threshold configurable). A confirmed bonus goes to pocket money, not into the monthly
  balance/split calculation.

## Privacy

Default display is aggregates only. Individual transactions are HA-admin only.
