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
