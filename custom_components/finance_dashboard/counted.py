"""The one rule for what counts as income or spending.

Every view (monthly summary, plan vs actual, home, household summary, notify,
contracts, wizards) reads the same list from here, so the same period shows the
same total everywhere. What is left out is *movement*:

- **Transfer chains**: every leg of a chain is money moving between own
  accounts, however many accounts it crosses. The purchase behind a cascade
  (savings -> bank -> PayPal -> shop) is the merchant debit on the last
  account, which is no chain member and counts once. A chain the user rejected
  is ordinary bookings again.
- **Own-account transfers**: bookings categorised ``transfers``, linked or not.
- **PayPal mirror**: with a PayPal account linked, its lines name the real
  merchant and are the counted side. The bank debit that funds such a line, a
  top-up with its funding credit and a pay-later instalment are movement.
  Without a counterpart (PayPal not linked, or no such line) the debit is the
  only trace of the purchase and counts.

Only booked lines with a date count; ``include_pending`` keeps pending ones for
views that show what is still to come.

Refunds are netted by :func:`net_counted`, again the same for every view: the
expense shrinks and keeps its date, category and owner; a credit without a
matched expense falls back to the merchant's own category. Pure functions; no
I/O, no clock.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from .life_areas import (
    INCOME_REFUND,
    OTHER,
    TRANSFERS,
    is_income,
    is_refund,
    is_spending,
)
from .merchants import merchant_key
from .refund_matcher import net_refunds, ref_id
from .text_norm import canonical_name, processor_merchant_text
from .tx_dates import effective_day

MOVEMENT_CHAIN = "transfer_chain"
MOVEMENT_OWN = "own_transfer"
MOVEMENT_PAYPAL = "paypal_mirror"
MOVEMENT_TOPUP = "paypal_topup"
MOVEMENT_PAY_LATER = "paypal_pay_later"

PAYPAL_MIRROR_DAYS = 5
_PAY_LATER = re.compile(
    r"pay\s*later|paylater|pay\s*in\s*(3|30)|später\s*bezahlen|spaeter\s*bezahlen"
    r"|in\s*3\s*raten|ratenzahlung|ratenkauf",
    re.IGNORECASE,
)


def is_spending_area(category: str | None) -> bool:
    return category != OTHER and is_spending(category)


def amount_of(tx: dict[str, Any]) -> float:
    try:
        return float((tx.get("transactionAmount") or {}).get("amount", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def is_paypal(text: str) -> bool:
    return "paypal" in text.lower()


def paypal_account_ids(accounts: list[dict[str, Any]]) -> set[str]:
    """Uids of linked accounts that are PayPal accounts."""
    return {
        str(a.get("id"))
        for a in accounts or []
        if a.get("id") and is_paypal(f"{a.get('institution', '')} {a.get('name', '')}")
    }


def _same_merchant(merchant: str, line: dict[str, Any]) -> bool:
    """The bank debit names no merchant, or the PayPal line's payee shares a word with it."""
    if not merchant:
        return True
    payee = canonical_name(str(line.get("creditorName") or line.get("debtorName") or ""))
    return not payee or bool(set(merchant.split()) & set(payee.split()))


def is_funding_line(tx: dict[str, Any]) -> bool:
    """A credit on PayPal that can be a top-up: a merchant's refund cannot."""
    category = tx.get("category")
    text = str(tx.get("remittanceInformationUnstructured") or "")
    return category != INCOME_REFUND and not is_spending_area(category) and not is_refund(text)


def _paypal_movement(booked: list[dict[str, Any]], pp_ids: set[str]) -> dict[int, str]:
    """``id(tx)`` -> reason for the lines that only move money to PayPal.

    Each PayPal line pairs with one debit (same amount, within
    ``PAYPAL_MIRROR_DAYS``), so a second equal purchase is not swallowed by the
    first debit.
    """
    if not pp_ids:
        return {}
    purchases: dict[int, list[dict[str, Any]]] = defaultdict(list)
    credits_: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for tx in booked:
        if effective_day(tx) is None or str(tx.get("_account_id") or "") not in pp_ids:
            continue
        cents = round(amount_of(tx) * 100)
        if cents < 0:
            purchases[cents].append(tx)
        elif cents > 0 and is_funding_line(tx):
            credits_[-cents].append(tx)
    debits = sorted(
        (
            tx
            for tx in booked
            if amount_of(tx) < 0
            and effective_day(tx) is not None
            and str(tx.get("_account_id") or "") not in pp_ids
            and is_paypal(f"{tx.get('creditorName', '')} {tx.get('debtorName', '')}")
        ),
        key=effective_day,
    )

    def gap(day: date, line: dict[str, Any]) -> int | None:
        days = abs((effective_day(line) - day).days)
        return days if days <= PAYPAL_MIRROR_DAYS else None

    out: dict[int, str] = {}
    for tx in debits:
        day, cents = effective_day(tx), round(amount_of(tx) * 100)
        funding = [c for c in credits_.get(cents, []) if gap(day, c) is not None]
        remittance = str(tx.get("remittanceInformationUnstructured") or "")
        merchant = canonical_name(processor_merchant_text(remittance))
        bought = [
            p
            for p in purchases.get(cents, [])
            if gap(day, p) is not None and _same_merchant(merchant, p)
        ]
        if funding:
            credit = min(funding, key=lambda c: gap(day, c))
            credits_[cents].remove(credit)
            out[id(credit)] = MOVEMENT_TOPUP
        if bought:
            purchases[cents].remove(min(bought, key=lambda p: gap(day, p)))
        if funding or bought:
            out[id(tx)] = MOVEMENT_PAYPAL if bought else MOVEMENT_TOPUP
        elif _PAY_LATER.search(remittance):
            # repays purchases already counted on the PayPal account
            out[id(tx)] = MOVEMENT_PAY_LATER
    return out


def movement_reasons(
    transactions: list[dict[str, Any]], accounts: list[dict[str, Any]]
) -> dict[int, str]:
    """``id(tx)`` -> why a booking does not count (absent: it counts)."""
    booked = [t for t in transactions if t.get("_status", "booked") == "booked"]
    out = _paypal_movement(booked, paypal_account_ids(accounts))
    for tx in transactions:
        if tx.get("_transfer_chain_id") and tx.get("_transfer_confirmed") is not False:
            out[id(tx)] = MOVEMENT_CHAIN
        elif str(tx.get("category") or "") == TRANSFERS:
            out[id(tx)] = MOVEMENT_OWN
    return out


def counted_transactions(
    transactions: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    *,
    include_pending: bool = False,
) -> list[dict[str, Any]]:
    """Dated transactions that are real income or spending (see module doc)."""
    movement = movement_reasons(transactions, accounts)
    return [
        tx
        for tx in transactions
        if id(tx) not in movement
        and effective_day(tx) is not None
        and (include_pending or tx.get("_status", "booked") == "booked")
    ]


def _detector_allocations(counted: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Refund pairs of the transfer detector, in the shape of the refund matcher's."""
    originals = {
        t.get("_refund_pair_id"): t for t in counted if t.get("_refund_role") == "original"
    }
    out: dict[str, dict[str, float]] = {}
    for t in counted:
        if t.get("_refund_role") != "refund":
            continue
        original = originals.get(t.get("_refund_pair_id"))
        rid, eid = ref_id(t), ref_id(original) if original else ""
        if rid and eid:
            out[rid] = {eid: amount_of(t)}
    return out


def _merchant_categories(counted: list[dict[str, Any]]) -> dict[str, str]:
    """The category a merchant's debits mostly carry."""
    seen: dict[str, Counter[str]] = defaultdict(Counter)
    for t in counted:
        key = merchant_key(t)
        if key and amount_of(t) < 0:
            seen[key][str(t.get("category") or OTHER)] += 1
    return {key: c.most_common(1)[0][0] for key, c in seen.items()}


def net_counted(
    counted: list[dict[str, Any]], allocations: dict[str, dict[str, float]] | None = None
) -> list[dict[str, Any]]:
    """Counted bookings with every refund netted into the expense it belongs to.

    ``allocations`` are the refund matcher's (#119) and win over the detector's
    pair for the same refund. A credit note without a matched expense reduces
    the merchant's usual category, so an annual settlement lowers energy, not
    "other", and is no income (#170).
    """
    merged = {**_detector_allocations(counted), **(allocations or {})}
    netted = net_refunds(counted, merged) if merged else list(counted)
    by_merchant = _merchant_categories(netted)
    out: list[dict[str, Any]] = []
    for t in netted:
        if amount_of(t) > 0 and (
            t.get("category") == INCOME_REFUND or t.get("_refund_role") == "refund"
        ):
            home = by_merchant.get(merchant_key(t))
            if home is not None:
                t = {**t, "category": home, "_net_expense": True, "_refund_role": None}
        out.append(t)
    return out


def is_income_line(tx: dict[str, Any]) -> bool:
    """Money that came in as income; any other credit reduces an expense.

    A shop's credit carries the shop's category and is no income.
    """
    if amount_of(tx) <= 0 or tx.get("_refund_role") == "refund" or tx.get("_net_expense"):
        return False
    category = tx.get("category")
    return not category or category == OTHER or is_income(category)


def is_salary_candidate(tx: dict[str, Any]) -> bool:
    """A credit that may open an income cycle: income, and never a refund."""
    return is_income_line(tx) and tx.get("category") != INCOME_REFUND


def income_payer(tx: dict[str, Any]) -> str:
    """Who paid a credit; ``""`` when the bank does not say."""
    return canonical_name(str(tx.get("debtorName") or ""))
