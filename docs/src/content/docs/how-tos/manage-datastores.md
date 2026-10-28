---
title: "Managing Datastores"
---

<span id="managing-datastores"></span>

A [`DataStore`](/r2x-core/references/api/) manages a collection of validated `DataFile` mapping definitions rooted at an existing directory. It does not read or process those inputs. Use `DataReader` to load named sources or `build_system` to construct configured outputs.

## Create a DataStore

Use [`DataStore`](/r2x-core/references/api/) to instantiate an empty data store:

```python doctest
>>> from r2x_core import DataStore
>>> store = DataStore()
>>> type(store).__name__
# 'DataStore'
```

## Load a Plugin's File Mapping

For new code, construct the store and load its mapping explicitly:

```python
from r2x_core import DataStore, PluginConfig

config = PluginConfig()
store = DataStore(path="/path/to/inputs")
store.configure_upgrades(plugin_config=config)
store.load_file_mapping(config.fmap_path)
```

Existing plugins can continue to use `DataStore.from_plugin_config(config, path=...)` during migration.
The compatibility factory returns an empty store when the mapping is absent and retries after a configured upgrade handler restores missing required inputs.

## Add Files to a DataStore

Use the [`add_data`](/r2x-core/references/api/) method to register data files:

```python doctest
>>> from pathlib import Path
>>> from r2x_core import DataFile, DataStore
>>>
>>> # Single file
>>> store = DataStore()
>>> store.add_data([DataFile(name="generators", relative_fpath="gen.csv")])
>>>
>>> # Multiple files at once
>>> files = [
...     DataFile(name="generators", relative_fpath="gen.csv"),
...     DataFile(name="loads", relative_fpath="load.csv")
... ]
>>> store = DataStore()
>>> store.add_data(files)
>>> len(store.list_data())
# 2
```

## List Available Data Files

Check which data files are registered in the store:

```python doctest
>>> from pathlib import Path
>>> from r2x_core import DataFile, DataStore
>>>
>>> # Create datastore with files
>>> store = DataStore()
>>> store.add_data([DataFile(name="generators", relative_fpath="gen.csv")])
>>> store.add_data([DataFile(name="loads", relative_fpath="load.csv")])
>>>
>>> # Check registered data
>>> "generators" in store.list_data()
# True
>>> sorted(store.list_data())
# ['generators', 'loads']
```

## See Also

- [Read data files](/r2x-core/how-tos/read-data-files/) - Load named typed sources
- [Build a parser](/r2x-core/how-tos/build-parsers/) - Construct configured systems
- [configure data files](/r2x-core/how-tos/configure-data-files/) - Configure data file formats and parsing
- [`DataStore`](/r2x-core/references/api/) - DataStore API reference
- [`DataFile`](/r2x-core/references/api/) - DataFile API reference
