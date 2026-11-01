"""Bundled benchmark dataset: schema, labelling, allowlist, lookup, no network."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from custom_components.finance_dashboard import benchmark
from custom_components.finance_dashboard.benchmark import (
    DATASET_PATH,
    BenchmarkProvider,
    household_size_keys,
    normalize_state,
    resolve,
)

PKG = Path(benchmark.__file__).parent


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _values(data: dict):
    for dim_id, dim in data["dimensions"].items():
        for entry in dim["values"]:
            yield dim_id, entry


def test_dataset_is_bundled_inside_the_integration() -> None:
    assert DATASET_PATH.is_file()
    assert PKG in DATASET_PATH.parents


def test_top_level_schema(data: dict) -> None:
    for key in (
        "dataset_version",
        "generated",
        "country",
        "sources",
        "dimensions",
        "allowed_domains",
        "statistics",
    ):
        assert key in data, key
    assert data["country"] == "DE"
    assert data["sources"], "sources allowlist must not be empty"
    ids = [s["id"] for s in data["sources"]]
    assert len(ids) == len(set(ids))
    for source in data["sources"]:
        for key in ("id", "publisher", "title", "url", "published", "reference_period"):
            assert source.get(key), (source.get("id"), key)


def test_every_value_has_source_year_and_statistic(data: dict) -> None:
    source_ids = {s["id"] for s in data["sources"]}
    count = 0
    for dim_id, entry in _values(data):
        count += 1
        assert entry["source"] in source_ids, (dim_id, entry["source"])
        assert entry["statistic"] in data["statistics"], (dim_id, entry["statistic"])
        assert isinstance(entry["reference_year"], int) and 2015 <= entry["reference_year"] <= 2030
        assert (
            isinstance(entry["publication_year"], int) and 2015 <= entry["publication_year"] <= 2030
        )
        assert entry["level"] in data["levels"]
        assert isinstance(entry["value"], (int, float)) and entry["value"] > 0
        assert entry.get("household_size", "all")
        if entry.get("derived"):
            assert entry.get("derivation"), dim_id
    assert count > 0


def test_every_used_source_is_on_the_domain_allowlist(data: dict) -> None:
    allowed = data["allowed_domains"]
    for source in data["sources"]:
        url = urlparse(source["url"])
        assert url.scheme == "https", source["id"]
        host = url.hostname or ""
        assert any(host == d or host.endswith("." + d) for d in allowed), host


def test_unsourced_dimensions_are_null_with_a_note(data: dict) -> None:
    for dim_id, dim in data["dimensions"].items():
        assert dim["unit"] and dim["label_de"] and dim["label_en"], dim_id
        assert dim["direction"] in ("lower_is_better", "higher_is_better")
        if not dim["values"]:
            assert dim["note"].startswith("Not sourced"), dim_id


def test_every_sourced_dimension_has_a_germany_value(data: dict) -> None:
    for dim_id, dim in data["dimensions"].items():
        if dim["values"]:
            assert any(v["level"] == "country" and v["region"] == "DE" for v in dim["values"]), (
                dim_id
            )


def test_concept_dimensions_are_present(data: dict) -> None:
    for dim_id in (
        "rent_per_sqm",
        "electricity_price",
        "electricity_consumption",
        "heating_gas_price",
        "heating_district_heating_price",
        "heating_oil_price",
        "heating_heat_pump_price",
        "food",
        "mobility",
        "insurance",
        "communication",
        "debt_ratio",
        "savings_rate",
        "equivalised_income",
        "regelbedarf",
    ):
        assert dim_id in data["dimensions"], dim_id


def test_benchmark_module_has_no_network_code() -> None:
    tree = ast.parse((PKG / "benchmark.py").read_text(encoding="utf-8"))
    forbidden = (
        "aiohttp",
        "requests",
        "httpx",
        "urllib",
        "http",
        "socket",
        "homeassistant.helpers.aiohttp_client",
    )
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            assert not any(name == f or name.startswith(f + ".") for f in forbidden), name
    assert "Store(" not in (PKG / "benchmark.py").read_text(encoding="utf-8")


def test_household_size_keys() -> None:
    assert household_size_keys(None) == ["all"]
    assert household_size_keys(2) == ["2", "all"]
    assert household_size_keys(4) == ["4", "4+", "all"]
    assert household_size_keys(6) == ["6", "5+", "4+", "all"]


def test_normalize_state() -> None:
    assert normalize_state("BY") == "DE-BY"
    assert normalize_state("de-hh") == "DE-HH"
    assert normalize_state("Thüringen") == "DE-TH"
    assert normalize_state("Atlantis") is None
    assert normalize_state(None) is None


def test_state_value_used_when_published(data: dict) -> None:
    hit = resolve(data, "rent_per_sqm", state="HH")
    assert hit["level"] == "state" and hit["region"] == "DE-HH"
    assert hit["statistic"] == "mean" and hit["reference_year"] == 2022


def test_missing_state_falls_back_to_country(data: dict) -> None:
    hit = resolve(data, "rent_per_sqm", state="NW")
    assert hit["level"] == "country" and hit["requested_level"] == "state"
    assert hit["value"] == data["dimensions"]["rent_per_sqm"]["values"][0]["value"]


def test_postcode_falls_back_to_state_then_country(data: dict) -> None:
    with_state = resolve(data, "rent_per_sqm", postcode="00000", state="BY")
    assert with_state["requested_level"] == "postcode" and with_state["level"] == "state"
    without_state = resolve(data, "rent_per_sqm", postcode="00000")
    assert without_state["level"] == "country"


def test_household_size_variants(data: dict) -> None:
    food = data["dimensions"]["food"]["values"]
    by_size = {v["household_size"]: v["value"] for v in food}
    assert resolve(data, "food", household_size=2)["value"] == by_size["2"]
    assert resolve(data, "food", household_size=7)["value"] == by_size["5+"]
    assert resolve(data, "food")["value"] == by_size["all"]
    kwh = resolve(data, "electricity_consumption", household_size=5)
    assert kwh["household_size"] == "4+"


def test_unsourced_dimension_resolves_to_none(data: dict) -> None:
    assert resolve(data, "insurance") is None
    assert resolve(data, "debt_ratio") is None
    assert resolve(data, "does_not_exist") is None


def test_provider_compare_is_labelled(data: dict) -> None:
    provider = BenchmarkProvider(dataset=data)
    food = resolve(data, "food", household_size=2)["value"]
    result = provider.compare("groceries", food + 50, household_size=2)
    assert result["better"] is False
    assert result["difference"] == 50
    for key in (
        "statistic",
        "source",
        "source_url",
        "reference_year",
        "publication_year",
        "survey_year",
        "level",
        "unit",
        "text",
    ):
        assert result[key] not in (None, ""), key
    assert "Destatis" in result["text"]
    assert provider.compare("insurance", 100.0) is None
    assert provider.compare("loans", 100.0) is None
    assert provider.get_benchmark_for_category("unknown") is None


def test_higher_is_better_direction(data: dict) -> None:
    provider = BenchmarkProvider(dataset=data)
    rate = resolve(data, "savings_rate")["value"]
    assert provider.compare("savings", rate + 1)["better"] is True


def test_provider_loads_bundled_file_without_hass() -> None:
    provider = BenchmarkProvider()
    asyncio.run(provider.async_initialize())
    info = provider.dataset_info()
    assert info["dataset_version"] and info["country"] == "DE"
    refs = provider.references(household_size=1)
    ids = [r["id"] for r in refs]
    assert "regelbedarf" in ids and "rent_per_sqm" in ids
    floor = next(r for r in refs if r["id"] == "regelbedarf")
    assert floor["variant"] == "rbs1" and floor["statistic"] == "statutory"
    assert {u["id"] for u in provider.unavailable()} >= {"insurance", "debt_ratio"}
    assert all(b["statistic"] for b in provider.get_benchmarks())
