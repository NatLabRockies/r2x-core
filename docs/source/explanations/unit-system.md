# Unit System Design and Architecture

This document explains the design philosophy and implementation of the unit
handling system in R2X Core, providing insight into how it works and why certain
architectural decisions were made.

## Purpose and Motivation

Power system analysis fundamentally relies on per-unit normalization to enable
meaningful comparisons across equipment with vastly different ratings. A 500 MVA
generator and a 10 MVA generator cannot be directly compared using absolute
power values, but expressing both as fractions of their respective rated
capacities provides immediate insight into their operating states. The R2X Core
unit system addresses the challenge of managing these normalizations while
maintaining flexibility for different analysis contexts.

Traditional power system software often hard-codes per-unit conversions or
requires manual calculation by users. This approach introduces several problems.
Data imported from external sources arrives in natural units that must be
converted before use. Components moving between systems with different base
values require recalculation. Display and reporting tools must handle multiple
unit representations. The R2X Core unit system solves these challenges through
automatic conversion, flexible display modes, and type-safe field annotations.

## Core Design Principles

The unit system architecture follows several guiding principles that shape its
implementation and usage patterns.

### Separation of Storage and Display

The system maintains a strict separation between how values are stored
internally and how they are displayed to users. All per-unit quantities are
stored internally as floating point numbers normalized to their designated base
values. This internal representation never changes regardless of how the user
chooses to view the data. Display modes are transient settings that affect only
the string representation of values, not their underlying storage. This
separation ensures that calculations always work with consistent values while
allowing flexible reporting.

```python
from r2x_core import set_unit_system, UnitSystem

# Create a generator with a 100 MW base
gen = Generator(name="Gen1", p_max=0.5)  # 0.5 pu = 50 MW

# Internal storage is always 0.5 (device-base pu)
print(gen.p_max)  # Output: 0.5

# Change display mode - underlying value unchanged
set_unit_system(UnitSystem.NATURAL_UNITS)
print(gen)  # Display shows: 50.0 MW

set_unit_system(UnitSystem.DEVICE_BASE)
print(gen)  # Display shows: 0.5 pu

# Value accessed programmatically is always the same
assert gen.p_max == 0.5  # Always true, regardless of display mode
```

```{important}
Internal storage is always in device-base per-unit. Display modes (device-base, natural units, system-base) affect only the string representation when printing or generating reports. Calculations always operate on the consistent internal representation.
```

### Type Safety Through Annotations

Field annotations using Python's typing system provide compile-time safety and
runtime validation. When a field is annotated as
`Annotated[float, Unit("pu", base="base_power")]`, the type system declares both
the storage type (float) and the semantic meaning (per-unit referenced to
base_power). Pydantic's validator system hooks into these annotations to
automatically convert input values to the correct internal representation.
Invalid inputs are caught during construction rather than producing silent
errors during calculation.

```python doctest
>>> from typing import Annotated
>>> from pydantic import BaseModel
>>> from r2x_core import HasUnits, Unit
>>>
>>> class Generator(HasUnits, BaseModel):
...     name: str
...     base_power: Annotated[float, Unit("MW")]
...     p_max: Annotated[float, Unit("pu", base="base_power")]
...     voltage_kv: Annotated[float, Unit("kV")]
>>>
>>> gen1 = Generator(name="Gen1", base_power=100.0, p_max=0.8, voltage_kv=13.8)
>>> gen2 = Generator.model_validate({
...     "name": "Gen2",
...     "base_power": 50.0,
...     "p_max": {"value": 40.0, "unit": "MW"},
...     "voltage_kv": 13.8,
... })
>>> gen1.p_max == gen2.p_max == 0.8
True
```

The base field must also carry a `Unit` annotation. Numeric per-unit input is
stored directly, while the mapping input is converted using that base.

### Composability and Inheritance

Components can inherit from either `HasUnits` or `HasPerUnit` depending on
whether they need system-base tracking. The `HasUnits` mixin provides unit field
support without any dependency on system base values, making it suitable for
components with fixed units or quantities that do not participate in system-wide
normalization. The `HasPerUnit` class extends `HasUnits` with system-base
display support. This hierarchy lets components opt into exactly the features
they need.

```python doctest
>>> from typing import Annotated
>>> from infrasys import Component
>>> from pydantic import BaseModel
>>> from r2x_core import HasUnits, HasPerUnit, System, Unit
>>>
>>> class Transformer(HasUnits, BaseModel):
...     name: str
...     impedance: Annotated[float, Unit("ohm")]
...     x_r_ratio: float
>>>
>>> transformer = Transformer(name="TX1", impedance=0.05, x_r_ratio=2.0)
>>> transformer.system_base is None
True
>>>
>>> class Generator(HasPerUnit, Component):
...     base_power: Annotated[float, Unit("MVA")]
...     p_max: Annotated[float, Unit("pu", base="base_power")]
>>>
>>> gen = Generator(name="Gen1", base_power=100.0, p_max=0.8)
>>> system = System(system_base=100.0)
>>> system.add_components(gen)
>>> gen.system_base
100.0
```

```{tip}
Use `HasUnits` for standalone components that don't need system integration. Use `HasPerUnit` when components will be added to a `System` and need system-base display capabilities.
```

## Architecture Overview

The unit system consists of four main components that work together to provide
seamless unit handling.

### Unit Specifications (UnitSpec)

The `UnitSpec` class serves as metadata attached to field annotations. Each
specification contains two key pieces of information: the physical unit of the
quantity (such as "MVA" or "kV") and an optional reference to a base field for
per-unit calculations. When a field has no base reference, it stores absolute
quantities in the specified unit. When a base reference is provided, the field
stores per-unit values calculated relative to that base.

```python doctest
>>> from typing import Annotated
>>> from pydantic import BaseModel
>>> from r2x_core import HasUnits, Unit
>>>
>>> class Bus(HasUnits, BaseModel):
...     name: str
...     base_mva: Annotated[float, Unit("MVA")] = 100.0
...     voltage_kv: Annotated[float, Unit("kV")]
...     p_mva: Annotated[float, Unit("MVA", base="base_mva")]
>>>
>>> bus = Bus.model_validate({
...     "name": "Bus1",
...     "voltage_kv": 138.0,
...     "p_mva": {"value": 50.0, "unit": "MVA"},
... })
>>> bus.p_mva
0.5
>>> bus.voltage_kv
138.0
```

The specification integrates with Pydantic's validation system through the
`__get_pydantic_core_schema__` method. This integration allows natural unit
inputs in dictionary form to be automatically converted during model
construction. A user can provide `{"value": 150.0, "unit": "MVA"}` and the
validator converts this to per-unit by dividing by the appropriate base value.
The validator also coerces integers to floats. Define base fields before their
dependent fields so their values are available during field validation.

### Unit-Aware Mixins (HasUnits and HasPerUnit)

The mixin classes provide the foundation for components to declare and manage
unit-aware fields. `HasUnits.__get_pydantic_core_schema__` collects `UnitSpec`
metadata into the class-level `unit_specs` mapping after field annotations
resolve, including during `model_rebuild()`. A missing or unannotated base field
is rejected when the schema is built.

Specifications are immutable and can be reused across models. A field validator
resolves each scalar input's base unit from the owning model, so subclasses can
override base units without affecting their parents.

The `HasPerUnit` class extends this foundation with system-base display support.
It stores system base power internally and exposes it through the `system_base`
property. `System.add_components` binds that value through
`bind_system_base`; display formatting uses it to convert device-base per-unit
to system-base per-unit.

### Utility Functions and Conversions

The `r2x_core.units.conversion` module provides unit conversion and formatting
functions. `convert_to_internal` takes an input value (a float or a mapping
with value and unit), a unit specification, and base values, then returns the
per-unit representation. It uses Pint for dimensional conversion when the
input and base units differ. `format_for_display` applies the configured display
mode, rendering per-unit values as device-base, natural-unit, or system-base
values as appropriate.

### Global Display State

The unit system maintains a global display mode that affects all components
simultaneously. This global state is managed through the `UnitSystem`
enumeration which defines three modes: `DEVICE_BASE`, `NATURAL_UNITS`, and
`SYSTEM_BASE`. The `set_unit_system` function updates this global state, while
the `get_unit_system` function retrieves it. A context manager `unit_system`
allows temporary mode changes that automatically revert when the context exits.

This global state design enables consistent reporting across an entire system.
When generating a report, a user can set the display mode once and all
components will render in that mode. The alternative of passing display mode to
every formatting call would be cumbersome and error-prone. The global state is
thread-local to support concurrent use in multi-threaded applications.

```{note}
The `unit_system` context manager provides a convenient way to temporarily change display mode for a specific code block, automatically reverting to the previous mode when the context exits.
```

## Integration with System Class

The `System` class plays a crucial role in the unit system by managing the
relationship between components and the system base power. When the system is
initialized, it stores the system base power and defines a custom Pint unit
called "system_base" with that magnitude. This allows components to perform
conversions using the Pint library's dimension analysis.

When components are added to a system through `add_components`, the system
checks if they inherit from `HasPerUnit` and binds the system's base power with
`bind_system_base`. It rejects a component already bound to a different system
base. Deserialization restores the same relationship for each `HasPerUnit`
component so system-base display works after reloading.

## Pint Integration for Unit Conversion

The R2X Core unit system leverages the Pint library for dimensional analysis and
unit conversion. Pint provides a registry of known units and the mathematical
relationships between them. When a user provides input in natural units that
differ from the base unit (such as kW when the base is MVA), the conversion
system uses Pint to perform the transformation.

The integration creates a shared `UnitRegistry` instance that all conversions
use. The system base power is registered as a custom unit within this registry,
allowing expressions like `device_pu.to('system_base')` to work correctly.
Pint's dimensional analysis ensures that unit mismatches are caught. Attempting
to convert a power quantity to a voltage unit will raise an exception rather
than silently producing incorrect results.

This integration provides robustness and extensibility. New units can be added
to support different domains without modifying core conversion logic. The
dimensional type system prevents common errors such as adding voltages to powers
or multiplying incompatible quantities.

## Performance Considerations

The unit system is designed with performance in mind for large-scale power
system models. Internal storage in per-unit form means that most calculations
work with simple floating point operations without unit tracking overhead.
Conversion happens only at component construction and during display formatting.
The validation system caches unit specifications during class definition rather
than computing them for each instance.

Display formatting is lazy and occurs only when string representations are
requested. Accessing field values programmatically returns raw floats without
formatting overhead. This design ensures that computational loops operating on
component data do not pay any unit conversion penalty. Only user-facing
operations such as printing or report generation incur the formatting cost.

```{hint}
For performance-critical code, access component field values directly (e.g., `gen.output`) to get raw floats. Unit conversion overhead only occurs when converting string representations for display or logging.
```

## Design Trade-offs and Alternatives

The global display state design represents a trade-off between convenience and
thread safety. An alternative design could pass display mode explicitly to every
formatting operation, which would be more functional but significantly more
verbose. The current design accepts the need for thread-local state in exchange
for cleaner usage patterns.

The choice to store all per-unit values in device-base internally could have
been made differently. An alternative would be to convert everything to
system-base at the point of system addition. This would simplify system-base
display but would require recalculating values if components are moved between
systems or if the system base changes. The current design maintains component
autonomy at the cost of requiring both device and system base values for
system-base display.

The integration with Pydantic's validation system through
`__get_pydantic_core_schema__` tightly couples the unit system to Pydantic. An
alternative design using custom descriptors or metaclasses could provide more
independence but would lose the automatic validation, serialization, and type
introspection that Pydantic provides. The trade-off favors integration for
better developer experience.

## Extension Points and Future Directions

The unit system architecture provides several extension points for future
enhancement. Additional display modes could be added by extending the
`UnitSystem` enumeration and implementing corresponding formatting logic.
Support for complex units (such as impedance in ohms per mile) could be added
through enhanced unit specifications. Per-component display mode overrides could
allow mixing modes within a single report.

The system could be extended to track uncertainty or ranges alongside values,
enabling interval arithmetic for sensitivity analysis. Support for symbolic
units in equations could facilitate automatic unit checking in complex
calculations. Integration with optimization solvers could leverage unit
information to improve numerical conditioning through automatic scaling.

## Conclusion

The R2X Core unit system provides a robust foundation for handling the diverse
unit requirements of power system analysis. By separating internal storage from
external display, leveraging type annotations for safety, and integrating
carefully with both Pydantic validation and the System class lifecycle, it
achieves both flexibility and reliability. The architectural decisions reflect
the practical needs of power system modeling while maintaining clean
abstractions that support future extension.
