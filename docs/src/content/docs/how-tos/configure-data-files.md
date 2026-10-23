---
title: "Configure Data Files"
---

`DataFile` describes one physical input, named source, ordered source selection,
or configuration-owned inline table. It contains availability settings, an
optional symbolic reader with options, and an ordered processing spec. Path
existence and glob matching are resolved at execution time.

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

An optional physical file can become required when a previously declared table
contains a row matching an expression. The original file or HDF5-group error
is preserved when the condition is true. Missing inputs remain optional when it
is false, while malformed present files still fail.

```python doctest
>>> from r2x_core import DataFile, FileInfo, FileRequirement, SourcePredicate
>>> condition = SourcePredicate(source="water_switch", predicate="enabled")
>>> condition.source
'water_switch'
>>> water = DataFile(
...     name="water_upgrades",
...     relative_fpath="inputs_case/upgradelink_water.csv",
...     info=FileInfo(requirement=FileRequirement.OPTIONAL),
...     required_when={"source": "water_switch", "predicate": "enabled"},
... )
>>> water.required_when.source
'water_switch'
```

The predicate source must be declared before the physical input and must be
tabular. It is required when any row matches.

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

## Inline tables and source selection

An inline table has an explicit schema for its raw records, before its own
`proc_spec` runs. Each row must contain exactly the schema keys. A whole row
list or individual values can use placeholders, which are resolved and
validated before processing. `rows=[]` is a present, typed empty source.

```python doctest
>>> from r2x_core import DataFile, InlineTable, SourceSelection
>>> defaults = DataFile(
...     name="defaults",
...     inline_table=InlineTable.model_validate({
...         "schema": {"year": "int64", "technology": "string"},
...         "rows": [{"year": 2030, "technology": "wind"}],
...     }),
... )
>>> defaults.inline_table.raw_schema
{'year': 'int64', 'technology': 'string'}
>>> selected = DataFile(
...     name="selected_costs",
...     source_selection=SourceSelection(
...         mode="first_present", sources=["default_costs", "market_costs"]
...     ),
... )
>>> selected.source_selection.mode
'first_present'
```

`first_present` selects the first available named source even if it has no
rows. `first_nonempty` skips absent and present-empty sources. An explicit
`empty_fallback` inline table can provide a typed terminal result. Optional
physical inputs that are absent are omitted. Present-empty inputs remain
available, and malformed present inputs still fail. Declare candidate sources
before the selector in the ordered data-file list.

JSON processing has a separate step vocabulary:

```python doctest
>>> from r2x_core import JSONProcessing
>>> processing = JSONProcessing(steps=[
...     {"op": "rename_keys", "mapping": {"old_key": "new_key"}},
...     {"op": "replace_values", "replacements": [
...         {"old": 0, "new": "missing"},
...         {"old": True, "new": "enabled"},
...     ]},
...     {"op": "select_keys", "keys": ["new_key"]},
... ])
>>> [step.op for step in processing.steps]
['rename_keys', 'replace_values', 'select_keys']
```

See the [processor reference](/r2x-core/references/processors/) for operation
schemas and [Read data files](/r2x-core/how-tos/read-data-files/) for source
loading.
