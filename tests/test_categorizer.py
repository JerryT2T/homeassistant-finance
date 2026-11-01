"""Parametrized tests for TransactionCategorizer rule coverage (T4).

Tests all 9 rule categories plus income detection and custom-rule injection.
Each category is exercised with multiple real-world merchant / reference
patterns that a German household would encounter.
"""

from __future__ import annotations

import pytest

from custom_components.finance_dashboard.categorizer import (
    TransactionCategorizer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _txn(
    creditor: str = "",
    remittance: str = "",
    amount: float = -10.00,
    debtor: str = "",
    additional: str = "",
) -> dict:
    """Build a minimal transaction dict."""
    txn: dict = {
        "transactionAmount": {"amount": str(amount), "currency": "EUR"},
    }
    if creditor:
        txn["creditorName"] = creditor
    if remittance:
        txn["remittanceInformationUnstructured"] = remittance
    if debtor:
        txn["debtorName"] = debtor
    if additional:
        txn["additionalInformation"] = additional
    return txn


# ---------------------------------------------------------------------------
# Housing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("creditor", "Vonovia Wohnungsvermietung GmbH"),
        ("remittance", "Miete Dezember 2025 WE 34"),
        ("creditor", "Hausgeld Eigentümergemeinschaft"),
        ("remittance", "Kaltmiete Monat November"),
        ("creditor", "Rent payment Wohnung Berlin"),
    ],
)
def test_housing(field, value):
    cat = TransactionCategorizer()
    if field == "creditor":
        result = cat.categorize(_txn(creditor=value))
    else:
        result = cat.categorize(_txn(remittance=value))
    assert result == "housing_cold", f"Expected housing_cold for '{value}', got '{result}'"


# ---------------------------------------------------------------------------
# Food
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("creditor", "REWE Supermarkt"),
        ("creditor", "EDEKA Center"),
        ("creditor", "ALDI SUED"),
        ("creditor", "Lidl GmbH & Co KG"),
        ("creditor", "HelloFresh SE"),
        ("remittance", "Einkauf Supermarkt"),
        ("creditor", "REWE Markt GmbH"),
    ],
)
def test_food(field, value):
    cat = TransactionCategorizer()
    if field == "creditor":
        result = cat.categorize(_txn(creditor=value))
    else:
        result = cat.categorize(_txn(remittance=value))
    assert result == "groceries", f"Expected groceries for '{value}', got '{result}'"


@pytest.mark.parametrize(
    "value",
    ["Lieferando.de", "Restaurant Essenbei Tisch 4", "Uber Eats Berlin", "Pizzeria Roma"],
)
def test_gastro_is_leisure(value):
    """Eating out is leisure, not groceries (#112)."""
    assert TransactionCategorizer().categorize(_txn(creditor=value)) == "leisure"


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("remittance", "Deutschlandticket Monatsbeitrag"),
        ("creditor", "Deutsche Bahn AG"),
        ("remittance", "DB Fernverkehr Ticket"),
        ("creditor", "Shell Tankstelle"),
        ("creditor", "ARAL AG"),
        ("creditor", "Uber Germany GmbH"),
        ("remittance", "Taxifahrt Berlin"),
        ("remittance", "Bahn Ticket S-Bahn"),
    ],
)
def test_transport(field, value):
    cat = TransactionCategorizer()
    if field == "creditor":
        result = cat.categorize(_txn(creditor=value))
    else:
        result = cat.categorize(_txn(remittance=value))
    assert result == "mobility", f"Expected mobility for '{value}', got '{result}'"


# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("creditor", "TK Techniker Krankenkasse"),
        ("creditor", "AOK Bayern"),
        ("creditor", "Barmer GEK"),
        ("remittance", "Haftpflichtversicherung Jahresbeitrag"),
        ("remittance", "Rechtsschutzversicherung ADAC"),
        ("remittance", "Krankenversicherung Beitrag"),
        ("creditor", "Allianz Versicherung"),
    ],
)
def test_insurance(field, value):
    cat = TransactionCategorizer()
    if field == "creditor":
        result = cat.categorize(_txn(creditor=value))
    else:
        result = cat.categorize(_txn(remittance=value))
    assert result == "health", f"Expected health for '{value}', got '{result}'"


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("creditor", "Netflix International BV"),
        ("creditor", "Spotify AB"),
        ("remittance", "Amazon Prime Mitgliedschaft"),
        ("creditor", "Disney+ Abo"),
        ("remittance", "Xbox Game Pass Ultimate"),
        ("remittance", "Google One Speicher 200GB"),
        ("remittance", "iCloud+ Abonnement"),
        ("remittance", "YouTube Premium Monatsabo"),
    ],
)
def test_subscriptions(field, value):
    cat = TransactionCategorizer()
    if field == "creditor":
        result = cat.categorize(_txn(creditor=value))
    else:
        result = cat.categorize(_txn(remittance=value))
    assert result == "media", f"Expected media for '{value}', got '{result}'"


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("remittance", "Kreditrate Monat Januar"),
        ("remittance", "Tilgung Baudarlehen 2024"),
        ("remittance", "Darlehen Sondertilgung"),
        ("remittance", "Loan repayment Consorsbank"),
        ("remittance", "Finanzierung Ratenzahlung"),
    ],
)
def test_loans(field, value):
    cat = TransactionCategorizer()
    result = cat.categorize(_txn(remittance=value))
    assert result == "finance", f"Expected finance for '{value}', got '{result}'"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("remittance", "EnBW Strom Abschlag Oktober", "housing_warm"),
        ("remittance", "Stromabschlag Monat Oktober", "housing_warm"),
        ("remittance", "Gasrechnung Dezember", "housing_warm"),
        ("remittance", "Wasserversorgung Stadtwerke", "housing_warm"),
        ("remittance", "Fernwärme Abschlag", "housing_warm"),
        ("remittance", "Nebenkosten Abrechnung 2024", "housing_warm"),
        ("creditor", "Deutsche Telekom AG", "media"),
        ("creditor", "Vodafone GmbH", "media"),
        ("creditor", "O2 Telefónica Deutschland", "media"),
        ("remittance", "Rundfunkbeitrag ARD ZDF", "media"),
        ("remittance", "GEZ Gebühr Halbjahr", "media"),
    ],
)
def test_utilities_split_into_energy_and_media(field, value, expected):
    """The legacy utilities bucket is two life areas (#112)."""
    cat = TransactionCategorizer()
    if field == "creditor":
        result = cat.categorize(_txn(creditor=value))
    else:
        result = cat.categorize(_txn(remittance=value))
    assert result == expected, f"Expected {expected} for '{value}', got '{result}'"


def test_gastro_is_never_gas():
    assert TransactionCategorizer().categorize(_txn(creditor="Gastro Bar Eck")) == "leisure"


# ---------------------------------------------------------------------------
# Income (keyword-based)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("remittance", "Gehalt November 2025 Mustermann GmbH"),
        ("remittance", "Lohn Dezember"),
        ("remittance", "Salary payment"),
        ("remittance", "Vergütung Werkstudent Oktober"),
    ],
)
def test_income_keyword(field, value):
    """Money coming in with a work keyword is work income."""
    cat = TransactionCategorizer()
    result = cat.categorize(_txn(remittance=value, amount=2500.0))
    assert result == "income_work", f"Expected income_work for '{value}', got '{result}'"


def test_income_keyword_never_files_an_expense_as_income():
    # "Zinsen" on a debit is a loan cost, not capital income
    cat = TransactionCategorizer()
    assert cat.categorize(_txn(remittance="Zinsen Darlehen", amount=-45.0)) == "finance"
    assert cat.categorize(_txn(remittance="Zinsen Tagesgeld", amount=12.0)) == "income_capital"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Kindergeld Familienkasse", "income_state"),
        ("Dividende ETF", "income_capital"),
        ("Erstattung Ruecksendung 4711", "income_refund"),
        ("Danke fuer gestern", "income_private"),
    ],
)
def test_income_areas(text, expected):
    assert TransactionCategorizer().categorize(_txn(remittance=text, amount=80.0)) == expected


# ---------------------------------------------------------------------------
# Income (positive amount fallback)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount,label",
    [
        (500.00, "standard deposit"),
        (0.01, "micro deposit"),
        (9999.99, "large transfer"),
    ],
)
def test_income_positive_amount_fallback(amount, label):
    """Transactions with no matching keyword but positive amount → income."""
    cat = TransactionCategorizer()
    # Use an unrecognized creditor to avoid keyword matches
    result = cat.categorize(_txn(creditor="Unbekannter Absender XYZ", amount=amount))
    assert result == "income_private", (
        f"Expected income_private for {label} (amount={amount}), got '{result}'"
    )


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("remittance", "Umbuchung Konto 2"),
        ("remittance", "Übertrag Sparkonto"),
        ("remittance", "Transfer to savings account"),
    ],
)
def test_transfers(field, value):
    cat = TransactionCategorizer()
    result = cat.categorize(_txn(remittance=value))
    assert result == "transfers", f"Expected transfers for '{value}', got '{result}'"


# ---------------------------------------------------------------------------
# Other (fallback)
# ---------------------------------------------------------------------------


def test_other_fallback_negative_amount():
    """Transactions with no matching keyword and negative amount → other."""
    cat = TransactionCategorizer()
    result = cat.categorize(
        _txn(
            creditor="Completely Unknown Merchant XYZXYZ",
            remittance="REF 12345678",
            amount=-50.00,
        )
    )
    assert result == "other"


def test_other_empty_transaction():
    """An entirely empty transaction dict → other."""
    cat = TransactionCategorizer()
    result = cat.categorize({})
    assert result == "other"


def test_other_no_text_fields():
    """Transaction with only an amount field and no text → other (negative amount)."""
    cat = TransactionCategorizer()
    result = cat.categorize({"transactionAmount": {"amount": "-1.00"}})
    assert result == "other"


# ---------------------------------------------------------------------------
# Custom rules
# ---------------------------------------------------------------------------


def test_custom_rule_adds_keyword():
    """Custom rules injected via constructor must extend category matching."""
    cat = TransactionCategorizer(
        custom_rules={"groceries": ["biomarkt", "demeter"]}
    )
    result = cat.categorize(_txn(creditor="Alnatura Biomarkt"))
    assert result == "groceries"


def test_custom_rule_new_category():
    """Custom rules for a previously-unseen category key must work."""
    cat = TransactionCategorizer(
        custom_rules={"fitness": ["fitnessstudio", "clever fit"]}
    )
    result = cat.categorize(_txn(creditor="Clever Fit Koblenz"))
    assert result == "fitness"


def test_update_rules_adds_keyword():
    """update_rules must extend matching for an existing category."""
    cat = TransactionCategorizer()
    cat.update_rules("groceries", ["naschmarkt"])
    result = cat.categorize(_txn(creditor="Naschmarkt Wien"))
    assert result == "groceries"


def test_get_rules_returns_copy():
    """get_rules() must return a copy — mutations must not affect the instance."""
    cat = TransactionCategorizer()
    rules = cat.get_rules()
    rules["groceries"].append("__sentinel__")
    # Internal rules must not be polluted
    assert "__sentinel__" not in cat.get_rules()["groceries"]


# ---------------------------------------------------------------------------
# Case-insensitivity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "REWE SUPERMARKT",
        "rewe supermarkt",
        "Rewe Supermarkt",
        "rEwE",
    ],
)
def test_case_insensitive_matching(text):
    """Rule matching must be case-insensitive."""
    cat = TransactionCategorizer()
    result = cat.categorize(_txn(creditor=text))
    assert result == "groceries", f"Expected groceries for '{text}', got '{result}'"


# ---------------------------------------------------------------------------
# Multi-field priority
# ---------------------------------------------------------------------------


def test_creditor_name_matched():
    """creditorName field must be searched for keyword matches."""
    cat = TransactionCategorizer()
    result = cat.categorize({"creditorName": "Netflix", "transactionAmount": {"amount": "-9.99"}})
    assert result == "media"


def test_remittance_array_matched():
    """remittanceInformationUnstructuredArray entries must all be searched."""
    cat = TransactionCategorizer()
    txn = {
        "remittanceInformationUnstructuredArray": ["Ref 001", "Miete April", "WE-042"],
        "transactionAmount": {"amount": "-700.00"},
    }
    result = cat.categorize(txn)
    assert result == "housing_cold"


# ---------------------------------------------------------------------------
# Payment processors (#120)
# ---------------------------------------------------------------------------

_PAYPAL = "PayPal Europe S.a.r.l. et Cie S.C.A"


def _processor_line(name: str, remittance: str, amount: str = "-23.50") -> dict:
    return {
        "creditorName": name,
        "remittanceInformationUnstructured": remittance,
        "transactionAmount": {"amount": amount, "currency": "EUR"},
    }


def test_processor_name_never_decides_the_category():
    # even a rule that names the processor itself must not fire on its own lines
    cat = TransactionCategorizer(custom_rules={"mobility": ["paypal", "europe"]})
    tx = _processor_line(_PAYPAL, "PP.4471.PP . Pizza Roma, Ihr Einkauf bei Pizza Roma")
    assert cat.categorize(tx) == "leisure"


def test_processor_line_without_merchant_is_unclear():
    cat = TransactionCategorizer(custom_rules={"transport": ["paypal"]})
    assert cat.categorize(_processor_line(_PAYPAL, "Abbuchung")) == "other"
    assert cat.categorize(_processor_line("Klarna Bank AB", "Rechnung 89002")) == "other"


def test_merchant_inside_processor_name_still_counts():
    # "PAYPAL *NETFLIX": the merchant is part of the name, not a processor-only line
    cat = TransactionCategorizer()
    assert cat.categorize(_processor_line("PAYPAL *NETFLIX", "")) == "media"
