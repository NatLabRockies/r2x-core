---
title: "Create Power System Components with Units"
---

Learn how to define power system components with proper unit handling, including
per-unit normalization, multiple base values, and automatic unit conversions.

## Prerequisites

Complete [Installation](/r2x-core/install/) and [environment setup](/r2x-core/getting-started/environment/) first.

## Step 1: Create a Component with Per-Unit Fields

Define a generator with per-unit fields using the `HasPerUnit` mixin and `Unit`
annotations. R2X Core stores all per-unit quantities internally in device-base
per-unit, so display modes only affect how values appear, not how they're
calculated.

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core import HasPerUnit, Unit
>>>
>>> class Generator(HasPerUnit, Component):
...     """Generator with per-unit power tracking."""
...     base_power: Annotated[float, Unit("MVA")]
...     rated_voltage: Annotated[float, Unit("kV")]
...     output: Annotated[float, Unit("pu", base="base_power")]
>>>
>>> gen = Generator(
...     name="Coal Plant 1",
...     base_power=500.0,
...     rated_voltage=22.0,
...     output=0.85
... )
>>> print(gen.name)
Coal Plant 1
>>> import json
>>> fields = {"name", "base_power", "rated_voltage", "output"}
>>> snapshot = gen.model_dump(include=fields)
>>> snapshot
{'name': 'Coal Plant 1', 'base_power': 500.0, 'rated_voltage': 22.0, 'output': 0.85}
>>> json.loads(gen.model_dump_json(include=fields)) == snapshot
True
>>> Generator.model_fields["output"].metadata
[UnitSpec(unit='pu', base='base_power')]
```

The `output` field stores the value in per-unit normalized to `base_power`.

## Step 2: Handle Multiple Base Values

Equipment with multiple ratings, like transformers, can reference different
bases. Each field independently specifies which base it normalizes to, and R2X
Core tracks and converts accordingly.

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core import HasPerUnit, Unit
>>>
>>> class Transformer(HasPerUnit, Component):
...     """Transformer with multiple voltage references."""
...     base_power: Annotated[float, Unit("MVA")]
...     high_voltage: Annotated[float, Unit("kV")]
...     low_voltage: Annotated[float, Unit("kV")]
...     impedance: Annotated[float, Unit("pu", base="base_power")]
...     tap_position: Annotated[float, Unit("pu", base="high_voltage")]
>>>
>>> tx = Transformer(
...     name="Main TX",
...     base_power=100.0,
...     high_voltage=138.0,
...     low_voltage=13.8,
...     impedance=0.10,
...     tap_position=1.05
... )
>>> print(tx.name)
Main TX
```

## Step 3: Change Display Modes

View unit values in different display modes without affecting internal
calculations. The `UnitSystem` controls how values are presented to users.

```python doctest
>>> from r2x_core import UnitSystem, set_unit_system, get_unit_system
>>>
>>> current = get_unit_system()
>>> print(type(current).__name__)
UnitSystem
>>>
>>> set_unit_system(UnitSystem.DEVICE_BASE)
```

## Step 4: Work with the HasUnits Mixin

Use the `HasUnits` mixin to get unit-aware access to all component fields. This
provides a convenient interface for components that need explicit unit
management.

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core import HasUnits, Unit
>>>
>>> class Load(HasUnits, Component):
...     """Load with unit-aware power tracking."""
...     base_power: Annotated[float, Unit("MVA")]
...     active_power: Annotated[float, Unit("pu", base="base_power")]
...     reactive_power: Annotated[float, Unit("pu", base="base_power")]
>>>
>>> load = Load(
...     name="Load 1",
...     base_power=50.0,
...     active_power=0.8,
...     reactive_power=0.3
... )
>>> print(load.name)
Load 1
```

## Inspect the serialized generator

Use the `gen` instance from Step 1. `model_dump()` returns a Python dictionary;
`model_dump_json()` returns a JSON string. The focused view below includes the
name, physical base values, and per-unit output. It deliberately omits the
component's `uuid`; calling either method without `include` retains that field.

```python
fields = {"name", "base_power", "rated_voltage", "output"}
snapshot = gen.model_dump(include=fields)
json_text = gen.model_dump_json(include=fields, indent=2)
print(json_text)
```

The JSON string prints as:

```json
{
  "name": "Coal Plant 1",
  "base_power": 500.0,
  "rated_voltage": 22.0,
  "output": 0.85
}
```

The Python dictionary contains the same names and numeric values, as shown in
Step 1. Neither representation expands these fields into `{value, unit}` objects:
`output` remains **0.85 per-unit**, with the physical base value **500.0** retained
in `base_power`. For this generator, that corresponds to 425 MW.
The units (`MVA`, `kV`, `pu`) and `output`'s link to `base_power` belong to the
`Generator` class's `Unit(...)` annotations; those annotations are **not** embedded
in this model dump. The numbers alone do not tell an independent reader their units.

Verify the dict and JSON agree:

```python
import json

assert json.loads(json_text) == snapshot
assert snapshot["output"] == 0.85
assert snapshot["output"] * snapshot["base_power"] == 425.0
```

Keep the matching component class available when interpreting or validating this
representation. Changing display mode does not replace the internally stored
per-unit value with MW in these dumps.
For a complete persisted system, use [System serialization](/r2x-core/references/data-workflow/#system-serialization)
and retain its companion storage; `System.to_json()` serves that different purpose.
A component's `model_dump_json()` is not a substitute for a complete system artifact.

## Summary

You've learned how to:

- Create components with unit-aware fields using `HasPerUnit` and `Unit`
  annotations
- Handle equipment with multiple base values by specifying base references per
  field
- Change display modes to view values in different units
- Use the `HasUnits` mixin for explicit unit management in components

## Next Steps

- [convert units](/r2x-core/how-tos/convert-units/) - Learn advanced unit operations
- [process file data](/r2x-core/how-tos/process-file-data/) - Import measurement data with automatic conversions

## See Also

- [`Unit`](/r2x-core/references/api/) - Unit annotation API
- [`HasPerUnit`](/r2x-core/references/api/) - Per-unit mixin class
- [unit system](/r2x-core/explanations/unit-system/) - Design philosophy behind the unit system
