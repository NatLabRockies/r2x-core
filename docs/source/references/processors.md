# Data Processors

<span id="multi-row-csvtsv-headers"></span>

`DataFile.proc_spec` is a discriminated union of `TabularProcessing` and
`JSONProcessing`. Each model contains an ordered `steps` list. The `kind` field
is set by the model and serialized as `"tabular"` or `"json"` so file mappings
can validate the union directly.

A tabular backend receives a `TabularProcessing` instance and executes each
step in list order. The default Polars backend operates on `LazyFrame` values.
JSON processing uses the injected `JSONProcessor`. A file format must match the
processing kind: table formats use tabular processing, and JSON uses JSON
processing. XML does not support declarative processing.

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

## Backend interfaces

`TabularBackend` processes an application-defined frame type. A custom backend
implements `supports_data` and `process`. Implement the separate
`MappingStepBackend` protocol when it also needs to support the public
`apply_mapping_steps` runner.

A custom `JSONProcessor` implements `process` and receives JSON-compatible
values. `DataReader(json_processor=...)` injects it without requiring the
Polars backend.

See {py:class}`~r2x_core.TabularProcessing`,
{py:class}`~r2x_core.JSONProcessing`,
{py:class}`~r2x_core.TabularBackend`, and
{py:class}`~r2x_core.json_adapter.JSONProcessor` for API contracts.
