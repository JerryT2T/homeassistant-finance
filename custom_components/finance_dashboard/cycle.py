"""Income cycles — a person's and the household's budget period.

A cycle is not a calendar month: it starts when the main income arrives and
runs until the day before the next one.

Rules (decided with the user, see ``docs/dev/household-model.md``):

- **Person**: the cycle runs from one salary to the next. The salary is the
  highest income that *recurs*: per payer, amounts that come back in another
  month set a level, and credits around that level (compared with the payer's
  neighbouring credits, so a raise is followed) are salary events. A one-off
  large credit (sale proceeds, a deposit returned, a loan payout) has no level
  and moves nothing. Incomes within the ±5-day salary tolerance of each other
  are one salary event; the earliest of them marks the start. Only without any
  recurring income does the largest credit seen stand in.
- **Household**: the highest income of all persons sets the cycle start, unless
  another person's salary falls within the 7 days *before* it - then that
  earlier one is the start (both salaries belong to the same budget round).

All functions are pure: no I/O, no clock. ``today`` is always passed in.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from statistics import median

# Incomes this many days apart are one salary event.
SALARY_TOLERANCE_DAYS = 5
# An income counts as "the salary" within this fraction of the salary level.
SALARY_AMOUNT_RATIO = 0.8
# Credits below this fraction of a payer's level are not salary but small extras.
SALARY_SIGNIFICANT_RATIO = 0.5
# Neighbouring credits of a payer that form the local level (each side).
SALARY_NEIGHBOURS = 3
# A payer pays one salary per cycle: a credit sooner than this after the last one is an extra.
SALARY_MIN_GAP_DAYS = 25
# A payer without a credit for this long no longer sets the level (the job has ended).
SALARY_ACTIVE_DAYS = 62
# A household salary this many days (or fewer) before the highest one pulls the
# cycle start forward.
HOUSEHOLD_ANCHOR_WINDOW_DAYS = 7
# Used when only one salary event is known and the interval cannot be measured.
DEFAULT_CYCLE_DAYS = 30

# ``(date, amount)`` or ``(date, amount, payer)``; ``""`` = the bank names no payer.
Income = tuple


def _payer_level(rows: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """The credits of one payer that make up its recurring level ([] = none).

    A credit recurs when another one of similar size lands in a different
    month. Small extras of the same payer stay out of the level.
    """
    def recurs(day: date, amount: float) -> bool:
        return any(
            (d.year, d.month) != (day.year, day.month)
            and amount * SALARY_AMOUNT_RATIO <= a <= amount / SALARY_AMOUNT_RATIO
            for d, a in rows
        )

    recurring = [a for d, a in rows if recurs(d, a)]
    if not recurring:
        return []

    def weight(amount: float) -> float:
        return amount * sum(
            amount * SALARY_AMOUNT_RATIO <= a <= amount / SALARY_AMOUNT_RATIO for a in recurring
        )

    # The level carrying the most money: a yearly bonus recurs too, and must
    # not push the monthly salary below the floor.
    floor = max(recurring, key=weight) * SALARY_SIGNIFICANT_RATIO
    return [(d, a) for d, a in rows if a >= floor]


def _payer_events(rows: list[tuple[date, float]]) -> list[date]:
    """Salary dates of a recurring payer, judged against its neighbouring credits."""
    amounts = [a for _, a in rows]
    events: list[date] = []
    for i, (day, amount) in enumerate(rows):
        local = median(amounts[max(0, i - SALARY_NEIGHBOURS) : i + SALARY_NEIGHBOURS + 1])
        if amount < local * SALARY_AMOUNT_RATIO:
            continue
        # A salary, also with a bonus or a raise, lands on payday; a credit between
        # two paydays is an extra, and so is a large one with nothing to compare.
        if events and (day - events[-1]).days < SALARY_MIN_GAP_DAYS:
            continue
        if not events and amount > local / SALARY_AMOUNT_RATIO:
            continue
        events.append(day)
    return events


def _salary_levels(incomes: list[Income]) -> dict[str, list[tuple[date, float]]]:
    """Per payer the credits of its recurring level, sorted by date."""
    by_payer: dict[str, list[tuple[date, float]]] = {}
    for row in incomes:
        if float(row[1]) > 0:
            by_payer.setdefault(str(row[2]) if len(row) > 2 else "", []).append(  # noqa: PLR2004
                (row[0], float(row[1]))
            )
    out = {}
    for payer, rows in by_payer.items():
        level = _payer_level(sorted(rows))
        if level:
            out[payer] = level
    return out


def _top_level(levels: dict[str, list[tuple[date, float]]]) -> float:
    """The highest level among payers still paying.

    A lower-paid new job must not lose against a level that ended years ago.
    """
    latest = max(rows[-1][0] for rows in levels.values())
    return max(
        median(a for _, a in rows)
        for rows in levels.values()
        if (latest - rows[-1][0]).days <= SALARY_ACTIVE_DAYS
    )


def salary_level(incomes: list[Income]) -> float:
    """The typical salary amount (0 when there is no income at all)."""
    levels = _salary_levels(incomes)
    if levels:
        return _top_level(levels)
    return max((float(row[1]) for row in incomes if float(row[1]) > 0), default=0.0)


def salary_starts(incomes: list[Income]) -> list[date]:
    """Dates on which a new salary cycle began, ascending.

    Args:
        incomes: ``(booking_date, amount[, payer])`` of incoming money, amount
            positive. The payer lets a one-off credit of salary size stay out.
    """
    positive = [(row[0], float(row[1])) for row in incomes if float(row[1]) > 0]
    if not positive:
        return []
    levels = _salary_levels(incomes)
    if levels:
        top = _top_level(levels)
        events = sorted(
            d
            for rows in levels.values()
            if median(a for _, a in rows) >= top * SALARY_AMOUNT_RATIO
            for d in _payer_events(rows)
        )
    else:  # nothing recurs yet: the largest credit is the best guess there is
        top = max(a for _, a in positive)
        events = sorted(d for d, a in positive if a >= top * SALARY_AMOUNT_RATIO)
    starts: list[date] = []
    for d in events:
        if starts and (d - starts[-1]).days <= SALARY_TOLERANCE_DAYS:
            continue  # same salary event, keep the earliest
        starts.append(d)
    return starts


def calendar_cycle(today: date) -> tuple[date, date]:
    """Calendar month containing ``today`` (fallback when no salary is known)."""
    last = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=1), today.replace(day=last)


def _typical_length(starts: list[date]) -> int:
    gaps = [(b - a).days for a, b in zip(starts, starts[1:], strict=False)]
    return max(1, round(median(gaps))) if gaps else DEFAULT_CYCLE_DAYS


def cycle_windows(starts: list[date]) -> list[tuple[date, date]]:
    """Closed ``(start, end)`` windows between consecutive starts."""
    return [(a, b - timedelta(days=1)) for a, b in zip(starts, starts[1:], strict=False)]


def _window(starts: list[date], today: date) -> tuple[date, date] | None:
    """Cycle ``(start, end)`` containing ``today`` from known start dates."""
    past = [s for s in starts if s <= today]
    if not past:
        return None
    start = past[-1]
    future = [s for s in starts if s > today]
    if future:
        end = future[0] - timedelta(days=1)
    else:
        end = start + timedelta(days=_typical_length(starts) - 1)
    # The expected next salary is overdue: the cycle runs on until it lands.
    return start, max(end, today)


def person_cycle(incomes: list[Income], today: date) -> tuple[date, date]:
    """``(start, end)`` of the person's current cycle, both inclusive.

    Falls back to the calendar month when no salary is known yet.
    """
    return _window(salary_starts(incomes), today) or calendar_cycle(today)


def household_starts(person_incomes: dict[str, list[Income]]) -> list[tuple[date, str]]:
    """Household cycle starts ``(date, anchor person)``, ascending.

    Every salary event of the person with the highest income opens a cycle; an
    earlier salary of someone else within the 7 days before it moves the start.
    """
    per_person = {name: salary_starts(inc) for name, inc in person_incomes.items()}
    per_person = {name: s for name, s in per_person.items() if s}
    if not per_person:
        return []

    main = max(per_person, key=lambda n: (salary_level(person_incomes[n]), n))
    out: list[tuple[date, str]] = []
    for anchor_date in per_person[main]:
        start, who = anchor_date, main
        for name, starts in per_person.items():
            if name == main:
                continue
            for d in starts:
                if 0 < (anchor_date - d).days <= HOUSEHOLD_ANCHOR_WINDOW_DAYS and d < start:
                    start, who = d, name
        out.append((start, who))
    return out


def household_cycle(
    person_incomes: dict[str, list[Income]], today: date
) -> tuple[date, date, str | None]:
    """``(start, end, anchor_person)`` of the household's current cycle."""
    starts = household_starts(person_incomes)
    window = _window([s for s, _ in starts], today)
    if window is None:
        start, end = calendar_cycle(today)
        return start, end, None
    anchor = next(who for s, who in starts if s == window[0])
    return window[0], window[1], anchor
