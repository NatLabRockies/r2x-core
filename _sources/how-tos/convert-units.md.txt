# Work with Units

Create components with unit-aware fields using the `HasPerUnit` mixin.

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
100.0
>>> gen.active_power
0.95
```

## Input Values in Natural Units

Automatically convert natural units to per-unit:

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
0.8
```

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
0.9
>>> set_unit_system(UnitSystem.NATURAL_UNITS)
>>> repr_str = repr(gen)
>>> "MVA" in repr_str
True
```

## See Also

- {doc}../tutorials/working-with-units - Full unit documentation
