# File formats and reader selection

`DataFile.format_name` is a symbolic string. Common built-in extensions map to
reader names through `EXTENSION_MAPPING`; an application can explicitly select
any registered name with `ReaderConfig.format`, including for a new extension.
No core whitelist change is required for application formats.

| Inferred extension | Symbolic format |
| --- | --- |
| `.csv` | `csv` |
| `.tsv` | `tsv` |
| `.h5`, `.hdf5` | `hdf5` |
| `.parquet` | `parquet` |
| `.json` | `json` |
| `.xml` | `xml` |

`FileInfo.file_type` describes content semantics. It does not declare reader
capabilities or restrict whether a decoded source can supply one of the three
configured outputs: components, time series, or supplemental attributes.
Output purpose and fields are configured separately in `parser_rules.json`.

```python doctest
>>> from r2x_core import DataFile, FileInfo, FileType, ReaderConfig
>>> common = DataFile(name="load", relative_fpath="load.h5")
>>> common.format_name
'hdf5'
>>> custom = DataFile(
...     name="case",
...     relative_fpath="case.raw",
...     reader=ReaderConfig(format="dummy_raw"),
...     info=FileInfo(file_type=FileType.TIME_SERIES),
... )
>>> custom.format_name, custom.info.file_type.value
('dummy_raw', 'time_series')
```

An unknown extension without an explicit format raises when `format_name` is
resolved. A configured symbolic format delegates validation and decoding to its
registered reader. See [Register an application format](/r2x-core/how-tos/add-file-format/),
[Configure data files](/r2x-core/how-tos/configure-data-files/), and the
[generated API reference](/r2x-core/references/api/).
