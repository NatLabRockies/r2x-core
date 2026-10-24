# r2x-core Data Files and DataStore Reference

Use this when the task is about declaring files, loading files, processing
payloads, or wiring a translator's input data through `DataFile`, `DataReader`,
and `DataStore`.

## Contracts (source-verified)

- `DataFile(name, *, fpath=None, relative_fpath=None, glob=None, info=None, reader=None, proc_spec=None)`
- Physical `DataFile` records set exactly one of `fpath`, `relative_fpath`, or
  `glob`; named-source records use `source` instead.
- `FileInfo(description=None, file_type=FileType.STATIC, requirement=FileRequirement.REQUIRED, units=None)`
- `ReaderConfig(format: str | None = None, options: dict[str, JSONValue] = {})`
- `TabularProcessing(kind="tabular", steps=[...])` and
  `JSONProcessing(kind="json", steps=[...])` execute typed operations in order.
- `DataReader(file_readers: Mapping[str, FileReader] | None = None)`
- `DataReader.read_data_files(data_files, *, folder_path, placeholders=None) -> DecodedSources`
- `DataStore(path: str | Path | None = None)` manages mapping configuration.
- `DataStore.add_data(data_files: Sequence[DataFile], *, overwrite=False) -> None`
- `DataStore.load_file_mapping(mapping_path: Path) -> None`
- `DataStore.to_json(fpath, **model_dump_kwargs) -> None`

## Do

- Treat `DataFile` as the contract for where a file is and how to read/process
  it.
- Use `relative_fpath` for files resolved under a `DataStore(path=...)` root.
- Use `fpath` for already-resolved absolute or explicit paths.
- Use `glob` only when one matching file is expected.
- Put parser options in `ReaderConfig(options=...)` and select a registered
  reader with `ReaderConfig(format=...)` when extension inference is not enough.
- Put declarative transformations in `proc_spec`, not in ad-hoc plugin code.
- Use `FileInfo` for descriptive metadata, static/time-series semantics,
  availability requirements, and units.
- Pass a sequence to `DataStore.add_data([...])`, even for one file.
- Use `DataReader.read_data_files(...)` to load named sources; `DataStore`
  stores mapping configuration and does not read files.

## Don't

- Do not pass `DataFile(reader_config=..., processing=..., file_info=...)`;
  current fields are `reader`, `proc_spec`, and `info`.
- Do not call `DataStore.add_data(file_a, file_b)`; pass a sequence.
- Do not assume `DataStore.path` exists; use `store.folder`.
- Do not rely on `DataStore` caching loaded payloads. It caches `DataFile`
  configurations; reads go through `DataReader`.
- Do not bypass `DataStore` inside plugins just to call pandas/polars directly.
  Configure the `DataFile` instead.

## Basic DataFile

```python
from pathlib import Path

from r2x_core import DataFile, FileInfo

file_spec = DataFile(
    name="generators",
    fpath=Path("/data/reeds/generators.csv"),
    info=FileInfo(
        description="Generator capacity data",
        units="MW",
    ),
)
```

`DataFile.format_name` uses an explicit `reader.format` first, then infers an
unambiguous format from the path extension. `FileInfo.file_type` separately
describes static versus time-series data. For custom formats, register a
`FileReader` under the chosen symbolic name in `DataReader(file_readers=...)`.

## DataStore with relative paths

```python
from r2x_core import DataFile, DataStore

store = DataStore(path="/data/reeds")
store.add_data([
    DataFile(name="generators", relative_fpath="gen.csv"),
    DataFile(name="loads", relative_fpath="load.parquet"),
])

assert store.folder.name == "reeds"
assert store.list_data() == ["generators", "loads"]

from r2x_core import DataReader

sources = DataReader().read_data_files(
    [store["generators"], store["loads"]], folder_path=store.folder
)
```

`relative_fpath` resolves against `store.folder` when read by `DataReader`. A
missing required path raises `FileNotFoundError`; optional inputs are omitted
from the returned source mapping. An upgrade handler is configured through
`DataStore.configure_upgrades(plugin_config=..., upgrade_handler=...)` or
`PluginConfig.upgrade_handler`. It receives keyword-only `store` and `ctx`.

## DataReader direct reads

```python
from pathlib import Path

from r2x_core import DataFile, DataReader

reader = DataReader()
data_file = DataFile(name="generators", relative_fpath="generators.csv")
source = reader.read_data_files([data_file], folder_path=Path("/data/reeds"))["generators"]
```

The returned value is a typed `DecodedSource` such as `TabularSource` or
`DocumentSource`, not a bare payload. Use `source.data` for the native
representation and source methods for fields, rows, and values.

## ReaderConfig

Use `ReaderConfig` to select a symbolic reader and provide reader-specific options.

```python
from r2x_core import DataFile, ReaderConfig

csv_file = DataFile(
    name="pipe_csv",
    relative_fpath="pipe.csv",
    reader=ReaderConfig(options={"separator": "|"}),
)

profile_file = DataFile(
    name="profiles",
    relative_fpath="profiles.csv",
    reader=ReaderConfig(options={"header_rows": 2, "header_separator": "|"}),
)
```

The built-in Polars CSV/TSV reader validates its configured options. Custom
readers receive `ReaderConfig` and validate their own option schema. See
[Custom Readers](../../../docs/src/content/docs/how-tos/custom-readers-and-backends.md)
for the public `FileReader` registration contract.

## TabularProcessing

Use `TabularProcessing` with the built-in tabular readers for CSV, TSV,
Parquet, and HDF5. Other built-in formats are `json`, `xml`, and `hdf5_array`.

```python
from r2x_core import DataFile, TabularProcessing

processing = TabularProcessing(
    steps=[
        {"op": "filter_columns", "filter_by": {"region": "north"}},
        {"op": "rename_columns", "column_mapping": {"old_name": "new_name"}},
        {"op": "drop_columns", "drop_columns": ["unused"]},
        {"op": "cast_columns", "column_schema": {"capacity": "float"}},
    ]
)

data_file = DataFile(
    name="north_generators",
    relative_fpath="generators.csv",
    proc_spec=processing,
)
```

Input case is preserved by default. Add a `lowercase` step where it belongs in
the declared order. See the processor reference for all operation schemas,
validation rules, and placeholder behavior. For CSV/TSV files,
`ReaderConfig(options={"header_rows": 2, "header_separator": "|"})` combines two header rows.

## JSONProcessing

```python
from r2x_core import DataFile, JSONProcessing

json_file = DataFile(
    name="metadata",
    relative_fpath="metadata.json",
    proc_spec=JSONProcessing(
        steps=[
            {"op": "rename_keys", "mapping": {"old_key": "new_key"}},
            {"op": "select_keys", "keys": ["new_key", "scenario"]},
        ]
    ),
)
```

JSON step operations are `rename_keys`, `drop_keys`, `filter`,
`replace_values`, and `select_keys`. Replacement values use a typed list of
`{"old": scalar, "new": JSON value}` records. For example:

```python
JSONProcessing(steps=[
    {"op": "replace_values", "replacements": [
        {"old": 0, "new": "missing"},
        {"old": True, "new": "enabled"},
    ]},
])
```

JSON matching is recursive and exact by JSON scalar type: booleans do not match
numbers, while numerically equal integers and floats do. Null filters require
the key to exist. Duplicate matching replacement sources and non-finite
replacement numbers are rejected. The former dictionary replacement shape is
not supported.

## HDF5 files

HDF5 files use the built-in `hdf5` tabular reader or `hdf5_array` reader.
Configure row-oriented data with an explicit `data_key`; `columns_key` can
provide labels for its matrix columns. For columnar groups where each column is
a separate dataset, set `columns_as_datasets=True` and `columns_key` to the
label dataset. Use `group_key` to select a group.

```python
from r2x_core import DataFile, ReaderConfig

row_table = DataFile(
    name="load_profiles",
    relative_fpath="profiles.h5",
    reader=ReaderConfig(
        format="hdf5",
        options={"data_key": "data", "columns_key": "columns"},
    ),
)
columnar_table = DataFile(
    name="columns",
    relative_fpath="profiles.h5",
    reader=ReaderConfig(
        format="hdf5",
        options={"columns_as_datasets": True, "columns_key": "columns"},
    ),
)
```

Other HDF5 options include `index_names_key`, `index_key`, `datetime_key`,
`datetime_column_name`, `strip_timezone`, `additional_keys`, `decode_bytes`,
and `column_name_mapping`. Options are strictly validated, and unknown names,
empty `data_key` values, and non-boolean boolean options are rejected. Verify
option details against `r2x_core.h5_adapter.readers` and its fixture tests.

## Optional files

```python
from r2x_core import DataFile, FileInfo, FileRequirement

optional = DataFile(
    name="optional_overrides",
    relative_fpath="overrides.csv",
    info=FileInfo(requirement=FileRequirement.OPTIONAL, description="Optional override file"),
)
```

When read through `DataReader`, missing optional files are omitted from the
returned source mapping. Required missing files raise `FileNotFoundError`.

## Glob patterns

```python
from r2x_core import DataFile

file_spec = DataFile(name="scenario", glob="scenario_*.csv")
```

A glob must include enough extension information to detect file type. Runtime
resolution expects exactly one match; no matches or multiple matches are errors.

## Custom readers and processing backends

Register app-specific file readers by symbolic format name:

```python
reader = DataReader(file_readers={"vendor": my_file_reader})
```

A `FileReader` returns named `DecodedSource` objects. For a native table
representation, implement `TabularProcessor[Payload]` and pair it with a
`TabularSource`. The built-in Polars reader and processor are loaded only when
those defaults are used. See `r2x_core.file_reader` and
`docs/src/content/docs/how-tos/custom-readers-and-backends.md`.

## Placeholders in paths and processing specs

`DataReader.read_data_files(..., placeholders=...)` substitutes placeholders
in path sources and processing values. Whole-value placeholders preserve their
type; embedded placeholders in strings become text. Unknown names raise an
error.

```python
from pathlib import Path
from r2x_core import DataFile, DataReader

file_spec = DataFile(name="scenario_loads", relative_fpath="{scenario}_loads.csv")
sources = DataReader().read_data_files(
    [file_spec],
    folder_path=Path("/data"),
    placeholders={"scenario": "Reference"},
)
```

Keep placeholders at read boundaries; do not format file mappings in plugin
internals.

## JSON mapping files

`DataStore.load_file_mapping(...)` loads a JSON array of `DataFile` records.
Metadata belongs in `info`, and processing specs include the `kind` tag and
ordered `steps` list.

```json
[
  {
    "name": "generators",
    "fpath": "gen_data.csv",
    "info": { "description": "Generator capacity data", "units": "MW" }
  },
  {
    "name": "loads",
    "fpath": "load_data.csv",
    "proc_spec": {
      "kind": "tabular",
      "steps": [
        { "op": "filter_columns", "filter_by": { "year": 2030 } }
      ]
    }
  }
]
```

A physical record defines exactly one of `fpath`, `relative_fpath`, or `glob`.
Named-source processing records instead name a prior source. Physical paths
resolve against the folder passed to `DataReader`; glob patterns are resolved
at read time. Path sources and processing values accept placeholders.

## Serialization

Persist a configured store with `to_json(...)`:

```python
store.to_json("file_mapping.json")
loaded = DataStore(path=store.folder)
loaded.load_file_mapping(Path("file_mapping.json"))
```

`to_json` writes a JSON array of configured records. Avoid hand-written JSON
unless you need a stable external config artifact.

## Failure playbook

- `DataFile` validation says path sources are invalid:
  - Ensure exactly one of `fpath`, `relative_fpath`, or `glob` is set.
- `store[name]` raises `KeyError`:
  - Check `store.list_data()` and the configured input name.
- File not found:
  - Inspect `store.folder` and the configured `DataFile` path source.
  - For optional files, confirm `info=FileInfo(requirement=FileRequirement.OPTIONAL)`.
- File type cannot be determined:
  - Ensure the filename or glob has a supported extension.
  - Check `DataFile.format_name` and the selected reader registration.
- Processing returns zero rows unexpectedly:
  - Case is preserved unless `lowercase=True`; check filter values against the
    input and configured casing.
- Processing fails:
  - Validate `proc_spec` field names against `TabularProcessing` or
    `JSONProcessing`.
  - Check the documented tabular operation order and referenced columns.
  - Pass required `placeholders` at read time. Placeholders can parameterize
    filter and tabular transformation values.
- JSON mapping load fails:
  - Confirm the mapping file is a JSON array.
  - Confirm each record defines exactly one of `fpath`, `relative_fpath`, or
    `glob`.

## Source modules and docs to verify on drift

- `r2x_core.datafile`: `DataFile`, `FileInfo`, `ReaderConfig`, processing specs.
- `r2x_core.reader`: `DataReader`, read pipeline, supported formats.
- `r2x_core.processors`: transformation order and placeholder substitution.
- `r2x_core.store`: `DataStore` and JSON mappings.
- `r2x_core.utils.files`: path/glob resolution.
- Docs: `how-tos/configure-data-files/`, `how-tos/read-data-files/`,
  `how-tos/configure-data-settings/`.

## Output expectations

- Registered `DataFile` names and path source (`fpath`, `relative_fpath`,
  `glob`, or a named `source`).
- Resolved `DataStore.folder` and relevant file paths.
- Reader configuration per file, including symbolic format and options.
- Processing specs applied (`TabularProcessing` / `JSONProcessing`).
- Optional/glob/placeholder behavior if used.
- HDF5 layout details when relevant.
