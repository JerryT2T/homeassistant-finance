"""Acceptance bar for contract detection (#106, epic #123).

Runs every synthetic case of ``tests/fixtures/contracts`` through the
production path: categorizer -> transfer-chain enrichment ->
``counted_transactions`` -> ``build_contracts`` (as ``api/contracts`` does).

A case that a later milestone issue still has to fix is a strict xfail naming
that issue; the fix removes the marker in its own PR, so each fix is proven by
exactly the case it was written for.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from custom_components.finance_dashboard.categorizer import TransactionCategorizer
from custom_components.finance_dashboard.contracts import (
    build_contracts,
    own_account_names,
)
from custom_components.finance_dashboard.household_summary import counted_transactions, pending_debits
from custom_components.finance_dashboard.recurring import INTERVALS
from custom_components.finance_dashboard.transfer_detector import (
    detect_transfer_chains,
    enrich_transactions,
)
from tests.fixtures.contracts.cases import CASES, build
from tests.test_contracts import blank_store

EXPECTED = json.loads(
    (Path(__file__).parent / "fixtures" / "contracts" / "expected.json").read_text("utf-8")
)
SPEC: dict[str, dict[str, Any]] = EXPECTED["cases"]
TARGETS = EXPECTED["targets"]


def _today(case: str) -> date:
    return date.fromisoformat(SPEC[case].get("today", EXPECTED["today"]))


def _detect(case: str) -> list[dict[str, Any]]:
    accounts, txns = build(case)
    categorizer = TransactionCategorizer()
    for tx in txns:
        tx["category"] = categorizer.categorize(tx)
    chains, refunds = detect_transfer_chains(txns, accounts)
    txns = enrich_transactions(txns, chains, refunds)
    store = blank_store()
    counted = counted_transactions(txns, accounts) + pending_debits(txns)  # as the API (#115)
    return build_contracts(
        counted, store, today=_today(case), own_names=own_account_names(accounts)
    )


def _matches(found: dict[str, Any], want: dict[str, Any]) -> bool:
    plan = abs(float(found["plan_amount"]))
    return (
        want["creditor"] in found["creditor"]
        and found["interval"] == want["interval"]
        and abs(plan - want["plan_amount"]) <= 0.01 * want["plan_amount"] + 0.005
    )


def _pair(found: list[dict[str, Any]], wanted: list[dict[str, Any]]):
    """One-to-one: expected -> detected (or None), plus unmatched detections."""
    free = list(found)
    pairs = []
    for want in wanted:
        hit = next((f for f in free if _matches(f, want)), None)
        if hit is not None:
            free.remove(hit)
        pairs.append((want, hit))
    return pairs, free


def _fixed(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What counts as a fixed cost: unconfirmed candidates (#110) do not."""
    return [f for f in found if not f.get("candidate")]


def _annual(want: dict[str, Any]) -> float:
    return want["plan_amount"] * INTERVALS[want["interval"]][1]


def _case_params():
    for case in CASES:
        reason = SPEC[case].get("xfail")
        marks = [pytest.mark.xfail(strict=True, reason=f"fixed by {reason}")] if reason else []
        yield pytest.param(case, id=case, marks=marks)


def test_every_case_has_an_expectation():
    assert set(CASES) == {k for k in SPEC if not k.startswith("_")}


def test_fixtures_carry_no_real_account_data():
    for case in CASES:
        accounts, _ = build(case)
        for acc in accounts:
            iban = acc.get("iban")
            assert iban is None or iban.startswith("DE00000000"), (case, "real-looking IBAN")


@pytest.mark.parametrize("case", list(_case_params()))
def test_case(case: str):
    found = _detect(case)
    pairs, extra = _pair(found, SPEC[case]["contracts"])
    missing = [w for w, hit in pairs if hit is None]
    assert not missing, f"not detected: {missing}"
    # a case may expect a candidate (a question, #109); every other contract must be sure
    unsure = [
        w["creditor"]
        for w, hit in pairs
        if hit is not None and bool(hit.get("candidate")) != bool(w.get("candidate"))
    ]
    assert not unsure, f"detected only as a candidate (#129): {unsure}"
    false_positives = [f["creditor"] for f in _fixed(extra)]
    assert not false_positives, f"counted as contract by mistake: {false_positives}"
    for want, hit in pairs:
        for field in ("status", "last_seen"):
            if field in want:
                assert hit[field] == want[field], (want["creditor"], field)


def _all_pairs():
    for case in CASES:
        found = _detect(case)
        pairs, extra = _pair(found, SPEC[case]["contracts"])
        yield case, pairs, extra


@pytest.mark.xfail(strict=True, reason="#123: targets met once every milestone issue has landed")
def test_detection_meets_epic_targets():
    expected = matched = detected = false_pos = 0
    want_total = got_total = 0.0
    for _case, pairs, extra in _all_pairs():
        expected += len(pairs)
        matched += sum(1 for _w, hit in pairs if hit is not None)
        fixed_hits = [hit for _w, hit in pairs if hit is not None and not hit.get("candidate")]
        fixed_extra = _fixed(extra)
        detected += len(fixed_hits) + len(fixed_extra)
        false_pos += len(fixed_extra)
        want_total += sum(_annual(w) for w, _hit in pairs)
        got_total += sum(float(f["annual_cost"]) for f in fixed_hits + fixed_extra)
    recall = matched / expected
    fp_rate = false_pos / detected if detected else 0.0
    deviation = abs(got_total - want_total) / want_total
    assert recall >= TARGETS["recall"], f"recall {recall:.1%}"
    assert fp_rate <= TARGETS["false_positive_rate"], f"false positives {fp_rate:.1%}"
    assert deviation <= TARGETS["annual_total_deviation"], f"annual total off by {deviation:.1%}"


def test_detected_contracts_carry_their_kind():
    checked = 0
    for _case, pairs, _extra in _all_pairs():
        for want, hit in pairs:
            if hit is not None:
                checked += 1
                assert hit.get("kind") == want["kind"], (want["creditor"], hit.get("kind"))
    assert checked


@pytest.mark.xfail(
    strict=True, reason="#123: invented payee names only the question flow or AI can place"
)
def test_detected_contracts_carry_their_life_area():
    checked, wrong = 0, []
    for _case, pairs, _extra in _all_pairs():
        for want, hit in pairs:
            if hit is not None:
                checked += 1
                if hit.get("category") != want["category"]:
                    wrong.append((want["creditor"], want["category"], hit.get("category")))
    assert checked
    assert wrong == []


@pytest.mark.xfail(strict=True, reason="#119: refund matching across cycles")
def test_health_refunds_are_allocated_to_their_expenses():
    # #119 owns the matcher's API; adapt this call when it lands.
    from custom_components.finance_dashboard.refund_matcher import match_refunds  # noqa: PLC0415

    _accounts, txns = build("health_refunds")
    want = {k: v for k, v in SPEC["health_refunds"]["refunds"].items() if not k.startswith("_")}
    assert match_refunds(txns) == want
