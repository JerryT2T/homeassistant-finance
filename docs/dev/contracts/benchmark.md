# Contract: `GET /api/finance_dashboard/benchmark`

Auth: HA user (`requires_auth`). Query: `month`, `year` (optional, default now). Cache read only -
the reference side comes from the bundled dataset, never from the network. Returns 404 with
`{"error": "Not configured"}` when the integration has no manager.

## Response

```json
{
  "month": 10,
  "year": 2026,
  "income_net_total": 0.0,
  "has_plan": true,
  "dataset": {"dataset_version": "2026.10.1", "generated": "2026-10-28", "country": "DE"},
  "location": {"state": "BY", "postcode": null, "household_size": 2},
  "comparisons": ["Comparison"],
  "references": ["Reference"],
  "unavailable": [{"id": "insurance", "label": "Versicherungen", "note": "Not sourced: ..."}]
}
```

`location` echoes what was used: `state` / `postcode` from the options `benchmark_state` /
`benchmark_postcode` (either may be null), `household_size` = number of plan persons (null when
the plan has none). Children are not plan persons, so a family is compared by its adult count.

### Reference (context value, not compared)

Emitted for `rent_per_sqm`, `electricity_price`, `electricity_consumption`, `heating_gas_price`
(variant `multi_family_house`), `savings_rate`, `equivalised_income`, `regelbedarf` (variant
`rbs1`, the floor) - only when the dataset has a value.

| Field | Type | Meaning |
|---|---|---|
| `id` | string | dimension id |
| `label` / `label_en` | string | German / English label |
| `value` | number | benchmark value |
| `unit` | string | e.g. `EUR/month`, `EUR/m²/month`, `EUR/kWh`, `kWh/year`, `%`, `EUR/month/person` |
| `direction` | `lower_is_better` or `higher_is_better` | |
| `statistic` | `median`, `mean`, `aggregate_ratio`, `statutory`, `threshold_60pct_median` | must be shown next to the value |
| `derived` | bool | true when computed from a published figure (see the dataset `derivation`) |
| `variant` | string or null | e.g. `rbs1`, `single_family_house` |
| `household_size` | string | size class actually used: `all`, `1` to `4`, `4+`, `5+` |
| `level` | `postcode`, `district`, `state`, `country` | level actually used |
| `requested_level` | same | finest level the location allowed. `level != requested_level` means fallback |
| `region` | string | `DE` or ISO state code `DE-XX` |
| `source` / `publisher` / `source_url` | string | label the value with these |
| `reference_year` / `publication_year` | int | |
| `survey_year` | int | = `reference_year` (kept for the existing frontend) |
| `note` | string | caveat for the dimension |
| `dataset_version` | string | |

### Comparison (plan vs. benchmark)

A Reference plus:

| Field | Type | Meaning |
|---|---|---|
| `category` | string | plan metric (a life area, #112): `housing_cold` (cold + warm housing), `groceries`, `mobility`, `media` |
| `dimension` | string | dataset dimension (`housing_energy`, `food`, `mobility`, `communication`) |
| `user_value` | number | our planned monthly amount in EUR (or % of net income for `%` units) |
| `our_amount` | number | numerator in EUR |
| `source_categories` | string[] | plan categories summed into `our_amount` |
| `benchmark_value` | number | = `value` |
| `difference` | number | `user_value - benchmark_value` |
| `better` | bool | per `direction` |
| `fetch_date` | string | always `bundled` |
| `text` | string | ready-made German line, e.g. `Nahrungsmittel, Getränke, Tabak: 520 EUR/month (DE Ø 505 EUR/month, Destatis 2024, 2 Pers.)` |

Categories whose dimension has no sourced value (`health`, `finance`) are omitted, as are
categories with a zero planned amount.

The manual water comparison (option `water_consumption_ratio`) keeps its legacy shape with
`statistic: "manual"`, `manual: true`, `unit: "x Ø"` and no `source_url`.

## Frontend rules

- Always render `statistic` (Ø for mean, "Median" for median), `source` and `reference_year`.
- Show a fallback hint when `level !== requested_level` (e.g. "Bundeswert - kein Landeswert").
- Treat `regelbedarf` as a floor line, not as an average to beat.
- List `unavailable` as "noch keine amtliche Quelle", never as zero.
