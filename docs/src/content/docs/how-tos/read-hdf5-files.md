---
title: "Reading HDF5 Data Files"
---

<span id="reading-hdf5-data-files"></span>

HDF5 (Hierarchical Data Format) is a flexible format for storing large amounts of structured data. r2x-core provides specialized readers for HDF5 files through [`H5Format`](/r2x-core/references/api/) and the [`h5_readers`](/r2x-core/references/api/) module, supporting both flat and hierarchical data structures.

## Configure HDF5 File Reading

Create a [`DataFile`](/r2x-core/references/api/) configuration for an HDF5 file:

```python doctest
>>> from r2x_core import DataFile
>>>
>>> # Basic HDF5 configuration
>>> data_file = DataFile(name="timeseries", relative_fpath="data/timeseries.h5")
>>> data_file.name
'timeseries'
>>> data_file.relative_fpath
'data/timeseries.h5'
```

## Read a Specific Dataset from HDF5

Specify which dataset to read using the `data_key` parameter in [`ReaderConfig`](/r2x-core/references/api/):

```python doctest
>>> from r2x_core import DataFile, ReaderConfig
>>>
>>> # Read a specific nested dataset
>>> data_file = DataFile(
...     name="generators",
...     relative_fpath="data/models.h5",
...     reader=ReaderConfig(kwargs={"data_key": "models/gen_data"})
... )
>>> data_file.reader.kwargs
{'data_key': 'models/gen_data'}
```

## Map Column Names in HDF5 Data

Use `column_name_mapping` to rename generic dataset keys to meaningful column names:

```python doctest
>>> from r2x_core import DataFile, ReaderConfig
>>>
>>> # Map generic names to meaningful column names
>>> mapping = {
...     "col0": "capacity_factor",
...     "col1": "efficiency",
...     "col2": "availability"
... }
>>> data_file = DataFile(
...     name="profiles",
...     relative_fpath="data/timeseries.h5",
...     reader=ReaderConfig(kwargs={"column_name_mapping": mapping})
... )
>>> data_file.reader.kwargs["column_name_mapping"]["col0"]
'capacity_factor'
```

## Read the HDF5 File

Use [`DataReader`](/r2x-core/references/api/) to load a configured HDF5 file:

```python doctest
>>> import tempfile
>>> from pathlib import Path
>>> import h5py
>>> import numpy as np
>>> from r2x_core import DataReader, DataFile, ReaderConfig
>>>
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     # Create HDF5 file with standard tabular structure
...     h5_file = Path(tmpdir) / "timeseries.h5"
...     with h5py.File(h5_file, "w") as f:
...         columns = np.array(["generation", "load"], dtype="S")
...         data = np.array([[100.0, 80.0], [200.0, 150.0], [150.0, 120.0], [175.0, 140.0]])
...         _ = f.create_dataset("columns", data=columns)
...         _ = f.create_dataset("data", data=data)
...
...     # Read using DataReader with configuration
...     data_file = DataFile(
...         name="timeseries",
...         relative_fpath="timeseries.h5",
...         reader=ReaderConfig(kwargs={"data_key": "data", "columns_key": "columns"})
...     )
...     reader = DataReader()
...     df = reader.read_data_file(data_file, folder_path=Path(tmpdir))
...
...     # Collect and verify
...     result = df.collect()
...     print("Columns:", result.columns)
...     print("Shape:", result.shape)
...     print("First row:", result.row(0))
Columns: ['generation', 'load']
Shape: (4, 2)
First row: (100.0, 80.0)
```

## Use the Configurable HDF5 Reader Directly

For advanced use cases, use [`configurable_h5_reader`](/r2x-core/references/api/) directly to read HDF5 files with full control over dataset mapping:

```python doctest
>>> import tempfile
>>> from pathlib import Path
>>> import h5py
>>> import numpy as np
>>> from r2x_core.h5_readers import configurable_h5_reader
>>>
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     # Create HDF5 file with flat structure
...     h5_file = Path(tmpdir) / "capacity.h5"
...     with h5py.File(h5_file, "w") as f:
...         f.create_dataset("gen_data", data=np.array([[500.0, 600.0], [750.0, 800.0]]))
...         f.create_dataset("gen_names", data=np.array(["gen1", "gen2"], dtype="S"))
...
...     # Read the HDF5 file with configurable_h5_reader
...     with h5py.File(h5_file, "r") as f:
...         result = configurable_h5_reader(
...             f,
...             data_key="gen_data",
...             columns_key="gen_names"
...         )
...     # Result contains data mapped to column names
...     print("Number of generators:", len(result))
...     gen1_values = result[list(result.keys())[0]]
...     print("First generator values:", gen1_values)
...     print("Data shape:", gen1_values.shape)
<HDF5 dataset "gen_data": shape (2, 2), type "<f8">
<HDF5 dataset "gen_names": shape (2,), type "|S4">
Number of generators: 2
First generator values: [500. 750.]
Data shape: (2,)
```

## See Also

- [manage datastores](/r2x-core/how-tos/manage-datastores/) - Manage collections of data files including HDF5
- [process file data](/r2x-core/how-tos/process-file-data/) - Transform HDF5 data during loading
- [read data files](/r2x-core/how-tos/read-data-files/) - Basic data file reading
- [`H5Format`](/r2x-core/references/api/) - HDF5 file format class
- [`h5_readers`](/r2x-core/references/api/) - HDF5 reader utilities
