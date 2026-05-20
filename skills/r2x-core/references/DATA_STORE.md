# r2x-core Data Files and DataStore Reference

Use this when the task is about declaring files, loading files, processing
payloads, or wiring a translator's input data through `DataFile`, `DataReader`,
and `DataStore`.

## Contracts (source-verified)

- `DataFile(name, *, fpath=None, relative_fpath=None, glob=None, info=None, reader=None, proc_spec=None)`
- `DataFile` must set exactly one path source: `fpath`, `relative_fpath`, or
  `glob`.
- `FileInfo(description=None, is_input=True, is_optional=False, is_timeseries=False, units=None)`
- `ReaderConfig(kwargs: dict[str, Any] = ..., function: Callable[[Path], Any] | None = None)`
- `TabularProcessing(...)` declares many fields, but current tabular execution
  applies only lowercase, drop, rename, pivot, cast, filter, and select unless
  source has added more transformations.
- `JSONProcessing(...)` supports key mapping, key selection/drop, filtering, and
  value replacement specs.
- `DataReader.read_data_file(data_file, *, folder_path, placeholders=None) -> Any`
- `DataReader.get_supported_file_types() -> list[str]`
- `DataStore(path=None, *, reader=None, upgrade_handler=None)`
- `DataStore.add_data(data_files: Sequence[DataFile], *, overwrite=False) -> None`
- `DataStore.read_data(name, *, placeholders=None) -> Any`
- `DataStore.from_json(json_fpath, *, path=None, upgrade_handler=None) -> DataStore`
- `DataStore.load_file(fpath, *, name=None, proc_spec=None) -> Any`

## Do

- Treat `DataFile` as the contract for where a file is and how to read/process
  it.
- Use `relative_fpath` for files resolved under a `DataStore(path=...)` root.
- Use `fpath` for already-resolved absolute or explicit paths.
- Use `glob` only when one matching file is expected.
- Put parser options in `ReaderConfig(kwargs=...)`.
- Put declarative transformations in `proc_spec`, not in ad-hoc plugin code.
- Use `FileInfo` for metadata, optional files, time-series hints, and units.
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
        is_input=True,
        units="MW",
    ),
)
```

`DataFile.file_type` is computed from the path extension. Supported extensions
come from `DataReader.get_supported_file_types()`.

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
    proc_spec=TabularProcessing(drop_columns=["scratch_column"]),
)
```

Use a full `DataStore` when the translator has multiple named files, optional
inputs, placeholders, or an upgrade handler.

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
    name="legacy_csv",
    relative_fpath="legacy.csv",
    reader=ReaderConfig(kwargs={"separator": "|"}),
)
```

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
    filter_by={"region": "north"},
    column_mapping={"old_name": "new_name"},
    drop_columns=["unused"],
    column_schema={"capacity": "float64"},
)

data_file = DataFile(
    name="north_generators",
    relative_fpath="generators.csv",
    proc_spec=processing,
)
```

The tabular pipeline lowercases string values and column names before applying
other transformations. Use lowercase column names and string filter values in
`proc_spec` unless source behavior changes.

Currently executed fields in the tabular pipeline are `drop_columns`,
`column_mapping`, `pivot_on`, `column_schema`, `filter_by`, and
`select_columns` (after automatic lowercasing). Other declared fields may
validate without being executed; inspect `r2x_core.processors` before relying on
one.

## JSONProcessing

```python
from r2x_core import DataFile, JSONProcessing

json_file = DataFile(
    name="metadata",
    relative_fpath="metadata.json",
    proc_spec=JSONProcessing(
        key_mapping={"old_key": "new_key"},
        select_keys=["new_key", "scenario"],
    ),
)
```

Common fields: `key_mapping`, `rename_index`, `drop_keys`, `filter_by`,
`replace_values`, `select_keys`. Do not use `drop_columns` for JSON configs;
the public field is `drop_keys`.

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
may fall back to the first dataset. Verify exact accepted kwargs against
`r2x_core.file_readers`, `r2x_core.h5_readers`, and project fixture tests. Do
not poke raw HDF5 datasets inside plugin code if a `DataFile` reader config can
express it.

## Optional files

```python
from r2x_core import DataFile, FileInfo

optional = DataFile(
    name="optional_overrides",
    relative_fpath="overrides.csv",
    info=FileInfo(is_optional=True, description="Optional override file"),
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

## Custom transformations

`DataReader.register_custom_transformation(...)` delegates to the processing
pipeline. Source currently calls transforms as:

```python
def transform(data, *, data_file, proc_spec):
    ...
```

Verify the callable signature against `r2x_core.processors.apply_processing`
before registering custom transformations; reader docstrings may lag this
internal call shape.

## Placeholders in processing specs

`DataReader.read_data_file(..., placeholders=...)` and
`DataStore.read_data(..., placeholders=...)` pass placeholder values into the
processing pipeline. Use this for parameterized filters, for example model year
or scenario values.

```python
store.read_data("regional_loads", placeholders={"solve_year": 2030})
```

Keep placeholders at read boundaries; do not string-format file mappings in
plugin internals unless the DataFile/reader layer cannot express the case.

## JSON mapping files

`DataStore.from_json(...)` loads a JSON array of `DataFile` records.

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
    "proc_spec": { "filter_by": { "year": 2030 } }
  }
]
```

Important source detail: `DataFile.from_record(...)`, used by
`DataStore.from_json(...)`, currently reads the JSON record's `fpath` and
resolves it against the store folder. For JSON mapping files, prefer `fpath`
records unless source changes. Direct Python construction can still use
`relative_fpath`.

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
  - For optional files, confirm `info=FileInfo(is_optional=True)`.
- File type cannot be determined:
  - Ensure the filename or glob has a supported extension.
  - Check `DataReader().get_supported_file_types()`.
- Processing returns zero rows unexpectedly:
  - Remember the tabular pipeline lowercases string values and column names
    before filtering. Try lowercase filter values such as `"north"`.
- Processing fails:
  - Validate `proc_spec` field names against `TabularProcessing` or
    `JSONProcessing`.
  - Pass required `placeholders` at read time.
- JSON mapping load fails:
  - Confirm the mapping file is a JSON array.
  - Confirm each record has `fpath` for current `from_record(...)` behavior.

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
