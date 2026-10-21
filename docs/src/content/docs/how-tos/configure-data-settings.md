---
title: "Configuring Data Settings"
---

<span id="configuring-data-settings"></span>

`DataStore` loads an array of `DataFile` records from JSON. File metadata is
nested under `info`, and processing settings use a tagged `proc_spec` with
ordered steps.

## Define file records

```python doctest
>>> config = [
...     {
...         "name": "generators",
...         "relative_fpath": "gen_data.csv",
...         "info": {"description": "Generator capacity", "units": "MW"},
...     },
...     {
...         "name": "loads",
...         "relative_fpath": "load_data.csv",
...         "info": {"file_type": "time_series", "requirement": "optional"},
...         "proc_spec": {
...             "kind": "tabular",
...             "steps": [
...                 {"op": "filter_columns", "filter_by": {"year": 2030}}
...             ],
...         },
...     },
... ]
>>> config[1]["proc_spec"]["steps"][0]["op"]
'filter_columns'
```

`file_type` describes static versus time-series content. `requirement`
controls whether a missing input is skipped. The physical format is inferred
from the file extension and is not configured as `file_type`.

## Load configuration into a DataStore

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> import json
>>> from r2x_core import DataStore
>>> with TemporaryDirectory() as directory:
...     root = Path(directory)
...     gen_path = root / "gen_data.csv"
...     _ = gen_path.write_text("name,capacity\nGen1,100\n", encoding="utf-8")
...     config_path = root / "data_config.json"
...     _ = config_path.write_text(
...         json.dumps([{"name": "generators", "fpath": str(gen_path)}]),
...         encoding="utf-8",
...     )
...     store = DataStore.from_json(config_path, path=root)
...     store.list_data()
['generators']
```

## Record fields

A file record accepts one path source: `fpath`, `relative_fpath`, or `glob`.
Optional metadata belongs in `info`, for example:

- `description`: human-readable context.
- `file_type`: `static` or `time_series`.
- `requirement`: `required` or `optional`.
- `units`: units for single-column data.

A tabular `proc_spec` has `kind: "tabular"` and an ordered `steps` list. A JSON
`proc_spec` has `kind: "json"` and JSON-specific steps. See the
[processor reference](/r2x-core/references/processors/) for supported
operations and examples.

## See also

- [Manage datastores](/r2x-core/how-tos/manage-datastores/)
- [Read data files](/r2x-core/how-tos/read-data-files/)
- [Process file data](/r2x-core/how-tos/process-file-data/)
- [`DataStore`](/r2x-core/references/api/)
- [`DataFile`](/r2x-core/references/api/)
