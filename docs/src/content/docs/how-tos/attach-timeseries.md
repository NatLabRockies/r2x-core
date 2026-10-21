---
title: "Attaching Time Series"
---

<span id="attaching-time-series"></span>

Use `FileInfo.file_type` to describe whether a file contains static values or
time-varying data. This semantic type is separate from the physical format
reported by `DataFile.file_format`.

## Mark time-series inputs

```python doctest
>>> from r2x_core import DataFile, FileInfo, FileType
>>> profiles = DataFile(
...     name="generation_profiles",
...     relative_fpath="data/profiles.csv",
...     info=FileInfo(file_type=FileType.TIME_SERIES, units="MW"),
... )
>>> profiles.info.file_type
<FileType.TIME_SERIES: 'time_series'>
>>> type(profiles.file_format).__name__
'TableFormat'
```

Use `FileType.STATIC` for component attributes that do not vary over time. It
is the default, so static files need no special setting:

```python doctest
>>> from r2x_core import DataFile, FileInfo, FileType
>>> generators = DataFile(
...     name="generators",
...     relative_fpath="data/generators.csv",
...     info=FileInfo(description="Generator properties"),
... )
>>> generators.info.file_type is FileType.STATIC
True
```

`DataFile.file_format` checks whether the selected format supports time-series
data. For example, table, HDF5, and Parquet formats support it, while JSON and
XML do not. This check concerns metadata semantics. It does not convert tabular
records into the `infrasys` time-series representation.

## Mark optional inputs

Use `FileRequirement.OPTIONAL` when an absent input should be skipped by the
reader. Required inputs are the default.

```python doctest
>>> from r2x_core import DataFile, FileInfo, FileRequirement
>>> optional_profiles = DataFile(
...     name="optional_profiles",
...     relative_fpath="profiles.csv",
...     info=FileInfo(requirement=FileRequirement.OPTIONAL),
... )
>>> optional_profiles.info.requirement
<FileRequirement.OPTIONAL: 'optional'>
```

## Transfer time-series metadata

Use [`transfer_time_series_metadata`](/r2x-core/references/api/) to transfer
time-series metadata from a source system to a target system:

```python doctest
>>> from r2x_core import transfer_time_series_metadata
>>> transfer_time_series_metadata.__doc__.splitlines()[0]
'Transfer time series metadata for target system.'
```

Use [`replace_single_time_series`](/r2x-core/references/api/) to replace one
target association while preserving backing data that may be shared with the
source system:

```python doctest
>>> from r2x_core import replace_single_time_series
>>> replace_single_time_series.__doc__.splitlines()[0]
'Replace exactly one time series association without removing shared data.'
```

## See also

- [Manage datastores](/r2x-core/how-tos/manage-datastores/)
- [Read data files](/r2x-core/how-tos/read-data-files/)
- [`FileInfo`](/r2x-core/references/api/)
- [`DataFile`](/r2x-core/references/api/)
