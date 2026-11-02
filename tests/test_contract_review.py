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


# --- D: manual contracts -------------------------------------------------------


def _manual(store, **kw):
    data = {"name": "Kfz-Versicherung", "amount": 480, "interval": "yearly", "category": "mobility",
            "start": "2025-11-01", **kw}
    return store.add_manual(data, TODAY)


def test_manual_contract_shows_in_list_totals_and_reserves_without_bookings():
    store = blank_store()
    mid = _manual(store)
    assert mid == "m_kfz_versicherung"
    (c,) = build_contracts([], store, today=TODAY)
    assert c["source"] == "manual" and c["id"] == mid
    assert (c["annual_cost"], c["monthly_equivalent"], c["category"]) == (480.0, 40.0, "mobility")
    assert c["next_expected"] == "2026-11-01" and c["status"] == "active"
    assert c["kind"] == "contract" and c["owner"] == "shared" and not c["candidate"]
    assert c["next_deadline"]  # a contract keeps a notice deadline
    assert contract_totals([c])["fixed"] == {"monthly": 40.0, "yearly": 480.0, "count": 1}
    (item,) = build_reserves([c])["items"]
    assert item["monthly_reserve"] == 40.0 and item["next_due"] == "2026-11-01"


def test_manual_contract_is_edited_like_any_other_and_can_be_deleted():
    store = blank_store()
    mid = _manual(store)
    _manual(store)  # same name twice -> a second id
    assert set(store.manual) == {mid, f"{mid}_2"}
    store.contracts[mid].apply({"display_name": "Auto", "interval": "quarterly", "plan_fixed_amount": 130})
    c = next(c for c in build_contracts([], store, today=TODAY) if c["id"] == mid)
    assert (c["display_name"], c["interval"], c["annual_cost"]) == ("Auto", "quarterly", 520.0)
    assert store.remove_manual(mid) and not store.remove_manual(mid)
    assert [c["id"] for c in build_contracts([], store, today=TODAY)] == [f"{mid}_2"]
    assert mid not in store.contracts


@pytest.mark.parametrize(
    "bad",
    [{"name": ""}, {"amount": 0}, {"amount": "12"}, {"interval": "daily"}, {"kind": "loan"}, {"start": "x"}],
)
def test_manual_contract_input_is_validated(bad):
    store = blank_store()
    with pytest.raises(ContractError):
        _manual(store, **bad)
    assert store.manual == {} and store.contracts == {}


# --- E / F: merge, split, booking assignment -----------------------------------


def structured_store():
    from custom_components.finance_dashboard.contracts import ContractStructure

    store = blank_store()
    store.structure = ContractStructure(None, store=object())
    return store


def _keyed(rows, prefix):
    for i, r in enumerate(rows):
        r.update(_ledger_id=f"{prefix}{i}", _account_key="acc0")
    return rows


def _two_sides():
    bank = _keyed(monthly([-12.99] * 3, name="Streamly", start=date(2026, 1, 3)), "b")
    paypal = _keyed(monthly([-12.99] * 3, name="PayPal Europe", start=date(2026, 4, 3)), "p")
    return bank + paypal


def test_merge_joins_two_series_and_undo_brings_both_back_under_their_ids():
    store = structured_store()
    before = {c["creditor"]: c["id"] for c in build_contracts(_two_sides(), store, today=TODAY)}
    assert len(before) == 2
    target, source = before["streamly"], before["paypal europe"]
    store.contracts[target] = Contract(target, display_name="Streamly Abo")
    store.structure.merge(target, source)
    (merged,) = build_contracts(_two_sides(), store, today=TODAY)
    assert merged["id"] == target and merged["display_name"] == "Streamly Abo"
    assert merged["occurrences"] == 6 and merged["status"] == "active"
    assert merged["merged_from"] == [{"id": source, "name": "paypal europe"}]
    assert len(merged["ledger_ids"]) == 6
    assert store.structure.unmerge(target, source)
    after = {c["creditor"]: c["id"] for c in build_contracts(_two_sides(), store, today=TODAY)}
    assert after == before


def test_merging_a_target_onto_another_moves_its_sources_along():
    store = structured_store()
    store.structure.merge("a", "b")
    store.structure.merge("c", "a")
    assert store.structure.merges == {"c": ["b", "a"]}
    with pytest.raises(ContractError):
        store.structure.merge("c", "c")


def test_chained_merges_stay_flat_and_cycles_are_rejected():
    st = structured_store().structure
    st.merge("c", "b")  # B -> C
    st.merge("b", "a")  # A -> B, and B already is in C: A -> C
    assert st.merges == {"c": ["b", "a"]}
    sources = [s for srcs in st.merges.values() for s in srcs]
    assert len(sources) == len(set(sources))  # every source has exactly one target
    for target, source in (("a", "c"), ("b", "c")):  # C into its own source
        with pytest.raises(ContractError):
            st.merge(target, source)
    assert st.merges == {"c": ["b", "a"]}


def test_chained_merges_end_in_one_series():
    third = _keyed(monthly([-12.99] * 3, name="Apple Services", start=date(2025, 10, 3)), "a")
    rows = _two_sides() + third
    store = structured_store()
    ids = {c["creditor"]: c["id"] for c in build_contracts(rows, store, today=TODAY)}
    a, b, c = ids["apple services"], ids["streamly"], ids["paypal europe"]
    store.structure.merge(c, b)
    store.structure.merge(b, a)
    (one,) = build_contracts(rows, store, today=TODAY)
    assert one["id"] == c and one["occurrences"] == 9
    assert {m["id"] for m in one["merged_from"]} == {a, b}


def test_merge_carries_the_sources_settlements_over():
    store = structured_store()
    credit = _keyed([txn("2026-05-20", 5.0, "PayPal Europe")], "c")
    refund = _keyed([txn("2026-05-25", 20.0, "Inkasso Partner")], "r")
    rows = _two_sides() + credit + refund
    ids = {c["creditor"]: c["id"] for c in build_contracts(rows, store, today=TODAY)}
    target, source = ids["streamly"], ids["paypal europe"]
    store.contracts[source] = Contract(source, settlements=["acc0|c0"])  # same payee, by hand
    store.structure.assign("acc0|r0", source)  # any booking, by assignment
    (src,) = [c for c in build_contracts(rows, store, today=TODAY) if c["id"] == source]
    assert {s["key"] for s in src["settlement"]["history"]} == {"acc0|c0", "acc0|r0"}
    store.structure.merge(target, source)
    (merged,) = build_contracts(rows, store, today=TODAY)
    assert {s["key"] for s in merged["settlement"]["history"]} == {"acc0|c0", "acc0|r0"}
    assert "acc0|r0" in merged["ledger_ids"]


def test_split_by_amount_and_undo_keep_the_payee_id():
    rows = monthly([-10, -10, -10, -15, -15, -15], name="Gym")
    store = structured_store()
    (whole,) = build_contracts(rows, store, today=TODAY)
    store.structure.split(whole["payee_key"], "amount")
    parts = build_contracts(rows, store, today=TODAY)
    assert len(parts) == 2 and all(p["split_by"] == "amount" for p in parts)
    assert whole["id"] in {p["id"] for p in parts}
    again = build_contracts(rows, store, today=TODAY)
    assert {p["id"] for p in again} == {p["id"] for p in parts}
    assert store.structure.unsplit(whole["payee_key"])
    (back,) = build_contracts(rows, store, today=TODAY)
    assert back["id"] == whole["id"]


def test_split_by_reference_separates_successive_contracts():
    rows = monthly([-40] * 3, name="Bank", remittanceInformationUnstructured="Darlehen 1234567")
    rows += monthly([-40] * 3, name="Bank", start=date(2026, 4, 12),
                    remittanceInformationUnstructured="Darlehen 7654321")
    store = structured_store()
    (whole,) = build_contracts(rows, store, today=TODAY)
    store.structure.split(whole["payee_key"], "reference")
    assert len(build_contracts(rows, store, today=TODAY)) == 2


def test_split_that_finds_nothing_to_split_keeps_one_series():
    rows = monthly([-10] * 5, name="Gym")
    store = structured_store()
    (whole,) = build_contracts(rows, store, today=TODAY)
    store.structure.split(whole["payee_key"], "reference")
    (still,) = build_contracts(rows, store, today=TODAY)
    assert still["id"] == whole["id"]
    with pytest.raises(ContractError):
        store.structure.split(whole["payee_key"], "colour")


def test_assigned_booking_joins_the_series_and_leaves_its_payee():
    rows = _keyed(monthly([-12.99] * 4, name="Streamly", start=date(2026, 2, 3)), "s")
    stray = _keyed([txn("2026-01-03", -12.99, "Kartenzahlung 4711")], "x")
    store = structured_store()
    (c,) = build_contracts(rows + stray, store, today=TODAY)
    assert c["occurrences"] == 4
    store.structure.assign("acc0|x0", c["id"])
    (c,) = build_contracts(rows + stray, store, today=TODAY)
    assert c["occurrences"] == 5 and "acc0|x0" in c["ledger_ids"]
    assert [a["key"] for a in c["assigned"]] == ["acc0|x0"]


def test_assigned_refund_becomes_a_settlement_of_the_contract():
    rows = _keyed(monthly([-80] * 5, name="Stadtwerke", start=date(2026, 1, 3)), "s")
    refund = _keyed([txn("2026-05-20", 35.0, "Inkasso Partner")], "r")
    store = structured_store()
    (c,) = build_contracts(rows + refund, store, today=TODAY)
    store.structure.assign("acc0|r0", c["id"])
    (c,) = build_contracts(rows + refund, store, today=TODAY)
    assert [(s["key"], s["source"]) for s in c["settlement"]["history"]] == [("acc0|r0", "manual")]
    assert c["occurrences"] == 5


def test_booking_assigned_to_a_manual_contract_is_linked_and_one_to_a_gone_id_returns():
    store = structured_store()
    mid = _manual(store)
    paid = _keyed([txn("2025-11-02", -480, "HUK Coburg")], "k")
    rows = _keyed(monthly([-12.99] * 4, name="Streamly", start=date(2026, 2, 3)), "s")
    store.structure.assign("acc0|k0", mid)
    store.structure.assign("acc0|s0", "s_gone")
    out = {c["id"]: c for c in build_contracts(paid + rows, store, today=TODAY)}
    assert out[mid]["ledger_ids"] == ["acc0|k0"] and out[mid]["annual_cost"] == 480.0
    (streamly,) = [c for c in out.values() if c["source"] == "detected"]
    assert streamly["occurrences"] == 4  # the booking assigned to a gone id is back
    assert store.remove_manual(mid) and "acc0|k0" not in store.structure.assignments


def test_structure_persists_and_reloads():
    import asyncio

    from custom_components.finance_dashboard.contracts import ContractStructure
    from tests.fakes import FakeStore

    st = ContractStructure(None, store=FakeStore(None, 1, "x"))
    st.merge("s_a", "s_b")
    st.split("acme|out", "amount")
    st.assign("acc0|x0", "s_a")
    asyncio.run(st.async_save())
    again = ContractStructure(None, store=st._store)  # noqa: SLF001
    asyncio.run(again.async_load())
    assert (again.merges, again.splits, again.assignments) == (st.merges, st.splits, st.assignments)
