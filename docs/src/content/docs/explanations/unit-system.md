---
title: "Unit handling"
---

<span id="unit-system-design-and-architecture"></span>

r2x-core uses unit annotations to validate input, store relative values, and format them for display.

## Why units matter

Per unit values help compare equipment with different ratings. A 500 MVA
generator and a 10 MVA generator can be compared by expressing each output as a
fraction of its own rating. r2x-core stores relative values this way and can
display them in device units, natural units, or system base units.

Input data may use MW or kW even when a model stores a per unit value. A field
annotation names its unit and, when needed, its base. Pydantic validates and
converts supported unit mappings when it creates the model.

## How values are stored and shown

Values in per unit fields are stored as floats relative to their declared base.
Changing the display mode affects the formatted model representation, not the
stored value. Calculations use the stored values.

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from r2x_core import HasPerUnit, Unit
>>> class Generator(HasPerUnit, Component):
...     base_power: Annotated[float, Unit("MVA")]
...     p_max: Annotated[float, Unit("pu", base="base_power")]
...
>>> from r2x_core import get_unit_system, set_unit_system, UnitSystem
>>> gen = Generator(name="Gen1", base_power=100.0, p_max=0.5)
>>> original_mode = get_unit_system()
>>> try:
...     set_unit_system(UnitSystem.NATURAL_UNITS)
...     natural_stored = gen.model_dump()["p_max"]
...     set_unit_system(UnitSystem.DEVICE_BASE)
...     device_stored = gen.model_dump()["p_max"]
... finally:
...     set_unit_system(original_mode)
...
>>> assert natural_stored == device_stored == 0.5
>>> natural_stored, device_stored
# (0.5, 0.5)
```

> Changing the display mode only changes the formatted model representation. It does not change stored values.


## Unit annotations

A field such as `Annotated[float, Unit("pu", base="base_power")]` declares its
Python type, unit, and base field. Pydantic validates the value when it creates
the model. A number is treated as an already normalized value. A mapping with a
value and unit is converted using the declared base.

```python doctest
>>> from typing import Annotated
>>> from pydantic import BaseModel
>>> from r2x_core import HasUnits, Unit
>>> class Generator(HasUnits, BaseModel):
...     name: str
...     base_power: Annotated[float, Unit("MVA")]
...     p_max: Annotated[float, Unit("pu", base="base_power")]
...     voltage_kv: Annotated[float, Unit("kV")]
...
>>> gen1 = Generator(name="Gen1", base_power=100.0, p_max=0.8, voltage_kv=13.8)
>>> gen2 = Generator(name="Gen2", base_power=50.0, p_max={"value": 40.0, "unit": "MW"}, voltage_kv=13.8)
>>> assert gen1.p_max == gen2.p_max == 0.8
>>> gen1.p_max, gen2.p_max
# (0.8, 0.8)
```

A base field must also have a `Unit` annotation. For a relative field, numeric
input is already in per unit form. A mapping with a value and unit is converted
using the base.

## Mixins

Use `HasUnits` for models with unit fields. Use `HasPerUnit` when a component
also needs system base display. When a `HasPerUnit` component is added to a
`System`, the system binds its base to the component.

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from pydantic import BaseModel
>>> from r2x_core import HasUnits, HasPerUnit, System, Unit
>>> class Transformer(HasUnits, BaseModel):
...     name: str
...     impedance: Annotated[float, Unit("ohm")]
...     x_r_ratio: float
...
>>> transformer = Transformer(name="TX1", impedance=0.05, x_r_ratio=2.0)
>>> assert transformer.system_base is None
>>> class Generator(HasPerUnit, Component):
...     base_power: Annotated[float, Unit("MVA")]
...     p_max: Annotated[float, Unit("pu", base="base_power")]
...
>>> gen = Generator(name="Gen1", base_power=100.0, p_max=0.8)
>>> system = System(system_base=100.0)
>>> system.add_components(gen)
>>> gen.system_base
# 100.0
```

> Use `HasUnits` for unit fields. Use `HasPerUnit` when a component needs system base display.


## Implementation

### Unit specifications

`UnitSpec` stores a field's unit and optional base field. A field without a base
stores values in its declared unit. A field with a base stores values relative
to that base.

```python doctest
>>> from typing import Annotated
>>> from pydantic import BaseModel
>>> from r2x_core import HasUnits, Unit
>>> class Bus(HasUnits, BaseModel):
...     name: str
...     base_mva: Annotated[float, Unit("MVA")] = 100.0
...     voltage_kv: Annotated[float, Unit("kV")]
...     p_mva: Annotated[float, Unit("pu", base="base_mva")]
...
>>> bus = Bus(name="Bus1", voltage_kv=138.0, p_mva={"value": 50.0, "unit": "MVA"})
>>> assert bus.p_mva == 0.5
>>> bus.p_mva, bus.voltage_kv
# (0.5, 138.0)
```

`UnitSpec` uses Pydantic schema hooks to convert unit mappings during model
construction. For example, `{"value": 150.0, "unit": "MVA"}` is converted using
the field's base. Define base fields before fields that use them so Pydantic has
the base value during validation.

### Model mixins

`HasUnits` collects `UnitSpec` metadata in the class level `unit_specs` mapping
when Pydantic builds the model schema. A base field must also have a unit
specification. Each model resolves its own base units, so a subclass can change
a base without changing its parent.

`HasPerUnit` adds system base display. `System.add_components` binds the system
base to each component, and the model representation uses it to format values.

### Conversion and display

`convert_to_internal` accepts a number or a mapping with a value and unit. It
returns the stored value and uses Pint when units need conversion.
`format_for_display` formats a value for the selected display mode.

### Display mode

`UnitSystem` defines `DEVICE_BASE`, `NATURAL_UNITS`, and `SYSTEM_BASE` display
modes. `set_unit_system` changes the active mode, and `get_unit_system` returns
it. The mode is a global variable, so changing it affects every model
representation in the process. The `unit_system` context manager restores the
previous mode when its block ends.

> Use `unit_system` to change the display mode for one block. It restores the previous mode when the block ends.


## System base

`System` stores its base power and registers a `system_base` unit with Pint.
When `System.add_components` adds a `HasPerUnit` component, it binds the
system's base to that component. It rejects a component already bound to a
different base. Loading a saved system restores the binding.

## Unit conversion

Pint converts compatible units. For a relative field, r2x-core compares the
converted quantity with the declared base. Incompatible units raise an error.

r2x-core uses a shared Pint `UnitRegistry`. `System` registers its base power as
the `system_base` unit. This lets Pint reject conversions between different
kinds of quantities, such as power and voltage.

## Performance

Unit mappings are converted during validation. The model representation
formats values only when requested. Read fields directly in calculations to
use the stored values.


## Design choices

The display mode is global, which makes it easy to format a whole system but
also means a change affects every model representation in the process. Stored
Relative values remain tied to each component's own base. System base display
needs both that base and the system base.
