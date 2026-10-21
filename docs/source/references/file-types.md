# File formats and validation

`DataFile.file_format` returns a lightweight marker selected from the file
extension. Format markers and `EXTENSION_MAPPING` are exposed through
`r2x_core.types`.

## Supported formats

| Marker | Extensions | Time-series support |
| --- | --- | --- |
| `TableFormat` | `.csv`, `.tsv` | Yes |
| `H5Format` | `.h5`, `.hdf5` | Yes |
| `ParquetFormat` | `.parquet` | Yes |
| `JSONFormat` | `.json` | No |
| `XMLFormat` | `.xml` | No |

`TableDataFormat` is the union of `TableFormat`, `H5Format` and
`ParquetFormat`. The marker only identifies the format. A reader must support
that format to load the file.

```python doctest
>>> from r2x_core import DataFile
>>> from r2x_core.types import EXTENSION_MAPPING, H5Format, JSONFormat, TableDataFormat, TableFormat
>>> csv_file = DataFile(name="profiles", relative_fpath="profiles.csv")
>>> h5_file = DataFile(name="load", relative_fpath="load.h5")
>>> isinstance(csv_file.file_format, TableFormat), isinstance(h5_file.file_format, H5Format)
(True, True)
>>> EXTENSION_MAPPING[".json"] is JSONFormat
True
>>> TableFormat.supports_timeseries, H5Format.supports_timeseries, JSONFormat.supports_timeseries
(True, True, False)
```

All format markers are dataclasses with slots. Their `supports_timeseries`
capability is class-level. A `DataFile` marked as time-series data cannot use a
format that does not support time series.

## Add a format

Adding a new extension requires a marker in `EXTENSION_MAPPING` and a reader
that supports it. Applications can supply readers and tabular backends through
the public interfaces without changing the core processing pipeline. See
[Add a file format](https://natlabrockies.github.io/r2x-core/how-tos/add-file-format/).

## See also

- [File configuration](https://natlabrockies.github.io/r2x-core/how-tos/configure-data-files/)
- [HDF5 reading](https://natlabrockies.github.io/r2x-core/how-tos/read-hdf5-files/)
- [Generated API reference](https://natlabrockies.github.io/r2x-core/references/api/)
