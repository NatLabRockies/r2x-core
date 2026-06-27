# Working with DataFiles

DataFiles configure how to load and process external data sources.

## Basic DataFile

```python doctest
>>> import tempfile
>>> from r2x_core import DataFile, FileInfo
>>> from pathlib import Path
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     csv_file = Path(tmpdir) / "data.csv"
...     _ = csv_file.write_text("a,b,c\n1,2,3\n")
...     file_spec = DataFile(
...         name="data",
...         fpath=csv_file,
...         info=FileInfo(description="My data", is_input=True)
...     )
...     print(file_spec.name)
...     print(file_spec.info.description)
data
My data
```

## Tabular Processing

Define transformations for CSV and Excel files:

```python doctest
>>> import tempfile
>>> from r2x_core import DataFile, TabularProcessing
>>> from pathlib import Path
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     csv_file = Path(tmpdir) / "data.csv"
...     _ = csv_file.write_text("old_name,unused,other\n1,2,3\n")
...     data_file = DataFile(
...         name="processed",
...         fpath=csv_file,
...         proc_spec=TabularProcessing(
...             column_mapping={"old_name": "new_name"},
...             drop_columns=["unused"]
...         )
...     )
...     print(data_file.proc_spec.column_mapping)
{'old_name': 'new_name'}
```

## JSON Processing

Define transformations for JSON files:

```python doctest
>>> import tempfile
>>> import json
>>> from r2x_core import DataFile, JSONProcessing
>>> from pathlib import Path
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     json_file = Path(tmpdir) / "data.json"
...     _ = json_file.write_text(json.dumps({"old_key": "value"}))
...     data_file = DataFile(
...         name="json_data",
...         fpath=json_file,
...         proc_spec=JSONProcessing(key_mapping={"old_key": "new_key"})
...     )
...     print(data_file.proc_spec.key_mapping)
{'old_key': 'new_key'}
```

## HDF5 Files

Work with HDF5 format files:

```python doctest
>>> import tempfile
>>> import h5py
>>> import numpy as np
>>> from r2x_core import DataFile, H5Format, ReaderConfig
>>> from pathlib import Path
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     h5_path = Path(tmpdir) / "data.h5"
...     with h5py.File(h5_path, "w") as f:
...         _ = f.create_dataset("load_profiles", data=np.array([1, 2, 3]))
...     h5_file = DataFile(
...         name="timeseries",
...         fpath=h5_path,
...         reader=ReaderConfig(kwargs={"key": "load_profiles"})
...     )
...     print(type(h5_file.file_type).__name__)
H5Format
```

## File Format Detection

Automatically detect and work with different file formats using FileFormat:

```python doctest
>>> import tempfile
>>> from pathlib import Path
>>> from r2x_core import DataFile, FileFormat
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     csv_path = Path(tmpdir) / "data.csv"
...     _ = csv_path.write_text("a,b\n1,2\n")
...     csv_file = DataFile(name="csv_data", fpath=csv_path)
...     # FileFormat is the base class for all file format types
...     isinstance(csv_file.file_type, FileFormat)
True
```

## See Also

- {doc}`read-data-files` - Reading files
- {doc}`configure-data-settings` - Configuration management
