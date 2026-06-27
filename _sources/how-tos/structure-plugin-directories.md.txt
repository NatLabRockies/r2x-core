# Plugin Directory Structure

All plugins follow a standard directory layout for consistency.

## Standard Layout

```
my_plugin/
├── __init__.py
├── config.py
└── config/
    └── defaults.json
```

## Configuration Class

Define a configuration class that extends `PluginConfig`:

```python doctest
>>> from r2x_core import PluginConfig
>>> class MyConfig(PluginConfig):
...     solve_year: int
...     scenario: str = "reference"
>>> config = MyConfig(solve_year=2030)
>>> config.solve_year
2030
>>> config.scenario
'reference'
```

## Using DataStore with Config

Create a `DataStore` directly from your plugin configuration:

```python doctest
>>> import tempfile
>>> from pathlib import Path
>>> from r2x_core import DataStore, PluginConfig
>>> class MyConfig(PluginConfig):
...     solve_year: int
>>> config = MyConfig(solve_year=2030)
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     store = DataStore.from_plugin_config(config, path=tmpdir)
...     print(type(store).__name__)
DataStore
```

## Register Custom Getters

Use the `getter` decorator to register custom field extractors:

```python doctest
>>> from r2x_core import getter
>>> @getter
... def extract_name(component):
...     return component.name
>>> extract_name.__name__
'extract_name'
```

## See Also

- {doc}`register-plugins` - Creating plugins
- {doc}`run-plugins` - Using plugins
