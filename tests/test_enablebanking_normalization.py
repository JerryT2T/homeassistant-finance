"""Tests for Enable Banking response normalization.

These cover the layer that had no test coverage at all and consequently did not
match the real API: the client expected ``{"booked": [...], "pending": [...]}``
while the API returns ``{"transactions": [...], "continuation_key": ...}`` —
a list, so ``.get("booked")`` raised AttributeError for every account and the
refresh silently produced zero transactions.

Payloads here are shaped after the Enable Banking API reference:
per-transaction ``status``, unsigned ``transaction_amount`` plus
``credit_debit_indicator``, ``remittance_information`` as an array, and ISO
20022 balance-type codes.
"""

from __future__ import annotations

import pytest

from custom_components.finance_dashboard.enablebanking_client import EnableBankingClient


def _txn(amount="10.00", indicator="DBDT", status="BOOK", **extra):
    payload = {
        "entry_reference": extra.pop("entry_reference", "tx1"),
        "booking_date": extra.pop("booking_date", "2026-06-15"),
        "status": status,
        "credit_debit_indicator": indicator,
        "transaction_amount": {"amount": amount, "currency": "EUR"},
    }
    payload.update(extra)
    return payload


class TestPageExtraction:
    """The real response shape, plus the shapes some sandboxes return."""

    def test_documented_shape_with_continuation_key(self):
        result = {"transactions": [_txn(), _txn()], "continuation_key": "abc"}
        txns, key = EnableBankingClient._extract_transaction_page(result)
        assert len(txns) == 2
        assert key == "abc"

    def test_transactions_is_a_list_not_a_dict(self):
        # The original bug: .get("booked") on a list raises AttributeError.
        result = {"transactions": [_txn()]}
        txns, key = EnableBankingClient._extract_transaction_page(result)
        assert len(txns) == 1
        assert key is None

    def test_bare_list_response(self):
        txns, key = EnableBankingClient._extract_transaction_page([_txn()])
        assert len(txns) == 1
        assert key is None

    def test_legacy_bucketed_shape_still_works(self):
        result = {"booked": [_txn()], "pending": [_txn(status="PDNG")]}
        txns, _ = EnableBankingClient._extract_transaction_page(result)
        assert len(txns) == 2

    def test_buckets_nested_under_transactions(self):
        result = {"transactions": {"booked": [_txn()], "pending": []}}
        txns, _ = EnableBankingClient._extract_transaction_page(result)
        assert len(txns) == 1

    @pytest.mark.parametrize("garbage", [None, "text", 42])
    def test_unexpected_payload_yields_no_transactions(self, garbage):
        txns, key = EnableBankingClient._extract_transaction_page(garbage)
        assert txns == []
        assert key is None


class TestAmountSign:
    """The sign carries income-vs-expense for the entire product."""

    @pytest.mark.parametrize("indicator", ["DBDT", "DBIT", "debit"])
    def test_debit_becomes_negative(self, indicator):
        amount = EnableBankingClient._signed_amount(
            {"amount": "42.50"}, {"credit_debit_indicator": indicator}
        )
        assert float(amount) == -42.50

    @pytest.mark.parametrize("indicator", ["CRDT", "credit"])
    def test_credit_becomes_positive(self, indicator):
        amount = EnableBankingClient._signed_amount(
            {"amount": "42.50"}, {"credit_debit_indicator": indicator}
        )
        assert float(amount) == 42.50

    def test_debit_indicator_normalises_an_already_negative_amount(self):
        amount = EnableBankingClient._signed_amount(
            {"amount": "-42.50"}, {"credit_debit_indicator": "DBDT"}
        )
        assert float(amount) == -42.50

    def test_without_indicator_the_supplied_sign_is_preserved(self):
        assert float(EnableBankingClient._signed_amount({"amount": "-5.00"}, {})) == -5.0
        assert float(EnableBankingClient._signed_amount({"amount": "5.00"}, {})) == 5.0

    def test_comma_decimal_is_accepted(self):
        amount = EnableBankingClient._signed_amount(
            {"amount": "1234,56"}, {"credit_debit_indicator": "CRDT"}
        )
        assert float(amount) == 1234.56

    def test_unparseable_amount_is_zero_not_a_crash(self):
        assert EnableBankingClient._signed_amount({"amount": "n/a"}, {}) == "0.00"


class TestStatusAndRemittance:
    """Per-transaction status and the array-valued payment reference."""

    @pytest.mark.parametrize("status", ["PDNG", "PENDING", "HELD"])
    def test_pending_states(self, status):
        assert EnableBankingClient._is_pending({"status": status}) is True

    @pytest.mark.parametrize("status", ["BOOK", "BOOKED", "", "SOMETHING_NEW"])
    def test_everything_else_counts_as_booked(self, status):
        # Treating a real debit as pending would drop it from the summary.
        assert EnableBankingClient._is_pending({"status": status}) is False

    def test_remittance_array_is_joined(self):
        text = EnableBankingClient._join_remittance(
            {"remittance_information": ["Invoice 123", "Customer 456"]}
        )
        assert "Invoice 123" in text
        assert "Customer 456" in text

    def test_remittance_string_still_works(self):
        assert EnableBankingClient._join_remittance({"remittance_information": "Rent"}) == "Rent"

    def test_remittance_absent(self):
        assert EnableBankingClient._join_remittance({}) == ""


class TestNormalizeTransaction:
    """End-to-end field mapping."""

    def test_debit_is_negative_and_searchable(self):
        result = EnableBankingClient._normalize_transaction(
            _txn(
                amount="1638.02",
                indicator="DBDT",
                remittance_information=["Miete Juni"],
                creditor={"name": "Landlord GmbH"},
            )
        )
        assert float(result["transactionAmount"]["amount"]) == -1638.02
        assert result["creditorName"] == "Landlord GmbH"
        assert "Miete Juni" in result["remittanceInformationUnstructured"]
        assert result["bookingDate"] == "2026-06-15"

    def test_salary_credit_is_positive(self):
        result = EnableBankingClient._normalize_transaction(
            _txn(amount="5000.00", indicator="CRDT", debtor={"name": "Employer"})
        )
        assert float(result["transactionAmount"]["amount"]) == 5000.00
        assert result["debtorName"] == "Employer"


    def test_mojibake_counterparty_is_repaired(self):
        result = EnableBankingClient._normalize_transaction(
            _txn(amount="9.99", indicator="DBDT", creditor={"name": "Streamly S.Ã  r.l."})
        )
        assert result["creditorName"] == "Streamly S.à r.l."

    def test_replacement_characters_are_dropped(self):
        result = EnableBankingClient._normalize_transaction(
            _txn(amount="5.00", indicator="CRDT", debtor={"name": "M￼ller �"})
        )
        assert "�" not in result["debtorName"]

    def test_transaction_date_is_kept_beside_an_empty_booking_date(self):
        txn = _txn(amount="13.99", indicator="DBDT")
        txn.update(booking_date=None, value_date=None, transaction_date="2026-08-12")
        result = EnableBankingClient._normalize_transaction(txn)
        assert result["bookingDate"] == ""
        assert result["transactionDate"] == "2026-08-12"


class TestNormalizeBalance:
    """ISO 20022 balance codes must survive normalization."""

    def test_iso_code_is_preserved_not_rewritten(self):
        result = EnableBankingClient._normalize_balance(
            {"balance_amount": {"amount": "1234.56", "currency": "EUR"}, "balance_type": "CLBD"}
        )
        assert result["balanceType"] == "CLBD"
        assert result["balanceAmount"]["amount"] == "1234.56"

    def test_missing_type_does_not_masquerade_as_closing_booked(self):
        # Defaulting to a specific type would make an unknown balance look
        # authoritative to the priority-based selection.
        result = EnableBankingClient._normalize_balance({"balance_amount": {"amount": "1.00"}})
        assert result["balanceType"] == "OTHR"


class TestBalanceSelection:
    """Priority must match what the API actually sends."""

    def test_iso_closing_booked_wins_over_expected(self):
        from custom_components.finance_dashboard.sensor import AccountBalanceSensor

        picked = AccountBalanceSensor._pick_balance(
            [
                {"balanceType": "XPCD", "balanceAmount": {"amount": "999.00"}},
                {"balanceType": "CLBD", "balanceAmount": {"amount": "100.00"}},
            ]
        )
        assert picked["balanceAmount"]["amount"] == "100.00"

    def test_demo_camel_case_resolves_identically(self):
        from custom_components.finance_dashboard.sensor import AccountBalanceSensor

        picked = AccountBalanceSensor._pick_balance(
            [
                {"balanceType": "interimAvailable", "balanceAmount": {"amount": "999.00"}},
                {"balanceType": "closingBooked", "balanceAmount": {"amount": "100.00"}},
            ]
        )
        assert picked["balanceAmount"]["amount"] == "100.00"

    def test_empty_list_returns_none(self):
        from custom_components.finance_dashboard.sensor import AccountBalanceSensor

        assert AccountBalanceSensor._pick_balance([]) is None
