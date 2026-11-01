"""Benchmark data provider - bundled, versioned German household benchmarks.

Reads ``data/benchmarks_de.json`` only. There is no network code in this
module by design (CLAUDE.md: "no runtime benchmark fetch"). The dataset is
refreshed by a maintainer and shipped with a release - see
``docs/dev/benchmark-sources.md`` for the source allowlist and the update
procedure.

Each comparison uses the finest level the dataset carries for the requested
location: postcode -> district -> state -> country. The bundled dataset has
no postcode or district values today, so those requests fall back to the
state (when known) or to Germany - the response says which level was used.

Every value is labelled with its statistic (median / mean / ...), source,
reference year and publication year. Dimensions without a sourced value are
present with an empty ``values`` list and a ``note`` and are never compared.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DATASET_PATH = Path(__file__).parent / "data" / "benchmarks_de.json"
LEVELS = ("postcode", "district", "state", "country")
COUNTRY_REGION = "DE"

# Plan category -> dataset dimension. A category whose dimension has no
# sourced value (insurance, loans) resolves to None and is not compared.
CATEGORY_DIMENSIONS: dict[str, str] = {
    "housing_cold": "housing_energy",
    "groceries": "food",
    "mobility": "mobility",
    "media": "communication",
    "health": "insurance",
    "finance": "debt_ratio",
    "savings": "savings_rate",
}

# Context values shown next to the category comparisons (not compared with
# plan amounts): dimension id -> variant to pick (None = first match).
REFERENCE_DIMENSIONS: dict[str, str | None] = {
    "rent_per_sqm": None,
    "electricity_price": None,
    "electricity_consumption": None,
    "heating_gas_price": "multi_family_house",
    "savings_rate": None,
    "equivalised_income": None,
    "regelbedarf": "rbs1",
}

# ISO 3166-2 codes of the 16 federal states, keyed by short code and name.
_STATES: dict[str, str] = {
    "BW": "Baden-Württemberg",
    "BY": "Bayern",
    "BE": "Berlin",
    "BB": "Brandenburg",
    "HB": "Bremen",
    "HH": "Hamburg",
    "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz",
    "SL": "Saarland",
    "SN": "Sachsen",
    "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}


def normalize_state(value: str | None) -> str | None:
    """Return the ISO code ``DE-XX`` for a state code or name, else None."""
    if not value:
        return None
    text = str(value).strip()
    upper = text.upper()
    if upper.startswith("DE-"):
        upper = upper[3:]
    if upper in _STATES:
        return "DE-" + upper
    lowered = text.casefold()
    for code, name in _STATES.items():
        if name.casefold() == lowered:
            return "DE-" + code
    return None


def load_dataset(path: Path | None = None) -> dict[str, Any]:
    """Read the bundled dataset from disk (blocking - use an executor in HA)."""
    with open(path or DATASET_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _cached_dataset() -> dict[str, Any]:
    return load_dataset()


def household_size_keys(size: int | None) -> list[str]:
    """Size classes to try for a household of ``size`` persons, finest first."""
    if not size or size < 1:
        return ["all"]
    keys = [str(size)]
    if size >= 5:
        keys.append("5+")
    if size >= 4:
        keys.append("4+")
    keys.append("all")
    return keys


def _source_meta(dataset: dict[str, Any], source_id: str) -> dict[str, Any]:
    for source in dataset.get("sources", []):
        if source.get("id") == source_id:
            return source
    return {}


def resolve(  # noqa: PLR0913
    dataset: dict[str, Any],
    dimension_id: str,
    *,
    state: str | None = None,
    postcode: str | None = None,
    district: str | None = None,
    household_size: int | None = None,
    variant: str | None = None,
) -> dict[str, Any] | None:
    """Pick the finest available value of one dimension for a location.

    Walks postcode -> district -> state -> country starting at the finest
    level the caller supplied, and within each level the household-size
    classes from exact size to "all". Returns None when the dimension has
    no sourced value.
    """
    dim = dataset.get("dimensions", {}).get(dimension_id)
    if not dim or not dim.get("values"):
        return None
    state_code = normalize_state(state)
    regions = {
        "postcode": str(postcode).strip() if postcode else None,
        "district": str(district).strip() if district else None,
        "state": state_code,
        "country": COUNTRY_REGION,
    }
    requested = next((lvl for lvl in LEVELS if regions[lvl]), "country")
    sizes = household_size_keys(household_size)
    start = LEVELS.index(requested)
    for level in LEVELS[start:]:
        region = regions[level]
        if not region:
            continue
        for size in sizes:
            for entry in dim["values"]:
                if entry.get("level") != level or entry.get("region") != region:
                    continue
                if entry.get("household_size", "all") != size:
                    continue
                if variant is not None and entry.get("variant") != variant:
                    continue
                return _labelled(dataset, dimension_id, dim, entry, requested)
    return None


def _labelled(
    dataset: dict[str, Any],
    dimension_id: str,
    dim: dict[str, Any],
    entry: dict[str, Any],
    requested: str,
) -> dict[str, Any]:
    source = _source_meta(dataset, entry["source"])
    return {
        "id": dimension_id,
        "label": dim.get("label_de", dimension_id),
        "label_en": dim.get("label_en", dimension_id),
        "value": entry["value"],
        "unit": dim.get("unit", ""),
        "direction": dim.get("direction", "lower_is_better"),
        "statistic": entry["statistic"],
        "derived": bool(entry.get("derived", False)),
        "variant": entry.get("variant"),
        "household_size": entry.get("household_size", "all"),
        "level": entry["level"],
        "requested_level": requested,
        "region": entry["region"],
        "source_id": entry["source"],
        "source": source.get("title", entry["source"]),
        "publisher": source.get("publisher", ""),
        "source_url": source.get("url", ""),
        "reference_year": entry["reference_year"],
        "publication_year": entry["publication_year"],
        # Kept for the existing frontend, which renders ``survey_year``.
        "survey_year": entry["reference_year"],
        "note": dim.get("note", ""),
        "note_de": dim.get("note_de", ""),
        "dataset_version": dataset.get("dataset_version", ""),
    }


class BenchmarkProvider:
    """Serves the bundled benchmark dataset. Never touches the network."""

    def __init__(
        self, hass: HomeAssistant | None = None, dataset: dict[str, Any] | None = None
    ) -> None:
        """Initialize; ``dataset`` injects a parsed dataset (tests)."""
        self._hass = hass
        self._dataset = dataset

    async def async_initialize(self) -> None:
        """Load the bundled file off the event loop."""
        if self._dataset is not None:
            return
        if self._hass is not None:
            self._dataset = await self._hass.async_add_executor_job(_cached_dataset)
        else:
            self._dataset = _cached_dataset()
        _LOGGER.debug("Benchmark dataset %s loaded", self._dataset.get("dataset_version"))

    @property
    def dataset(self) -> dict[str, Any]:
        """The parsed dataset (loads synchronously if not initialised)."""
        if self._dataset is None:
            self._dataset = _cached_dataset()
        return self._dataset

    def dataset_info(self) -> dict[str, Any]:
        """Version stamp for API responses."""
        data = self.dataset
        return {
            "dataset_version": data.get("dataset_version"),
            "generated": data.get("generated"),
            "country": data.get("country", COUNTRY_REGION),
        }

    def get_benchmarks(self) -> list[dict[str, Any]]:
        """Every dimension with a sourced value, at country level for all households."""
        result = []
        for dim_id in self.dataset.get("dimensions", {}):
            value = resolve(self.dataset, dim_id)
            if value is None:
                dim = self.dataset["dimensions"][dim_id]
                # Dimensions such as poverty_threshold only carry size-specific values.
                if dim.get("values"):
                    first = dim["values"][0]
                    value = _labelled(self.dataset, dim_id, dim, first, first["level"])
            if value is not None:
                result.append(value)
        return result

    def get_benchmark(
        self,
        benchmark_id: str,
        state: str | None = None,
        postcode: str | None = None,
        household_size: int | None = None,
        variant: str | None = None,
    ) -> dict[str, Any] | None:
        """One dimension, resolved for a location and household size."""
        return resolve(
            self.dataset,
            benchmark_id,
            state=state,
            postcode=postcode,
            household_size=household_size,
            variant=variant,
        )

    def get_benchmark_for_category(
        self,
        category: str,
        state: str | None = None,
        postcode: str | None = None,
        household_size: int | None = None,
    ) -> dict[str, Any] | None:
        """The benchmark covering a plan category, or None if unsourced.

        Callers need the unit before computing their own value: a "%" metric
        is a share of net income, an EUR metric an absolute monthly amount.
        """
        dim_id = CATEGORY_DIMENSIONS.get(category)
        if dim_id is None:
            return None
        return self.get_benchmark(
            dim_id, state=state, postcode=postcode, household_size=household_size
        )

    def references(
        self,
        state: str | None = None,
        postcode: str | None = None,
        household_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """Context values (rent per m², energy prices, floor ...) for a location."""
        result = []
        for dim_id, variant in REFERENCE_DIMENSIONS.items():
            value = resolve(
                self.dataset,
                dim_id,
                state=state,
                postcode=postcode,
                household_size=household_size,
                variant=variant,
            )
            if value is not None:
                result.append(value)
        return result

    def unavailable(self) -> list[dict[str, str]]:
        """Dimensions without a sourced value, with the reason."""
        return [
            {
                "id": dim_id,
                "label": dim.get("label_de", dim_id),
                "note": dim.get("note", ""),
                "note_de": dim.get("note_de", ""),
            }
            for dim_id, dim in self.dataset.get("dimensions", {}).items()
            if not dim.get("values")
        ]

    def compare(
        self,
        category: str,
        user_value: float,
        state: str | None = None,
        postcode: str | None = None,
        household_size: int | None = None,
    ) -> dict[str, Any] | None:
        """Compare a value from the plan with the benchmark for its category.

        Example text: "Nahrungsmittel, Getränke, Tabak: 520 EUR/month
        (DE Ø 505 EUR/month, LWR 2024, 2 Pers.)".
        """
        benchmark = self.get_benchmark_for_category(
            category, state=state, postcode=postcode, household_size=household_size
        )
        if not benchmark:
            return None
        bv = benchmark["value"]
        diff = user_value - bv
        lower_is_better = benchmark["direction"] != "higher_is_better"
        is_better = diff < 0 if lower_is_better else diff > 0
        unit = benchmark["unit"]
        symbol = "Median" if benchmark["statistic"] == "median" else "Ø"
        size = benchmark["household_size"]
        size_text = "" if size == "all" else f", {size} Pers."
        publisher = benchmark["publisher"]
        short = (
            publisher.split("(")[-1].rstrip(")") if "(" in publisher else publisher.split(" ")[0]
        ) or benchmark["source_id"]
        text = (
            f"{benchmark['label']}: {user_value:.0f} {unit} "
            f"({benchmark['region']} {symbol} {bv:.0f} {unit}, {short} "
            f"{benchmark['reference_year']}{size_text})"
        )
        result = dict(benchmark)
        result.update(
            {
                "category": category,
                "dimension": benchmark["id"],
                "user_value": user_value,
                "benchmark_value": bv,
                "difference": round(diff, 2),
                "better": is_better,
                "fetch_date": "bundled",
                "text": text,
            }
        )
        return result
