# Data Processors

`DataReader` applies `TabularProcessing` to Polars `LazyFrame` inputs after a
file is read. Operations remain lazy where Polars supports lazy execution. A
long-to-wide `pivot_on` performs a small discovery collection of distinct pivot
keys because Polars needs those output column names before constructing its lazy
pivot plan. `DataFile` validates processing settings against the file format:
tabular formats require `TabularProcessing`, JSON requires `JSONProcessing`,
and unknown fields are rejected. XML files do not support declarative processing.

## Case handling and operation order

Column names and string values retain their original case by default. Set
`lowercase=True` to lowercase both before applying other operations. When enabled,
configuration column names and string values must use lowercase too.

The pipeline starts with optional lowercasing and `drop_columns`, then applies
`copy_columns` before any split or reshape operation. A copy maps source names to
new output names, requires every source column, and cannot overwrite an existing
column. `ensure_null_columns` runs after renaming and literal additions, before
casting and fills. The remaining order depends on the reshape:

- With `unpivot_on`: unpivot, split, replace, strip, rename, add literals,
  `ensure_null_columns`, cast, scale, `safe_divide`, null fills, `filter_by`,
  `column_add`, ordered `conditional_assignments`, `filter_rows`, `reject_rows`,
  aggregate, deduplicate, sort, select.
- Without `unpivot_on`: split, rename, add literals, `ensure_null_columns`,
  replace, strip, cast, scale, `safe_divide`, null fills, `filter_by`,
  `column_add`, ordered `conditional_assignments`, `filter_rows`, `reject_rows`,
  optional `pivot_on`, aggregate, deduplicate, sort, select.

`drop_columns_after` runs after the other processing stages. `filter_rows` keeps
rows matching all configured typed predicates after column additions and
conditional assignments. Predicates support null checks and `is_nan` for
floating-point columns. The `in` operator accepts a literal list or a complete
placeholder that resolves to a list. An empty list is a valid set predicate and
matches no rows. Placeholder results are revalidated before execution. `reject_rows`
reports an error if any row matches its predicates.

References are validated against the columns available at each step. Processing
validation errors are returned as `Err` by `apply_processing`; `DataReader`
raises a `ReaderError` with the processing failure.

## Wide-to-long and long-to-wide

`unpivot_on` is the explicit wide-to-long operation. A list selects value
columns, `"all"` selects every column, and `{"all_except": [...]}` selects all
columns except the listed identifiers. Unselected columns stay as identifiers,
and the generated columns are named `variable` and `value`:

```python
from r2x_core import DataFile, TabularProcessing

processing = TabularProcessing(
    unpivot_on=["2025", "2030"],
    column_mapping={"variable": "year", "value": "capacity_mw"},
    column_schema={"year": "int"},
    filter_by={"year": "{solve_year}"},
)
file_spec = DataFile(name="capacity", relative_fpath="capacity.csv", proc_spec=processing)

fom_processing = TabularProcessing(
    unpivot_on={"all_except": ["technology"]},
    column_mapping={"variable": "year", "value": "fom_cost"},
    column_schema={"year": "int", "fom_cost": "float"},
)
```

Use `unpivot_on="all"` when every column contains a value and there are no
identifier columns. For a headerless CSV, configure the reader with
`ReaderConfig(kwargs={"has_header": False})`, then unpivot all columns.

For generated compound labels, `split_column` splits a column on a literal
separator before rename, cast, and filter operations:

```python
processing = TabularProcessing(
    unpivot_on=["2025|NYISO_A", "2030|NYISO_A"],
    split_column={"variable": {"separator": "|", "into": ["year", "zone"]}},
    column_schema={"year": "int"},
    filter_by={"year": "{solve_year}"},
)
```

`pivot_on` is the explicit long-to-wide operation. Its value must name an input
column; a missing column is an error. `group_by` supplies identifier columns,
`aggregate_on` supplies value columns and their aggregation function, and
missing `group_by` infers identifiers from remaining columns. Pivoting rejects
null keys. Pivot aggregations support `count`, `first`, `last`, `max`, `mean`,
`median`, `min`, and `sum`. Configurations that used `pivot_on` to stack wide
columns must instead set `unpivot_on` to the value columns.

`ensure_null_columns` adds a null-valued column only when its input is absent.
Use it for optional aggregate inputs. It does not replace existing values.

`group_by` requires `aggregate_on` or `weighted_mean`. Aggregation without
`group_by` produces one aggregate row. General aggregation functions are `count`,
`first`, `last`, `max`, `mean`, `median`, `min`, `n_unique`, `std`, `sum`, and
`var`. `weighted_mean` names a value column, its `weight_column`, and policies
for unknown values with positive weight, null weights, and nonpositive total
weight. These policies distinguish an unknown value from a known zero.

```python
processing = TabularProcessing(
    group_by=["technology", "region"],
    ensure_null_columns=["fom_cost", "heat_rate"],
    weighted_mean={
        "fom_cost": {
            "weight_column": "capacity",
            "unknown_positive_weight": "propagate",
            "null_weight": "ignore",
            "nonpositive_total": "null",
        }
    },
)
```

## Cleaning formatted numeric strings

Use `replace_values` for exact tokens, `strip_chars` for literal strings to
remove, `column_schema` to cast, and `scale` for unit conversion. `strip_chars`
also trims surrounding whitespace.

```python
processing = TabularProcessing(
    replace_values={"-": "0"},
    strip_chars={"limit": [","], "price": ["$"], "share": ["%"]},
    column_schema={
        "limit": "float",
        "price": "float",
        "share": "float",
        "count": "float",
    },
    scale={"share": 0.01},
)
```

This converts values such as `2,450`, `$4.99 `, `171.20%`, and `-` to numeric
values, with the percent column scaled to a fraction. `scale` is applied after
casting and requires numeric columns.

## Column calculations, conditional assignment, and null fallback

`safe_divide` adds named Float64 columns using a numerator and denominator from
the current table. Null numerators, null denominators, and zero denominators
produce null outputs. `fill_null_from` fills a target column from a second
column in the same row. Numeric columns with different numeric types are
compatible, and a Polars `Null`-typed column can be filled from a typed column.
`column_add` performs ordered numeric addition and propagates null inputs.
`conditional_assignments` run in list order. Each assignment uses either a typed
column source or a literal source, including an explicit null literal. A false
predicate keeps the target's current value, or leaves it null when first created.

These operations run in a fixed order after `scale`: all `safe_divide` outputs
exist before `fill_null_from` runs, so a null fill may use a calculated output.
Each stage is simultaneous and does not chain through another output from that
same stage. Output columns from `safe_divide` cannot overwrite existing columns.
Conditional assignments are sequential, so later assignments can override
values selected earlier.

```python
from r2x_core import TabularProcessing

processing = TabularProcessing(
    safe_divide={
        "line_cost_per_mile": {"numerator": "forward_cost", "denominator": "distance"}
    },
    fill_null_from={"reverse_capacity": "capacity"},
    conditional_assignments=[
        {
            "column": "rate",
            "when": [{"column": "override", "operator": "eq", "value": True}],
            "value_source": {"kind": "literal", "value": None},
        }
    ],
)
```

## Multi-row CSV/TSV headers

The built-in CSV/TSV reader can combine multiple header rows. The default
separator is `|`:

```python
from r2x_core import DataFile, ReaderConfig

file_spec = DataFile(
    name="profiles",
    relative_fpath="load_profiles.csv",
    reader=ReaderConfig(header_rows=2, header_separator="|"),
)
```

For example, the headers `2025` and `NYISO_A` become `2025|NYISO_A`. Use
`unpivot_on` and `split_column` to separate the combined label into fields.
`header_rows` applies to the built-in CSV/TSV reader, not custom reader
functions or other file formats.

## Placeholders

Placeholders can appear as whole values or inside strings in processing
settings and file paths. Whole-value placeholders preserve their type; embedded
placeholders are converted to strings. `lowercase` accepts a boolean placeholder,
and `scale` accepts numeric placeholders. Substituted values are validated
before processing. Unknown names return an error.

```python
from r2x_core import DataFile, DataStore, TabularProcessing

file_spec = DataFile(
    name="transmission",
    relative_fpath="{scenario} - New Transmission.csv",
    proc_spec=TabularProcessing(filter_by={"year": "{solve_year}"}),
)
store = DataStore(path="/data")
store.add_data([file_spec])
data = store.read_data(
    "transmission",
    placeholders={"scenario": "Reference", "solve_year": 2030},
)
```

`fpath`, `relative_fpath`, and `glob` path sources support placeholders. JSON
file mappings accept exactly one of those three path sources; `relative_fpath`
records are resolved against the configured data folder.

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
`replace_values` applies only when both values match a column's logical type
family, and casts that lose precision are skipped. Integer values may widen to
floating-point columns only when exactly representable. A `None` on either side
is allowed, but the other value must still match the column family. For example,
a boolean replacement does not become an integer replacement in numeric
columns, and string replacements skip unrelated numeric columns.

Pandas-style `set_index`, `reset_index`, and `rename_index` fields are not
supported for tabular data. Supplying these fields is rejected during
configuration validation. When updating an existing mapping, remove
`set_index` and `reset_index` because Polars treats every field as a column;
replace tabular `rename_index` with `column_mapping`. `JSONProcessing`
continues to support `rename_index` for JSON object keys.

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
