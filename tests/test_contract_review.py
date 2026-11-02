"""Contract review flow (#117): full edit, questions, manual contracts,
merge / split and booking assignment."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.finance_dashboard.contracts import (
    Contract,
    ContractError,
    build_contracts,
    build_reserves,
    contract_totals,
)
from tests.test_contracts import TODAY, blank_store, monthly, txn


# --- A: full edit ------------------------------------------------------------


def test_display_name_and_interval_override_survive_redetection():
    rows = monthly([-120] * 5, name="Streamly")
    store = blank_store()
    (first,) = build_contracts(rows, store, today=TODAY)
    store.contracts[first["id"]] = Contract.from_dict(
        first["id"], {"display_name": "Streaming", "interval": "quarterly", "category": "media"}
    )
    (again,) = build_contracts(rows, store, today=TODAY)
    assert again["id"] == first["id"]
    assert again["display_name"] == "Streaming"
    assert again["display_name_detected"] == "Streamly"
    assert again["interval"] == "quarterly"
    assert again["interval_detected"] == "monthly"
    assert again["annual_cost"] == 480.0
    assert again["category"] == "media"
    assert again["next_expected"] == "2026-08-10"


def test_interval_override_puts_a_series_into_the_reserves():
    rows = monthly([-60] * 5, name="Verein")
    store = blank_store()
    (c,) = build_contracts(rows, store, today=TODAY)
    assert not build_reserves([c])["items"]
    store.contracts[c["id"]] = Contract(c["id"], interval="yearly")
    (c,) = build_contracts(rows, store, today=TODAY)
    (item,) = build_reserves([c])["items"]
    assert item["monthly_reserve"] == 5.0


@pytest.mark.parametrize(
    ("field", "value"),
    [("interval", "daily"), ("display_name", "x" * 81), ("price_reviewed", "soon")],
)
def test_invalid_edit_fields_are_rejected(field, value):
    with pytest.raises(ContractError):
        Contract("s_x").apply({field: value})
