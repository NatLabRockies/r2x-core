# Reading HDF5 Data Files

HDF5 (Hierarchical Data Format) is a flexible format for storing large amounts of structured data. R2X Core provides specialized readers for HDF5 files through {py:class}`~r2x_core.H5Format` and the {py:mod}`~r2x_core.h5_readers` module, supporting both flat and hierarchical data structures.

## Configure HDF5 File Reading

Create a {py:class}`~r2x_core.DataFile` configuration for an HDF5 file:

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

Specify which dataset to read using the `data_key` parameter in {py:class}`~r2x_core.ReaderConfig`:

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

Use {py:class}`~r2x_core.DataReader` to load a configured HDF5 file:

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
...         f.create_dataset("columns", data=columns)
...         f.create_dataset("data", data=data)
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
...     print("First row:", result.row(0))  # doctest: +ELLIPSIS
<HDF5 dataset "columns": shape (2,), type "|S10">
<HDF5 dataset "data": shape (4, 2), type "<f8">
Columns: ['generation', 'load']
Shape: (4, 2)
First row: (100.0, 80.0)
```

## Use the Configurable HDF5 Reader Directly

For advanced use cases, use {py:func}`~r2x_core.h5_readers.configurable_h5_reader` directly to read HDF5 files with full control over dataset mapping:

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

- {doc}`manage-datastores` - Manage collections of data files including HDF5
- {doc}`process-file-data` - Transform HDF5 data during loading
- {doc}`read-data-files` - Basic data file reading
- {py:class}`~r2x_core.H5Format` - HDF5 file format class
- {py:mod}`~r2x_core.h5_readers` - HDF5 reader utilities
