---
title: "Configure Data Files"
---

`DataFile` describes one physical input or one named source transformation. It
contains path and availability settings, an optional symbolic reader selection
with options, and an ordered processing spec. Path existence and glob matching
are resolved at execution time.

## Working with datafiles

### Configure file metadata

`FileInfo.file_type` describes the content's purpose and does not restrict its
physical format or output use. `requirement` controls whether a missing input is
an error or is skipped.

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
```

## Select a reader

Common extensions are inferred when unambiguous. Configure `reader.format` to
select a registered reader for an uncommon extension. Reader-specific settings
belong in `reader.options`; the selected Python reader validates those options.
JSON configuration cannot import arbitrary code.

```python doctest
>>> from r2x_core import DataFile, ReaderConfig
>>> data_file = DataFile(
...     name="profiles",
...     relative_fpath="profiles.raw",
...     reader=ReaderConfig(format="dummy_raw", options={"encoding": "utf-8"}),
... )
>>> data_file.format_name
'dummy_raw'
>>> data_file.reader.options
{'encoding': 'utf-8'}
```

## Configure ordered processing

A processing spec is an ordered list of tagged operations. `FileProcessing` is
the discriminated union of the tabular and JSON models. The representation and
its paired processor determine compatibility, not the filename extension.

```python doctest
>>> from r2x_core import FileProcessing, TabularProcessing
>>> processing: FileProcessing = TabularProcessing()
>>> processing.kind
'tabular'
```

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

JSON processing has a separate step vocabulary:

```python doctest
>>> from r2x_core import JSONProcessing
>>> processing = JSONProcessing(steps=[
...     {"op": "rename_keys", "mapping": {"old_key": "new_key"}},
...     {"op": "select_keys", "keys": ["new_key"]},
... ])
>>> [step.op for step in processing.steps]
['rename_keys', 'select_keys']
```

See the [processor reference](/r2x-core/references/processors/) for operation
schemas and [Read data files](/r2x-core/how-tos/read-data-files/) for source
loading.
