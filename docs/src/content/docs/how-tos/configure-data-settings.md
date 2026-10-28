---
title: "Configuring Data Settings"
---

## Configuring data settings

`file_mapping.json` is an array of `DataFile` records. Metadata is nested under
`info`, reader selection and options under `reader`, and processing uses a
tagged `proc_spec` with ordered steps.

```json
[
  {
    "name": "generators",
    "relative_fpath": "gen_data.csv",
    "proc_spec": {
      "kind": "tabular",
      "steps": [
        {"op": "filter_columns", "filter_by": {"status": "active"}}
      ]
    }
  },
  {
    "name": "profiles",
    "relative_fpath": "load.h5",
    "reader": {
      "format": "hdf5",
      "options": {"data_key": "data", "columns_key": "columns"}
    },
    "info": {"file_type": "time_series", "requirement": "optional"}
  }
]
```

`file_type` describes content semantics; it does not restrict the physical
format or whether an output instruction can use the decoded source.
`requirement` is `required` by default. An explicit `reader.format` selects a
symbolic registration. Built-in and application readers validate their own
options.

### Load a mapping

`DataStore` manages validated mapping configuration. Use `load_file_mapping`
to read JSON; use `DataReader` for source loading or `build_system` for
configured construction and attachment.

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from r2x_core import DataFile, DataStore
>>> with TemporaryDirectory() as directory:
...     root = Path(directory)
...     mapping = root / "file_mapping.json"
...     _ = mapping.write_text(
...         '[{"name":"generators","relative_fpath":"generators.csv"}]',
...         encoding="utf-8",
...     )
...     store = DataStore(root)
...     store.load_file_mapping(mapping)
...     store.list_data()
['generators']
```

A record accepts exactly one path source: `fpath`, `relative_fpath`, or `glob`.
A glob must contain a wildcard and resolve to one file at read time. Placeholder
substitution and path availability are execution-time behavior.

Physical inputs may declare native columns, optional output renames, and a
strict `required` boolean (default `true`). These records provide the typed
schema for a missing optional input and distinguish a missing optional column
inside a present file:

```json
{
  "name": "optional_profile",
  "relative_fpath": "profile.csv",
  "info": {"requirement": "optional"},
  "columns": [
    {"name": "year", "dtype": "int64"},
    {"name": "value", "dtype": "float64", "rename": "load_mw", "required": false}
  ]
}
```

Missing required names in a present file are errors. A missing `required: false`
column becomes a typed null field without changing the file's rows. Present
columns are cast strictly and renamed before configured processing. Floating-
point columns declared as `int64` are rejected rather than truncated. Supported
types are `bool`, `int64`, `float64`, `string`, and `datetime`. Other columns in
a present table remain available with reader-provided types. If this optional
input file is missing, core retains its declared typed schema while marking the
source absent. Without `columns`, a missing optional file remains omitted.
Neither absence case creates rows.

See [Read data files](/r2x-core/how-tos/read-data-files/),
[Build a parser](/r2x-core/how-tos/build-parsers/), and the
[processor reference](/r2x-core/references/processors/).
