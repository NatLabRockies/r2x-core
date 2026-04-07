# Managing Datastores

A {py:class}`~r2x_core.DataStore` is a collection of {py:class}`~r2x_core.DataFile` objects that can be read together, providing a unified interface for managing multiple data sources.

## Create a DataStore

Use {py:class}`~r2x_core.DataStore` to instantiate an empty data store:

```python doctest
>>> from r2x_core import DataStore
>>> store = DataStore()
>>> type(store).__name__
'DataStore'
```

## Add Files to a DataStore

Use the {py:meth}`~r2x_core.DataStore.add_data` method to register data files:

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
2
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
True
>>> sorted(store.list_data())
['generators', 'loads']
```

## See Also

- {doc}`read-data-files` - Read individual data files
- {doc}`configure-data-files` - Configure data file formats and parsing
- {py:class}`~r2x_core.DataStore` - DataStore API reference
- {py:class}`~r2x_core.DataFile` - DataFile API reference
