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

### Common operations

- `filter_columns` retains rows that match every exact column-value condition.
- `filter` retains rows matching a mapping-expression predicate.
- `select_columns` keeps named columns; `select` derives columns from expressions.
- `rename_columns` renames columns, and `drop_columns` removes them.
- `with_columns` adds or replaces columns using expressions.
- `lowercase` lowercases column names and string values when enabled.
- `unpivot` names identifier columns explicitly. `unpivot_columns` names value
  columns and keeps all other columns as identifiers. Both default output names
  are `variable` and `value`.
- `split_columns` splits strings using a one-character separator and distinct
  output column names.
- `replace_values`, `strip_characters`, `cast_columns`, `scale_columns`, and
  `fill_null` clean or convert values.
- `aggregate` groups optionally and applies aggregation functions to columns.
  Aggregation without `group_by` returns one row.
- `pivot` uses `pivot_on` as the output-column key, `group_by` as identifiers,
  and `aggregate_on` as value columns. All value columns use one aggregation.
  Pivot supports `count`, `first`, `last`, `max`, `mean`, `median`, `min`, and
  `sum`. Null pivot keys are rejected.
- `group_by` computes named aggregate expressions.
- `sort` maps each column to `asc` or `desc`; `unique` removes duplicate rows
  based on its `subset`.
- `assert`, `join`, and `custom` provide predicate checks, named-frame joins,
  and application-registered handlers through the mapping-step backend.

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
values, replace scalar values, or select object keys. The concrete step model
rejects fields that do not belong to that operation.

## Reader and processor contracts

A custom `FileReader` implements `read_file(format_name, /, *, file_path,
reader_config)` and returns `DecodedSources`, a mapping from names to typed
sources. Output keys must be non-empty strings. `file_path` is the canonical,
resolved physical path, regardless of whether configuration used an absolute,
relative, or glob path. A `ProcessingSource[Payload]` couples a built-in payload
wrapper to its processor. An application-defined source can implement
`DecodedSource` directly and provide its own `process` implementation.

For native table representations, implement `TabularProcessor[Payload]` with
`process`, `column_names`, `iter_rows`, and `values`. Do not add a second
format-specific processor dispatcher. The separate `MappingStepBackend`
protocol remains the execution contract for `apply_mapping_steps` and ordered
mapping operations.

See {py:class}`~r2x_core.DecodedSource`,
{py:class}`~r2x_core.SourceProcessor`,
{py:class}`~r2x_core.TabularProcessor`,
{py:class}`~r2x_core.ProcessingSource`,
{py:class}`~r2x_core.TabularProcessing`, and
{py:class}`~r2x_core.JSONProcessing`.
