# Data Processors

<span id="multi-row-csvtsv-headers"></span>

`DataFile.proc_spec` is a discriminated union of `TabularProcessing` and
`JSONProcessing`. Each model contains an ordered `steps` list. The `kind` field
is set by the model and serialized as `"tabular"` or `"json"` so file mappings
can validate the union directly.

Processing is paired with the decoded payload through the public
`SourceProcessor[Payload]` contract. `TabularProcessor[Payload]` adds native
table field, row, and value access. `PolarsTabularBackend` processes Polars
`LazyFrame` values, while `JSONProcessingBackend` processes JSON values.
Representation compatibility is decided by the paired processor, not the file
extension. Requested unsupported operations return explicit errors. With no
requested steps, `DataReader` passes the decoded source through unchanged.

## Tabular processing

Core requires Polars `>=1.44.1,<2.0.0`. Earlier releases can return an incorrect
row count when projection pushdown follows a cross join with a scalar aggregate
([Polars #28729](https://github.com/pola-rs/polars/issues/28729), fixed by
[#28751](https://github.com/pola-rs/polars/pull/28751)). Version 1.44.0 contains
the fix but is yanked, so 1.44.1 is the earliest safe release.

Create a step list with the operation-specific fields:

```python
from r2x_core import TabularProcessing

processing = TabularProcessing(
    steps=[
        {"op": "rename_columns", "column_mapping": {"old_name": "name"}},
        {"op": "filter_columns", "filter_by": {"region": "North"}},
        {"op": "sort", "by": {"year": "asc"}},
    ]
)
```

Operations can also be expressed with model classes from `r2x_core.models`.
The tagged dictionaries are useful in JSON file mappings. Unknown fields and
invalid operation fields are rejected during model validation.

Expression values use a compact recursive form: a bare string names an exact
column, numbers, booleans, and null are literals, and `{"literal": "text"}`
represents a string literal. The explicit `literal` wrapper still accepts a
JSON scalar, which is useful when a placeholder resolves to a typed value. An
operation is a single-key map whose value is its ordered argument list. The
step object itself keeps its existing `op` key:

```json
{
  "op": "with_columns",
  "columns": {
    "doubled": {"multiply": ["capacity", 2]},
    "label": {"literal": "wind"}
  }
}
```

`{"optional_column": "field"}` reads the named column when present and
produces null when it is absent. `{"values": [...]}` supplies a typed
membership list. Literal and list placeholders are substituted before the
processing model is validated again. Date expressions include `year` and
`month`, which extract calendar fields from a date or datetime column, and
`strftime`, which formats one with a literal Polars/Chrono format string.

### Common operations

- `filter_columns` retains rows that match every exact column-value condition.
- `filter` retains rows matching a mapping-expression predicate.
  Configured column names are resolved literally, including names such as
  `^load$`, `*`, or names containing quotes. Pattern-shaped names are not
  regular expressions.
- `select_columns` keeps named columns; `select` derives columns from expressions.
- `rename_columns` renames columns, and `drop_columns` removes them.
- `with_columns` adds or replaces columns using expressions. Expressions include
  exact `eq`/`neq`, expression-based `starts_with`, binary `add`, and `repeat_by`
  for creating lists from row values and per-row counts. `month`, `year`, and
  `strftime` extract or format date and datetime values.
- `explode` expands one or more list columns into rows. Empty lists produce no
  rows, and null lists retain one null element. These semantics are explicit
  across the supported Polars versions.
- `lowercase` lowercases column names and string values when enabled.
- `unpivot` names identifier columns explicitly. `unpivot_columns` names value
  columns and keeps all other columns as identifiers. Both default output names
  are `variable` and `value`. Without `value_type_name`, Polars chooses a common
  value type. This can convert numbers to strings or booleans to integers. The
  table-mapping `unpivot` instead requires compatible declared types.
  `unpivot` may also declare `value_type_name` to add a backend-neutral logical
  type column. In that mode, values are cast to
  strings and the type column uses `bool`, `int64`, `float64`, `string`, or
  `datetime`. Null values remain null, and typed empty inputs retain the output
  schema. Other and non-scalar source dtypes are errors.
- `split_columns` splits strings using a one-character separator and distinct
  output column names.
- `cast_columns` converts columns to the configured types. Its `float_to_int`
  policy defaults to `truncate`, which discards fractional parts toward zero.
  Core logs a warning for this conversion when `r2x_core` logging is enabled.
  Library logging is disabled by default. Enable it with
  `loguru.logger.enable("r2x_core")` in the application.
  Set it to `reject` to reject float columns when casting to an integer type.
  Native input-column declarations always reject float-to-integer conversion.
- `replace_values`, `strip_characters`, `scale_columns`, and `fill_null` clean
  or convert values.
- `aggregate` groups optionally and applies aggregation functions to columns.
  Aggregation without `group_by` returns one row. Mapping expressions also
  support the full aggregation vocabulary listed below, with one operand each.
- `pivot` uses `pivot_on` as the output-column key, `group_by` as identifiers,
  and `aggregate_on` as value columns. All value columns use one aggregation.
  Pivot supports `count`, `first`, `last`, `max`, `mean`, `median`, `min`, and
  `sum`. Null pivot keys are rejected.
- `group_by` computes named aggregate expressions.
- `sort` maps each column to `asc` or `desc`; `unique` removes duplicate rows
  based on its `subset`.
- `assert` can include a configured failure message. `concat` appends explicit
  prior named sources using strict vertical schema equality. `join` combines
  named frames, and `custom` invokes application-registered handlers through
  the mapping-step backend. Cross joins omit `on` and allow only default or
  `m:m` validation.

`match_source_patterns` is a distinct source-backed operation. It selects one
best right-side record for each matching left value. Static `match_patterns`
retains its existing group semantics. The source-backed form requires explicit
range and prefix syntax, priority, tie, and unmatched policies:

```json
{
  "op": "match_source_patterns",
  "column": "asset_id",
  "source": "asset_patterns",
  "pattern_column": "pattern",
  "range_separator": "..",
  "prefix_separator": ".",
  "precedence": ["exact", "range", "prefix"],
  "prefix_policy": "longest",
  "duplicate_policy": "first",
  "unmatched": "keep",
  "case_sensitive": false
}
```

The left and pattern columns must be strings. A pattern containing
`range_separator` is a numeric-suffix range and must contain it exactly once.
It has the form `prefix{first}separatorprefix{last}`. Both endpoints have a
non-negative decimal suffix and MUST share the same literal prefix. The
endpoints define an inclusive numeric range. The Polars backend collects distinct
pattern values during assembly to reject malformed or reversed ranges, even for
an empty left input. A pattern without the range separator
can match as exact text or as a prefix followed by the configured
`prefix_separator`. `precedence` lists `exact`, `range`, and `prefix` once each,
in selection order. `prefix_policy` chooses the longest matching prefix or the
first matching prefix in source order. `duplicate_policy` chooses the first or
last source record when candidates otherwise tie. `unmatched` either preserves
the left row with typed null payloads or drops it. In case-insensitive mode,
this operation uses full Unicode casefold for input values, patterns, and
separators. Static `match_patterns` uses Unicode lowercase instead.

The source must be declared earlier. Every right-source column except
`pattern_column` is appended, and payload collisions are errors. Null left
values and null patterns never match. Left duplicates and row order are
preserved when `unmatched` is `keep`. Pattern syntax errors are rejected even
when the left input is empty.

Aggregation functions are `count`, `first`, `last`, `max`, `mean`, `median`,
`min`, `n_unique`, `std`, `sum`, and `var`. Pivot does not support `n_unique`,
`std`, or `var`. `scale_columns` requires numeric columns and finite factors.
Placeholders are substituted before execution and the resulting spec is
validated again.

### Ordered reshape example

```python
from r2x_core import TabularProcessing

processing = TabularProcessing(
    steps=[
        {"op": "unpivot_columns", "columns": ["2025", "2030"]},
        {"op": "rename_columns", "column_mapping": {"variable": "year"}},
        {"op": "cast_columns", "column_schema": {"year": "int"}},
        {"op": "filter_columns", "filter_by": {"year": "{solve_year}"}},
    ]
)
```

## JSON processing

JSON specs have their own ordered operations:

```python
from r2x_core import JSONProcessing

processing = JSONProcessing(
    steps=[
        {"op": "rename_keys", "mapping": {"old_name": "name"}},
        {"op": "drop_keys", "keys": ["internal_id"]},
        {"op": "filter", "where": {"status": "active"}},
        {"op": "select_keys", "keys": ["name", "status"]},
    ]
)
```

JSON operations recursively rename and drop keys, filter records by exact
values, replace scalar values, or select object keys. JSON replacement sources
use a list of typed `old`/`new` records rather than a dictionary, so JSON
round-trips preserve scalar types:

```python
from r2x_core import JSONProcessing

processing = JSONProcessing(steps=[
    {"op": "replace_values", "replacements": [
        {"old": 0, "new": "missing"},
        {"old": True, "new": "enabled"},
    ]},
])
```

Matching is recursive. Booleans are distinct from numbers, numerically equal
integers and floats compare equally, and strings do not coerce to numbers.
Filters require the tested key to exist, including when matching `null`.
Duplicate matching replacement sources and non-finite replacement numbers are
rejected. The concrete step model rejects fields that do not belong to that
operation.

## Reader and processor contracts

A custom `FileReader` implements `read_file(format_name, /, *, file_path,
reader_config)` and returns `DecodedSources`, a mapping from names to typed
sources. Output keys must be non-empty strings. `file_path` is the resolved physical
path, regardless of whether configuration used an absolute,
relative, or glob path. Declared native columns are available through the
optional `reader_config.columns` field. A `ProcessingSource[Payload]` couples a built-in payload
wrapper to its processor. An application-defined `DecodedSource` implements
`fields`, `is_empty`, `iter_rows`, `values`, and `process`. `is_empty` must agree
with whether `iter_rows` yields a record.

For native table representations, implement `TabularProcessor[Payload]` with
`process`, `column_names`, `is_empty`, `iter_rows`, and `values`. `is_empty`
checks whether records exist without collecting a complete table. Do not add a
second format-specific processor dispatcher. The separate `MappingStepBackend`
protocol remains the execution contract for `apply_mapping_steps` and ordered
mapping operations.

See {py:class}`~r2x_core.DecodedSource`,
{py:class}`~r2x_core.SourceProcessor`,
{py:class}`~r2x_core.TabularProcessor`,
{py:class}`~r2x_core.ProcessingSource`,
{py:class}`~r2x_core.TabularProcessing`, and
{py:class}`~r2x_core.JSONProcessing`.
