---
title: Assemble hourly reserve requirements
description: Prepare load, wind, and solar quantities, apply product factors, and build a complete hourly table for parser rules.
---

Build a table of hourly requirements for one reserve component and two solve
years. You will prepare compatible quantities, match them to product fractions,
and fill a complete output grid. The result contains six rows, including zeros
for a missing hour and a year with no observations.

Core supports the operations in the table-mapping reference. The checked-in
reserve mapping runs through `assemble_tables` or the opt-in
`build_system(..., table_mapping_path=...)` path. The seven inputs in this
walkthrough are prepared tables, so native-file preparation remains a separate
input-boundary concern.

The example uses ReEDS reserve policy. The operations are ordinary table
operations, and the same quantity/factor structure applies to other applications.
You do not need to write a custom reserve handler.

The [conformance contract](/r2x-core/references/table-mapping/#conformance-contract)
defines the exact format for both handwritten and generated mappings. In this
example, the parser consumes the table named `reserve_requirement_rows`. Keep
that exact name on its single table record, even if you rename intermediate
tables for your application.

## Prepare the example tables

Start with the seven prepared tables below. File reading, profile reshaping,
component naming, and calendar creation are upstream work. This tutorial begins
with their named table results, not with paths to native ReEDS files.

Use these application configuration values:

| Binding | Value |
| --- | --- |
| `primary_weather_year` | `2012` |
| `solve_year_rows` | `[{"solve_year": 2032}, {"solve_year": 2040}]` |

Whole-value placeholders preserve the configured type. Although written as JSON
strings, `"{primary_weather_year}"` resolves to an integer and
`"{solve_year_rows}"` resolves to a list of records, not text containing JSON.
In the `rows` constructor, `"values": "{solve_year_rows}"` therefore supplies
`[{"solve_year": 2032}, {"solve_year": 2040}]` as the `values` array.

Names and categories are strings, years are int64, and quantities and fractions
are float64. Timestamps are datetime values. They are displayed as text below.
The fractions are finite and non-null, and the product name is unique.

### Region and observations

`reserve_hierarchy` maps the input region to its transmission region:

| region | transmission_region |
| --- | --- |
| p1 | controlled |

`load_profile_rows` contains two hours of load:

| region | solve_year | datetime | weather_year | value |
| --- | ---: | --- | ---: | ---: |
| p1 | 2032 | 2012-01-01 00:00 | 2012 | 10.0 |
| p1 | 2032 | 2012-01-01 01:00 | 2012 | 10.0 |

`renewable_values` contains already scaled generation and capacity factors:

| region | solve_year | datetime | category | value | capacity_factor |
| --- | ---: | --- | --- | ---: | ---: |
| p1 | 2032 | 2012-01-01 00:00 | wind | 20.0 | 0.2 |
| p1 | 2032 | 2012-01-01 01:00 | wind | 0.0 | 0.0 |
| p1 | 2032 | 2012-01-01 00:00 | solar | 0.0 | 0.0 |
| p1 | 2032 | 2012-01-01 01:00 | solar | 100.0 | 0.5 |

`generator_owners` contains installed capacity. The 200 MW solar owner has the
profile above. The 300 MW solar owner has no profile. Owner identifiers are
omitted here because this calculation groups by region and year.

| region | solve_year | category | capacity |
| --- | ---: | --- | ---: |
| p1 | 2032 | wind | 100.0 |
| p1 | 2032 | solar | 200.0 |
| p1 | 2032 | solar | 300.0 |

### Product, component, and calendar

`reserve_products` contains the calculation fractions:

| reserve_type | load_fraction | wind_fraction | solar_fraction |
| --- | ---: | ---: | ---: |
| SPINNING | 0.3 | 0.1 | 0.2 |

`reserve_component_rows` identifies the existing component that will own the
requirement time series:

| name | transmission_region | reserve_type |
| --- | --- | --- |
| controlled_SPINNING | controlled | SPINNING |

`calendar` contains three hourly datetime values: `2012-01-01 00:00`,
`2012-01-01 01:00`, and `2012-01-01 02:00`. The last hour has no observations.
Keep it in the calendar so the output can include it.

## 1. Prepare load quantities

Define `reserve_load_quantities` from `load_profile_rows`. Join
`reserve_hierarchy` on `region`, filter `weather_year` using
`{primary_weather_year}`, and sum `value` by transmission region, solve year, and
datetime. Name the sum `quantity_mw`.

Use the table record's final `columns` map to retain the keys and quantity,
and add the literal `kind = "load"`. This map runs after `operations`. Its keys
name output fields. A string value copies a source column, while
`{"value": "load"}` supplies literal text.

Inside an operation, `columns` has that operation's meaning, such as the
right-table fields to include in a join or the keys to group by. It is not the
final output-column map.

The resulting table has these five columns:

| Column | Type |
| --- | --- |
| `datetime` | datetime |
| `kind` | string |
| `quantity_mw` | float64 |
| `solve_year` | int64 |
| `transmission_region` | string |

Expect 10 MW at each of the first two hours for `controlled`, 2032. The hierarchy
join runs before the filter because that is their order in `operations`.

## 2. Prepare wind quantities

Define `reserve_wind_quantities` from `renewable_values`. Join the hierarchy,
keep `category = "wind"`, and sum `value` over the same hourly keys. Project the
same five columns and use the literal `kind = "wind"`.

Expect 20 MW at midnight and 0 MW at 01:00. Do not multiply `value` by installed
capacity again, because the prepared source already contains generation in MW.

## 3. Prepare installed solar capacity

Define `reserve_solar_capacity` from `generator_owners`. Join the hierarchy,
keep solar owners, and sum `capacity` by transmission region and solve year into
`quantity_mw`. This table has no hourly key.

Expect one 500 MW row for `controlled`, 2032. Include the owner without a profile.
Restricting capacity to owners found in `renewable_values` would incorrectly
produce 200 MW.

## 4. Keep active solar hours

Define `reserve_solar_quantities` from `renewable_values`. Join the hierarchy,
keep solar rows, and calculate the maximum `capacity_factor` for each combination
of `transmission_region`, `solve_year`, and `datetime`. Name that aggregate
`max_cf`.

Filter `max_cf` with `greater_than` and value zero. Join the retained hours to
`reserve_solar_capacity` on transmission region and solve year. Project the five
quantity columns and add the literal `kind = "solar"`.

Expect one 500 MW quantity at 01:00 and no solar row at midnight. The capacity
factor selects active hours. It does not scale the installed capacity. The
quantity is therefore 500 MW, not 250 MW or the 100 MW generation value.

This requirement policy is separate from reserve-provider eligibility. Excluding
solar from provider membership does not remove its contribution to requirements.

## 5. Make the factor table

Define `reserve_factors` from `reserve_products`. Keep `reserve_type` as the
unpivot identifier. Map the three fraction columns to the labels `load`, `wind`,
and `solar`, using `kind` for the label column and `fraction` for the value.

Expect these rows:

| reserve_type | kind | fraction |
| --- | --- | ---: |
| SPINNING | load | 0.3 |
| SPINNING | solar | 0.2 |
| SPINNING | wind | 0.1 |

`"load": "load_fraction"` maps the output label to its input column explicitly.
There is no suffix stripping. Additional product metadata does not become a
factor. Calculation fractions are distinct from component metadata such as
`or_load_percentage`, `or_wind_percentage`, and `or_pv_percentage`.

## 6. Append the quantity tables

Define `reserve_quantities` with a `concat` operation listing load, wind, and
solar quantity tables in that order. Omit `source`, because `concat` constructs
the starting table.

Expect five rows for `controlled`, 2032:

| datetime | kind | quantity_mw |
| --- | --- | ---: |
| 2012-01-01 00:00 | load | 10.0 |
| 2012-01-01 01:00 | load | 10.0 |
| 2012-01-01 00:00 | wind | 20.0 |
| 2012-01-01 01:00 | wind | 0.0 |
| 2012-01-01 01:00 | solar | 500.0 |

The displayed rows also retain `transmission_region` and `solve_year`. There is
no solar row at midnight and no quantity row at 02:00. Concatenation appends
rows without matching or aggregating them.

## 7. Calculate each product's contributions

Define `reserve_contributions` from `reserve_quantities`. Inner join
`reserve_factors` on `kind`, retaining `reserve_type` and `fraction` from the
right side. Multiply `quantity_mw` by `fraction` into `contribution`.

Before grouping, expect:

| datetime | kind | quantity_mw | fraction | contribution |
| --- | --- | ---: | ---: | ---: |
| 2012-01-01 00:00 | load | 10.0 | 0.3 | 3.0 |
| 2012-01-01 01:00 | load | 10.0 | 0.3 | 3.0 |
| 2012-01-01 00:00 | wind | 20.0 | 0.1 | 2.0 |
| 2012-01-01 01:00 | wind | 0.0 | 0.1 | 0.0 |
| 2012-01-01 01:00 | solar | 500.0 | 0.2 | 100.0 |

Now group by transmission region, reserve type, solve year, and datetime, and
sum `contribution`. Expect totals of 5 MW and 103 MW. Keep `reserve_type` in the
group so additional products have separate totals.

You can check the 01:00 arithmetic independently. This Python example checks the
numbers, not execution of the JSON. Decimal arithmetic is used only to display
an exact result.

```python doctest
>>> from decimal import Decimal
>>> quantities: dict[str, Decimal] = {
...     "load": Decimal("10"), "wind": Decimal("0"), "solar": Decimal("500")
... }
>>> fractions: dict[str, Decimal] = {
...     "solar": Decimal("0.2"), "load": Decimal("0.3"), "wind": Decimal("0.1")
... }
>>> contributions: list[Decimal] = [
...     amount * fractions[kind] for kind, amount in quantities.items()
... ]
>>> contributions
[Decimal('3.0'), Decimal('0.0'), Decimal('100.0')]
>>> sum(contributions)
Decimal('103.0')
```

## 8. Construct the requested solve years

Define `solve_years` with a `rows` constructor. Declare an int64 `solve_year`
column and use `{solve_year_rows}` for its records.

Expect two rows, 2032 and 2040. The requested years come from configuration, not
from the observations. Keep 2040 even though no quantities exist for that year.

## 9. Complete the output grid

Define `reserve_requirement_rows` from `reserve_component_rows`. Cross join
`solve_years`, then the `datetime` column of `calendar`. One component, two years,
and three hours give six grid rows.

Left join `reserve_contributions` on all four matching keys: transmission region,
reserve type, solve year, and datetime. Fill a null `contribution` with zero.
Sort by `name`, `solve_year`, and `datetime`.

Finally, project `datetime`, `name`, `solve_year`, and `requirement`, copying
`contribution` into `requirement`. Expect:

| datetime | name | requirement | solve_year |
| --- | --- | ---: | ---: |
| 2012-01-01 00:00 | controlled_SPINNING | 5.0 | 2032 |
| 2012-01-01 01:00 | controlled_SPINNING | 103.0 | 2032 |
| 2012-01-01 02:00 | controlled_SPINNING | 0.0 | 2032 |
| 2012-01-01 00:00 | controlled_SPINNING | 0.0 | 2040 |
| 2012-01-01 01:00 | controlled_SPINNING | 0.0 | 2040 |
| 2012-01-01 02:00 | controlled_SPINNING | 0.0 | 2040 |

Notice that `datetime` stays on the weather-year calendar. The solve year is a
separate field. Missing observations do not remove grid rows.

## Complete configuration

Place the nine records in dependency order in `table_mapping.json`. The seven
prepared sources must be available before these records. This is the complete
configuration for the calculation above:

```json
[
  {
    "columns": {
      "datetime": "datetime",
      "kind": {
        "value": "load"
      },
      "quantity_mw": "quantity_mw",
      "solve_year": "solve_year",
      "transmission_region": "transmission_region"
    },
    "name": "reserve_load_quantities",
    "operations": [
      {
        "how": "inner",
        "on": [
          "region"
        ],
        "operation": "join",
        "source": "reserve_hierarchy"
      },
      {
        "column": "weather_year",
        "comparison": "equals",
        "operation": "filter",
        "value": "{primary_weather_year}"
      },
      {
        "aggregate": [
          {
            "column": "value",
            "operation": "sum",
            "output": "quantity_mw"
          }
        ],
        "columns": [
          "transmission_region",
          "solve_year",
          "datetime"
        ],
        "operation": "group_by"
      }
    ],
    "source": "load_profile_rows"
  },
  {
    "columns": {
      "datetime": "datetime",
      "kind": {
        "value": "wind"
      },
      "quantity_mw": "quantity_mw",
      "solve_year": "solve_year",
      "transmission_region": "transmission_region"
    },
    "name": "reserve_wind_quantities",
    "operations": [
      {
        "how": "inner",
        "on": [
          "region"
        ],
        "operation": "join",
        "source": "reserve_hierarchy"
      },
      {
        "column": "category",
        "comparison": "equals",
        "operation": "filter",
        "value": "wind"
      },
      {
        "aggregate": [
          {
            "column": "value",
            "operation": "sum",
            "output": "quantity_mw"
          }
        ],
        "columns": [
          "transmission_region",
          "solve_year",
          "datetime"
        ],
        "operation": "group_by"
      }
    ],
    "source": "renewable_values"
  },
  {
    "name": "reserve_solar_capacity",
    "operations": [
      {
        "how": "inner",
        "on": [
          "region"
        ],
        "operation": "join",
        "source": "reserve_hierarchy"
      },
      {
        "column": "category",
        "comparison": "equals",
        "operation": "filter",
        "value": "solar"
      },
      {
        "aggregate": [
          {
            "column": "capacity",
            "operation": "sum",
            "output": "quantity_mw"
          }
        ],
        "columns": [
          "transmission_region",
          "solve_year"
        ],
        "operation": "group_by"
      }
    ],
    "source": "generator_owners"
  },
  {
    "columns": {
      "datetime": "datetime",
      "kind": {
        "value": "solar"
      },
      "quantity_mw": "quantity_mw",
      "solve_year": "solve_year",
      "transmission_region": "transmission_region"
    },
    "name": "reserve_solar_quantities",
    "operations": [
      {
        "how": "inner",
        "on": [
          "region"
        ],
        "operation": "join",
        "source": "reserve_hierarchy"
      },
      {
        "column": "category",
        "comparison": "equals",
        "operation": "filter",
        "value": "solar"
      },
      {
        "aggregate": [
          {
            "column": "capacity_factor",
            "operation": "max",
            "output": "max_cf"
          }
        ],
        "columns": [
          "transmission_region",
          "solve_year",
          "datetime"
        ],
        "operation": "group_by"
      },
      {
        "column": "max_cf",
        "comparison": "greater_than",
        "operation": "filter",
        "value": 0
      },
      {
        "columns": [
          "quantity_mw"
        ],
        "how": "inner",
        "on": [
          "transmission_region",
          "solve_year"
        ],
        "operation": "join",
        "source": "reserve_solar_capacity"
      }
    ],
    "source": "renewable_values"
  },
  {
    "name": "reserve_factors",
    "operations": [
      {
        "columns": {
          "load": "load_fraction",
          "solar": "solar_fraction",
          "wind": "wind_fraction"
        },
        "index": [
          "reserve_type"
        ],
        "operation": "unpivot",
        "value_name": "fraction",
        "variable_name": "kind"
      }
    ],
    "source": "reserve_products"
  },
  {
    "name": "reserve_quantities",
    "operations": [
      {
        "operation": "concat",
        "sources": [
          "reserve_load_quantities",
          "reserve_wind_quantities",
          "reserve_solar_quantities"
        ]
      }
    ]
  },
  {
    "name": "reserve_contributions",
    "operations": [
      {
        "columns": [
          "reserve_type",
          "fraction"
        ],
        "how": "inner",
        "on": [
          "kind"
        ],
        "operation": "join",
        "source": "reserve_factors"
      },
      {
        "columns": [
          "quantity_mw",
          "fraction"
        ],
        "operation": "multiply",
        "output": "contribution"
      },
      {
        "aggregate": [
          {
            "column": "contribution",
            "operation": "sum",
            "output": "contribution"
          }
        ],
        "columns": [
          "transmission_region",
          "reserve_type",
          "solve_year",
          "datetime"
        ],
        "operation": "group_by"
      }
    ],
    "source": "reserve_quantities"
  },
  {
    "name": "solve_years",
    "operations": [
      {
        "operation": "rows",
        "schema": [
          {
            "dtype": "int64",
            "name": "solve_year"
          }
        ],
        "values": "{solve_year_rows}"
      }
    ]
  },
  {
    "columns": {
      "datetime": "datetime",
      "name": "name",
      "requirement": "contribution",
      "solve_year": "solve_year"
    },
    "name": "reserve_requirement_rows",
    "operations": [
      {
        "how": "cross",
        "operation": "join",
        "source": "solve_years"
      },
      {
        "columns": [
          "datetime"
        ],
        "how": "cross",
        "operation": "join",
        "source": "calendar"
      },
      {
        "columns": [
          "contribution"
        ],
        "how": "left",
        "on": [
          "transmission_region",
          "reserve_type",
          "solve_year",
          "datetime"
        ],
        "operation": "join",
        "source": "reserve_contributions"
      },
      {
        "columns": [
          "contribution"
        ],
        "operation": "fill_null",
        "value": 0
      },
      {
        "columns": [
          "name",
          "solve_year",
          "datetime"
        ],
        "operation": "sort"
      }
    ],
    "source": "reserve_component_rows"
  }
]
```

## Connect the output to parser rules

Add the following time-series instruction to the list in `parser_rules.json`,
not to the nine table records in `table_mapping.json`. The reserve component must
already exist when this instruction attaches its series:

```json
{
  "kind": "time_series",
  "source": "reserve_requirement_rows",
  "name": "requirement",
  "values": "requirement",
  "time_axis": {
    "kind": "column",
    "column": "datetime",
    "resolution_seconds": 3600
  },
  "metadata": {"weather_year": "{primary_weather_year}"},
  "metadata_columns": {"solve_year": "solve_year"},
  "skip_if_empty": true,
  "owners": [{"component_type": "ReEDSReserve", "name_field": "name"}]
}
```

`ReEDSReserve` is the application's model. The source table's `name` column
identifies the owner through `owners[].name_field`. The instruction's
`"name": "requirement"` names the attached time series. Its `values` field selects
the source table's `requirement` column, and `solve_year` partitions the samples
into separate metadata groups. The three hourly samples give each group a regular
time axis. `skip_if_empty` controls an empty source, not invalid nonempty data.
See [Attach time series](/r2x-core/how-tos/attach-timeseries/) for that contract.

## Continue with your application

To add a product, contributor, or year-specific coefficient, use the
[table-mapping how-to guides](/r2x-core/how-tos/adapt-table-mappings/).
For exact operation fields, defaults, and null behavior, use the
[table-mapping reference](/r2x-core/references/table-mapping/).
