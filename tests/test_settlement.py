"""Advance payments and annual settlements of usage-based contracts (#116)."""

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
from custom_components.finance_dashboard.recurring import add_months, detect_series
from custom_components.finance_dashboard.settlement import (
    SOURCE_KEYWORD,
    SOURCE_MANUAL,
    TRAIT_USAGE_BASED,
    expected,
)
from tests.test_contract_acceptance import _detect
from tests.test_contracts import blank_store, txn

TODAY = date(2026, 11, 1)


def _energy(settlement=-240.0, text="Jahresabrechnung 2025 Nachzahlung", refund=None):
    rows = []
    for i in range(9):
        rows.append(txn(add_months(date(2025, 11, 10), i).isoformat(), -85.0, "Stadtwerke Muster",
                        remittanceInformationUnstructured="Abschlag Kd-Nr 5550123",
                        _ledger_id=f"a{i}"))
    if settlement is not None:
        rows.append(txn("2026-07-24", settlement, "Stadtwerke Muster",
                        remittanceInformationUnstructured=text, _ledger_id="s1"))
    if refund is not None:
        r = txn("2026-07-24", refund, "", remittanceInformationUnstructured="Erstattung Guthaben 2025",
                _ledger_id="r1")
        r["debtorName"] = "Stadtwerke Muster"
        rows.append(r)
    for i in range(3):
        rows.append(txn(add_months(date(2026, 8, 10), i).isoformat(), -95.0, "Stadtwerke Muster",
                        remittanceInformationUnstructured="Abschlag Kd-Nr 5550123",
                        _ledger_id=f"b{i}"))
    return rows


def test_fixture_keeps_the_advance_series_and_shows_the_settlement():
    (c,) = _detect("energy_advance_and_settlement")
    assert c["occurrences"] == 12 and c["plan_amount"] == -95.0
    assert c["kind_trait"] == TRAIT_USAGE_BASED
    history = c["settlement"]["history"]
    assert [(h["date"], h["amount"], h["source"]) for h in history] == [
        ("2026-07-24", -240.0, SOURCE_KEYWORD)
    ]
    # the advance step is still a price change, though the last payments agree
    assert c["price_change"]["previous"] == -85.0 and c["price_change"]["last"] == -95.0
    assert c["price_change"]["increase"] is True


def test_expected_settlement_becomes_a_monthly_reserve():
    (c,) = build_contracts(_energy(), blank_store(), today=TODAY)
    exp = c["settlement"]["expected"]
    # 240 back-payment, the advance rose by 10 a month: 120 still expected
    assert exp["last_amount"] == 240.0 and exp["advance_step"] == 10.0
    assert exp["amount"] == 120.0 and exp["monthly_reserve"] == 10.0
    assert exp["next_due"] == "2027-07-24"
    assert c["annual_cost"] == 1140.0 and c["annual_total"] == 1260.0
    reserves = build_reserves([c])
    (item,) = reserves["items"]
    assert item["type"] == "settlement" and item["monthly_reserve"] == 10.0
    assert reserves["total_monthly"] == 10.0
    assert contract_totals([c])["fixed"]["yearly"] == 1260.0


def test_a_refund_lowers_the_yearly_cost_and_needs_no_reserve():
    (c,) = build_contracts(_energy(settlement=None, refund=60.0), blank_store(), today=TODAY)
    assert [h["amount"] for h in c["settlement"]["history"]] == [60.0]
    exp = c["settlement"]["expected"]
    assert exp["amount"] == -180.0  # 60 refund plus the higher advance
    assert c["annual_total"] == 960.0
    assert build_reserves([c])["items"] == []


def test_settlement_without_keyword_can_be_assigned_by_hand_and_removed():
    rows = _energy(text="Rechnung 2025")
    store = blank_store()
    (c,) = build_contracts(rows, store, today=TODAY)
    assert c["settlement"]["history"] == []
    cand = c["settlement"]["candidates"]
    assert [x["key"] for x in cand] == ["|s1"]
    store.contracts[c["id"]] = Contract(c["id"], settlements=["|s1"])
    (c,) = build_contracts(rows, store, today=TODAY)
    assert [(h["key"], h["source"]) for h in c["settlement"]["history"]] == [("|s1", SOURCE_MANUAL)]
    assert c["settlement"]["candidates"] == []
    store.contracts[c["id"]].apply({"settlements": None})
    (c,) = build_contracts(rows, store, today=TODAY)
    assert c["settlement"]["history"] == []


def test_user_can_switch_usage_based_off():
    store = blank_store()
    (c,) = build_contracts(_energy(), store, today=TODAY)
    store.contracts[c["id"]] = Contract(c["id"], usage_based=False)
    (c,) = build_contracts(_energy(), store, today=TODAY)
    assert c["settlement"]["usage_based"] is False and c["settlement"]["expected"] is None
    assert c["annual_total"] == c["annual_cost"]


def test_monthly_card_statement_stays_a_series():
    rows = [txn(add_months(date(2026, 1, 5), i).isoformat(), -300.0, "Stadtwerke Bank",
                remittanceInformationUnstructured="Kreditkartenabrechnung") for i in range(8)]
    (s,) = detect_series(rows, today=TODAY)
    assert s["occurrences"] == 8 and s["settlements"] == []


def test_insurer_refund_is_no_settlement():
    rows = [txn(add_months(date(2026, 1, 5), i).isoformat(), -30.0, "Muster Versicherung AG",
                remittanceInformationUnstructured="Wohngebaeude Leitungswasser Beitrag")
            for i in range(8)]
    rows.append(txn("2026-06-20", 30.0, "Muster Versicherung AG",
                    remittanceInformationUnstructured="Beitragserstattung"))
    s = next(x for x in detect_series(rows, today=TODAY) if x["direction"] == "out")
    assert s["settlements"] == [] and s["settlement_candidates"] == [] and s["kind_trait"] != TRAIT_USAGE_BASED


def test_doubled_instalment_is_no_price_step():
    amounts = [-150.0] * 3 + [-300.0] + [-150.0] * 4
    rows = [txn(add_months(date(2024, 12, 15), 3 * i).isoformat(), a, "Hausrat Muster",
                remittanceInformationUnstructured="Beitrag Vertrag HR-20031")
            for i, a in enumerate(amounts)]
    (s,) = detect_series(rows, today=TODAY)
    assert s["price_change"] is None


def test_old_settlement_predicts_nothing():
    assert expected([{"date": "2024-01-10", "amount": -200.0}], [], [], 12, TODAY) is None


@pytest.mark.parametrize("value", [["x" * 201], "s1", [1], ["a"] * 51])
def test_manual_settlement_keys_are_validated(value):
    with pytest.raises(ContractError):
        Contract("s").apply({"settlements": value})


def test_bad_stored_settlements_never_void_the_contract():
    c = Contract.from_dict("s", {"min_term_months": 24, "settlements": "bad", "usage_based": "yes"})
    assert c.min_term_months == 24 and c.settlements is None and c.usage_based is None


def test_settlement_goes_to_the_meter_it_names():
    rows = []
    for i in range(10):
        day = add_months(date(2025, 12, 5), i).isoformat()
        rows.append(txn(day, -60.0, "Stadtwerke Muster",
                        remittanceInformationUnstructured="Abschlag Strom Vertrag 11112222"))
        rows.append(txn(day, -40.0, "Stadtwerke Muster",
                        remittanceInformationUnstructured="Abschlag Gas Vertrag 33334444"))
    rows.append(txn("2026-09-20", -80.0, "Stadtwerke Muster",
                    remittanceInformationUnstructured="Jahresabrechnung Vertrag 33334444"))
    series = {s["plan_amount"]: s for s in detect_series(rows, today=TODAY)}
    assert series[-60.0]["settlements"] == []
    assert [x["amount"] for x in series[-40.0]["settlements"]] == [-80.0]


def test_advance_citing_the_last_bill_stays_an_advance():
    # QA #116: "Abschlag lt. Abrechnung" is no settlement
    rows = [txn(add_months(date(2025, 11, 10), i).isoformat(), -95.0, "Stadtwerke Muster",
                remittanceInformationUnstructured="Abschlag Strom" + (" lt. Abrechnung 2025" if i >= 8 else ""))
            for i in range(12)]
    (s,) = detect_series(rows, today=TODAY)
    assert s["occurrences"] == 12 and s["settlements"] == []


def test_one_energy_word_makes_no_utility():
    # QA #116: a PayPal stream keeps its refunds out of the subscription
    rows = [txn(add_months(date(2025, 11, 3), i).isoformat(), -9.99, "PayPal Europe",
                remittanceInformationUnstructured="Spotify") for i in range(12)]
    rows.append(txn("2026-05-20", -30.0, "PayPal Europe",
                    remittanceInformationUnstructured="Energie Drink shop"))
    refund = txn("2026-06-02", 45.0, "", remittanceInformationUnstructured="Erstattung Bestellung 123")
    refund["debtorName"] = "PayPal Europe"
    rows.append(refund)
    s = next(x for x in detect_series(rows, today=TODAY) if x["direction"] == "out")
    assert s["settlements"] == [] and s["kind_trait"] != TRAIT_USAGE_BASED


def test_payee_split_by_spelling_keeps_its_settlement():
    # QA #116: _keep_known_apart yields the spelling, the pool is keyed canonically
    from custom_components.finance_dashboard.recurring import series_id

    rows = []
    for i in range(10):
        day = add_months(date(2025, 12, 5), i).isoformat()
        rows.append(txn(day, -70.0, "Stadtwerke Z AG", remittanceInformationUnstructured="Abschlag Strom"))
        rows.append(txn(day, -50.0, "Stadtwerke Z GmbH", remittanceInformationUnstructured="Abschlag Gas"))
    rows.append(txn("2026-09-20", -300.0, "Stadtwerke Z AG",
                    remittanceInformationUnstructured="Jahresabrechnung Nachzahlung"))
    known = {series_id("stadtwerke z ag", True), series_id("stadtwerke z gmbh", True)}
    found = {s["plan_amount"]: s for s in detect_series(rows, today=TODAY, known_ids=known)}
    assert [x["amount"] for x in found[-70.0]["settlements"]] == [-300.0]
    assert found[-50.0]["settlements"] == []


def test_step_is_measured_on_the_full_history():
    # QA #116: the settlement lies outside the last 12 payments shown
    rows = [txn(add_months(date(2025, 3, 10), i).isoformat(), -80.0 if i < 4 else -95.0,
                "Stadtwerke Muster", remittanceInformationUnstructured="Abschlag Strom")
            for i in range(20)]
    rows.append(txn("2025-06-20", -300.0, "Stadtwerke Muster",
                    remittanceInformationUnstructured="Jahresabrechnung Nachzahlung"))
    (c,) = build_contracts(rows, blank_store(), today=TODAY)
    exp = c["settlement"]["expected"]
    assert exp["advance_step"] == 15.0 and exp["amount"] == 120.0
    assert exp["next_due"] == TODAY.isoformat()  # overdue: due now
