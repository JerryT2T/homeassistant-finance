"""Labels: catalogue, per-booking labels, inheritance from contracts (#113)."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.finance_dashboard.contracts import Contract, ContractError, build_contracts
from custom_components.finance_dashboard.labels import (
    AUTO_BNPL,
    AUTO_CARD,
    AUTO_DIRECT_DEBIT,
    AUTO_PAYPAL,
    AUTO_PRICE_INCREASED,
    STARTER_LABELS,
    LabelError,
    LabelStore,
    booking_auto_labels,
    contract_auto_labels,
    resolve_bookings,
    slugify,
)
from tests.fakes import FakeStore
from tests.test_contracts import TODAY, blank_store, monthly


def _store() -> LabelStore:
    return LabelStore(None, store=FakeStore())


def test_catalogue_has_starter_custom_and_auto_labels():
    s = _store()
    lid = s.add("Kita & Schule")
    assert lid == "kita_schule"
    cat = s.catalogue()
    assert [c["id"] for c in cat if c["kind"] == "starter"] == list(STARTER_LABELS)
    assert {"id": "kita_schule", "name": "Kita & Schule", "kind": "custom"} in cat
    assert {c["id"] for c in cat if c["kind"] == "auto"} >= {AUTO_PAYPAL, AUTO_PRICE_INCREASED}


def test_custom_ids_never_collide_with_starters_or_each_other():
    s = _store()
    assert s.add("Energie") == "energie"
    assert s.add("Energie!") == "energie_2"
    assert s.add("Energy") == "energy_2"  # "energy" is a starter label
    assert slugify("Ärzte & Co.") == "arzte_co"
    assert slugify("2024") == "l_2024"


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, None])
def test_invalid_names_are_rejected(name):
    with pytest.raises(LabelError) as err:
        _store().add(name)
    assert err.value.code == "invalid_name"


def test_booking_labels_validate_against_the_catalogue_and_drop_on_delete():
    s = _store()
    own = s.add("Urlaub 2026")
    assert s.set_booking("L1", ["energy", own, "energy"]) == ["energy", own]
    with pytest.raises(LabelError):
        s.set_booking("L2", ["nope"])
    with pytest.raises(LabelError):
        s.set_booking("L2", [AUTO_PAYPAL])  # automatic labels are read-only
    s.remove(own)
    assert s.bookings == {"L1": ["energy"]}
    assert s.set_booking("L1", []) == [] and s.bookings == {}
    with pytest.raises(LabelError):
        s.remove("energy")  # starter labels stay


def test_store_round_trip():
    s = _store()
    lid = s.add("Garten")
    s.set_booking("L9", [lid])
    asyncio.run(s.async_save())
    again = LabelStore(None, store=s._store)  # noqa: SLF001
    asyncio.run(again.async_load())
    assert again.custom == {lid: "Garten"} and again.bookings == {"L9": [lid]}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("PayPal Europe S.a.r.l. 1043", [AUTO_PAYPAL]),
        ("Klarna Rechnung 77", [AUTO_BNPL]),
        ("VISA Debitkarte REWE", [AUTO_CARD]),
        ("SEPA-Basislastschrift Mandat 4711", [AUTO_DIRECT_DEBIT]),
        ("Ueberweisung Miete", []),
    ],
)
def test_payment_channel_is_an_automatic_label(text, expected):
    assert booking_auto_labels({"remittanceInformationUnstructured": text}) == expected


def test_contract_auto_labels():
    item = {"price_change": {"increase": True}, "special_termination_available": True}
    assert contract_auto_labels(item) == [AUTO_PRICE_INCREASED, "auto_special_termination"]
    assert contract_auto_labels({"price_change": None}) == []


def test_contract_labels_are_validated():
    c = Contract("s1")
    c.apply({"labels": ["energy", "energy", "insurance"]})
    assert c.labels == ["energy", "insurance"] and c.to_dict()["labels"] == ["energy", "insurance"]
    c.apply({"labels": []})
    assert c.labels is None
    with pytest.raises(ContractError):
        c.apply({"labels": ["Bad Label"]})
    with pytest.raises(ContractError):
        c.apply({"labels": [AUTO_PAYPAL]})


def _gym_rows():
    rows = monthly([-45.0] * 5, name="Fitnessclub")
    for i, r in enumerate(rows):
        r["_ledger_id"] = f"gym{i}"
        r["category"] = "leisure"
        r["remittanceInformationUnstructured"] = "SEPA Lastschrift Mitgliedsbeitrag"
    return rows


def test_bookings_inherit_the_contracts_category_and_labels():
    rows = _gym_rows()
    loose = {**rows[0], "_ledger_id": "x1", "creditorName": "Kiosk", "category": "groceries"}
    store = blank_store()
    sid = build_contracts(rows, store, today=TODAY)[0]["id"]
    store.contracts[sid] = Contract(sid, category="health", labels=["membership"])
    contracts = build_contracts(rows, store, today=TODAY)
    assert contracts[0]["labels"] == ["membership"]
    assert sorted(contracts[0]["ledger_ids"]) == [f"gym{i}" for i in range(5)]

    out = resolve_bookings([*rows, loose], contracts, {"gym2": ["refundable"]})
    linked = out["gym2"]
    assert linked["contract_id"] == sid and linked["category_source"] == "contract"
    assert linked["category"] == "health"
    assert linked["labels_inherited"] == ["membership"]
    assert linked["labels_own"] == ["refundable"]
    assert linked["labels_auto"] == [AUTO_DIRECT_DEBIT]
    own = out["x1"]
    assert own["contract_id"] is None and own["category"] == "groceries"
    assert own["category_source"] == "own" and own["labels_inherited"] == []


def test_a_candidate_passes_nothing_on():
    rows = _gym_rows()
    contracts = [{"id": "s", "candidate": True, "ledger_ids": ["gym0"], "category": "health",
                  "contract": {"stored": {"labels": ["membership"]}}}]
    assert resolve_bookings(rows[:1], contracts, {})["gym0"]["category_source"] == "own"
