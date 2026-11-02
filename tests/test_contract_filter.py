"""Contract search and filters (#118): validate, apply, totals, and the JS twin.

The shared cases in ``fixtures/contract_filter_cases.json`` (invented data) run
against ``contract_filter.py`` here and against ``fd-contract-filter.js`` via
Node (skipped without Node), so the two implementations cannot drift.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from custom_components.finance_dashboard import contract_filter as cf

ROOT = Path(__file__).parent
DATA = json.loads((ROOT / "fixtures" / "contract_filter_cases.json").read_text("utf-8"))
CTX = DATA["ctx"]
JS = ROOT.parent / "custom_components" / "finance_dashboard" / "frontend" / "fd-contract-filter.js"
CASES = DATA["cases"]


def _ids(spec_raw, **ctx):
    spec, _ = cf.validate_spec(spec_raw)
    return [c["id"] for c in cf.apply(DATA["contracts"], spec, **(ctx or CTX))["items"]]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_cases_python(case) -> None:
    spec, errors = cf.validate_spec(case["raw"])
    assert spec == case["spec"]
    assert [[e["field"], e["reason"]] for e in errors] == case["error_fields"]
    res = cf.apply(DATA["contracts"], spec, **CTX)
    assert [c["id"] for c in res["items"]] == case["ids"]
    assert res["totals"] == case["totals"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_shared_cases_js_twin_agree() -> None:
    script = """
const vm = require("vm"), fs = require("fs");
const ctx = { window: { _fd: {} } };
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const cf = ctx.window._fd.contractFilter;
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const out = data.cases.map((c) => {
  const { spec, errors } = cf.validateSpec(c.raw);
  const res = cf.apply(data.contracts, spec, data.ctx);
  return { name: c.name, spec, error_fields: errors.map((e) => [e.field, e.reason]),
           ids: res.items.map((i) => i.id), totals: res.totals };
});
process.stdout.write(JSON.stringify(out));
"""
    done = subprocess.run(  # noqa: S603
        ["node", "-e", script, str(JS), str(ROOT / "fixtures" / "contract_filter_cases.json")],  # noqa: S607
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=60,
    )
    got = json.loads(done.stdout)
    assert len(got) == len(CASES)
    for want, have in zip(CASES, got, strict=True):
        assert have == {k: want[k] for k in ("name", "spec", "error_fields", "ids", "totals")}


def test_invalid_parts_dropped_valid_parts_kept() -> None:
    spec, errors = cf.validate_spec(
        {"kinds": ["contract", "bogus"], "q": "abc", "amount_min": "x", "sort": "amount"}
    )
    assert spec["kinds"] == ["contract"]
    assert spec["q"] == "abc"
    assert spec["amount_min"] is None
    assert spec["sort"] == "amount"
    assert {(e["field"], e["reason"]) for e in errors} == {
        ("kinds", "unknown_value"), ("amount_min", "invalid_value")}


@pytest.mark.parametrize("raw", [None, "text", 5, [], [1]])
def test_non_object_gives_default_spec_and_error(raw) -> None:
    spec, errors = cf.validate_spec(raw)
    assert spec == cf.default_spec()
    assert errors == [{"field": "_", "reason": "not_an_object"}]


def test_ich_wir_map_to_tokens_and_vocab_is_enforced() -> None:
    spec, errors = cf.validate_spec({"owners": ["ich", "WIR", "Haushalt"]})
    assert spec["owners"] == ["me", "shared"] and not errors
    vocab = {"categories": {"media"}, "labels": {"home": None, "gift": "Geschenke"},
             "owners": {"Anna", "Ben"}}
    spec, errors = cf.validate_spec(
        {"owners": ["anna", "Clara", "partner"], "categories": ["media", "x"],
         "labels": ["Geschenke", "home", "nope"]}, vocab)
    assert spec["owners"] == ["Anna", "partner"]
    assert spec["categories"] == ["media"]
    assert spec["labels"] == ["gift", "home"]
    assert sorted(e["field"] for e in errors) == ["categories", "labels", "owners"]


def test_me_resolves_to_the_current_person_and_partner_to_the_others() -> None:
    assert _ids({"owners": ["me"]}) == ["c4", "c2", "c7"]
    assert _ids({"owners": ["partner"]}) == ["c3", "c6", "c10"]
    assert _ids({"owners": ["me"]}, me=None, persons=[]) == []


def test_candidates_only_when_asked_for() -> None:
    assert "c8" not in _ids({})
    assert _ids({"statuses": ["candidate"]}) == ["c8"]


def test_totals_sum_the_filtered_set_only() -> None:
    spec, _ = cf.validate_spec({"kinds": ["subscription"], "statuses": ["active", "overdue"]})
    res = cf.apply(DATA["contracts"], spec, **CTX)
    assert [c["id"] for c in res["items"]] == ["c3", "c4"]
    assert res["totals"]["yearly"] == round((13.99 + 29.9) * 12, 2)
    assert res["totals"]["fixed"]["count"] == 2 and res["totals"]["regular"]["count"] == 0
    # ended contracts are listed but do not count without an explicit status filter
    full = cf.apply(DATA["contracts"], cf.default_spec(), **CTX)
    assert "c7" in [c["id"] for c in full["items"]]
    assert full["totals"]["count"] == 8


def test_totals_match_contract_totals_for_the_unfiltered_list() -> None:
    from custom_components.finance_dashboard.contracts import contract_totals

    live = [c for c in DATA["contracts"] if not c["candidate"]]
    want = contract_totals(live)
    got = cf.apply(DATA["contracts"], cf.default_spec(), **CTX)["totals"]
    for group in ("fixed", "regular"):
        assert got[group] == want[group]


def test_amount_range_and_sort_are_deterministic() -> None:
    assert _ids({"amount_min": 13, "amount_max": 45}) == ["c3", "c4", "c6", "c10"]
    assert _ids({"sort": "amount"})[:2] == ["c9", "c5"]
    assert _ids({}) == _ids({}) and _ids({"sort": "amount"}) == _ids({"sort": "amount"})
    # ended last, undated after dated
    assert _ids({})[-1] == "c7"


def test_hand_and_ai_specs_give_the_same_result() -> None:
    """The AI's answer goes through the very same validate + apply as the hand-set filters."""
    by_hand = {"kinds": ["subscription"], "owners": ["me"], "sort": "amount"}
    ai_answer = json.dumps({"kinds": ["subscription"], "owners": ["ich"], "sort": "amount"})
    from_ai, _ = cf.validate_spec(cf.parse_answer("```json\n" + ai_answer + "\n```"))
    by_hand_spec, _ = cf.validate_spec(by_hand)
    assert from_ai == by_hand_spec
    assert cf.apply(DATA["contracts"], from_ai, **CTX) == cf.apply(DATA["contracts"], by_hand_spec, **CTX)


def test_parse_answer_tolerates_chatter_and_rejects_garbage() -> None:
    assert cf.parse_answer('Here you go: {"q": "x"} hope it helps') == {"q": "x"}
    assert cf.parse_answer("no json here") is None
    assert cf.parse_answer(None) is None


def test_prompt_holds_only_question_and_names() -> None:
    vocab = {"categories": ["media", "other"], "labels": {"home": None, "gift": "Geschenke"},
             "owners": {"Anna", "Ben"}}
    prompt = cf.build_query_prompt("Abos von mir ueber 20 Euro, IBAN DE89370400440532013000", vocab)
    assert "DE89" not in prompt
    assert "Anna" in prompt and "Geschenke" in prompt and "media" in prompt
    assert "ueber 20 Euro" in prompt  # a bound the user typed must survive
