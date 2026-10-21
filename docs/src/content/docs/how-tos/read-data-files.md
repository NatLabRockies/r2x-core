---
title: "Read Data Files"
---

Load and process configured inputs with `DataReader` or `DataStore`.

## Create a DataFile

A [`DataFile`](/r2x-core/references/api/) selects exactly one path source.
Relative paths are resolved against the supplied folder when reading.

```python doctest
>>> from r2x_core import DataFile
>>> data_file = DataFile(name="generators", relative_fpath="data/generators.csv")
>>> data_file.name
'generators'
>>> data_file.relative_fpath
'data/generators.csv'
```

## Supported file formats

`DataReader` selects a reader from the inferred physical format:

```python doctest
>>> from r2x_core import DataReader
>>> reader = DataReader()
>>> sorted(reader.get_supported_file_types())
['.csv', '.h5', '.hdf5', '.json', '.parquet', '.tsv', '.xml']
```

## Configure processing

Processing operations run in the order listed in `steps`:

```python doctest
>>> from r2x_core import DataFile, TabularProcessing
>>> processing = TabularProcessing(steps=[
...     {"op": "filter_columns", "filter_by": {"region": "North"}},
...     {"op": "rename_columns", "column_mapping": {"value": "amount"}},
...     {"op": "drop_columns", "drop_columns": ["temp_id"]},
... ])
>>> data_file = DataFile(
...     name="north_data",
...     relative_fpath="data/regional_data.csv",
...     proc_spec=processing,
... )
>>> [step.op for step in data_file.proc_spec.steps]
['filter_columns', 'rename_columns', 'drop_columns']
```

JSON uses its own step vocabulary. Its `kind` tag is supplied by
`JSONProcessing` when constructing the model:

```python doctest
>>> from r2x_core import JSONProcessing
>>> processing = JSONProcessing(steps=[
...     {"op": "rename_keys", "mapping": {"old": "new"}},
...     {"op": "select_keys", "keys": ["new"]},
... ])
>>> processing.model_dump()["kind"]
'json'
```

## Read a file

```python doctest
>>> import tempfile
>>> from pathlib import Path
>>> from r2x_core import DataFile, DataReader
>>> with tempfile.TemporaryDirectory() as directory:
...     root = Path(directory)
...     _ = (root / "generators.csv").write_text(
...         "id,name,capacity\n1,Gen1,500\n2,Gen2,300\n", encoding="utf-8"
...     )
...     data_file = DataFile(name="generators", relative_fpath="generators.csv")
...     frame = DataReader().read_data_file(data_file, folder_path=root).collect()
...     frame.columns
['id', 'name', 'capacity']
```

See [Configure data files](/r2x-core/how-tos/configure-data-files/) for file
metadata and [Process file data](/r2x-core/how-tos/process-file-data/) for
operation details.
