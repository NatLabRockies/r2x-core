---
title: "Read Data Files"
---

`DataReader` is the public source-loading and composition seam. It resolves
physical paths at execution time, selects a reader from an explicit symbolic
format or an unambiguous common extension, and returns a mapping of named typed
sources. `DataStore` manages file-mapping configuration; it does not read or
process files.

## Configure an input

A physical `DataFile` selects exactly one path source: `fpath`,
`relative_fpath`, or `glob`. Derived files may instead reference a prior named
source, select among prior names, or define an inline table. Relative paths are
resolved against the supplied folder when reading. An explicit symbolic format
supports new extensions without editing core's inference table.

```python doctest
>>> from r2x_core import DataFile, ReaderConfig
>>> data_file = DataFile(
...     name="generators",
...     relative_fpath="data/generators.csv",
...     reader=ReaderConfig(options={"skip_rows": 1}),
... )
>>> data_file.name
'generators'
>>> data_file.format_name
'csv'
```

Built-in reader options are validated by the selected reader. Application
readers validate their own options and are registered by symbolic name. JSON
configuration selects names and options only, it does not import Python code.

## Read named sources

One input can produce several named sources. A table remains paired with its
tabular processor, while JSON documents and HDF5 arrays retain their own
representations. The source map is execution-local.

```python doctest
>>> import tempfile
>>> from pathlib import Path
>>> from r2x_core import DataFile, DataReader, TabularSource
>>> with tempfile.TemporaryDirectory() as directory:
...     root = Path(directory)
...     _ = (root / "generators.csv").write_text(
...         "id,name,capacity\n1,Gen1,500\n2,Gen2,300\n", encoding="utf-8"
...     )
...     sources = DataReader().read_data_files(
...         [DataFile(name="generators", relative_fpath="generators.csv")],
...         folder_path=root,
...     )
...     table = sources["generators"]
...     is_table = isinstance(table, TabularSource)
...     columns = table.data.collect().columns
>>> is_table
True
>>> columns
['id', 'name', 'capacity']
```

## Optional inputs and paths

Required inputs are the default. Set `info.requirement` to `optional` to skip a
missing file or an optional configured HDF5 group. Required missing inputs and
ambiguous globs fail explicitly. `fpath` can be absolute or relative to the
execution folder. A glob must contain a wildcard and resolve to exactly one
file.

`SourceSelection` distinguishes `first_present` from `first_nonempty`. The first
selects a present empty source, while the second skips absent and empty sources.
Declare its candidates before the selector. An explicit inline fallback keeps
an empty result typed. Malformed present inputs still fail.

`fpath`, `relative_fpath`, `glob`, reader options, and processing values can
contain placeholders. `DataReader` resolves these before the relevant read or
processing step. A physical decode is reused only for the same resolved path,
format, and options during one `read_data_files` call.

See [Configure data files](/r2x-core/how-tos/configure-data-files/) for the
configuration schema, [Read HDF5 files](/r2x-core/how-tos/read-hdf5-files/) for
HDF5 layout options, and [Process file data](/r2x-core/how-tos/process-file-data/)
for ordered transformations.
