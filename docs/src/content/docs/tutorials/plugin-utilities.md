---
title: "Export component records and filter keyword arguments"
---

The helpers in `r2x_core.utils` work with ordinary systems, paths and callables.
This tutorial creates its own components and temporary output; it needs no model
dataset. Use the exact public module imports below on current main.

## Select and rename record fields

A model dump normally includes a UUID. Selecting named fields makes the result
deterministic and limits an export to the intended contract.

```python doctest
>>> from infrasys import Component
>>> from r2x_core import System
>>> from r2x_core.utils import components_to_records
>>> class Generator(Component):
...     capacity_mw: float
>>> system = System(name="demo")
>>> system.add_component(Generator(name="Alpha", capacity_mw=100.0))
>>> records = components_to_records(system, fields=["name", "capacity_mw"], key_mapping={"capacity_mw": "capacity"})
>>> # Expected: selected fields are retained and the output key is renamed.
>>> records
[{'name': 'Alpha', 'capacity': 100.0}]
>>> selected = components_to_records(system, fields=["name"], filter_func=lambda component: component.capacity_mw > 200)
>>> selected
[]
```

## Write and check a CSV

This independent example uses generic named components. The temporary directory
is removed after the check, so no persistent user files are modified.

```python doctest
>>> import csv
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from infrasys import Component
>>> from r2x_core import System
>>> from r2x_core.utils import export_components_to_csv
>>> system = System(name="csv-demo")
>>> system.add_component(Component(name="Alpha"))
>>> with TemporaryDirectory() as directory:
...     output = Path(directory) / "components.csv"
...     export_components_to_csv(system, file_path=output, fields=["name"])
...     with output.open(encoding="utf-8", newline="") as stream:
...         rows = list(csv.DictReader(stream))
>>> # Expected: the file contains the exported component name.
>>> rows
[{'name': 'Alpha'}]
```

## Filter arguments for a known callable

`filter_kwargs_for` filters keys by a callable's accepted parameters; it does not
validate values or implement a model transformation.

```python doctest
>>> from r2x_core.utils import filter_kwargs_for
>>> def scale(value: float, *, factor: float = 2.0) -> float:
...     return value * factor
>>> options = filter_kwargs_for(scale, kwargs={"factor": 3.0, "unused": "ignored"})
>>> # Expected: unknown keys are removed before calling the function.
>>> options
{'factor': 3.0}
>>> scale(4.0, **options)
12.0
```

See [Utilities](/r2x-core/references/utils/) for exact signatures and
[Export a system](/r2x-core/how-tos/build-exporters/) for an artifact that preserves
system metadata and companion storage. A CSV record export is a different boundary.

<span id="available-utilities"></span>

<span id="component-data-extraction"></span>

<span id="component-creation"></span>

<span id="create_component"></span>

<span id="getter-decorator"></span>

<span id="time-series-management"></span>

<span id="transfer_time_series_metadata"></span>

<span id="common-patterns"></span>

<span id="batch-processing-components"></span>

<span id="exporting-component-subsets"></span>

<span id="error-handling-with-component-creation"></span>

<span id="api-compatibility"></span>

<span id="see-also"></span>
