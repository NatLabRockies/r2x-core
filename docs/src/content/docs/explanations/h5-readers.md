---
title: "Why HDF5 reading needs explicit dataset selectors"
---

<span id="hdf5-reader-system"></span>

HDF5 stores named datasets and groups without prescribing a power-system table
layout. The reader needs the dataset location and the meaning of its columns;
recognizing a `.h5` suffix alone does not supply that information.

## Select a dataset and its labels

`configurable_h5_reader` accepts an open HDF5 file and explicit options.
`data_key` selects row-oriented data; `columns_key` selects labels for a 2D matrix.
The following self-contained example writes a small actual HDF5 file and checks
the returned column values. The temporary fixture is removed after the read.

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> import h5py
>>> import numpy as np
>>> from r2x_core.h5_adapter import configurable_h5_reader
>>> with TemporaryDirectory() as directory:
...     path = Path(directory) / "measurements.h5"
...     with h5py.File(path, "w") as stream:
...         _ = stream.create_dataset("values", data=np.array([[100.0, 150.0], [120.0, 160.0]]))
...         _ = stream.create_dataset("labels", data=np.array(["north", "south"], dtype="S"))
...     with h5py.File(path, "r") as stream:
...         columns = configurable_h5_reader(stream, data_key="values", columns_key="labels")
>>> # Expected: the matrix is separated into the two named columns.
>>> sorted(columns)
['north', 'south']
>>> columns["north"].tolist()
[100.0, 120.0]
>>> columns["south"].tolist()
[150.0, 160.0]
```

## Groups, time indexes and columnar data

`group_key` limits lookup to an HDF5 group. With `columns_as_datasets=True`,
columns are separate datasets rather than columns in one matrix.
`datetime_key`, `index_key` and `additional_keys` include supporting indexes.
Their lengths and meanings must match the selected data; a reader cannot infer
a model's calendar or missing-hour policy from arbitrary array names. HDF5
results contain backend-neutral NumPy arrays rather than Polars frames.

## Datetime values

When `datetime_key` selects an ISO 8601 string dataset, the reader parses it to
NumPy `datetime64[us]` values. By default, `strip_timezone=True` removes a
present timezone without adjusting the displayed wall time. Set
`strip_timezone=False` to convert offset-aware values to UTC before removing
the timezone.

For parser configuration through `DataFile` and `ReaderConfig`, use
[Reading HDF5 Data Files](/r2x-core/how-tos/read-hdf5-files/).
Dataset names in that configuration guide are examples of settings, not a claim
that an external model file exists in the project.
See the [reader implementation](https://github.com/NatLabRockies/r2x-core/blob/main/src/r2x_core/h5_adapter/readers.py)
for the supported selectors and explicit errors on missing groups/datasets.

<span id="overview"></span>

<span id="design-philosophy"></span>

<span id="how-the-reader-works"></span>

<span id="default-behavior"></span>

<span id="specifying-the-data-location"></span>

<span id="adding-column-names"></span>

<span id="parsing-datetime-fields"></span>

<span id="including-additional-metadata"></span>

<span id="configuration-parameters"></span>

<span id="automatic-behaviors"></span>

<span id="architecture-decisions"></span>

<span id="configuration-over-custom-functions"></span>

<span id="single-generic-reader-over-multiple-reader-classes"></span>

<span id="single-dispatch-for-file-types"></span>

<span id="trade-offs"></span>

<span id="future-considerations"></span>

<span id="power-system-data-in-hdf5"></span>

<span id="common-power-system-data-characteristics"></span>

<span id="typical-power-system-hdf5-layout"></span>

<span id="examples-of-file-structures"></span>

<span id="reeds-hourly-time-series"></span>

<span id="plexos-interval-output"></span>

<span id="generic-energy-model-time-series"></span>

<span id="scientific-measurements"></span>

<span id="simple-tabular-data"></span>

<span id="summary"></span>

<span id="practical-workflow"></span>
