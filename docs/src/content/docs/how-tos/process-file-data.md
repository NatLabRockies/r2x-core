---
title: "Processing File Data"
---

<span id="processing-file-data"></span>

Tabular and JSON transformations are declared as ordered steps in
`DataFile.proc_spec`. Every step has an `op` tag and only the fields used by
that operation.

## Rename, remove, and filter columns

```python doctest
>>> from r2x_core import DataFile, TabularProcessing
>>> processing = TabularProcessing(steps=[
...     {"op": "rename_columns", "column_mapping": {"old_name": "new_name"}},
...     {"op": "drop_columns", "drop_columns": ["temp_col"]},
...     {"op": "filter_columns", "filter_by": {"year": 2030}},
... ])
>>> data_file = DataFile(name="data", relative_fpath="data.csv", proc_spec=processing)
>>> [step.op for step in data_file.proc_spec.steps]
['rename_columns', 'drop_columns', 'filter_columns']
```

`filter_columns` matches exact values in every listed column. Use the
expression-based `filter` operation when a predicate needs a comparison or
combination that exact matching cannot express.

## Order reshape and column operations explicitly

A wide-to-long step selects value columns. All other columns remain as
identifiers. The following steps can then rename and cast the generated fields
before filtering:

```python doctest
>>> from r2x_core import TabularProcessing
>>> processing = TabularProcessing(steps=[
...     {"op": "unpivot_columns", "columns": ["2025", "2030"]},
...     {"op": "rename_columns", "column_mapping": {"variable": "year", "value": "capacity_mw"}},
...     {"op": "cast_columns", "column_schema": {"year": "int"}},
...     {"op": "filter_columns", "filter_by": {"year": "{solve_year}"}},
... ])
>>> [step.op for step in processing.steps]
['unpivot_columns', 'rename_columns', 'cast_columns', 'filter_columns']
```

Use `unpivot` when the identifier columns should be specified explicitly. Use
`unpivot_columns` when every column not listed in `columns` should be retained
as an identifier.

For combined labels, `split_columns` splits a named string column using a
single-character separator:

```python doctest
>>> from r2x_core import SplitColumnSpec
>>> split = SplitColumnSpec(separator="|", into=["year", "zone"])
>>> split.model_dump()
{'separator': '|', 'into': ['year', 'zone']}
```

## Normalize formatted numeric values

Use ordered steps to replace tokens, remove literal characters, cast, and
scale. The example shows the configuration; the processor reference documents
value-family validation and supported aggregation functions.

```python doctest
>>> from r2x_core import TabularProcessing
>>> processing = TabularProcessing(steps=[
...     {"op": "replace_values", "replace_values": {"-": "0"}},
...     {"op": "strip_characters", "strip_chars": {"price": ["$"], "share": ["%"]}},
...     {"op": "cast_columns", "column_schema": {"price": "float", "share": "float"}},
...     {"op": "scale_columns", "scale": {"share": 0.01}},
... ])
>>> [step.op for step in processing.steps]
['replace_values', 'strip_characters', 'cast_columns', 'scale_columns']
```

`lowercase` changes column names and string values when enabled. Place it first
if later steps use lowercase column names:

```python doctest
>>> from r2x_core import TabularProcessing
>>> processing = TabularProcessing(steps=[
...     {"op": "lowercase", "lowercase": True},
...     {"op": "select_columns", "select_columns": ["name"]},
... ])
>>> [step.op for step in processing.steps]
['lowercase', 'select_columns']
```

## Use placeholders

Whole-value placeholders preserve their type. For example, placeholders can
supply a boolean to `lowercase`, a number to `scale_columns`, or a filter value.
They are validated again after substitution. Unknown names return a processing
error.

```python doctest
>>> from r2x_core import TabularProcessing
>>> processing = TabularProcessing(steps=[
...     {"op": "filter_columns", "filter_by": {"year": "{solve_year}"}},
...     {"op": "scale_columns", "scale": {"capacity": "{scale_factor}"}},
... ])
>>> [step.op for step in processing.steps]
['filter_columns', 'scale_columns']
```

`fpath`, `relative_fpath`, and `glob` path sources also support placeholders.
`DataReader` resolves them when `read_data_file` or `DataStore.read_data` is
called with a `placeholders` mapping.

## Process a Polars frame directly

```python doctest
>>> import polars as pl
>>> from r2x_core import DataFile, TabularProcessing
>>> from r2x_core.polars_adapter import PolarsTabularBackend
>>> backend = PolarsTabularBackend()
>>> result = backend.process(
...     pl.LazyFrame({"NAME": ["ALPHA"]}),
...     data_file=DataFile(name="example", relative_fpath="example.csv"),
...     proc_spec=TabularProcessing(steps=[{"op": "lowercase", "lowercase": True}]),
... )
>>> result.is_ok()
True
>>> result.value.collect().to_dicts()
[{'name': 'alpha'}]
```

See the [processor reference](/r2x-core/references/processors/) for the full
step vocabulary and JSON processing contract.
