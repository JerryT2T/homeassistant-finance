"""Cascading transfer detection.

Detects when the same money flow cascades through multiple accounts:
  HelloFresh -39.90 from PayPal → PayPal -39.90 from DKB → top-up DKB from savings

Without detection, this single €39.90 expense counts 3x in summaries.
The detector links the money moves into a chain; none of its legs counts, the
merchant debit is the purchase (``counted.py``).

IMPORTANT: Accounts like PayPal are NOT globally marked as intermediaries.
Only individual transactions are detected as pass-through when amount and
timing match across accounts.

A link needs evidence beyond amount and date (a linked IBAN, an account or
holder name, a transfer keyword): an unrelated purchase and credit of the same
amount must not hide each other (#174). Such a pair is only offered as a
question; the answer is stored like any chain decision and links it for good.

Chain ids are derived from the member bookings, so a decision survives refresh,
reprocess and restart (#173).
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .const import (
    REFUND_KEYWORDS,
    TRANSFER_AMOUNT_TOLERANCE,
    TRANSFER_AUTO_CONFIDENCE,
    TRANSFER_REFUND_WINDOW_DAYS,
    TRANSFER_TIME_WINDOW_DAYS,
)
from .own_accounts import OwnAccounts, normalize_iban
from .tx_dates import effective_day

_LOGGER = logging.getLogger(__name__)

CHAIN_ID_PREFIX = "chain:"
REFUND_ID_PREFIX = "refund:"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TransferPair:
    """A matched pair of transactions across two accounts."""

    outgoing_txn_id: str
    incoming_txn_id: str
    outgoing_account_id: str
    incoming_account_id: str
    amount: float
    confidence: float
    date_delta_days: int


@dataclass
class TransferChain:
    """A chain of linked transfer pairs forming a cascade."""

    chain_id: str
    pairs: list[TransferPair] = field(default_factory=list)
    txn_ids: list[str] = field(default_factory=list)
    source_txn_id: str = ""
    destination_txn_id: str = ""
    intermediate_txn_ids: list[str] = field(default_factory=list)
    total_confidence: float = 0.0


@dataclass
class RefundPair:
    """A refund matched to its original transaction."""

    refund_id: str
    original_txn_id: str
    refund_txn_id: str
    amount: float
    creditor: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _txn_id(txn: dict[str, Any]) -> str:
    """Identity of a booking; PayPal rows often have no transaction id.

    A ledger id is unique per account only, the same fingerprint can sit on two.
    """
    lid = txn.get("_ledger_id")
    if lid:
        return f"{txn.get('_account_key') or txn.get('_account_id') or ''}|{lid}"
    return str(txn.get("transactionId") or "")


def stable_chain_id(members: list[dict[str, Any]]) -> str:
    """Deterministic chain id: the same member bookings always give the same id."""
    joined = "\n".join(sorted(_txn_id(t) for t in members))
    return CHAIN_ID_PREFIX + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


def is_stable_chain_id(chain_id: Any) -> bool:
    return isinstance(chain_id, str) and chain_id.startswith(CHAIN_ID_PREFIX)


def detect_transfer_chains(
    transactions: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    overrides: dict[str, bool] | None = None,
) -> tuple[list[TransferChain], list[RefundPair]]:
    """Detect cascading transfers and refunds in transaction list.

    Args:
        transactions: All transactions (enriched with _account_id etc.)
        accounts: Account metadata list
        config: Optional overrides for tolerances/thresholds
        overrides: Stored chain decisions; ``True`` links a pair that has no
            evidence of its own

    Returns:
        Tuple of (chains, refunds)
    """
    cfg = _merge_config(config)

    # Only process booked transactions
    booked = [t for t in transactions if t.get("_status") == "booked"]

    # Phase A — find transfer pairs
    pairs, _open = _find_transfer_pairs(booked, accounts, cfg, overrides)
    _LOGGER.debug("Phase A: found %d transfer pairs", len(pairs))

    # Phase B — resolve cascades into chains
    chains = _resolve_chains(pairs, booked)
    _LOGGER.debug("Phase B: resolved %d chains", len(chains))

    # Phase C — detect refunds (independent of chains)
    refunds = _detect_refunds(booked, cfg)
    _LOGGER.debug("Phase C: found %d refund pairs", len(refunds))

    _LOGGER.info(
        "Transfer detection: %d chains, %d refund pairs",
        len(chains),
        len(refunds),
    )
    return chains, refunds


def transfer_questions(
    transactions: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    overrides: dict[str, bool] | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Pairs that match on amount and date only and nobody decided on yet.

    Each entry: ``{"id", "out", "in", "confidence"}`` with the two bookings.
    """
    booked = [t for t in transactions if t.get("_status") == "booked"]
    _pairs, unanswered = _find_transfer_pairs(booked, accounts, _merge_config(config), overrides)
    by_id = {_txn_id(t): t for t in booked}
    out: list[dict[str, Any]] = []
    for pair in unanswered:
        out_txn, in_txn = by_id[pair.outgoing_txn_id], by_id[pair.incoming_txn_id]
        out.append(
            {
                "id": stable_chain_id([out_txn, in_txn]),
                "out": out_txn,
                "in": in_txn,
                "confidence": pair.confidence,
            }
        )
    return out


def enrich_transactions(
    transactions: list[dict[str, Any]],
    chains: list[TransferChain],
    refunds: list[RefundPair],
) -> list[dict[str, Any]]:
    """Add transfer chain and refund metadata to transactions.

    Mutates the transaction dicts in place and returns the same list.
    """
    # Build lookup: txn_id → chain info
    chain_lookup: dict[str, tuple[TransferChain, str]] = {}
    for chain in chains:
        for txn_id in chain.txn_ids:
            if txn_id == chain.source_txn_id:
                role = "source"
            elif txn_id == chain.destination_txn_id:
                role = "destination"
            else:
                role = "intermediate"
            chain_lookup[txn_id] = (chain, role)

    # Build lookup: txn_id → refund info
    refund_lookup: dict[str, tuple[str, str]] = {}
    for ref in refunds:
        refund_lookup[ref.original_txn_id] = (ref.refund_id, "original")
        refund_lookup[ref.refund_txn_id] = (ref.refund_id, "refund")

    for txn in transactions:
        txn_id = _txn_id(txn)

        # Chain enrichment
        if txn_id in chain_lookup:
            chain, role = chain_lookup[txn_id]
            txn["_transfer_chain_id"] = chain.chain_id
            txn["_transfer_role"] = role
            txn["_transfer_linked_txns"] = [tid for tid in chain.txn_ids if tid != txn_id]
            txn["_transfer_confidence"] = chain.total_confidence
            txn["_transfer_confirmed"] = None  # awaiting user action
        else:
            txn["_transfer_chain_id"] = None
            txn["_transfer_role"] = None
            txn["_transfer_linked_txns"] = []
            txn["_transfer_confidence"] = None
            txn["_transfer_confirmed"] = None

        # Refund enrichment
        if txn_id in refund_lookup:
            refund_id, refund_role = refund_lookup[txn_id]
            txn["_refund_pair_id"] = refund_id
            txn["_refund_role"] = refund_role
        else:
            txn["_refund_pair_id"] = None
            txn["_refund_role"] = None

    return transactions


def get_effective_transactions(
    transactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Filter out every leg of a transfer chain (a chain is pure movement).

    A rejected chain (user said "no") is kept as independent transactions. This
    is the chain part of the one counting rule; views use
    :func:`counted.counted_transactions`, which applies the rest as well.
    """
    return [
        txn
        for txn in transactions
        if not txn.get("_transfer_role") or txn.get("_transfer_confirmed") is False
    ]


def apply_overrides(
    transactions: list[dict[str, Any]],
    overrides: dict[str, bool],
) -> None:
    """Apply user confirmations/rejections to chain-detected transactions.

    Args:
        transactions: Enriched transaction list
        overrides: {chain_id: True/False} from persistent storage
    """
    for txn in transactions:
        chain_id = txn.get("_transfer_chain_id")
        if chain_id and chain_id in overrides:
            txn["_transfer_confirmed"] = overrides[chain_id]


# ---------------------------------------------------------------------------
# Phase A — Pair detection
# ---------------------------------------------------------------------------


def _find_transfer_pairs(
    transactions: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
    config: dict[str, Any],
    overrides: dict[str, bool] | None = None,
) -> tuple[list[TransferPair], list[TransferPair]]:
    """Find matching pairs across accounts: ``(linked, unanswered questions)``."""
    decided = overrides or {}
    tolerance = config["amount_tolerance"]
    window_days = config["time_window_days"]
    auto_confidence = config["auto_confidence"]

    # Build account name lookup for creditor/debtor matching
    account_names = _build_account_name_set(accounts)
    own = OwnAccounts.of(accounts)
    ibans = {str(a.get("id")): normalize_iban(a.get("iban")) for a in accounts if a.get("id")}

    # Separate outgoing (negative) and incoming (positive) transactions
    outgoing = []
    incoming = []
    for txn in transactions:
        amount = float(txn.get("transactionAmount", {}).get("amount", 0))
        if amount < 0:
            outgoing.append(txn)
        elif amount > 0:
            incoming.append(txn)

    # Index incoming by amount bucket for faster lookup
    incoming_by_amount = _bucket_by_amount(incoming, tolerance)

    def best_for(
        out_txn: dict[str, Any], used: set[str], *, want_link: bool
    ) -> TransferPair | None:
        """The best partner for a debit among linkable pairs, or among open questions."""
        out_amount = abs(float(out_txn["transactionAmount"]["amount"]))
        out_date = effective_day(out_txn)
        out_account = out_txn.get("_account_id", "")
        if not out_date or not out_account:
            return None
        best: TransferPair | None = None
        for in_txn in _get_amount_candidates(incoming_by_amount, out_amount, tolerance):
            in_id = _txn_id(in_txn)
            in_account = in_txn.get("_account_id", "")
            if in_id in used or in_account == out_account:
                continue  # taken, or same account — not a transfer
            in_date = effective_day(in_txn)
            if not in_date:
                continue
            date_delta = abs((out_date - in_date).days)
            if date_delta > window_days:
                continue
            confidence = _score_pair(
                out_txn,
                in_txn,
                out_amount,
                float(in_txn["transactionAmount"]["amount"]),
                date_delta,
                account_names,
                tolerance,
            )
            if confidence < auto_confidence or (best and confidence <= best.confidence):
                continue
            if _has_evidence(out_txn, in_txn, account_names, own, ibans):
                decision = True
            else:
                decision = decided.get(stable_chain_id([out_txn, in_txn]))
            if decision is False or (decision is True) != want_link:
                continue
            best = TransferPair(
                outgoing_txn_id=_txn_id(out_txn),
                incoming_txn_id=in_id,
                outgoing_account_id=out_account,
                incoming_account_id=in_account,
                amount=out_amount,
                confidence=confidence,
                date_delta_days=date_delta,
            )
        return best

    # Real links first: an unproven pair must not take a credit from a proven one.
    pairs: list[TransferPair] = []
    used_incoming: set[str] = set()
    linked_out: set[str] = set()
    for out_txn in outgoing:
        pair = best_for(out_txn, used_incoming, want_link=True)
        if pair:
            pairs.append(pair)
            used_incoming.add(pair.incoming_txn_id)
            linked_out.add(pair.outgoing_txn_id)
    unanswered: list[TransferPair] = []
    for out_txn in outgoing:
        if _txn_id(out_txn) in linked_out:
            continue
        pair = best_for(out_txn, used_incoming, want_link=False)
        if pair:
            unanswered.append(pair)
            used_incoming.add(pair.incoming_txn_id)
    return pairs, unanswered


def _has_evidence(
    out_txn: dict[str, Any],
    in_txn: dict[str, Any],
    account_names: set[str],
    own: OwnAccounts,
    ibans: dict[str, str],
) -> bool:
    """Something beyond amount and date says the two bookings are one transfer."""
    out_iban = ibans.get(str(out_txn.get("_account_id") or ""))
    in_iban = ibans.get(str(in_txn.get("_account_id") or ""))
    paid_to = normalize_iban((out_txn.get("creditorAccount") or {}).get("iban"))
    paid_by = normalize_iban((in_txn.get("debtorAccount") or {}).get("iban"))
    if (in_iban and paid_to == in_iban) or (out_iban and paid_by == out_iban):
        return True
    # One leg says "own account"; the other must not name somebody else.
    out_own = own.matches(out_txn) or out_txn.get("category") == "transfers"
    in_own = own.matches(in_txn) or in_txn.get("category") == "transfers"
    if (out_own or in_own) and (out_own or not out_txn.get("creditorName")) and (
        in_own or not in_txn.get("debtorName")
    ):
        return True
    out_name = _normalize(out_txn.get("_account_name", ""))
    in_name = _normalize(in_txn.get("_account_name", ""))
    creditor = _normalize(out_txn.get("creditorName", ""))
    debtor = _normalize(in_txn.get("debtorName", ""))
    out_text = _normalize(out_txn.get("remittanceInformationUnstructured", ""))
    in_text = _normalize(in_txn.get("remittanceInformationUnstructured", ""))
    if _names(in_name, creditor) or _names(in_name, out_text):
        return True
    if _names(out_name, debtor) or _names(out_name, in_text):
        return True
    # A known account name on one leg, nobody else on the other.
    out_known = any(_names(name, creditor) for name in account_names)
    in_known = any(_names(name, debtor) for name in account_names)
    return (out_known or in_known) and (out_known or not creditor) and (in_known or not debtor)


def _score_pair(
    out_txn: dict[str, Any],
    in_txn: dict[str, Any],
    out_amount: float,
    in_amount: float,
    date_delta: int,
    account_names: set[str],
    tolerance: float,
) -> float:
    """Calculate confidence score for a candidate transfer pair."""
    score = 0.0

    # Amount match
    amount_diff = abs(out_amount - in_amount)
    if amount_diff < 0.01:
        score += 0.4
    elif amount_diff <= tolerance:
        score += 0.2

    # Date proximity
    if date_delta <= 1:
        score += 0.3
    elif date_delta <= 2:
        score += 0.2
    elif date_delta <= 3:
        score += 0.1

    # Account name appears in creditor/debtor fields
    out_account_name = _normalize(out_txn.get("_account_name", ""))
    in_account_name = _normalize(in_txn.get("_account_name", ""))

    out_creditor = _normalize(out_txn.get("creditorName", ""))
    in_debtor = _normalize(in_txn.get("debtorName", ""))
    out_remittance = _normalize(out_txn.get("remittanceInformationUnstructured", ""))
    in_remittance = _normalize(in_txn.get("remittanceInformationUnstructured", ""))

    # Does the outgoing creditor reference the incoming account?
    if _names(in_account_name, out_creditor) or _names(in_account_name, out_remittance):
        score += 0.3
    # Does the incoming debtor reference the outgoing account?
    elif _names(out_account_name, in_debtor) or _names(out_account_name, in_remittance):
        score += 0.3
    # Check against known account names in the system
    elif _any_account_name_match(out_creditor, in_debtor, account_names):
        score += 0.2

    # Category is already "transfers"
    if out_txn.get("category") == "transfers":
        score += 0.1
    if in_txn.get("category") == "transfers":
        score += 0.1

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Phase B — Cascade resolution
# ---------------------------------------------------------------------------


def _resolve_chains(
    pairs: list[TransferPair],
    transactions: list[dict[str, Any]],
) -> list[TransferChain]:
    """Build transfer chains from pairs by linking cascades.

    If account B has both an incoming pair (from A) and an outgoing pair
    (to C), these are merged into a single chain A → B → C.
    """
    if not pairs:
        return []

    # Build adjacency: incoming_txn_id → pair (the pair that delivers to B)
    delivers_to: dict[str, TransferPair] = {}
    for pair in pairs:
        delivers_to[pair.incoming_txn_id] = pair

    # Build adjacency: outgoing_txn_id → pair (the pair that takes from B)
    takes_from: dict[str, TransferPair] = {}
    for pair in pairs:
        takes_from[pair.outgoing_txn_id] = pair

    # Transaction lookup for account resolution
    txn_lookup = {_txn_id(t): t for t in transactions}

    # Find chains by following the cascade
    visited_pairs: set[int] = set()
    chains: list[TransferChain] = []

    for pair in pairs:
        pair_id = id(pair)
        if pair_id in visited_pairs:
            continue

        # Walk backward to find the start of the chain
        chain_pairs = [pair]
        visited_pairs.add(pair_id)

        # Walk backward: is there a pair that delivers to our outgoing account?
        current = pair
        while True:
            # The outgoing txn of current pair — is it also an incoming txn
            # of another pair? That means money flowed IN before flowing OUT.
            out_txn = txn_lookup.get(current.outgoing_txn_id, {})
            out_account = out_txn.get("_account_id", "")

            # Find a pair where incoming_account == our outgoing_account
            # AND the incoming amount matches
            predecessor = _find_matching_predecessor(
                current,
                out_account,
                pairs,
                visited_pairs,
                txn_lookup,
            )
            if predecessor:
                chain_pairs.insert(0, predecessor)
                visited_pairs.add(id(predecessor))
                current = predecessor
            else:
                break

        # Walk forward: does the destination have an outgoing pair?
        current = pair
        while True:
            in_txn = txn_lookup.get(current.incoming_txn_id, {})
            in_account = in_txn.get("_account_id", "")

            successor = _find_matching_successor(
                current,
                in_account,
                pairs,
                visited_pairs,
                txn_lookup,
            )
            if successor:
                chain_pairs.append(successor)
                visited_pairs.add(id(successor))
                current = successor
            else:
                break

        # Build the chain
        chain = _build_chain(chain_pairs, txn_lookup)
        chains.append(chain)

    return chains


def _find_matching_predecessor(
    current: TransferPair,
    out_account: str,
    pairs: list[TransferPair],
    visited: set[int],
    txn_lookup: dict[str, dict[str, Any]],
) -> TransferPair | None:
    """Find a pair that delivers money to the outgoing account of current."""
    for pair in pairs:
        if id(pair) in visited:
            continue
        if pair.incoming_account_id != out_account:
            continue
        # Amount should be similar
        if abs(pair.amount - current.amount) > TRANSFER_AMOUNT_TOLERANCE:
            continue
        # The incoming txn date should be close to outgoing txn date
        in_txn = txn_lookup.get(pair.incoming_txn_id, {})
        out_txn = txn_lookup.get(current.outgoing_txn_id, {})
        in_date = effective_day(in_txn)
        out_date = effective_day(out_txn)
        if in_date and out_date:
            if abs((in_date - out_date).days) <= TRANSFER_TIME_WINDOW_DAYS:
                return pair
    return None


def _find_matching_successor(
    current: TransferPair,
    in_account: str,
    pairs: list[TransferPair],
    visited: set[int],
    txn_lookup: dict[str, dict[str, Any]],
) -> TransferPair | None:
    """Find a pair that takes money from the incoming account of current."""
    for pair in pairs:
        if id(pair) in visited:
            continue
        if pair.outgoing_account_id != in_account:
            continue
        if abs(pair.amount - current.amount) > TRANSFER_AMOUNT_TOLERANCE:
            continue
        in_txn = txn_lookup.get(current.incoming_txn_id, {})
        out_txn = txn_lookup.get(pair.outgoing_txn_id, {})
        in_date = effective_day(in_txn)
        out_date = effective_day(out_txn)
        if in_date and out_date:
            if abs((in_date - out_date).days) <= TRANSFER_TIME_WINDOW_DAYS:
                return pair
    return None


def _build_chain(
    chain_pairs: list[TransferPair],
    txn_lookup: dict[str, dict[str, Any]],
) -> TransferChain:
    """Build a TransferChain from an ordered list of pairs."""
    # Collect all unique transaction IDs in order
    all_txn_ids: list[str] = []
    seen: set[str] = set()
    for pair in chain_pairs:
        if pair.outgoing_txn_id not in seen:
            all_txn_ids.append(pair.outgoing_txn_id)
            seen.add(pair.outgoing_txn_id)
        if pair.incoming_txn_id not in seen:
            all_txn_ids.append(pair.incoming_txn_id)
            seen.add(pair.incoming_txn_id)

    chain_id = stable_chain_id([txn_lookup.get(tid, {"transactionId": tid}) for tid in all_txn_ids])

    # Source = first outgoing, Destination = last incoming
    source_txn_id = chain_pairs[0].outgoing_txn_id
    destination_txn_id = chain_pairs[-1].incoming_txn_id
    intermediate_txn_ids = [
        tid for tid in all_txn_ids if tid not in {source_txn_id, destination_txn_id}
    ]

    # Average confidence across all pairs
    avg_confidence = sum(p.confidence for p in chain_pairs) / len(chain_pairs)

    return TransferChain(
        chain_id=chain_id,
        pairs=chain_pairs,
        txn_ids=all_txn_ids,
        source_txn_id=source_txn_id,
        destination_txn_id=destination_txn_id,
        intermediate_txn_ids=intermediate_txn_ids,
        total_confidence=round(avg_confidence, 2),
    )


# ---------------------------------------------------------------------------
# Phase C — Refund detection
# ---------------------------------------------------------------------------


def _detect_refunds(
    transactions: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[RefundPair]:
    """Detect refund pairs: same amount, same creditor, same account."""
    window_days = config["refund_window_days"]
    refunds: list[RefundPair] = []
    used: set[str] = set()

    # Group outgoing transactions by (account, creditor)
    outgoing_index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for txn in transactions:
        amount = float(txn.get("transactionAmount", {}).get("amount", 0))
        if amount >= 0:
            continue
        account = txn.get("_account_id", "")
        creditor = _normalize(txn.get("creditorName", ""))
        if account and creditor:
            outgoing_index[(account, creditor)].append(txn)

    # Search incoming transactions for refund matches
    for txn in transactions:
        amount = float(txn.get("transactionAmount", {}).get("amount", 0))
        if amount <= 0:
            continue

        txn_id = _txn_id(txn)
        if txn_id in used:
            continue

        account = txn.get("_account_id", "")
        # For refunds, the creditor on the incoming side is who sends money back
        creditor = _normalize(txn.get("creditorName", "") or txn.get("debtorName", ""))
        if not account or not creditor:
            continue

        # Check if this looks like a refund (text contains refund keyword)
        text = _normalize(txn.get("remittanceInformationUnstructured", ""))
        creditor_text = _normalize(txn.get("creditorName", ""))
        combined = f"{text} {creditor_text}"
        is_refund_text = any(kw in combined for kw in REFUND_KEYWORDS)
        if not is_refund_text:
            continue

        in_date = effective_day(txn)
        if not in_date:
            continue

        # Find matching outgoing transaction
        candidates = outgoing_index.get((account, creditor), [])
        for orig in candidates:
            orig_id = _txn_id(orig)
            if orig_id in used:
                continue

            orig_amount = abs(float(orig["transactionAmount"]["amount"]))
            if abs(orig_amount - amount) > 0.01:
                continue

            orig_date = effective_day(orig)
            if not orig_date:
                continue

            # Refund must come AFTER the original
            delta = (in_date - orig_date).days
            if 0 <= delta <= window_days:
                refund_id = REFUND_ID_PREFIX + stable_chain_id([orig, txn])[len(CHAIN_ID_PREFIX) :]
                refunds.append(
                    RefundPair(
                        refund_id=refund_id,
                        original_txn_id=orig_id,
                        refund_txn_id=txn_id,
                        amount=amount,
                        creditor=creditor,
                    )
                )
                used.add(txn_id)
                used.add(orig_id)
                break

    return refunds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge_config(
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge user config with defaults."""
    defaults = {
        "amount_tolerance": TRANSFER_AMOUNT_TOLERANCE,
        "time_window_days": TRANSFER_TIME_WINDOW_DAYS,
        "refund_window_days": TRANSFER_REFUND_WINDOW_DAYS,
        "auto_confidence": TRANSFER_AUTO_CONFIDENCE,
    }
    if config:
        defaults.update(config)
    return defaults


def _normalize(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ""
    return " ".join(text.lower().strip().split())


def _build_account_name_set(
    accounts: list[dict[str, Any]],
) -> set[str]:
    """Build a set of normalized account names and institution names."""
    names: set[str] = set()
    for acc in accounts:
        for key in ("name", "custom_name", "institution"):
            val = acc.get(key, "")
            if val:
                normalized = _normalize(val)
                if len(normalized) >= 3:  # Skip very short names
                    names.add(normalized)
    return names


def _names(name: str, text: str) -> bool:
    """``text`` contains ``name`` as whole words: "ING" is not in "Leasing"."""
    if not name or not text:
        return False
    return re.search(rf"(?<![a-z0-9äöüß]){re.escape(name)}(?![a-z0-9äöüß])", text) is not None


def _any_account_name_match(
    creditor: str,
    debtor: str,
    account_names: set[str],
) -> bool:
    """Check if creditor or debtor contains any known account name."""
    return any(_names(name, creditor) or _names(name, debtor) for name in account_names)


def _bucket_by_amount(
    transactions: list[dict[str, Any]],
    tolerance: float,
) -> dict[int, list[dict[str, Any]]]:
    """Index transactions by rounded amount for fast lookup."""
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for txn in transactions:
        amount = abs(float(txn.get("transactionAmount", {}).get("amount", 0)))
        # Use integer cents as bucket key
        bucket = round(amount * 100)
        buckets[bucket].append(txn)
    return buckets


def _get_amount_candidates(
    buckets: dict[int, list[dict[str, Any]]],
    amount: float,
    tolerance: float,
) -> list[dict[str, Any]]:
    """Get transactions with similar amounts from the bucket index."""
    target = round(amount * 100)
    tolerance_cents = round(tolerance * 100)
    candidates = []
    for bucket_key in range(target - tolerance_cents, target + tolerance_cents + 1):
        candidates.extend(buckets.get(bucket_key, []))
    return candidates
