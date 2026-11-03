"""Tests for the transfer chain detector (T5).

Covers:
- Simple two-account transfer (-100 A, +100 B, same day)
- Three-stage cascade chain (HelloFresh → PayPal → DKB)
- Manual override (user confirms / rejects a chain)
- Non-transfer false-positive guard (two equal amounts, different vendors)
- Confidence scoring (high / medium / low)
- Refund detection (same creditor, storno keyword)
- enrich_transactions populates _transfer_role correctly
- get_effective_transactions excludes intermediate / destination legs
- apply_overrides propagates user decisions
"""

from __future__ import annotations

from custom_components.finance_dashboard.transfer_detector import (
    apply_overrides,
    detect_transfer_chains,
    enrich_transactions,
    get_effective_transactions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_IBAN = "DE89370400440532013000"


def _txn(
    txn_id: str,
    account_id: str,
    amount: float,
    date: str = "2025-01-15",
    creditor: str = "",
    debtor: str = "",
    remittance: str = "",
    account_name: str = "",
    status: str = "booked",
    category: str = "",
) -> dict:
    t: dict = {
        "transactionId": txn_id,
        "_account_id": account_id,
        "_account_name": account_name,
        "_status": status,
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
        "bookingDate": date,
    }
    if creditor:
        t["creditorName"] = creditor
    if debtor:
        t["debtorName"] = debtor
    if remittance:
        t["remittanceInformationUnstructured"] = remittance
    if category:
        t["category"] = category
    return t


def _account(acc_id: str, name: str) -> dict:
    return {"id": acc_id, "name": name}


# ---------------------------------------------------------------------------
# T5-A: Simple two-account transfer
# ---------------------------------------------------------------------------


class TestSimpleTransfer:
    """€100 moves from account A to account B on the same day."""

    def _make_txns(self):
        return [
            _txn("out-1", "acc-a", -100.00, creditor="Savings account",
                 account_name="Checking"),
            _txn("in-1", "acc-b", 100.00, debtor="Checking",
                 account_name="Savings account"),
        ]

    def _make_accounts(self):
        return [
            _account("acc-a", "Checking"),
            _account("acc-b", "Savings account"),
        ]

    def test_simple_transfer_detects_one_chain(self):
        chains, refunds = detect_transfer_chains(
            self._make_txns(), self._make_accounts()
        )
        assert len(chains) == 1
        assert len(refunds) == 0

    def test_simple_transfer_chain_has_two_legs(self):
        chains, _ = detect_transfer_chains(
            self._make_txns(), self._make_accounts()
        )
        chain = chains[0]
        assert len(chain.txn_ids) == 2

    def test_simple_transfer_source_and_destination(self):
        chains, _ = detect_transfer_chains(
            self._make_txns(), self._make_accounts()
        )
        chain = chains[0]
        assert chain.source_txn_id == "out-1"
        assert chain.destination_txn_id == "in-1"
        assert chain.intermediate_txn_ids == []

    def test_simple_transfer_confidence_above_threshold(self):
        chains, _ = detect_transfer_chains(
            self._make_txns(), self._make_accounts()
        )
        assert chains[0].total_confidence >= 0.60

    def test_simple_transfer_not_detected_across_same_account(self):
        """Two transactions on the same account must NOT form a chain."""
        txns = [
            _txn("out-1", "acc-a", -100.00),
            _txn("in-1", "acc-a", 100.00),  # same account!
        ]
        chains, _ = detect_transfer_chains(txns, [_account("acc-a", "Checking")])
        assert len(chains) == 0


# ---------------------------------------------------------------------------
# T5-B: Cascade / three-stage chain
# ---------------------------------------------------------------------------


class TestCascadeChain:
    """HelloFresh charges PayPal; PayPal draws from DKB.

    Transaction flow:
      DKB  -39.90 → PayPal (DKB funds PayPal)
      PayPal -39.90 → HelloFresh (PayPal pays HelloFresh)

    After detection the chain should be:
      source: DKB outgoing, intermediate: PayPal inflow+outflow, destination: HelloFresh inflow
    """

    def _make_txns(self):
        base = "2025-02-10"
        next_day = "2025-02-11"
        return [
            # DKB funds PayPal (leg 1)
            _txn("dkb-out", "dkb", -39.90, date=base,
                 creditor="PayPal Europe", account_name="DKB Girokonto"),
            _txn("pp-in", "paypal", 39.90, date=next_day,
                 debtor="DKB Girokonto", account_name="PayPal"),
            # PayPal pays HelloFresh (leg 2)
            _txn("pp-out", "paypal", -39.90, date=next_day,
                 creditor="HelloFresh SE", account_name="PayPal"),
            _txn("hf-in", "hellofresh", 39.90, date=next_day,
                 debtor="PayPal", account_name="HelloFresh SE"),
        ]

    def _make_accounts(self):
        return [
            _account("dkb", "DKB Girokonto"),
            _account("paypal", "PayPal"),
            _account("hellofresh", "HelloFresh SE"),
        ]

    def test_cascade_detects_chain(self):
        chains, _ = detect_transfer_chains(self._make_txns(), self._make_accounts())
        assert len(chains) >= 1

    def test_cascade_has_intermediate_leg(self):
        chains, _ = detect_transfer_chains(self._make_txns(), self._make_accounts())
        # At least one chain must have intermediate legs
        has_intermediate = any(len(c.intermediate_txn_ids) > 0 for c in chains)
        assert has_intermediate, "Expected at least one chain with an intermediate leg"

    def test_cascade_source_is_dkb_outgoing(self):
        chains, _ = detect_transfer_chains(self._make_txns(), self._make_accounts())
        # The fully resolved chain must originate from the DKB transaction
        full_chain = max(chains, key=lambda c: len(c.txn_ids))
        assert full_chain.source_txn_id == "dkb-out"

    def test_cascade_destination_is_hellofresh(self):
        chains, _ = detect_transfer_chains(self._make_txns(), self._make_accounts())
        full_chain = max(chains, key=lambda c: len(c.txn_ids))
        assert full_chain.destination_txn_id == "hf-in"


# ---------------------------------------------------------------------------
# T5-C: Override / manual marker
# ---------------------------------------------------------------------------


class TestOverride:
    """User can confirm or reject a detected chain."""

    def _setup(self):
        txns = [
            _txn("out-1", "acc-a", -50.00, creditor="acc-b",
                 account_name="Account A"),
            _txn("in-1", "acc-b", 50.00, debtor="Account A",
                 account_name="Account B"),
        ]
        accounts = [_account("acc-a", "Account A"), _account("acc-b", "Account B")]
        chains, refunds = detect_transfer_chains(txns, accounts)
        enrich_transactions(txns, chains, refunds)
        return txns, chains

    def test_override_confirm_true(self):
        txns, chains = self._setup()
        chain_id = chains[0].chain_id
        apply_overrides(txns, {chain_id: True})
        confirmed = [t["_transfer_confirmed"] for t in txns if t.get("_transfer_chain_id")]
        assert all(c is True for c in confirmed)

    def test_override_confirm_false(self):
        txns, chains = self._setup()
        chain_id = chains[0].chain_id
        apply_overrides(txns, {chain_id: False})
        rejected = [t["_transfer_confirmed"] for t in txns if t.get("_transfer_chain_id")]
        assert all(r is False for r in rejected)

    def test_rejected_chain_transactions_counted_in_effective(self):
        """When a chain is rejected, all legs appear in effective transactions."""
        txns, chains = self._setup()
        chain_id = chains[0].chain_id
        apply_overrides(txns, {chain_id: False})
        effective = get_effective_transactions(txns)
        # Both legs must appear (chain rejected → treated as independent)
        effective_ids = {t["transactionId"] for t in effective}
        assert "out-1" in effective_ids
        assert "in-1" in effective_ids

    def test_unrejected_chain_is_pure_movement(self):
        """With no override (None), no leg of a chain counts (#166)."""
        txns, _chains = self._setup()
        # No override applied — default None
        effective = get_effective_transactions(txns)
        effective_ids = {t["transactionId"] for t in effective}
        assert "out-1" not in effective_ids
        assert "in-1" not in effective_ids


# ---------------------------------------------------------------------------
# T5-D: False-positive guard
# ---------------------------------------------------------------------------


class TestFalsePositive:
    """Two equal amounts that are NOT a transfer must not be linked."""

    def test_same_amount_different_creditors_not_a_transfer(self):
        """Two €50 expenses to different creditors on the same day → no chain."""
        txns = [
            _txn("rent-1", "acc-a", -50.00, creditor="Max Mustermann",
                 date="2025-03-01", account_name="Checking"),
            _txn("rent-2", "acc-b", -50.00, creditor="Erika Musterfrau",
                 date="2025-03-01", account_name="Savings"),
        ]
        accounts = [_account("acc-a", "Checking"), _account("acc-b", "Savings")]
        chains, _ = detect_transfer_chains(txns, accounts)
        assert len(chains) == 0, "Two unrelated same-amount expenses must not form a chain"

    def test_amounts_beyond_tolerance_not_linked(self):
        """Amounts differing by more than the tolerance must not match."""
        txns = [
            _txn("out-1", "acc-a", -100.00, creditor="acc-b",
                 account_name="Account A"),
            _txn("in-1", "acc-b", 99.00, debtor="Account A",
                 account_name="Account B"),  # 1.00 diff > 0.50 tolerance
        ]
        accounts = [_account("acc-a", "Account A"), _account("acc-b", "Account B")]
        chains, _ = detect_transfer_chains(txns, accounts)
        assert len(chains) == 0

    def test_dates_outside_window_not_linked(self):
        """Transactions more than TRANSFER_TIME_WINDOW_DAYS apart must not link."""
        txns = [
            _txn("out-1", "acc-a", -100.00, date="2025-01-01",
                 creditor="acc-b", account_name="Account A"),
            _txn("in-1", "acc-b", 100.00, date="2025-01-10",
                 debtor="Account A", account_name="Account B"),
        ]
        accounts = [_account("acc-a", "Account A"), _account("acc-b", "Account B")]
        chains, _ = detect_transfer_chains(txns, accounts)
        assert len(chains) == 0

    def test_pending_transactions_ignored(self):
        """Transactions with _status != 'booked' must be excluded from detection."""
        txns = [
            _txn("out-1", "acc-a", -100.00, status="pending",
                 creditor="Account B", account_name="Account A"),
            _txn("in-1", "acc-b", 100.00, status="pending",
                 debtor="Account A", account_name="Account B"),
        ]
        accounts = [_account("acc-a", "Account A"), _account("acc-b", "Account B")]
        chains, _ = detect_transfer_chains(txns, accounts)
        assert len(chains) == 0


# ---------------------------------------------------------------------------
# T5-E: Confidence scoring
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    """Verify the confidence tiers: high / medium / low."""

    def test_high_confidence_name_and_same_day(self):
        """Name match + same day → confidence should be well above auto threshold."""
        txns = [
            _txn("out-1", "acc-a", -200.00, date="2025-04-01",
                 creditor="Savings Account", account_name="Checking Account"),
            _txn("in-1", "acc-b", 200.00, date="2025-04-01",
                 debtor="Checking Account", account_name="Savings Account"),
        ]
        accounts = [
            _account("acc-a", "Checking Account"),
            _account("acc-b", "Savings Account"),
        ]
        chains, _ = detect_transfer_chains(txns, accounts)
        assert chains, "Expected a chain to be detected"
        assert chains[0].total_confidence >= 0.70

    def test_lower_confidence_no_name_match(self):
        """Amount match + same day but no name hints → confidence <= 0.70.

        Score breakdown: exact amount match (0.4) + same-day (0.3) = 0.70.
        No account-name cross-reference, so the ceiling is 0.70 for this case.
        """
        txns = [
            _txn("out-1", "acc-a", -75.00, date="2025-04-01",
                 account_name="Account A"),
            _txn("in-1", "acc-b", 75.00, date="2025-04-01",
                 account_name="Account B"),
        ]
        accounts = [_account("acc-a", "Account A"), _account("acc-b", "Account B")]
        chains, _ = detect_transfer_chains(txns, accounts)
        # May or may not detect — if detected, confidence must not exceed 0.70
        # (no name-hint bonus, only amount + date scoring applies)
        if chains:
            assert chains[0].total_confidence <= 0.70

    def test_category_transfer_boosts_confidence(self):
        """Pre-tagged category='transfers' must increase pair confidence."""
        txns = [
            _txn("out-1", "acc-a", -300.00, date="2025-04-01",
                 creditor="Account B", account_name="Account A",
                 category="transfers"),
            _txn("in-1", "acc-b", 300.00, date="2025-04-01",
                 debtor="Account A", account_name="Account B",
                 category="transfers"),
        ]
        accounts = [_account("acc-a", "Account A"), _account("acc-b", "Account B")]
        chains, _ = detect_transfer_chains(txns, accounts)
        assert chains
        assert chains[0].total_confidence >= 0.70


# ---------------------------------------------------------------------------
# T5-F: Refund detection
# ---------------------------------------------------------------------------


class TestRefundDetection:
    """Storno / refund matching."""

    def _make_refund_pair(self):
        return [
            _txn("orig-1", "acc-a", -49.99, date="2025-01-10",
                 creditor="amazon marketplace"),
            _txn("ref-1", "acc-a", 49.99, date="2025-01-20",
                 creditor="amazon marketplace",
                 remittance="Storno Bestellung 1234"),
        ]

    def test_refund_detected(self):
        txns = self._make_refund_pair()
        _, refunds = detect_transfer_chains(txns, [_account("acc-a", "Checking")])
        assert len(refunds) == 1

    def test_refund_original_and_refund_ids_correct(self):
        txns = self._make_refund_pair()
        _, refunds = detect_transfer_chains(txns, [_account("acc-a", "Checking")])
        ref = refunds[0]
        assert ref.original_txn_id == "orig-1"
        assert ref.refund_txn_id == "ref-1"
        assert abs(ref.amount - 49.99) < 0.01

    def test_no_refund_without_keyword(self):
        """A positive incoming transaction without a refund keyword must not match."""
        txns = [
            _txn("orig-1", "acc-a", -49.99, creditor="amazon marketplace"),
            _txn("in-1", "acc-a", 49.99, creditor="amazon marketplace",
                 remittance="Bonus Zahlung"),  # no storno keyword
        ]
        _, refunds = detect_transfer_chains(txns, [_account("acc-a", "Checking")])
        assert len(refunds) == 0

    def test_refund_before_original_not_detected(self):
        """Refund must come AFTER the original purchase."""
        txns = [
            _txn("orig-1", "acc-a", -49.99, date="2025-01-20",
                 creditor="amazon marketplace"),
            _txn("ref-1", "acc-a", 49.99, date="2025-01-10",  # 10 days BEFORE
                 creditor="amazon marketplace",
                 remittance="Storno Bestellung"),
        ]
        _, refunds = detect_transfer_chains(txns, [_account("acc-a", "Checking")])
        assert len(refunds) == 0


# ---------------------------------------------------------------------------
# T5-G: enrich_transactions
# ---------------------------------------------------------------------------


class TestEnrichTransactions:
    """Verify that enrich_transactions populates all _transfer_* fields."""

    def test_source_role_set(self):
        txns = [
            _txn("out-1", "acc-a", -100.00, creditor="Account B",
                 account_name="Account A"),
            _txn("in-1", "acc-b", 100.00, debtor="Account A",
                 account_name="Account B"),
        ]
        accounts = [_account("acc-a", "Account A"), _account("acc-b", "Account B")]
        chains, refunds = detect_transfer_chains(txns, accounts)
        enrich_transactions(txns, chains, refunds)

        roles = {t["transactionId"]: t["_transfer_role"] for t in txns}
        assert roles["out-1"] == "source"
        assert roles["in-1"] == "destination"

    def test_non_chain_transaction_has_null_fields(self):
        """Transactions not in any chain must have null transfer fields."""
        txns = [_txn("solo-1", "acc-a", -25.00, creditor="REWE")]
        enrich_transactions(txns, [], [])
        t = txns[0]
        assert t["_transfer_chain_id"] is None
        assert t["_transfer_role"] is None
        assert t["_transfer_linked_txns"] == []
        assert t["_transfer_confidence"] is None

    def test_refund_fields_populated(self):
        txns = [
            _txn("orig-1", "acc-a", -49.99, date="2025-01-10",
                 creditor="amazon marketplace"),
            _txn("ref-1", "acc-a", 49.99, date="2025-01-20",
                 creditor="amazon marketplace",
                 remittance="Storno Bestellung 1234"),
        ]
        accounts = [_account("acc-a", "Checking")]
        chains, refunds = detect_transfer_chains(txns, accounts)
        enrich_transactions(txns, chains, refunds)

        by_id = {t["transactionId"]: t for t in txns}
        assert by_id["orig-1"]["_refund_role"] == "original"
        assert by_id["ref-1"]["_refund_role"] == "refund"
        assert by_id["orig-1"]["_refund_pair_id"] == by_id["ref-1"]["_refund_pair_id"]
