# Configuring Data Settings

Define data source configurations as JSON to manage file paths, units, filtering rules, and metadata. Use {py:meth}`~r2x_core.DataStore.from_json` to load configurations into a {py:class}`~r2x_core.DataStore`.

## Define Data Configuration in JSON

Create a JSON configuration file that describes multiple data files with their properties and processing rules:

```python doctest
>>> import json
>>> config = [
...     {
...         "name": "generators",
...         "relative_fpath": "gen_data.csv",
...         "description": "Generator capacity data",
...         "units": "MW"
...     },
...     {
...         "name": "loads",
...         "relative_fpath": "load_data.csv",
...         "description": "Load profiles",
...         "filter_by": {"year": 2030}
...     }
... ]
>>> # Verify configuration structure
>>> config[0]["name"]
'generators'
>>> config[1]["relative_fpath"]
'load_data.csv'
>>> len(config)
2
```

## Load Configuration into a DataStore

Load a JSON configuration file to create a {py:class}`~r2x_core.DataStore` with all file definitions:

```python doctest
>>> from pathlib import Path
>>> from r2x_core import DataStore
>>> import json
>>> import tempfile
>>>
>>> # Create a temporary config file for demonstration
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     # Create sample CSV files
...     gen_path = Path(tmpdir) / "gen_data.csv"
...     _ = gen_path.write_text("name,capacity\nGen1,100\nGen2,200\n")
...     load_path = Path(tmpdir) / "load_data.csv"
...     _ = load_path.write_text("zone,load\nZone1,50\nZone2,75\n")
...
...     config = [
...         {"name": "generators", "fpath": str(gen_path)},
...         {"name": "loads", "fpath": str(load_path)}
...     ]
...     config_path = Path(tmpdir) / "data_config.json"
...     with open(config_path, "w") as f:
...         json.dump(config, f)
...
...     # Load the configuration
...     store = DataStore.from_json(str(config_path), path=tmpdir)
...     files = store.list_data()
...     print("Configured files:", len(files))
...     print("Generator data configured:", "generators" in files)
Configured files: 2
Generator data configured: True
```

## Configuration File Format

A configuration JSON file should be an array of objects, each representing a {py:class}`~r2x_core.DataFile` with properties such as:

- **name**: Unique identifier for the data source
- **fpath**: Relative path to the data file
- **description**: Human-readable description of the data
- **units**: Unit of measurement if applicable
- **is_timeseries**: Boolean indicating if data contains time-varying values
- **filter_by**: Dictionary of column-value pairs for filtering rows

## See Also

- {doc}`manage-datastores` - Manage data file collections
- {doc}`read-data-files` - Read configured data files
- {doc}`process-file-data` - Apply transformations during reading
- {py:class}`~r2x_core.DataStore` - DataStore API reference
- {py:class}`~r2x_core.DataFile` - DataFile API reference
