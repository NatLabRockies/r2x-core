# r2x-core Data Files and DataStore Reference

Use this when the task is about declaring files, loading files, processing
payloads, or wiring a translator's input data through `DataFile`, `DataReader`,
and `DataStore`.

## Contracts (source-verified)

- `DataFile(name, *, fpath=None, relative_fpath=None, glob=None, info=None, reader=None, proc_spec=None)`
- `DataFile` must set exactly one path source: `fpath`, `relative_fpath`, or
  `glob`.
- `FileInfo(description=None, file_type=FileType.STATIC, requirement=FileRequirement.REQUIRED, units=None)`
- `ReaderConfig(kwargs: dict[str, Any] = ..., function: Callable[..., Any] | None = None)`
- `TabularProcessing(kind="tabular", steps=[...])` executes typed tabular
  operations in their declared order.
- `JSONProcessing(kind="json", steps=[...])` executes JSON-specific operations
  in their declared order.
- `DataReader.read_data_file(data_file, *, folder_path, placeholders=None) -> Any`
- `DataReader.get_supported_file_types() -> list[str]`
- `DataStore(path=None, *, reader=None)`
- `DataStore.add_data(data_files: Sequence[DataFile], *, overwrite=False) -> None`
- `DataStore.read_data(name, *, placeholders=None) -> Any`
- `DataStore.from_json(json_fpath, *, path=None) -> DataStore`
- `DataStore.load_file(fpath, *, name=None, proc_spec=None) -> Any`

## Do

- Treat `DataFile` as the contract for where a file is and how to read/process
  it.
- Use `relative_fpath` for files resolved under a `DataStore(path=...)` root.
- Use `fpath` for already-resolved absolute or explicit paths.
- Use `glob` only when one matching file is expected.
- Put parser options in `ReaderConfig(kwargs=...)`.
- Put declarative transformations in `proc_spec`, not in ad-hoc plugin code.
- Use `FileInfo` for descriptive metadata, static/time-series semantics,
  availability requirements, and units.
- Pass a sequence to `DataStore.add_data([...])`, even for one file.
- Use `DataReader` directly for low-level reads and `DataStore` for translator
  workflows with multiple named inputs.
- Use `DataStore.load_file(...)` for a one-off file read.

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

`DataFile.file_format` is computed from the path extension. `FileInfo.file_type`
separately describes static versus time-series data. Supported extensions come
from `DataReader.get_supported_file_types()`.

```python
from r2x_core import DataReader

reader = DataReader()
assert ".csv" in reader.get_supported_file_types()
```

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
generators = store.read_data("generators")
```

`relative_fpath` resolves against `store.folder` at read time. If the path is
missing and the file is not optional, `read_data(...)` raises.

## One-off reads

For quick scripts or tests, use `DataStore.load_file(...)`:

```python
from r2x_core import DataStore, TabularProcessing

data = DataStore.load_file(
    "/data/reeds/gen.csv",
    proc_spec=TabularProcessing(
        steps=[{"op": "drop_columns", "drop_columns": ["scratch_column"]}]
    ),
)
```

Use a full `DataStore` when the translator has multiple named files, optional
inputs, placeholders, or an upgrade handler. Configure upgrades through
`PluginConfig.upgrade_handler` or `DataStore.from_plugin_config(...,
upgrade_handler=...)`; handlers receive both `store` and `ctx` keyword arguments.

## DataReader direct reads

```python
from pathlib import Path

from r2x_core import DataFile, DataReader

reader = DataReader()
data_file = DataFile(name="generators", relative_fpath="generators.csv")
df = reader.read_data_file(data_file, folder_path=Path("/data/reeds"))
```

Use this for low-level tests of a single `DataFile`. Prefer `DataStore` inside
translator code.

## ReaderConfig

Use `ReaderConfig` for parser kwargs or a custom reader function.

```python
from r2x_core import DataFile, ReaderConfig

csv_file = DataFile(
    name="pipe_csv",
    relative_fpath="pipe.csv",
    reader=ReaderConfig(kwargs={"separator": "|"}),
)

profile_file = DataFile(
    name="profiles",
    relative_fpath="profiles.csv",
    reader=ReaderConfig(kwargs={"header_rows": 2, "header_separator": "|"}),
)
```

The built-in Polars CSV/TSV reader validates header options in `kwargs`.
Custom readers receive kwargs and define their own behavior.

Custom functions receive the resolved path plus any kwargs:

```python
from pathlib import Path
from typing import Any

from r2x_core import DataFile, ReaderConfig


def read_special(path: Path, *, scale: float) -> dict[str, Any]:
    return {"path": path, "scale": scale}

special = DataFile(
    name="special",
    relative_fpath="special.dat",
    reader=ReaderConfig(function=read_special, kwargs={"scale": 100.0}),
)
```

## TabularProcessing

Use `TabularProcessing` to transform CSV, TSV, Parquet, Excel-like, or HDF5
payloads after reading.

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
`ReaderConfig(kwargs={"header_rows": 2, "header_separator": "|"})` combines two header rows.

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
`replace_values`, and `select_keys`. Each step uses an `op` discriminator and
has only the fields relevant to that operation.

## HDF5 files

HDF5 files are detected from `.h5` / `.hdf5`. Configure the dataset/layout with
`ReaderConfig(kwargs=...)`.

```python
from r2x_core import DataFile, ReaderConfig

h5_file = DataFile(
    name="load_profiles",
    relative_fpath="profiles.h5",
    reader=ReaderConfig(kwargs={"data_key": "load_profiles"}),
)
```

Useful HDF5 kwargs from current docs/source include `data_key`, `columns_key`,
`index_key`, `datetime_key`, `datetime_column_name`, `strip_timezone`,
`additional_keys`, and `decode_bytes`. If no `data_key` is set, current readers
may fall back to the first dataset. Verify exact accepted kwargs against the
`H5PyFileReader` adapter, `r2x_core.polars_adapter.readers`, and project fixture
tests. Do not poke raw HDF5 datasets inside plugin code if a `DataFile` reader
config can express it.

## Optional files

```python
from r2x_core import DataFile, FileInfo, FileRequirement

optional = DataFile(
    name="optional_overrides",
    relative_fpath="overrides.csv",
    info=FileInfo(requirement=FileRequirement.OPTIONAL, description="Optional override file"),
)
```

When read through `DataReader` / `DataStore`, missing optional files return
`None` instead of raising. Required missing files raise `FileNotFoundError`.

## Glob patterns

```python
from r2x_core import DataFile

file_spec = DataFile(name="scenario", glob="scenario_*.csv")
```

A glob must include enough extension information to detect file type. Runtime
resolution expects exactly one match; no matches or multiple matches are errors.

## Custom readers and processing backends

Provide app-specific adapters to `DataReader` rather than registering global
transform functions:

```python
reader = DataReader(
    file_readers=[my_file_reader],
    tabular_backend=my_tabular_backend,
    json_processor=my_json_processor,
)
```

Polars is a runtime dependency for the built-in tabular reader and backend, but
is imported only when those defaults are used. Implement `FileReader` for a
supported file format, `TabularBackend` for a non-default tabular representation,
or `JSONProcessor` for custom JSON processing. Injected adapters remain
independent of the Polars implementation. See `r2x_core.file_reader`,
`r2x_core.tabular_backend`, and `r2x_core.json_adapter` for their contracts.

## Placeholders in paths and processing specs

`DataReader.read_data_file(..., placeholders=...)` and
`DataStore.read_data(..., placeholders=...)` substitute placeholders in path
sources and processing values. Whole-value placeholders preserve their type;
embedded placeholders in strings become text. Unknown names return an error.

```python
file_spec = DataFile(
    name="scenario_loads",
    relative_fpath="{scenario}_loads.csv",
)
store.read_data("scenario_loads", placeholders={"scenario": "Reference"})
```

Keep placeholders at read boundaries; do not format file mappings in plugin
internals.

## JSON mapping files

`DataStore.from_json(...)` loads a JSON array of `DataFile` records. Metadata
belongs in `info`, and processing specs include the `kind` tag and ordered
`steps` list.

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

Each record must define exactly one path source. `fpath` and `relative_fpath`
records resolve against the store folder; `glob` patterns pass through for
resolution at read time. All three path sources accept placeholders.

## Serialization

Persist a configured store with `to_json(...)`:

```python
store.to_json("file_mapping.json")
loaded = DataStore.from_json("file_mapping.json", path=store.folder)
```

Use `mode="json"` defaults from `DataStore.to_json(...)`; avoid hand-written
JSON unless you need a stable external config artifact.

## Failure playbook

- `DataFile` validation says path sources are invalid:
  - Ensure exactly one of `fpath`, `relative_fpath`, or `glob` is set.
- `read_data(name)` raises `KeyError`:
  - Check `store.list_data()` and spelling.
- File not found:
  - Inspect `store.folder` and the configured `DataFile` path source.
  - For optional files, confirm `info=FileInfo(requirement=FileRequirement.OPTIONAL)`.
- File type cannot be determined:
  - Ensure the filename or glob has a supported extension.
  - Check `DataReader().get_supported_file_types()`.
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
- `r2x_core.store`: `DataStore`, JSON mappings, one-off loads.
- `r2x_core.utils._datafile`: path/glob resolution.
- Docs: `how-tos/configure-data-files.html`, `how-tos/read-data-files.html`,
  `how-tos/configure-data-settings.html`.

## Output expectations

- Registered `DataFile` names and path source (`fpath`, `relative_fpath`, or
  `glob`).
- Resolved `DataStore.folder` and relevant file paths.
- Reader configuration per file, including custom functions or kwargs.
- Processing specs applied (`TabularProcessing` / `JSONProcessing`).
- Optional/glob/placeholder behavior if used.
- HDF5 layout details when relevant.
