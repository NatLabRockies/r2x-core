---
title: "Read HDF5 Files"
---

The built-in `hdf5` reader turns configured datasets and column layouts into a
Polars table source. Use `hdf5_array` when an output should retain native array
samples. Reader options are strictly validated without coercion and belong in
`ReaderConfig.options`. Boolean options must be booleans, unknown options are
rejected, and a supplied `data_key` must be non-empty.

## Reading HDF5 data files

### Configure a tabular HDF5 layout

For row-oriented data, use `data_key` and optionally `columns_key` to label
matrix columns. A group can be selected with `group_key`. `datetime_key`,
`index_key`, and `additional_keys` add configured fields. The HDF5 reader also
supports columnar groups where each field is a dataset.

```python doctest
>>> from r2x_core import DataFile, ReaderConfig
>>> item = DataFile(
...     name="load",
...     relative_fpath="load.h5",
...     reader=ReaderConfig(
...         format="hdf5",
...         options={"data_key": "data", "columns_key": "columns"},
...     ),
... )
>>> item.reader.options["columns_key"]
'columns'
```

### Read a configured HDF5 table

```python doctest
>>> import tempfile
>>> from pathlib import Path
>>> import h5py
>>> import numpy as np
>>> from r2x_core import DataFile, DataReader, ReaderConfig, TabularSource
>>> with tempfile.TemporaryDirectory() as directory:
...     root = Path(directory)
...     path = root / "timeseries.h5"
...     with h5py.File(path, "w") as h5_file:
...         _ = h5_file.create_dataset("columns", data=np.array(["generation", "load"], dtype="S"))
...         _ = h5_file.create_dataset("data", data=np.array([[100.0, 80.0], [200.0, 150.0]]))
...     item = DataFile(
...         name="timeseries",
...         relative_fpath="timeseries.h5",
...         reader=ReaderConfig(format="hdf5", options={"data_key": "data", "columns_key": "columns"}),
...     )
...     source = DataReader().read_data_files([item], folder_path=root)["timeseries"]
...     assert isinstance(source, TabularSource)
...     frame = source.data.collect()
...     frame.columns
['generation', 'load']
>>> frame.shape
(2, 2)
```

### Preserve arrays for time-series output

Use `hdf5_array` to decode one-dimensional samples without converting them to
Polars. A `time_series` parser instruction then selects the sample field and
attaches it by component type and name. Units and metadata come from that
instruction. See [Attach time series](/r2x-core/how-tos/attach-timeseries/).

```python doctest
>>> from r2x_core import ArraySource, H5PyFileReader, H5Reader
>>> issubclass(H5PyFileReader, H5Reader)
True
>>> ArraySource.__name__
'ArraySource'
```

For direct HDF5 dataset inspection, `r2x_core.h5_adapter.configurable_h5_reader`
remains available. System ingestion should use `DataReader` or `build_system`.
See [Configure data files](/r2x-core/how-tos/configure-data-files/) and
[Read data files](/r2x-core/how-tos/read-data-files/).
