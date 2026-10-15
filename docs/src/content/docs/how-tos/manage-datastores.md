---
title: "Managing Datastores"
---

A [`DataStore`](/r2x-core/references/api/) is a collection of [`DataFile`](/r2x-core/references/api/) objects that can be read together, providing a unified interface for managing multiple data sources.

## Create a DataStore

Use [`DataStore`](/r2x-core/references/api/) to instantiate an empty data store:

```python
>>> from r2x_core import DataStore
>>> store = DataStore()
>>> type(store).__name__
'DataStore'
```

## Add Files to a DataStore

Use the [`add_data`](/r2x-core/references/api/) method to register data files:

```python
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
2
```

## List Available Data Files

Check which data files are registered in the store:

```python
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
True
>>> sorted(store.list_data())
['generators', 'loads']
```

## See Also

- [read data files](/r2x-core/how-tos/read-data-files/) - Read individual data files
- [configure data files](/r2x-core/how-tos/configure-data-files/) - Configure data file formats and parsing
- [`DataStore`](/r2x-core/references/api/) - DataStore API reference
- [`DataFile`](/r2x-core/references/api/) - DataFile API reference
