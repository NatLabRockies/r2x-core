---
title: "Work with Units"
---

<span id="work-with-units"></span>

Create components with fields that use units and the `HasPerUnit` mixin.

## Create Components with Units

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core.units import HasPerUnit, Unit
>>> class Generator(HasPerUnit, Component):
...     base_power: Annotated[float, Unit("MVA")]
...     active_power: Annotated[float, Unit("pu", base="base_power")]
>>> gen = Generator(name="Gen1", base_power=100.0, active_power=0.95)
>>> gen.base_power
# 100.0
>>> gen.active_power
# 0.95
```

## Input Values in Natural Units

Pass a mapping with `value` and `unit` to convert a physical value to per unit form.
Declare the base field before the dependent field. Compatible prefixes are
normalized before division. Unknown or incompatible units and missing, zero,
or bases that are not finite fail scalar conversion:

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core.units import HasPerUnit, Unit
>>> class Generator(HasPerUnit, Component):
...     base_power: Annotated[float, Unit("MVA")]
...     active_power: Annotated[float, Unit("pu", base="base_power")]
>>> gen = Generator(
...     name="Gen2",
...     base_power=250.0,
...     active_power={"value": 200.0, "unit": "MVA"}
... )
>>> gen.active_power
# 0.8
>>> small = Generator(
...     name="Gen3",
...     base_power=100.0,
...     active_power={"value": 5000.0, "unit": "kW"},
... )
>>> small.active_power
# 0.05
```

Fields without `base=...` also convert mappings to their declared unit. For
example, `{"value": 13800.0, "unit": "V"}` becomes 13.8 in a `Unit("kV")` field.
Bare numbers are already in the field's internal units and are not converted.
For scalar unit fields, the Pydantic validation JSON Schema accepts both the
field's scalar input and a `{value, unit}` envelope with a numeric magnitude.
The serialization schema and serialized value remain the declared scalar type.

## Persist structured unit fields

For a structured relative field, supply a model or bare mapping in natural
units. Serialization adds a `unit: "pu"` marker so loading the stored values
does not divide them by the base again:

```python doctest
>>> from typing import Annotated
>>> from pydantic import BaseModel
>>> from r2x_core import HasUnits, Unit
>>> class Limits(BaseModel):
...     minimum: float
...     maximum: float
>>> class Battery(HasUnits, BaseModel):
...     base_power: Annotated[float, Unit("MW")]
...     limits: Annotated[Limits, Unit("MW", base="base_power")]
>>> battery = Battery(
...     base_power=50.0,
...     limits=Limits(minimum=-40.0, maximum=40.0),
... )
>>> battery.model_dump()["limits"]
# {'value': {'minimum': -0.8, 'maximum': 0.8}, 'unit': 'pu'}
>>> restored = Battery.model_validate(battery.model_dump())
>>> restored.limits.minimum, restored.limits.maximum
# (-0.8, 0.8)
>>> Battery.model_validate_json(battery.model_dump_json()).limits.maximum
# 0.8
```

`System.to_json()` uses the same representation for component fields. Keep the
marker when storing or transferring serialized data. The shape
`{"value": <mapping>, "unit": "pu"}` is reserved for stored internal values.
A natural structured mapping with scalar `value` and `unit` fields is input data,
not an envelope. Bare structured mappings are always input in natural units, not
a format for saved internal values. Optional structured fields preserve `None`.

## Switch Display Modes

Change how values are displayed:

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core.units import HasPerUnit, Unit, UnitSystem, set_unit_system
>>> from r2x_core import System
>>> class Generator(HasPerUnit, Component):
...     base_power: Annotated[float, Unit("MVA")]
...     active_power: Annotated[float, Unit("pu", base="base_power")]
>>> set_unit_system(UnitSystem.DEVICE_BASE)
>>> gen = Generator(name="Gen", base_power=150.0, active_power=0.90)
>>> gen.active_power
# 0.9
>>> set_unit_system(UnitSystem.NATURAL_UNITS)
>>> repr_str = repr(gen)
>>> "MVA" in repr_str
# True
```

## See Also

- [Working with units](/r2x-core/tutorials/working-with-units/) - Full unit documentation
