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


# ---------------------------------------------------------------------------
# Actual-vs-benchmark (B1): the household's real yearly spend, plan as second mark
# ---------------------------------------------------------------------------

TYPICAL_TOLERANCE = 0.10  # within +-10 % of the benchmark reads as "typical"
BAND_BELOW, BAND_TYPICAL, BAND_ABOVE = "below", "typical", "above"
SAVINGS_CATEGORY = "savings"
TEASER_N = 3
FULL_YEAR_MONTHS = 12


def deviation(user: float, bench: float) -> tuple[float | None, float | None, str | None]:
    """``(deviation_pct, position, band)`` of ``user`` against ``bench``.

    ``deviation_pct`` is relative (0.12 = 12 % above). ``position`` is 0..1 on
    the overview scale (0.5 = exactly typical, 0 / 1 = 50 % or more below /
    above). ``band`` is ``below`` / ``typical`` / ``above``.
    """
    if not bench:
        return None, None, None
    d = (user - bench) / abs(bench)
    band = BAND_TYPICAL if abs(d) <= TYPICAL_TOLERANCE else (BAND_ABOVE if d > 0 else BAND_BELOW)
    return round(d, 4), round(min(1.0, max(0.0, 0.5 + d)), 4), band


def _own_values(
    metric: str,
    cats: list[str],
    percent: bool,
    actual_monthly: dict[str, float],
    plan_monthly: dict[str, float],
    income_actual: float,
    income_plan: float,
    months_covered: int,
) -> tuple[float | None, float | None, float | None]:
    """``(actual, plan, amount)`` of the household for one dimension."""
    if metric == SAVINGS_CATEGORY:
        actual = (
            round((income_actual - sum(actual_monthly.values())) / income_actual * 100, 2)
            if months_covered and income_actual > 0
            else None
        )
        plan = (
            round((income_plan - sum(plan_monthly.values())) / income_plan * 100, 2)
            if income_plan > 0 and plan_monthly
            else None
        )
        return actual, plan, None
    a_sum = round(sum(actual_monthly.get(c, 0.0) for c in cats), 2)
    p_sum = round(sum(plan_monthly.get(c, 0.0) for c in cats), 2)
    if percent:
        actual = (
            round(a_sum / income_actual * 100, 2)
            if months_covered and a_sum > 0 and income_actual > 0
            else None
        )
        plan = round(p_sum / income_plan * 100, 2) if p_sum > 0 and income_plan > 0 else None
    else:
        actual = a_sum if months_covered and a_sum > 0 else None
        plan = p_sum if p_sum > 0 else None
    return actual, plan, a_sum


def compare_all(  # noqa: PLR0913
    provider: BenchmarkProvider,
    sources: dict[str, list[str]],
    *,
    actual_monthly: dict[str, float],
    plan_monthly: dict[str, float],
    income_actual: float,
    income_plan: float,
    months_covered: int,
    year: int,
    location: dict[str, Any],
) -> list[dict[str, Any]]:
    """One comparison per dimension, outliers (largest relative deviation) first.

    The household's own side is the **actual** monthly average of the year
    (counted spend by category over ``months_covered`` finished cycles); an
    incomplete year is flagged ``extrapolated``. The plan value is the second
    mark. A dimension without actual spend falls back to the plan
    (``basis: "plan"``). Source, statistic, year and fallback level stay with
    every figure (the provider's labels).
    """
    rows: list[dict[str, Any]] = []
    for metric, cats in {**sources, SAVINGS_CATEGORY: [SAVINGS_CATEGORY]}.items():
        bench = provider.get_benchmark_for_category(metric, **location)
        if not bench:
            continue
        actual, plan, amount = _own_values(
            metric, cats, bench.get("unit") == "%", actual_monthly, plan_monthly,
            income_actual, income_plan, months_covered,
        )
        basis, value = ("actual", actual) if actual is not None else ("plan", plan)
        if value is None:
            continue
        row = provider.compare(metric, value, **location)
        if not row:
            continue
        dev, position, band = deviation(value, row["benchmark_value"])
        row.update(
            {
                "basis": basis,
                "actual_value": actual,
                "plan_value": plan,
                "plan_deviation_pct": (
                    deviation(plan, row["benchmark_value"])[0] if plan is not None else None
                ),
                "deviation_pct": dev,
                "position": position,
                "band": band,
                "extrapolated": basis == "actual" and months_covered < FULL_YEAR_MONTHS,
                "months_covered": months_covered if basis == "actual" else 0,
                "year": year,
                "our_amount": amount,
                "source_categories": cats,
            }
        )
        rows.append(row)
    rows.sort(key=lambda r: -abs(r["deviation_pct"] or 0.0))
    return rows


def teaser(comparisons: list[dict[str, Any]], n: int = TEASER_N) -> list[dict[str, Any]]:
    """The ``n`` largest deviations, for the year view (A11)."""
    return [
        {
            "dimension": r["dimension"],
            "label": r["label"],
            "deviation_pct": r["deviation_pct"],
            "band": r["band"],
            "better": r["better"],
            "user_value": r["user_value"],
            "benchmark_value": r["benchmark_value"],
            "unit": r["unit"],
            "extrapolated": r.get("extrapolated", False),
        }
        for r in comparisons
        if r.get("deviation_pct") is not None and not r.get("manual")
    ][:n]
