# File formats and validation

`FileFormat` is a lightweight sentinel for reader dispatch. Format instances have
no per-file state. `supports_timeseries` is a class-level capability flag;
`DataFile` combines the format with a path, reader options and `FileInfo`.

## Format classes

| Class | Extensions | Supports time series |
| --- | --- | --- |
| `TableFormat` | `.csv`, `.tsv` | Yes |
| `H5Format` | `.h5`, `.hdf5` | Yes |
| `ParquetFormat` | `.parquet` | Yes |
| `JSONFormat` | `.json` | No |
| `XMLFormat` | `.xml` | No |

`EXTENSION_MAPPING` maps suffixes to format classes. `TableDataFormat` is the
union of `TableFormat`, `H5Format` and `ParquetFormat`.
These are the current public names; the old `FileType`/`TableFile` compatibility
aliases are not the current API.

## Inspect format selection

This example checks configuration only. The relative path identifies a format;
it does not claim that a file has been created or read.

```python doctest
>>> from r2x_core import DataFile
>>> from r2x_core.file_types import EXTENSION_MAPPING, H5Format, JSONFormat, TableFormat
>>> definition = DataFile(name="generators", relative_fpath="generators.csv")
>>> # Expected: the suffix selects a table format without loading a dataset.
>>> type(definition.file_type).__name__
'TableFormat'
>>> [(extension, EXTENSION_MAPPING[extension].__name__) for extension in (".csv", ".h5", ".json")]
[('.csv', 'TableFormat'), ('.h5', 'H5Format'), ('.json', 'JSONFormat')]
>>> TableFormat.supports_timeseries, H5Format.supports_timeseries, JSONFormat.supports_timeseries
(True, True, False)
```

## Validation

Time-series metadata is incompatible with formats that do not support it.
Unknown suffixes and incompatible processing settings also require a corrected
configuration or an implemented reader for the format, not a renamed file.

```python doctest
>>> from r2x_core import DataFile, FileInfo
>>> # Expected: JSON is not accepted as a tabular time-series source.
>>> try:
...     DataFile(name="profiles", relative_fpath="profiles.json", info=FileInfo(is_timeseries=True))
... except ValueError as error:
...     assert "time series" in str(error).lower()
...     print(type(error).__name__)
ValueError
```

## Adding New File Types

Adding a format is a contributor task that changes the registry and reader,
not a runtime plugin registration setting. Use [Add a file format](/r2x-core/how-tos/add-file-format/).

## Best Practices

Keep format capability, reader behavior and model validation distinct.
The [file configuration guide](/r2x-core/how-tos/configure-data-files/) and
[HDF5 guide](/r2x-core/how-tos/read-hdf5-files/) show checked configuration;
the [CSV tutorial](/r2x-core/tutorials/getting-started/) reads an actual small fixture.

## See Also

Use the [generated API](/r2x-core/references/api/) for signatures and pinned source.

<span id="file-types-api-reference"></span>

<span id="overview"></span>

<span id="base-class"></span>

<span id="filetype"></span>

<span id="file-type-classes"></span>

<span id="tablefile"></span>

<span id="h5file"></span>

<span id="parquetfile"></span>

<span id="jsonfile"></span>

<span id="xmlfile"></span>

<span id="extension-mapping"></span>

<span id="type-alias"></span>

<span id="tabledatafiletype"></span>
