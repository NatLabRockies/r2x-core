---
title: Adapt table mappings to your application's data
description: Select model years, reshape scenarios, match prices by year, complete grids for missing hours, and add products or contributors.
---

Use these recipes when your application needs a different input shape, matching
rule, or output grid. Each starts from named prepared tables and shows the JSON
record to add or replace in `table_mapping.json`.

Core supports typed row and concat constructors, bindings for whole values, and
the final `columns` projection used in these recipes. The [reference for table
mappings](/r2x-core/references/table-mapping/) defines their fields, order,
types, and null behavior.

Declare dependencies before their consumers. The JSON objects below are table
records to place inside the top level list, not separate configuration formats.
For exact field definitions, see the [reference for table mappings](/r2x-core/references/table-mapping/).
If you are learning the format, start with the
[reserve requirement tutorial](/r2x-core/tutorials/assemble-reserve-requirements/).

## Reuse a small shared intermediate

A named table can be explicitly materialized after its operations and final
projection when several downstream tables reuse an expensive, bounded result.
For example, if `technology_inputs` has a `supported` flag, add:

```json
{
  "name": "supported_technologies",
  "source": "technology_inputs",
  "operations": [
    {"operation": "filter", "column": "supported", "comparison": "equals", "value": true}
  ],
  "columns": {"technology": "technology", "technology_key": "technology_key"},
  "materialize": true
}
```

Point each dependent table at `supported_technologies`. The filtered projection
is evaluated once at that boundary and kept in memory for those downstream
plans. Materialization moves lazy errors in the final projected plan to assembly
time and holds the complete result in memory. Keep the default lazy behavior for
large tables or tables used only once.

## Select one model year and rename fields for the parser

Use a filter when an upstream source contains more years or categories than the
current build needs. Bind `selected_year` to the integer `2032` in application
configuration.

Start with `generator_inputs`:

| name | year | category | capacity |
| --- | ---: | --- | ---: |
| Wind_A | 2032 | wind | 100.0 |
| Wind_A | 2040 | wind | 120.0 |
| Solar_B | 2032 | solar | 50.0 |

Add this table definition:

```json
{
  "name": "wind_component_rows",
  "source": "generator_inputs",
  "operations": [
    {"operation": "filter", "column": "year", "comparison": "equals", "value": "{selected_year}"},
    {"operation": "filter", "column": "category", "comparison": "equals", "value": "wind"}
  ],
  "columns": {
    "capacity_mw": "capacity",
    "component_family": {"value": "variable"},
    "name": "name",
    "solve_year": "year"
  }
}
```

The result contains one row:

| capacity_mw | component_family | name | solve_year |
| ---: | --- | --- | ---: |
| 100.0 | variable | Wind_A | 2032 |

`"solve_year": "year"` copies and renames a column. The `value` wrapper makes
`variable` literal text rather than a column reference. Other input columns are
not included in the result.

For a build that covers several years, remove the filter by year and keep
`solve_year` in the output. Do not bind a list to this equality comparison and
expect it to match any item in the list. For a different component schema,
change the final column map without changing the source file description.

## Turn scenario columns into scenario rows

Use unpivot when a file encodes the same measure in one column per scenario.
Select the measure columns explicitly so metadata cannot become measurement
rows.

Start with `scenario_loads`:

| region | solve_year | base_mw | high_mw | note |
| --- | ---: | ---: | ---: | --- |
| North | 2032 | 100.0 | 120.0 | reviewed |
| South | 2032 | 50.0 | 80.0 | provisional |

Add:

```json
{
  "name": "scenario_load_rows",
  "source": "scenario_loads",
  "operations": [
    {
      "operation": "unpivot",
      "index": ["region", "solve_year"],
      "columns": {"base": "base_mw", "high": "high_mw"},
      "variable_name": "scenario",
      "value_name": "load_mw"
    }
  ]
}
```

The result is:

| region | solve_year | scenario | load_mw |
| --- | ---: | --- | ---: |
| North | 2032 | base | 100.0 |
| South | 2032 | base | 50.0 |
| North | 2032 | high | 120.0 |
| South | 2032 | high | 80.0 |

The note is excluded. The scenario labels are strings supplied by the mapping,
not parsed fragments of the input column names.

To add a `low` scenario, prepare a numeric `low_mw` column and add
`"low": "low_mw"` to the unpivot map. To keep metadata shared across scenarios,
include its column in `index`.

## Calculate costs with prices that change by region and year

Join on every dimension that determines the price. Do not match on category
alone when the same category has different prices across regions or years.

Start with `energy_quantities` in MWh:

| region | solve_year | kind | energy_mwh |
| --- | ---: | --- | ---: |
| North | 2032 | wind | 10.0 |
| North | 2032 | solar | 20.0 |
| North | 2040 | wind | 10.0 |
| North | 2040 | solar | 20.0 |

Prepare `energy_prices` with one applicable price per key, in a common currency
per MWh:

| region | solve_year | kind | price_per_mwh |
| --- | ---: | --- | ---: |
| North | 2032 | wind | 30.0 |
| North | 2032 | solar | 20.0 |
| North | 2040 | wind | 40.0 |
| North | 2040 | solar | 10.0 |

Add:

```json
{
  "name": "annual_energy_costs",
  "source": "energy_quantities",
  "operations": [
    {
      "operation": "join",
      "source": "energy_prices",
      "how": "inner",
      "on": ["region", "solve_year", "kind"],
      "columns": ["price_per_mwh"]
    },
    {
      "operation": "multiply",
      "columns": ["energy_mwh", "price_per_mwh"],
      "output": "cost"
    },
    {
      "operation": "group_by",
      "columns": ["region", "solve_year"],
      "aggregate": [{"operation": "sum", "column": "cost", "output": "total_cost"}]
    },
    {"operation": "sort", "columns": ["region", "solve_year"]}
  ]
}
```

Expect:

| region | solve_year | total_cost |
| --- | ---: | ---: |
| North | 2032 | 700.0 |
| North | 2040 | 600.0 |

For 2032, the two costs are 300 and 400. For 2040, they are 400 and 200. Omitting
`solve_year` from `on` would match each quantity to prices from both years.

If prices are global, remove `region` from the price source and the join keys.
Keep it in the quantity table and grouping keys when regional totals are still
required. If prices are hourly, carry `datetime` on both sides and add it to the
join keys.

This inner join retains priced rows only. Account for every required price key
before accepting totals. To inspect missing prices, use a left join and inspect
null `price_per_mwh` values before aggregation. A left join alone does not make
the total complete, because `sum` ignores null contributions. Do not fill an
unknown price with zero unless that is an explicit application policy.

## Produce every requested owner, year, and hour

Build a grid first when the parser needs a regular series even if observations
are sparse. Use zero filling only when an absent observation means zero for the
quantity being modeled.

Start with `load_owners`, containing names `NorthLoad` and `SouthLoad`, and a
`calendar` with datetime values `2012-01-01 00:00` and `2012-01-01 01:00`.
Bind `solve_year_rows` to `[{"solve_year": 2032}, {"solve_year": 2040}]`.
The prepared `load_observations` table contains one row:

| name | solve_year | datetime | load_mw |
| --- | ---: | --- | ---: |
| NorthLoad | 2032 | 2012-01-01 00:00 | 10.0 |

Add these two definitions in order:

```json
[
  {
    "name": "requested_years",
    "operations": [
      {
        "operation": "rows",
        "schema": [{"name": "solve_year", "dtype": "int64"}],
        "values": "{solve_year_rows}"
      }
    ]
  },
  {
    "name": "hourly_load_rows",
    "source": "load_owners",
    "operations": [
      {"operation": "join", "source": "requested_years", "how": "cross"},
      {"operation": "join", "source": "calendar", "how": "cross", "columns": ["datetime"]},
      {
        "operation": "join",
        "source": "load_observations",
        "how": "left",
        "on": ["name", "solve_year", "datetime"],
        "columns": ["load_mw"]
      },
      {"operation": "fill_null", "columns": ["load_mw"], "value": 0},
      {"operation": "sort", "columns": ["name", "solve_year", "datetime"]}
    ],
    "columns": {
      "datetime": "datetime",
      "load_mw": "load_mw",
      "name": "name",
      "solve_year": "solve_year"
    }
  }
]
```

Expect eight rows:

| datetime | load_mw | name | solve_year |
| --- | ---: | --- | ---: |
| 2012-01-01 00:00 | 10.0 | NorthLoad | 2032 |
| 2012-01-01 01:00 | 0.0 | NorthLoad | 2032 |
| 2012-01-01 00:00 | 0.0 | NorthLoad | 2040 |
| 2012-01-01 01:00 | 0.0 | NorthLoad | 2040 |
| 2012-01-01 00:00 | 0.0 | SouthLoad | 2032 |
| 2012-01-01 01:00 | 0.0 | SouthLoad | 2032 |
| 2012-01-01 00:00 | 0.0 | SouthLoad | 2040 |
| 2012-01-01 01:00 | 0.0 | SouthLoad | 2040 |

To preserve unknown samples, omit `fill_null` and let the consumer's null policy
apply. To use a different time range or resolution, change the prepared calendar
and the parser's time axis settings together. Do not infer a calendar from sparse
observations.

Keep grid keys unique when one row per key is required. Cross joins preserve
duplicate owners, years, and timestamps. They do not deduplicate them for you.

## Add another reserve product without another calculation branch

Start with the [reserve tutorial](/r2x-core/tutorials/assemble-reserve-requirements/).
Add the product to application configuration, including its required component
settings. Ensure upstream preparation supplies the corresponding product and
component rows.

For this variation, use these prepared `reserve_products` values. This table is
not the complete application configuration schema:

| reserve_type | load_fraction | wind_fraction | solar_fraction |
| --- | ---: | ---: | ---: |
| SPINNING | 0.3 | 0.1 | 0.2 |
| FLEXIBILITY | 0.1 | 0.2 | 0.0 |

Add the component row named `controlled_FLEXIBILITY` for transmission region
`controlled` and reserve type `FLEXIBILITY`. Leave the nine assembly definitions
unchanged.

The factor table now contains six rows. Each quantity matches one factor for
each product. For solve year 2032, expect these first two hours:

| name | datetime | requirement |
| --- | --- | ---: |
| controlled_FLEXIBILITY | 2012-01-01 00:00 | 5.0 |
| controlled_FLEXIBILITY | 2012-01-01 01:00 | 1.0 |
| controlled_SPINNING | 2012-01-01 00:00 | 5.0 |
| controlled_SPINNING | 2012-01-01 01:00 | 103.0 |

The missing hour and the unobserved solve year still receive zero rows from the
complete grid. Keep `reserve_type` in the contribution grouping keys so product
totals do not combine.

## Add another contributor without changing the shared arithmetic

Start from the tutorial's single `SPINNING` product. Suppose a new prepared
source, `hydro_hourly_rows`, has these values:

| transmission_region | solve_year | datetime | hydro_mw |
| --- | ---: | --- | ---: |
| controlled | 2032 | 2012-01-01 01:00 | 50.0 |

First, extend the application's configuration and preparation to supply
`hydro_fraction = 0.05` in `reserve_products`. Adding an unpivot entry does not
add a field to the application's configuration model. Supply a fraction for each
configured product, rather than relying on an undeclared default.

Add `reserve_hydro_quantities` before the factor and concatenation tables:

```json
{
  "name": "reserve_hydro_quantities",
  "source": "hydro_hourly_rows",
  "operations": [],
  "columns": {
    "datetime": "datetime",
    "kind": {"value": "hydro"},
    "quantity_mw": "hydro_mw",
    "solve_year": "solve_year",
    "transmission_region": "transmission_region"
  }
}
```

Replace the existing `reserve_factors` and `reserve_quantities` records with these
records. Do not append second definitions with the same names:

```json
[
  {
    "name": "reserve_factors",
    "source": "reserve_products",
    "operations": [
      {
        "operation": "unpivot",
        "index": ["reserve_type"],
        "columns": {
          "hydro": "hydro_fraction",
          "load": "load_fraction",
          "solar": "solar_fraction",
          "wind": "wind_fraction"
        },
        "variable_name": "kind",
        "value_name": "fraction"
      }
    ]
  },
  {
    "name": "reserve_quantities",
    "operations": [
      {
        "operation": "concat",
        "sources": [
          "reserve_load_quantities",
          "reserve_wind_quantities",
          "reserve_solar_quantities",
          "reserve_hydro_quantities"
        ]
      }
    ]
  }
]
```

Leave `reserve_contributions` and the output grid definition unchanged. At 01:00,
the new quantity contributes 2.5 MW, so the requirement becomes 105.5 MW. Midnight
remains 5 MW because no hydro quantity was supplied for that hour.

Match the literal `hydro` label exactly on both sides. An unmatched kind is
dropped by the inner factor join. It is not matched by spelling similarity or
assigned an automatic zero fraction.

If your new source has several rows per output key, aggregate it in its
preparation table before the final projection. If its units differ, convert them
upstream before concatenating quantities that will be summed.

## Diagnose an unexpected result

Inspect the named intermediate table immediately before the unexpected change.

| Symptom | Check |
| --- | --- |
| A category disappears | Exact category and factor labels, plus every inner join key. |
| Totals are unexpectedly multiplied | Duplicate matches on the right or a missing year, region, or product key. |
| A new source cannot concatenate | Matching output names and compatible column types in its final projection. |
| Product metadata becomes measurement rows | Explicit `unpivot.columns` and `index`, not an assumption about every remaining column. |
| Missing requested periods | The grid inputs, rather than just the observation timestamps. |
| Unknown prices appear as zero costs | Missing price matches, nulls before aggregation, and any `fill_null` policy. |
| Values are correct but attachment fails | Owner names, metadata partitions, and the parser's time axis requirements. |

For null, availability, and duplicate behavior, use the
[table mapping reference](/r2x-core/references/table-mapping/).
