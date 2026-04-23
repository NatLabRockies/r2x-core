# r2x-core DataStore Reference

Use this document when the task is about ingesting input files into a
translator: `DataStore`, `DataFile`, readers, processors, and HDF5 layout.

## Scope in this skill

This reference covers:

- `DataStore` and `DataFile` registration model
- `FileFormat` selection and `ReaderConfig`
- `TabularProcessing` and `JSONProcessing` post-read transforms
- `H5Format` and the `r2x_core.h5_readers` configurable HDF5 reader
- Caching and component tracking through the store

## Mental model

- The `DataStore` is the **single ingress point** for all source files. A
  plugin should never read raw files directly; it should always go through
  a registered `DataFile`.
- A `DataFile` declares **what** the file is (name, path) and **how** to
  read it (format, reader config, optional processing).
- Format detection is automatic for common extensions, but explicit
  `ReaderConfig` is preferred whenever the layout deviates from defaults.

## Minimal DataStore

```python
from r2x_core import DataStore, DataFile

store = DataStore(path="/data/reeds")
store.add_data(
    DataFile(name="generators", fpath="gen.csv"),
    DataFile(name="loads", fpath="load.parquet"),
)

gen_df = store.read_data("generators")
names = store.list_data()
store.remove_data("generators")
```

`DataStore.path` is the root for resolving each `DataFile.fpath`. Keep
relative paths in `DataFile`; let `DataStore.path` decide the absolute
location.

## DataFile fields

Common fields (verify against installed `r2x_core.datafile` source if
behavior drifts):

- `name`: logical key used in `DataStore.read_data(name)`.
- `fpath`: relative path under `DataStore.path`.
- `reader_config`: a `ReaderConfig` describing format and parser options.
- `processing`: optional `TabularProcessing` / `JSONProcessing` to run after
  read.
- `file_info`: metadata about the file (`FileInfo`).

## ReaderConfig

Use `ReaderConfig` when defaults from the file extension are insufficient:
non-standard delimiters, custom headers, partial column reads, type
overrides, sheet selection, etc.

```python
from r2x_core import DataFile, ReaderConfig

DataFile(
    name="generators",
    fpath="gen.csv",
    reader_config=ReaderConfig(
        delimiter=";",
        header=0,
        usecols=["name", "capacity", "zone"],
        dtype={"capacity": "float64"},
    ),
)
```

(Field names track the installed version; confirm via source.)

## TabularProcessing and JSONProcessing

`TabularProcessing` is a declarative post-read step for tabular payloads:
column renames, filters, type coercion. Prefer this over ad-hoc DataFrame
mutation in plugin code.

`JSONProcessing` plays the same role for JSON payloads (path extraction,
flattening, normalization).

```python
from r2x_core import DataFile, TabularProcessing

DataFile(
    name="generators",
    fpath="gen.csv",
    processing=TabularProcessing(
        rename={"cap_mw": "capacity"},
        filter="status == 'active'",
    ),
)
```

## FileFormat and explicit readers

`FileFormat` enumerates supported formats. Use it when you need to be
explicit (e.g., a `.dat` file that is actually CSV):

```python
from r2x_core import DataFile, FileFormat, ReaderConfig

DataFile(
    name="legacy",
    fpath="legacy.dat",
    reader_config=ReaderConfig(format=FileFormat.CSV, delimiter="|"),
)
```

For low-level reads outside the store (rare), use the helpers in
`r2x_core.file_readers`.

## HDF5 layout: H5Format and `h5_readers`

HDF5 access goes through the configurable reader in `r2x_core.h5_readers`.
Declare layout intent with `H5Format` (or the equivalent typed config in
your installed version) instead of poking dataset paths from plugin code.

```python
from r2x_core import DataFile, H5Format

DataFile(
    name="capacity_factor",
    fpath="cf.h5",
    reader_config=ReaderConfig(
        format=FileFormat.HDF5,
        h5_format=H5Format(
            dataset="/data/capacity_factor",
            index="/index/timestamps",
            columns="/index/regions",
        ),
    ),
)
```

The configurable reader supports flexible HDF5 layouts (separate
index/columns datasets, time-indexed arrays, group-per-variable layouts).
Confirm exact field names against `r2x_core.h5_readers` source.

## Caching and component tracking

`DataStore` caches read payloads and tracks component-producing reads. This
matters when the same file backs multiple rules:

- The first `read_data(name)` materializes and caches.
- Subsequent reads of the same name return the cached payload.
- If you mutate the returned payload in place, you mutate the cache. Copy
  before mutating, or perform mutation through `TabularProcessing` so the
  store-managed payload stays canonical.

## Failure playbook

- `read_data(name)` raises `KeyError`:
  - Verify the name was registered via `add_data(...)`.
- `read_data` raises file-not-found:
  - Verify `DataFile.fpath` resolves under `DataStore.path`.
  - Run `tools/check_data_store.py` to enumerate registered files and
    formats.
- Wrong column types:
  - Provide explicit `dtype` in `ReaderConfig`; do not rely on inference.
- HDF5 reader returns wrong shape:
  - Confirm `H5Format` dataset/index/columns paths match the file layout.
  - Use `h5dump` or `h5py` interactively to verify dataset paths exist.
- Cache returns stale data after the underlying file changed:
  - Re-create the `DataStore` (caches are per-instance) or call the
    explicit invalidation API exposed by your version of `DataStore`.

## Validation tooling

- `tools/check_data_store.py <path-to-data-folder>` enumerates files in the
  directory, classifies them by extension, and warns when an extension is
  not in the supported `FileFormat` set.

## Output expectations

- Registered `DataFile` names and their resolved paths.
- Reader configuration per file (format, options).
- Any `TabularProcessing` / `JSONProcessing` applied.
- HDF5 layout details when relevant.
- Cache and mutation considerations for shared payloads.
