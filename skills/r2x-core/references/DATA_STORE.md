# r2x-core Data Files and DataStore Reference

Use this for `DataFile`, file readers, `DataReader`, `DataStore`, processing
specs, optional inputs, HDF5, and typed source loading. For parser construction,
read [INGESTION.md](./INGESTION.md). For named-table assembly, read
[TABLE_MAPPING.md](./TABLE_MAPPING.md).

## Contents

- [Contracts](#contracts)
- [Configure and load files](#configure-and-load-files)
- [Reader and processing options](#reader-and-processing-options)
- [Derived and optional sources](#derived-and-optional-sources)
- [Failure playbook](#failure-playbook)
- [Source modules](#source-modules)

## Contracts

These signatures and fields are verified against the current source:

- `DataFile` accepts one physical path (`fpath`, `relative_fpath`, or `glob`),
  or one derived source mode (`source`, `source_selection`, or `inline_table`).
  It also accepts `columns`, `required_when`, `info`, `reader`, and `proc_spec`.
- `FileInfo(description=None, file_type=FileType.STATIC,
  requirement=FileRequirement.REQUIRED, units=None)` describes semantics and
  availability, not the physical format.
- `ReaderConfig(format=None, options={}, columns=())` selects a symbolic reader
  and its JSON-compatible options. `columns` is read-time metadata populated
  internally from `DataFile.columns`; do not set it on `DataFile.reader`.
- `DataStore(path=None)` holds file-mapping configuration. Its path must be an
  existing directory. Use `add_data(sequence, *, overwrite=False)`,
  `load_file_mapping(Path)`, `to_json(fpath, **model_dump_kwargs)`,
  `list_data()`, and `store[name]` for mapping operations.
- `DataReader(*, file_readers=None, step_handlers=None)` loads files. Its
  `read_data_files(data_files, *, folder_path, placeholders=None,
  initial_sources=None)` returns `DecodedSources`, a name-to-`DecodedSource`
  mapping.
- A reader implements `FileReader.read_file(format_name, /, *, file_path,
  reader_config) -> DecodedSources`.
- `TabularProcessing` and `JSONProcessing` contain ordered `steps`, each tagged
  with `op`. This is not the table-mapping `operations` schema.

`DataStore` does not have `read_data`, `load_file`, or `from_json`. It does not
read physical inputs. `DataReader.read_data_file(...)` and
`DataReader.get_supported_file_types()` are not APIs in this checkout.

## Configure and load files

```python
from pathlib import Path

from r2x_core import DataFile, DataReader, DataStore, FileInfo, FileRequirement, FileType

store = DataStore(path="/data/reeds")
store.add_data([
    DataFile(
        name="generators",
        relative_fpath="inputs_case/gen.csv",
        info=FileInfo(description="Generator capacity", units="MW"),
    ),
    DataFile(
        name="profiles",
        relative_fpath="inputs_case/load.h5",
        info=FileInfo(file_type=FileType.TIME_SERIES, requirement=FileRequirement.OPTIONAL),
    ),
])
sources = DataReader().read_data_files(store.data_files.values(), folder_path=store.folder)
generators = sources["generators"]
```

Relative `fpath` and `relative_fpath` values resolve against the `folder_path`
passed to `DataReader`; `DataStore.folder` is a convenient base when using a
store. Absolute `fpath` values remain absolute. A `glob` must contain a wildcard
and match exactly one file. Common extensions infer `csv`, `tsv`, `hdf5`,
`parquet`, `json`, or `xml`. Use `reader.format` for a custom format or
`hdf5_array`, which is not inferred from an extension.

Load or save a JSON array of `DataFile` records through the mapping API:

```python
from pathlib import Path
from r2x_core import DataStore

store = DataStore(path="/data/reeds")
store.load_file_mapping(Path("config/file_mapping.json"))
store.to_json("config/file_mapping.json")
```

A `DataStore` caches mapping records, not decoded data. Duplicate names are
rejected unless `overwrite=True`. `DataReader` returns typed `DecodedSource`
values such as `TabularSource`, `DocumentSource`, or `ArraySource`; inspect
`.data` for the native payload and use source methods for fields, rows, values,
and processing.

## Reader and processing options

Put reader options in `ReaderConfig.options`, not `kwargs`. For CSV/TSV, the
built-in reader supports `header_rows` and `header_separator` in addition to
Polars scan options. HDF5 uses the same `options` field:

```python
from r2x_core import DataFile, ReaderConfig

profile = DataFile(
    name="profiles",
    relative_fpath="profiles.h5",
    reader=ReaderConfig(
        format="hdf5",
        options={"data_key": "data", "columns_key": "columns"},
    ),
)
```

The HDF5 reader also accepts `group_key`, `columns_as_datasets`,
`index_names_key`, `datetime_key`, `datetime_column_name`, `strip_timezone`,
`index_key`, `additional_keys`, `decode_bytes`, and `column_name_mapping`.
Options are strictly validated; consult `h5py_adapter/readers.py` and its tests
before using less common layouts. Use `hdf5_array` for native array output.

Declare physical input columns with `DataFile.columns`, not
`ReaderConfig.columns`:

```python
from r2x_core import DataFile, InputColumn

file_spec = DataFile(
    name="generators",
    relative_fpath="generators.csv",
    columns=[
        InputColumn(name="generator_id", dtype="int64", rename="id"),
        InputColumn(name="capacity", dtype="float64", required=False),
    ],
)
```

Supported native column types are `bool`, `int64`, `float64`, `string`, and
`datetime`. Declared columns are cast before `proc_spec` runs. Missing required
columns fail; missing optional columns become typed null columns. Declarations
also provide the known schema for an absent optional file.

Use `TabularProcessing(steps=[...])` for ordered tabular transformations and
`JSONProcessing(steps=[...])` for JSON transformations. Every step uses a
strict tagged schema. For example:

```python
from r2x_core import DataFile, TabularProcessing

processed = DataFile(
    name="north_generators",
    relative_fpath="generators.csv",
    proc_spec=TabularProcessing(steps=[
        {"op": "filter_columns", "filter_by": {"region": "north"}},
        {"op": "rename_columns", "column_mapping": {"old_name": "name"}},
        {"op": "drop_columns", "drop_columns": ["scratch"]},
    ]),
)
```

Tabular steps include filters, projections, joins/concats, casts, replacements,
scaling, aggregation, sorting, uniqueness, unpivoting, matching, and registered
custom handlers. JSON steps include `rename_keys`, `drop_keys`, `filter`,
`replace_values`, and `select_keys`. Check the model schema or
[process-file-data docs](https://natlabrockies.github.io/r2x-core/how-tos/process-file-data/)
for exact arguments and validation.

## Derived and optional sources

A `DataFile` may refer to one earlier source, select among earlier sources, or
own a typed inline table. Do not combine these modes with a physical path or
with one another:

```python
from r2x_core import DataFile, InlineTable, SourceSelection

fallback = DataFile(
    name="defaults",
    inline_table=InlineTable.model_validate({
        "schema": {"year": "int64", "technology": "string"},
        "rows": [{"year": 2030, "technology": "wind"}],
    }),
)
selected = DataFile(
    name="costs",
    source_selection=SourceSelection(
        mode="first_nonempty", sources=["market_costs", "defaults"]
    ),
)
```

`first_present` selects the first present source even if it has no rows.
`first_nonempty` skips absent and empty sources. Declare candidates before the
selector. `source` refers to one earlier named source. `inline_table` declares a
strict raw schema and rows before `proc_spec` runs. Whole-value placeholders
preserve their JSON type; embedded placeholders in strings become text. Missing
placeholder names raise `ValueError`.

For optional physical inputs, `FileInfo(requirement=FileRequirement.OPTIONAL)`
allows a missing file or configured HDF5 group. Without declared `columns`, an
absent optional input is omitted from the returned mapping. With declared
columns, it is returned as an empty typed `TabularSource` marked
`SourceAvailability.ABSENT`. A present-empty source is distinct from an absent
one. Malformed present input is not silently skipped.

`required_when` applies only to optional physical files. It names an earlier
tabular source plus a typed expression predicate; the file is required when any
row matches. Do not use `required_when` to mask malformed present data.

## Failure playbook

- **Path source validation fails:** set exactly one physical path or one derived
  source mode. Do not set `reader.format` or `reader.options` on a derived source.
- **File type cannot be inferred:** check the filename extension or set
  `reader.format` to a registered symbolic reader name.
- **Glob resolution fails:** include a wildcard and ensure exactly one file
  matches under `folder_path`.
- **Optional input appears missing downstream:** check whether `DataFile.columns`
  is declared. Without it, an absent optional input has no returned source.
- **Processing fails:** check the `proc_spec.kind`, each step's `op` and field
  names, the current columns, and any placeholders.
- **HDF5 reader rejects an option:** verify the exact `H5PyReaderOptions` schema;
  unknown options and wrong types are errors.
- **Mapping load fails:** use a JSON array of valid `DataFile` records and call
  `store.load_file_mapping(Path(...))`.

## Source modules

- `r2x_core.datafile`: `DataFile`, `FileInfo`, `ReaderConfig`, inline/selected
  sources, and native columns.
- `r2x_core.types` and `r2x_core.models`: processing discriminators and steps.
- `r2x_core.reader`: ordered source loading and reader selection.
- `r2x_core.file_reader`: reader protocol and typed source representations.
- `r2x_core.store`: mapping configuration and JSON serialization.
- `r2x_core.processors`: placeholder substitution.
- `r2x_core.utils.files`: path and glob resolution.
- `r2x_core.h5py_adapter.readers` and `r2x_core.polars_adapter.readers`: built-in
  HDF5, CSV/TSV, and Parquet reader options.
