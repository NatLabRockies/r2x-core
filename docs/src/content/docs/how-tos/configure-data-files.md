---
title: "Working with DataFiles"
---

<span id="working-with-datafiles"></span>

`DataFile` describes where data lives, its semantics, the reader options, and
any ordered processing steps.

## Configure file metadata

`FileInfo.file_type` describes the data, while `DataFile.file_format` describes
its physical encoding. `requirement` says whether the input must be present.

```python doctest
>>> from r2x_core import DataFile, FileInfo, FileRequirement, FileType
>>> profile = DataFile(
...     name="profiles",
...     relative_fpath="profiles.csv",
...     info=FileInfo(
...         description="Hourly load profiles",
...         file_type=FileType.TIME_SERIES,
...         requirement=FileRequirement.OPTIONAL,
...         units="MW",
...     ),
... )
>>> profile.info.file_type
<FileType.TIME_SERIES: 'time_series'>
>>> profile.info.requirement
<FileRequirement.OPTIONAL: 'optional'>
>>> type(profile.file_format).__name__
'TableFormat'
```

`DataFile.info` and `DataFile.reader` have default models. Use the default
`FileInfo` for static, required inputs without extra metadata.

## Configure ordered tabular processing

A processing spec is an ordered list of tagged operations. The order in `steps`
is the execution order.

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from r2x_core import DataFile, TabularProcessing
>>> with TemporaryDirectory() as directory:
...     path = Path(directory) / "data.csv"
...     _ = path.write_text("old_name,unused\nalpha,1\n", encoding="utf-8")
...     processing = TabularProcessing(steps=[
...         {"op": "rename_columns", "column_mapping": {"old_name": "name"}},
...         {"op": "drop_columns", "drop_columns": ["unused"]},
...     ])
...     data_file = DataFile(name="processed", fpath=path, proc_spec=processing)
...     [step.op for step in data_file.proc_spec.steps]
['rename_columns', 'drop_columns']
```

Each step accepts only the fields relevant to that operation. For example,
`filter_columns` selects rows by exact values and `filter` accepts a mapping
expression:

```python doctest
>>> from r2x_core import TabularProcessing
>>> processing = TabularProcessing(steps=[
...     {"op": "filter_columns", "filter_by": {"region": "North"}},
...     {"op": "sort", "by": {"year": "asc"}},
... ])
>>> [step.op for step in processing.steps]
['filter_columns', 'sort']
```

The two processing models share the `FileProcessing` union, which uses their
`kind` field to validate JSON mapping records:

```python doctest
>>> from r2x_core import FileProcessing, TabularProcessing
>>> processing: FileProcessing = TabularProcessing()
>>> processing.kind
'tabular'
```

See the [processor reference](/r2x-core/references/processors/) for the
operation vocabulary and the JSON processing schema.

## Configure JSON processing

JSON processing uses its own ordered operations.

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from r2x_core import DataFile, JSONProcessing
>>> with TemporaryDirectory() as directory:
...     path = Path(directory) / "data.json"
...     _ = path.write_text('{"old_key": "value"}', encoding="utf-8")
...     processing = JSONProcessing(steps=[
...         {"op": "rename_keys", "mapping": {"old_key": "new_key"}},
...         {"op": "select_keys", "keys": ["new_key"]},
...     ])
...     data_file = DataFile(name="json_data", fpath=path, proc_spec=processing)
...     [step.op for step in data_file.proc_spec.steps]
['rename_keys', 'select_keys']
```

## Detect physical formats

The format is inferred from one configured path source. File formats are
validated against `EXTENSION_MAPPING` and exposed as `FileFormat` markers.

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from r2x_core import DataFile, FileFormat, H5Format
>>> with TemporaryDirectory() as directory:
...     path = Path(directory) / "data.csv"
...     _ = path.write_text("a,b\n1,2\n", encoding="utf-8")
...     data_file = DataFile(name="csv_data", fpath=path)
...     isinstance(data_file.file_format, FileFormat)
True
>>> h5_file = DataFile(name="hdf5_data", relative_fpath="data.h5")
>>> isinstance(h5_file.file_format, H5Format)
True
```

## See also

- [Read data files](/r2x-core/how-tos/read-data-files/)
- [Configure data settings](/r2x-core/how-tos/configure-data-settings/)
- [Processor reference](/r2x-core/references/processors/)
