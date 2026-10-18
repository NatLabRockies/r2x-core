# Configuring Data Settings

Define physical files and prepared tables in `file_mapping.json`, then load the
configuration into a {py:class}`~r2x_core.DataStore`. Physical files describe
how to read and process individual sources. Prepared tables declare left
many-to-one joins and tabular processing for a named result.

## Define files and prepared tables

A file-mapping document has `files` and `tables` lists. Join keys map left
column names to right column names. Join payloads map right source columns to
their output names. Prepared tables can read physical files only, not other
prepared tables.

```json
{
  "files": [
    {"name": "generators", "relative_fpath": "gen_data.csv"},
    {"name": "regions", "relative_fpath": "regions.csv"}
  ],
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

A join rejects null keys and duplicate right-side keys by default. Configure
`select_first` only when a representative row is intentional. With no
`order_by`, the first source row is retained. With `order_by`, rows are stably
sorted before selecting the first row for each join key. A missing optional base input makes `read_data` or `read_table` return
`None`. A missing optional enrichment input is skipped. If a table requires
columns supplied by that skipped input, result validation fails. Present inputs
with invalid columns or cardinality raise a named prepared-table error.

Prepared-table reads collect each physical input and validate the joined result
before returning it as a `LazyFrame`. They materialize data during each read and
do not cache prepared results across calls.

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

`DataStore.list_data()` and membership checks include both files and prepared
tables. Use `list_files()` for physical inputs and `list_tables()` for prepared
table definitions. `read_data(name)` reads either kind. `read_table(name)` reads
and validates a prepared table directly.

## Plugin configuration asset overrides

A plugin config can replace a complete JSON asset. For `file_mapping`, provide
the full envelope rather than a list of files:

```python doctest
>>> from r2x_core import PluginConfig, PluginConfigAsset
>>> mapping = {"files": [{"name": "buses", "relative_fpath": "buses.csv"}], "tables": []}
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
