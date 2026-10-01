# Managing Systems

A {py:class}`~r2x_core.System` represents a power system model containing components like generators, buses, and loads. Use this guide to perform common operations on system models.

## Get All Components as Records

```python doctest
>>> from r2x_core import System, components_to_records
>>> from infrasys import Component
>>> system = System(name="MySystem")
>>> system.add_component(Component(name="comp1"))
>>> system.add_component(Component(name="comp2"))
>>> records = components_to_records(system)
>>> len(records)
2
```

## Filter Components By Type

```python doctest
>>> from r2x_core import System, components_to_records
>>> from infrasys import Component
>>> class Generator(Component):
...     pass
>>> class Bus(Component):
...     pass
>>> system = System(name="MySystem")
>>> system.add_component(Generator(name="gen1"))
>>> system.add_component(Bus(name="bus1"))
>>> gen_records = components_to_records(
...     system,
...     filter_func=lambda c: isinstance(c, Generator)
... )
>>> len(gen_records)
1
```

## Select Specific Fields

```python doctest
>>> from r2x_core import System, components_to_records
>>> from infrasys import Component
>>> from pydantic import Field
>>> class Bus(Component):
...     voltage: float = Field(default=0.0)
>>> system = System(name="MySystem")
>>> system.add_component(Bus(name="bus1", voltage=230.0))
>>> records = components_to_records(
...     system,
...     filter_func=lambda c: isinstance(c, Bus),
...     fields=["name", "voltage"]
... )
>>> len(records[0])
2
```

## Export Components To CSV

```python doctest
>>> from r2x_core import System, export_components_to_csv
>>> from infrasys import Component
>>> from pathlib import Path
>>> import tempfile
>>> system = System(name="MySystem")
>>> system.add_component(Component(name="comp1"))
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     path = Path(tmpdir) / "output.csv"
...     export_components_to_csv(system, file_path=path)
...     path.exists()
True
```

## Create Components with Validation

Safely create components with automatic validation error handling:

```python doctest
>>> from r2x_core import create_component
>>> from infrasys import Component
>>> result = create_component(Component, name="MyComponent")
>>> result.is_ok()
True
>>> comp = result.unwrap()
>>> comp.name
'MyComponent'
```

## See Also

- {doc}`attach-timeseries` - Attach time series data to systems
- {doc}`build-parsers` - Create custom system parsers
- {doc}`build-exporters` - Export system data to files
- {py:class}`~r2x_core.System` - System API reference
- {py:mod}`~r2x_core.utils._component` - Component utilities
