---
title: "Create Power System Components with Units"
---

<span id="create-power-system-components-with-units"></span>

Learn how to define power system components with units. The examples cover
relative values, multiple bases, and unit conversion.

## Prerequisites

Complete [Installation](/r2x-core/install/) and [environment setup](/r2x-core/getting-started/environment/) first.

## Step 1: Add fields that store values per unit

Define a generator with `HasPerUnit` and `Unit` annotations. r2x-core stores
relative values using the field's base. Changing the display mode changes how a
value is shown, not how it is stored.

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core import HasPerUnit, Unit
>>>
>>> class Generator(HasPerUnit, Component):
...     """Generator with power values stored per unit."""
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
# Coal Plant 1
```

The `output` field stores the value relative to `base_power`.

## Step 2: Handle Multiple Base Values

Equipment with multiple ratings, such as transformers, can use different
bases. Each field names its base, and r2x-core converts its value using that
base.

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
# Main TX
```

## Step 3: Change Display Modes

Change the display mode to show values in different units without changing the
stored values. `UnitSystem` controls the model representation.

```python doctest
>>> from r2x_core import UnitSystem, set_unit_system, get_unit_system
>>>
>>> current = get_unit_system()
>>> print(type(current).__name__)
# UnitSystem
>>>
>>> set_unit_system(UnitSystem.DEVICE_BASE)
```

## Step 4: Work with the HasUnits Mixin

Use `HasUnits` when a model has fields with units but does not need system base
display.

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core import HasUnits, Unit
>>>
>>> class Load(HasUnits, Component):
...     """Load with power fields that use units."""
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
# Load 1
```

## Inspect the serialized generator

Use the `gen` instance from Step 1. `model_dump()` returns a Python dictionary.
`model_dump_json()` returns a JSON string. This view includes the name, base
values, and output, but not the component's `uuid`. Without `include`, both
methods retain that field.

The example below creates the same generator again:

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core import HasPerUnit, Unit
>>>
>>> class Generator(HasPerUnit, Component):
...     """Generator with power values stored per unit."""
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
>>> import json
>>> fields = {"name", "base_power", "rated_voltage", "output"}
>>> snapshot = gen.model_dump(include=fields)
>>> snapshot
# {'name': 'Coal Plant 1', 'base_power': 500.0, 'rated_voltage': 22.0, 'output': 0.85}
>>> json_text = gen.model_dump_json(include=fields, indent=2)
>>> print(json_text)
# {
#   "name": "Coal Plant 1",
#   "base_power": 500.0,
#   "rated_voltage": 22.0,
#   "output": 0.85
# }
>>> json.loads(json_text) == snapshot
# True
>>> snapshot["output"] * snapshot["base_power"]
# 425.0
>>> Generator.model_fields["output"].metadata
# [UnitSpec(unit='pu', base='base_power')]
```

Neither representation expands these fields into `{value, unit}` objects.
`output` remains **0.85 per unit**, and `base_power` remains **500.0**. That
represents 425 MW for this generator.
The units (`MVA`, `kV`, `pu`) and `output`'s link to `base_power` belong to the
`Generator` class's `Unit(...)` annotations, shown by the final check.
Those annotations are **not** embedded in the model dump. Numbers alone do not identify their units.

Keep the matching component class available when interpreting or validating this
representation. Changing display mode does not change the stored per unit value to MW in these dumps.
For a complete persisted system, use [System serialization](/r2x-core/references/data-workflow/#system-serialization)
and retain its companion storage. `System.to_json()` serves that purpose.
A component's `model_dump_json()` is not a substitute for a complete system artifact.

## Summary

You've learned how to:

- Create components with unit fields using `HasPerUnit` and `Unit` annotations
- Handle equipment with multiple base values by specifying base references per
  field
- Change display modes to view values in different units
- Use the `HasUnits` mixin for explicit unit management in components

## Next Steps

- [convert units](/r2x-core/how-tos/convert-units/) - Learn advanced unit operations
- [process file data](/r2x-core/how-tos/process-file-data/) - Import measurement data with automatic conversions

## See Also

- [`Unit`](/r2x-core/references/api/) - Unit annotation API
- [`HasPerUnit`](/r2x-core/references/api/) - Mixin for fields stored per unit
- [unit system](/r2x-core/explanations/unit-system/) - How r2x-core handles unit values
