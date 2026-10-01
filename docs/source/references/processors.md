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

The pipeline starts with optional lowercasing and `drop_columns`. The remaining
order depends on the reshape:

- With `unpivot_on`: unpivot, split columns, replace values, strip strings,
  rename columns, cast, scale, fill nulls, filter, aggregate, deduplicate, sort,
  select.
- Without `unpivot_on`: split columns, rename, replace values, strip strings,
  cast, scale, fill nulls, filter, optional `pivot_on`, aggregate, deduplicate,
  sort, select.

References are validated against the columns available at each step. Processing
validation errors are returned as `Err` by `apply_processing`; `DataReader`
raises a `ReaderError` with the processing failure.

## Wide-to-long and long-to-wide

`unpivot_on` is the explicit wide-to-long operation. Listed columns become
values, remaining columns stay as identifiers, and the generated columns are
named `variable` and `value`:

```python
from r2x_core import DataFile, TabularProcessing

processing = TabularProcessing(
    unpivot_on=["2025", "2030"],
    column_mapping={"variable": "year", "value": "capacity_mw"},
    column_schema={"year": "int"},
    filter_by={"year": "{solve_year}"},
)
file_spec = DataFile(name="capacity", relative_fpath="capacity.csv", proc_spec=processing)
```

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

`group_by` requires `aggregate_on`. Aggregation without `group_by` produces one
aggregate row. General aggregation functions are `count`, `first`, `last`,
`max`, `mean`, `median`, `min`, `n_unique`, `std`, `sum`, and `var`.

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
