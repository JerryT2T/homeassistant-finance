"""Contract kinds (#111): suggestion, defaults per kind, kinds without notice."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from custom_components.finance_dashboard.contract_kind import (
    KIND_CONTRACT,
    KIND_IRREGULAR,
    KIND_REGULAR,
    KIND_SUBSCRIPTION,
    kind_defaults,
)
from custom_components.finance_dashboard.contracts import (
    Contract,
    ContractError,
    aggregate_view,
    build_contracts,
    category_defaults,
)
from tests.test_contracts import TODAY, blank_store, monthly, txn


def _with_text(rows, text):
    for r in rows:
        r["remittanceInformationUnstructured"] = text
    return rows


def _one(rows, store=None):
    (c,) = build_contracts(rows, store or blank_store(), today=TODAY)
    return c


@pytest.mark.parametrize(
    ("text", "category", "kind"),
    [
        ("Abo Premium", "other", KIND_SUBSCRIPTION),
        ("Mitgliedsbeitrag", "other", KIND_SUBSCRIPTION),
        ("Darlehen 4711001 Rate", "other", KIND_CONTRACT),
        ("Miete Whg 3", "other", KIND_CONTRACT),
        ("Kartenzahlung", "food", KIND_REGULAR),
        ("Rezept", "health", KIND_IRREGULAR),
        ("Kartenzahlung", "insurance", KIND_CONTRACT),
        # QA #111: loose words never beat everyday spending, compounds still count
        ("Brötchen Rate 3 von 5", "food", KIND_REGULAR),
        ("Praxis Dr. Strom", "health", KIND_IRREGULAR),
        ("Handyvertrag Erika", "other", KIND_CONTRACT),
        ("Kita Beitrag", "other", KIND_CONTRACT),
        ("Taschengeld Max", "other", KIND_REGULAR),
    ],
)
def test_kind_is_suggested_from_text_and_category(text, category, kind):
    c = _one(_with_text(monthly([-20.0] * 5, category=category), text))
    assert c["kind"] == kind
    assert c["kind_suggested"] == kind


def test_weekly_habit_is_regular():
    start = date(2026, 3, 2)
    rows = [txn((start + timedelta(weeks=i)).isoformat(), -59.9, "Kochkiste") for i in range(10)]
    assert _one(rows)["kind"] == KIND_REGULAR


def test_yearly_payment_is_a_contract():
    rows = [txn("2024-11-20", -89.0, "Autoclub"), txn("2025-11-20", -89.0, "Autoclub")]
    c = build_contracts(rows, blank_store(), today=TODAY)
    assert [x["kind"] for x in c] == [KIND_CONTRACT]


def test_regular_and_irregular_spending_has_no_notice_deadline():
    c = _one(_with_text(monthly([-20.0] * 5, category="food"), "Kartenzahlung"))
    assert c["kind"] == KIND_REGULAR
    assert c["next_deadline"] is None
    assert c["days_until_deadline"] is None
    assert c["notice_due_soon"] is False
    assert c["contract"]["has_notice"] is False
    assert aggregate_view(c)["kind"] == KIND_REGULAR


def test_stored_kind_overrides_the_suggestion_and_keeps_user_fields():
    rows = _with_text(monthly([-20.0] * 5), "Abo Premium")
    store = blank_store()
    first = _one(rows, store)
    store.contracts[first["id"]] = Contract(first["id"], kind=KIND_REGULAR, notice_value=2)
    again = _one(rows, store)
    assert again["kind"] == KIND_REGULAR
    assert again["kind_suggested"] == KIND_SUBSCRIPTION
    assert again["next_deadline"] is None
    assert again["contract"]["stored"]["notice_value"] == 2
    store.contracts[first["id"]].apply({"kind": None})
    assert _one(rows, store)["kind"] == KIND_SUBSCRIPTION


def test_defaults_follow_the_kind_and_the_telecom_trait():
    phone = _one(_with_text(monthly([-29.99] * 5, category="utilities"), "Mobilfunk Vertrag"))
    assert phone["kind"] == KIND_CONTRACT
    assert phone["kind_trait"] == "telecom"
    assert phone["contract"]["min_term_months"] == 24
    sub = _one(_with_text(monthly([-9.99] * 5), "Abo Cloud"))
    assert sub["contract"]["notice_value"] == 0
    assert sub["contract"]["defaults"]["renewal_months"] == 1
    assert sub["contract"]["defaults_by_kind"][KIND_CONTRACT]["min_term_months"] == 12
    assert sub["contract"]["defaults_by_kind"][KIND_REGULAR] is None
    assert kind_defaults(KIND_REGULAR, "food") is None
    assert kind_defaults(KIND_CONTRACT, "unknown")["min_term_months"] == 12


def test_unknown_kind_is_rejected():
    with pytest.raises(ContractError) as err:
        Contract("s_x").apply({"kind": "habit"})
    assert err.value.code == "invalid_kind"


def test_category_defaults_keeps_its_old_answers():
    assert category_defaults("subscriptions")["notice_value"] == 0
    assert category_defaults("whatever")["renewal_months"] == 1
