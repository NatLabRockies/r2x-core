# Data Processors

`DataReader` applies `TabularProcessing` to Polars `LazyFrame` inputs after a
file is read. Operations remain lazy where Polars supports lazy execution. A
long-to-wide `pivot_on` performs a small discovery collection of distinct pivot
keys because Polars requires those output columns before constructing its lazy
pivot plan.

## Fixed tabular operation order

Operations always run in this order:

1. Lowercase column names and string values.
2. Drop columns with `drop_columns`.
3. Rename columns with `column_mapping`.
4. Replace values with `replace_values`.
5. Cast columns with `column_schema`.
6. Fill nulls with `fill_null`.
7. Filter rows with `filter_by`.
8. Reshape with `unpivot_on` or `pivot_on`.
9. Group and aggregate with `group_by` and `aggregate_on`.
10. Deduplicate with `distinct_on`.
11. Sort with `sort_by`.
12. Select final columns with `select_columns`.

Column references are checked against the schema at the point where each
operation runs. Errors identify the operation, missing columns, and available
columns. Column names in configuration should be lowercase because lowercasing
is the first operation.

## Reshaping and aggregation

`unpivot_on` is the explicit wide-to-long operation. Its listed columns become
values, all remaining columns remain identifiers, and the output columns are
`variable` and `value`:

```python
from r2x_core import DataFile, TabularProcessing

processing = TabularProcessing(
    unpivot_on=["january", "february"],
    group_by=["region", "variable"],
    aggregate_on={"value": "sum"},
    sort_by={"value": "descending"},
)
file_spec = DataFile(name="monthly", relative_fpath="monthly.csv", proc_spec=processing)
```

Aggregation runs after reshaping. `group_by` requires `aggregate_on`, and an
aggregation without `group_by` produces one aggregate row. Supported
aggregation functions are `count`, `first`, `last`, `max`, `mean`, `median`,
`min`, `n_unique`, `std`, `sum`, and `var`.

`pivot_on` is mutually exclusive with `unpivot_on`. When it names an input
column, it performs a long-to-wide pivot. `group_by` supplies identifier
columns, `aggregate_on` supplies value columns and their aggregation function,
and missing `group_by` infers identifiers from the remaining columns. When it
does not name an input column, it retains the existing compatibility behavior
and stacks all input columns into one value column named by `pivot_on`.

## Value, null, sort, and distinct operations

```python
processing = TabularProcessing(
    replace_values={"n/a": None, "west": "western"},
    fill_null={"capacity": 0},
    distinct_on=["region", "technology"],
    sort_by={"region": "asc", "capacity": "desc"},
)
```

Sort directions are `asc`, `ascending`, `desc`, and `descending`.
`replace_values` is applied to compatible columns, so a string replacement does
not fail on unrelated numeric columns.

## Placeholders

Placeholders may be used in processing values, including filters and
transformation settings:

```python
processing = TabularProcessing(
    filter_by={"year": "{solve_year}"},
    sort_by={"capacity": "{sort_direction}"},
)
store.read_data(
    "generators",
    placeholders={"solve_year": 2030, "sort_direction": "desc"},
)
```

A missing placeholder or a placeholder that resolves to an invalid operation
returns an explicit processing error. Pandas-style `set_index`, `reset_index`,
and `rename_index` fields are not supported because the public tabular result
is a Polars frame; supplying them is rejected during configuration validation.

## JSON processing

JSON processing has a separate pipeline for nested JSON values:

```python
from r2x_core import JSONProcessing

processing = JSONProcessing(
    key_mapping={"old_name": "name"},
    drop_keys=["internal_id"],
    filter_by={"status": "active"},
    select_keys=["name", "status"],
)
```

See {py:class}`~r2x_core.TabularProcessing`,
{py:class}`~r2x_core.JSONProcessing`, and
{py:func}`~r2x_core.processors.process_tabular_data` for the public API.
