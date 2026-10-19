# Configuring Data Settings

Define physical files and prepared tables in `file_mapping.json`, then load the
configuration into a {py:class}`~r2x_core.DataStore`. Physical files describe
how to read and process individual inputs. Runtime sources name generated,
configured-record, first-present, or System-projected frames. Prepared tables
declare explicit joins and tabular processing for a named result.

## Define files and prepared tables

A file-mapping document has `files`, `sources`, and `tables` lists. Join keys
map left column names to right column names. Join payloads map right source columns to
their output names. A table source or join source may name a physical file,
another prepared table, or a declared `frame_sources` input. Supply named frames
with `DataStore.prepare_table(name, inputs=...)`; transitive frame inputs may be
provided at the top-level call. All sources use the same join and processing
executor.

```json
{
  "files": [
    {"name": "generators", "relative_fpath": "gen_data.csv"},
    {"name": "regions", "relative_fpath": "regions.csv"}
  ],
  "sources": [],
  "tables": [
    {
      "name": "generator_details",
      "source": "generators",
      "required_columns": ["name", "capacity", "region_name"],
      "joins": [
        {
          "source": "regions",
          "on": {"zone": "id"},
          "columns": {"name": "region_name"}
        }
      ]
    }
  ]
}
```

`non_null_columns` optionally names output columns that must contain no nulls.
Each name must also appear in `required_columns`. A null output raises a named
prepared-table error after processing.

An `m:1` join rejects null keys and duplicate right-side keys by default.
Configure `select_first` only when a representative row is intentional. With no
`order_by`, the first source row is retained. With `order_by`, rows are stably
sorted before selecting the first row for each join key. A backward `asof` join
uses `asof.left_on` and `asof.right_on`, rejects duplicate temporal keys, and
preserves left row order. `right_filter` applies typed predicates before joining.
Set `allow_null_left_keys` when null left keys should remain unmatched.

A missing physical root marked optional by `FileInfo` makes its prepared table
return `None` before reading joins. That absence propagates through tables that
use it as their root. Each join independently sets `missing_source` to `error`
(the default), `skip`, or `null`. `skip` leaves the current result unchanged.
`null` adds null payload columns and requires a left join. `FileInfo.is_optional`
controls physical-file reading only and does not weaken a join's
`missing_source` contract. Declared frame roots are always required, while an
omitted join frame follows that join's configured mode.

Present inputs with invalid columns or cardinality raise a named prepared-table
error. Declared frame sources must be used by the root or a join. Prepared-table
references are validated for unknown sources and dependency cycles before
execution. A request resolves and materializes shared file, runtime, frame, and table
sources once across its dependency graph. Results are not cached across calls,
so each call reads sources using its own placeholders. `FirstPresentSource`
selects the first configured source that exists. A present but invalid source
fails without trying later candidates. Its `empty` policy distinguishes an
existing empty frame from an absent source. `CalendarSource` generates typed
calendar columns, `ConfigRecordsSource` reads typed records from plugin config,
and `SystemFrameSource` projects public component fields or attached series.
Removing a file or table referenced by a configured source or table is rejected.

## Load and read a configured table

```python doctest
>>> import json
>>> import tempfile
>>> from pathlib import Path
>>> from r2x_core import DataStore
>>>
>>> with tempfile.TemporaryDirectory() as temp_dir:
...     folder = Path(temp_dir)
...     generators_path = folder / "gen_data.csv"
...     generators_written = generators_path.write_text("name,zone,capacity\nGen1,Z1,100\n")
...     regions_path = folder / "regions.csv"
...     regions_written = regions_path.write_text("id,name\nZ1,North\n")
...     mapping = {
...         "files": [
...             {"name": "generators", "relative_fpath": "gen_data.csv"},
...             {"name": "regions", "relative_fpath": "regions.csv"},
...         ],
...         "tables": [
...             {
...                 "name": "generator_details",
...                 "source": "generators",
...                 "required_columns": ["name", "capacity", "region_name"],
...                 "joins": [
...                     {
...                         "source": "regions",
...                         "on": {"zone": "id"},
...                         "columns": {"name": "region_name"},
...                     }
...                 ],
...             }
...         ],
...     }
...     mapping_path = folder / "file_mapping.json"
...     mapping_written = mapping_path.write_text(json.dumps(mapping))
...     store = DataStore.from_json(mapping_path)
...     rows = store.read_data("generator_details").collect()
...     rows.select("name", "capacity", "region_name").to_dicts()
[{'name': 'Gen1', 'capacity': 100, 'region_name': 'North'}]
```

`DataStore.list_data()` and membership checks include physical files, runtime
sources, and prepared tables. Use `list_files()`, `list_sources()`, and
`list_tables()` to inspect each kind. `read_data(name)` reads any registered
name. `read_table(name)` resolves a configured prepared table directly. `prepare_table(name, inputs=...)`
accepts in-memory frames for its transitive `frame_sources` and resolves physical
files and prepared-table dependencies through the same store.

## Plugin configuration asset overrides

A plugin config can replace a complete JSON asset. For `file_mapping`, provide
the full envelope rather than a list of files:

```python doctest
>>> from r2x_core import PluginConfig, PluginConfigAsset
>>> mapping = {"files": [{"name": "buses", "relative_fpath": "buses.csv"}], "sources": [], "tables": []}
>>> config = PluginConfig(asset_overrides={"file_mapping": mapping})
>>> config.load_config(assets=[PluginConfigAsset.FILE_MAPPING])["file_mapping"] == mapping
True
```

`DataStore.from_plugin_config` reads the effective `file_mapping` from the same
config instance and resolved config path. Asset overrides replace the entire
asset. They are not merged by list position.

## See also

- {doc}`manage-datastores` - Manage data file collections
- {doc}`read-data-files` - Read configured data files
- {doc}`process-file-data` - Apply transformations during reading
- {py:class}`~r2x_core.DataStore` - DataStore API reference
- {py:class}`~r2x_core.DataFile` - DataFile API reference
- {py:class}`~r2x_core.PreparedTable` - Prepared-table configuration
