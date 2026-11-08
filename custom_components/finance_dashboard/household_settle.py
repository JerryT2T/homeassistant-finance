"""Settlement between the persons and the household (F1).

Money moves between a person and the household whenever the payer and the
owner differ:

* **personal spend paid from a household account** -> the person *owes* the
  household that amount;
* **household spend paid from a personal account** ({P} or {P,H}) -> the
  household *owes* the person that amount.

One counting rule: ``txs`` are the counted, netted bookings
(``counted.counted_transactions`` -> ``counted.net_counted``), dated through
``tx_dates``; a refund comes out as a negative spend and nets itself. The
owner of each booking is the one chain (``Classifier.classify_detail`` ->
``ownership.resolve_owner_detail``), so what the review shows and what is
settled can never disagree. A person's expense paid from *another* person's
account is not settled here (no household in between). Pure; no I/O.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .const import OWNER_SHARED
from .counted import amount_of, is_income_line
from .household_summary import Classifier
from .ownership import KIND_HOUSEHOLD, KIND_OPEN, OWNER_OPEN, tx_kind
from .tx_dates import effective_day


def settlement_balances(
    txs: list[dict[str, Any]],
    clf: Classifier,
    window: tuple[date, date] | None = None,
) -> dict[str, dict[str, float]]:
    """Per person ``{owes_household, household_owes, net}`` (euro, 2 decimals).

    ``net`` > 0: the person owes the household; ``net`` < 0: the household
    owes the person. ``window`` (inclusive) limits the bookings, e.g. a cycle
    from ``household_summary.cycle_windows``; ``None`` takes all of ``txs``.
    """
    out: dict[str, dict[str, float]] = {}

    def row(person: str) -> dict[str, float]:
        return out.setdefault(person, {"owes_household": 0.0, "household_owes": 0.0, "net": 0.0})

    for tx in txs:
        day = effective_day(tx)
        if day is None or (window is not None and not window[0] <= day <= window[1]):
            continue
        if is_income_line(tx):
            continue
        kind = tx_kind(tx)
        if kind == KIND_OPEN:
            continue
        owner = clf.classify_detail(tx, day)[0]
        if owner == OWNER_OPEN:
            continue
        spent = -amount_of(tx)
        payer = str(tx.get("_account_person") or "")
        if kind == KIND_HOUSEHOLD:
            if owner != OWNER_SHARED:  # someone's own spend from the joint account
                row(owner)["owes_household"] += spent
        elif owner == OWNER_SHARED and payer:  # the household's spend from a personal account
            row(payer)["household_owes"] += spent
    for vals in out.values():
        vals["owes_household"] = round(vals["owes_household"], 2)
        vals["household_owes"] = round(vals["household_owes"], 2)
        vals["net"] = round(vals["owes_household"] - vals["household_owes"], 2)
    return out
