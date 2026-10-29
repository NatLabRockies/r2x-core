# r2x-core Units Reference

Use this when the task touches `Annotated[..., Unit(...)]`, natural-unit input
conversion, per-unit values, display modes, or unit-aware model validation.

## Contracts (source-verified)

- `Unit(unit: str, *, base: str | None = None) -> UnitSpec`
- `HasUnits` collects immutable unit metadata when Pydantic builds or rebuilds
  a model schema. It binds scalar conversion to the owning model's base units
  and formats unit-aware fields in `repr`.
- `HasPerUnit` extends `HasUnits` with optional system-base display support.
- `set_unit_system(unit_system: UnitSystem) -> None`
- `get_unit_system() -> UnitSystem`
- `r2x_core.units.unit_system(mode: UnitSystem)` context manager for temporary
  display mode changes. It is not currently re-exported from `r2x_core`.

## Do

- Annotate unit-aware fields with `typing.Annotated` and `Unit(...)`.
- Annotate base fields too, e.g. `base_power: Annotated[float, Unit("MW")]`,
  when another field references them with `base="base_power"`.
- Use `Unit("pu", base="base_field")` for values stored internally as
  device-base per-unit.
- Accept natural-unit inputs as `{"value": number, "unit": "MW"}` when a
  field has a base. r2x-core converts to internal per-unit during validation.
- Use `HasUnits` for ordinary unit-aware Pydantic/infrasys models.
- Use `HasPerUnit` only when system-base display is needed.
- Set display mode once at an application/test boundary, or use the
  `unit_system(...)` context manager for temporary formatting checks.

## Don't

- Do not leave a referenced base field unannotated if you expect natural-unit
  conversion. The converter needs the base unit.
- Do not assume `UnitSystem` changes stored values. It affects representation
  formatting, not internal floats.
- Do not toggle `set_unit_system(...)` inside inner loops or per-component
  transforms.
- Do not use comments like `# In MW` as the unit contract. Use
  `Annotated[float, Unit("MW")]`.
- Do not reach for `HasPerUnit` just to parse `Unit("pu", base=...)` fields;
  `HasUnits` already supports validation and conversion.

## Core pattern: unit-aware Pydantic model

```python
from typing import Annotated

from pydantic import BaseModel
from r2x_core import HasUnits, Unit


class Generator(HasUnits, BaseModel):
    name: str
    base_power: Annotated[float, Unit("MW")]
    p_max: Annotated[float, Unit("pu", base="base_power")]
    voltage_kv: Annotated[float, Unit("kV")]


gen1 = Generator(
    name="Gen1",
    base_power=100.0,
    p_max=0.8,
    voltage_kv=13.8,
)

gen2 = Generator(
    name="Gen2",
    base_power=50.0,
    p_max={"value": 40.0, "unit": "MW"},
    voltage_kv=13.8,
)

assert gen1.p_max == gen2.p_max == 0.8
```

Key detail: `base_power` is annotated with `Unit("MW")`. Without that,
`p_max={"value": 40.0, "unit": "MW"}` cannot determine the base unit and
validation should fail.

## Component pattern

```python
from typing import Annotated

from infrasys import Component
from r2x_core import HasUnits, Unit


class Generator(HasUnits, Component):
    name: str
    base_power: Annotated[float, Unit("MW")]
    p_max: Annotated[float, Unit("pu", base="base_power")]
    voltage_kv: Annotated[float, Unit("kV")]
```

Use `class MyModel(HasUnits, BaseModel)` or `class MyComponent(HasUnits,
Component)`. The mixin relies on Pydantic schema and field-validation hooks.

## Input semantics

For `Annotated[float, Unit("pu", base="base_power")]`:

- Numeric input such as `0.8` is accepted as already-internal per-unit.
- Dict input such as `{"value": 40.0, "unit": "MW"}` is converted to
  per-unit using `base_power` and the base field's `Unit(...)` annotation.
- Dict input must contain both `value` and `unit`.
- Compatible prefixes are normalized before division. For example, 5000 kW
  against a 100 MW base becomes 0.05 pu.
- Natural-unit conversion needs both the base value and the base unit
  annotation. Declare base fields before dependent fields. Missing, zero, or
  non-finite bases fail conversion, as do unknown or incompatible units.
- Internal stored representation remains a float. Optional annotations accept
  `None` in both Python and JSON validation.

For `Annotated[float, Unit("kV")]` or other fields without `base=...`:

- Numeric input is stored as a float.
- Dict input with `value` and `unit` converts compatible units to the declared
  unit. For example, `{"value": 13800, "unit": "V"}` becomes 13.8 kV.
- Unknown or dimensionally incompatible units fail validation.

For structured fields such as `Annotated[Limits, Unit("MW", base="base_power")]`:

- A model instance or bare mapping is natural-unit input. Its numeric fields
  are divided by the base once.
- `model_dump()` and `model_dump_json()` use an explicit internal envelope:
  `{"value": {"minimum": -0.8, "maximum": 0.8}, "unit": "pu"}`.
- Validating that envelope checks the nested model without dividing again.
  The same representation is used in `System` persistence.
- `None` stays `None` for optional structured fields.
- Bare structured mappings are always natural input. Do not load previously
  saved bare per-unit mappings as if they were marked internal values.

## Display modes

```python
from r2x_core import UnitSystem, get_unit_system, set_unit_system
from r2x_core.units import unit_system

set_unit_system(UnitSystem.DEVICE_BASE)
assert get_unit_system() is UnitSystem.DEVICE_BASE

with unit_system(UnitSystem.NATURAL_UNITS):
    text = repr(gen2)  # p_max formats using base_power, e.g. "40 MW"
```

Display modes affect `repr` formatting:

- `UnitSystem.DEVICE_BASE`: relative fields display as device-base `pu`.
- `UnitSystem.NATURAL_UNITS`: relative fields display in the base field's
  natural unit when the base value and base unit are known.
- `UnitSystem.SYSTEM_BASE`: `HasPerUnit` can display relative values against
  a system base when one is set.

## `HasPerUnit` pattern

`HasPerUnit` is for models that need system-base display in addition to the
normal `HasUnits` validation/formatting behavior. It keeps per-instance
system-base state out of serialization. Keep device-base conversion on `HasUnits`.

```python
from typing import Annotated

from pydantic import BaseModel
from r2x_core import HasPerUnit, Unit


class Generator(HasPerUnit, BaseModel):
    base_power: Annotated[float, Unit("MW")]
    p_max: Annotated[float, Unit("pu", base="base_power")]
```

## Failure playbook

- Natural-unit input fails with "Base unit ... could not be determined":
  - Annotate the referenced base field with `Unit("MW")`, `Unit("MVA")`, etc.
  - Confirm the `base="..."` string exactly matches the field name.
- Values look unchanged after `set_unit_system(...)`:
  - Expected for attribute access. Stored attributes remain floats; display
    mode changes formatting only.
- Per-unit value looks off by base:
  - Verify the base field value and unit annotation.
  - Verify the input dict unit is compatible with the base unit.
- System-base display does not appear:
  - Confirm the model uses `HasPerUnit` and has system-base state configured.

## Source modules to verify on drift

- `r2x_core.units.specs`: `UnitSpec`, `Unit`, and the conversion validator.
- `r2x_core.units.mixins`: `HasUnits`, `HasPerUnit`, and repr formatting.
- `r2x_core.units.conversion`: conversion and display functions.
- `r2x_core.units.__init__`: `UnitSystem`, `set_unit_system`, `unit_system`.
- `src/r2x_core/__init__.py`: root-package re-exports.

## Output expectations

- Fields annotated with `Unit(...)`, including any base fields.
- Whether inputs are internal per-unit floats or natural-unit dicts.
- Active display mode and whether it affects only formatting or validation.
- Numerical sanity checks across conversion boundaries.
