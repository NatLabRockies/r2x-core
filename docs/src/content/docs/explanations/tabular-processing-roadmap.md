---
title: "Ordered Processing"
description: "How tabular and JSON processing specs preserve declared operation order."
---

`TabularProcessing` and `JSONProcessing` are strict configuration models with
ordered, tagged steps. Every operation runs in the order declared by its `steps`
list. There is no hidden branch that changes the order based on the selected
operations.

## Tabular processing

A tabular spec contains `MappingStep` variants such as `filter`,
`rename_columns`, `unpivot_columns`, `aggregate`, `sort`, and `unique`. Each step
validates its own inputs and is executed by the `SourceProcessor` paired with
the decoded payload. `PolarsTabularBackend` implements the built-in tabular
operations. Applications can register another typed reader and processor pair
for their native representation.

```python doctest
>>> from r2x_core import TabularProcessing
>>> processing = TabularProcessing(steps=[
...     {"op": "unpivot_columns", "columns": ["2025", "2030"]},
...     {"op": "rename_columns", "column_mapping": {"variable": "year"}},
...     {"op": "sort", "by": {"year": "asc"}},
... ])
>>> [step.op for step in processing.steps]
['unpivot_columns', 'rename_columns', 'sort']
```

The JSON `kind` tag is `"tabular"` and is filled by the model when omitted.
Serialized file mappings include the tag so `FileProcessing` can validate the
union without guessing the schema.

## JSON processing

`JSONProcessing` uses a separate set of steps for JSON values, including
`rename_keys`, `drop_keys`, `filter`, `replace_values`, and `select_keys`.
Its `kind` tag is `"json"`.

```python doctest
>>> from r2x_core import JSONProcessing
>>> processing = JSONProcessing(steps=[
...     {"op": "rename_keys", "mapping": {"old": "new"}},
...     {"op": "select_keys", "keys": ["new"]},
... ])
>>> [step.op for step in processing.steps]
['rename_keys', 'select_keys']
```

## Validation and execution

Strict models reject unknown fields, and each tagged step has a closed schema.
For example, column renaming and filtering are separate operations rather than
optional fields whose interaction depends on a global execution order.
Expected `ValueError` and Polars failures remain `Result` errors with their
causes. `DataReader` chains `ReaderError` from them. Callback `TypeError` and
other programming defects propagate unchanged.

See the [processor reference](/r2x-core/references/processors/) for the
supported steps and [custom readers and backends](/r2x-core/how-tos/custom-readers-and-backends/)
for the reader and typed processor contracts.
