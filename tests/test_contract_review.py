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


# --- B / G: contract questions -------------------------------------------------


def _cafe():
    return monthly(
        [-12.4, -13.1, -11.8], name="Cafe Bohne", start=date(2026, 3, 10), category="leisure",
        remittanceInformationUnstructured="VISA Debitkarte",
    )


def _answer(store, item, qtype, answer):
    from custom_components.finance_dashboard.contracts import answer_fields

    contract = store.get(item["id"])
    contract.apply(answer_fields(qtype, answer, item))
    store.contracts[item["id"]] = contract


def test_candidate_becomes_a_question_and_a_confirmed_one_counts_as_fixed_cost():
    from custom_components.finance_dashboard.questions import contract_questions

    store = blank_store()
    (cand,) = build_contracts(_cafe(), store, today=TODAY)
    assert cand["candidate"]
    (q,), total = contract_questions([cand], today=TODAY)
    assert total == 1
    assert (q["type"], q["id"], q["series_id"]) == ("contract", f"contract:{cand['id']}", cand["id"])
    assert contract_totals([cand])["fixed"]["count"] == 0
    _answer(store, cand, "contract", "subscription")
    (again,) = build_contracts(_cafe(), store, today=TODAY)
    assert not again["candidate"] and again["kind"] == "subscription"
    assert contract_totals([again])["fixed"]["count"] == 1
    assert contract_questions([again], today=TODAY) == ([], 0)


def test_coincidence_suppresses_the_series_for_good():
    store = blank_store()
    (cand,) = build_contracts(_cafe(), store, today=TODAY)
    _answer(store, cand, "contract", "coincidence")
    assert build_contracts(_cafe(), store, today=TODAY) == []


def test_unknown_answer_is_rejected():
    store = blank_store()
    (cand,) = build_contracts(_cafe(), store, today=TODAY)
    with pytest.raises(ContractError):
        _answer(store, cand, "contract", "maybe")


@pytest.mark.parametrize(("answer", "mode", "plan"), [("new_price", "last", -15.0), ("one_off", "median", -10.0)])
def test_price_jump_question_sets_the_plan_mode(answer, mode, plan):
    from custom_components.finance_dashboard.questions import contract_questions

    rows = monthly([-10, -10, -10, -10, -15], name="Streamly", start=date(2026, 1, 10))
    store = blank_store()
    (c,) = build_contracts(rows, store, today=TODAY)
    (q,), _ = contract_questions([c], today=TODAY)
    assert q["type"] == "price" and q["previous"] == -10 and q["last"] == -15
    _answer(store, c, "price", answer)
    (c,) = build_contracts(rows, store, today=TODAY)
    assert c["plan_mode"] == mode and c["plan_amount"] == plan
    assert contract_questions([c], today=TODAY) == ([], 0)


def test_old_price_jump_is_not_asked():
    from custom_components.finance_dashboard.questions import contract_questions

    rows = monthly([-10, -10, -15], name="Streamly", start=date(2026, 1, 10))
    (c,) = build_contracts(rows, blank_store(), today=date(2026, 3, 20))
    assert contract_questions([c], today=date(2026, 6, 1))[1] == 0
