---
title: "Managing Systems"
---

<span id="managing-systems"></span>

A [`System`](/r2x-core/references/api/) represents a power system model containing components like generators, buses, and loads. Use this guide to perform common operations on system models.

## Get All Components as Records

```python doctest
>>> from r2x_core import System, components_to_records
>>> from infrasys import Component
>>> system = System(name="MySystem")
>>> system.add_component(Component(name="comp1"))
>>> system.add_component(Component(name="comp2"))
>>> records = components_to_records(system)
>>> len(records)
# 2
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
# 1
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
# 2
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
# True
```

## Validate a component manually

For a small in-memory edit, validate the model before adding it. For file
ingestion, prefer `build_system` and configured component instructions so the
application does not own a construction loop.

```python doctest
>>> from infrasys import Component
>>> from r2x_core import System
>>> class Bus(Component):
...     base_kv: float
>>> bus = Bus.model_validate({"name": "north", "base_kv": 230.0})
>>> system = System(name="manual-edit")
>>> system.add_component(bus)
>>> system.get_component(Bus, "north").base_kv
# 230.0
```

## See Also

- [attach timeseries](/r2x-core/how-tos/attach-timeseries/) - Attach time series data to systems
- [build parsers](/r2x-core/how-tos/build-parsers/) - Create custom system parsers
- [build exporters](/r2x-core/how-tos/build-exporters/) - Export system data to files
- [`System`](/r2x-core/references/api/) - System API reference
- [Build a parser](/r2x-core/how-tos/build-parsers/) - Build components from configured sources
