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

```python
from typing import Annotated
from r2x_core import HasUnits, Unit
from pydantic import BaseModel

class Generator(HasUnits, BaseModel):
    name: str
    base_power: float  # In MW
    # Power output as per-unit (normalized to base_power)
    p_max: Annotated[float, Unit("pu", base="base_power")]
    # Voltage rating in absolute units
    voltage_kv: Annotated[float, Unit("kV")]

# Type-safe inputs - automatic conversion
gen1 = Generator(
    name="Gen1",
    base_power=100.0,
    p_max=0.8,  # 0.8 pu
    voltage_kv=13.8
)

# Natural unit input - automatic conversion
gen2 = Generator(
    name="Gen2",
    base_power=50.0,
    p_max={"value": 40.0, "unit": "MW"},  # Converts to 0.8 pu (40/50)
    voltage_kv=13.8
)

# Both generators have same internal representation
assert gen1.p_max == gen2.p_max == 0.8  # True
```

### Composability and Inheritance

Components can inherit from either `HasUnits` or `HasPerUnit` depending on
whether they need system-base tracking. The `HasUnits` mixin provides unit field
support without any dependency on system base values, making it suitable for
components with fixed units or quantities that do not participate in system-wide
normalization. The `HasPerUnit` class extends `HasUnits` to add system-base
tracking through a private `_system_base` attribute. This hierarchical design
allows components to opt into exactly the features they need.

```python
from typing import Annotated
from r2x_core import HasUnits, HasPerUnit, Unit
from pydantic import BaseModel

# Standalone component without system integration
class Transformer(HasUnits, BaseModel):
    name: str
    impedance: Annotated[float, Unit("ohm")]  # Fixed unit, no per-unit
    x_r_ratio: float  # Dimensionless quantity

# Transformers don't need system base
transformer = Transformer(
    name="TX1",
    impedance=0.05,
    x_r_ratio=2.0
)

# System-integrated component
class Generator(HasPerUnit, BaseModel):
    name: str
    base_power: float
    p_max: Annotated[float, Unit("pu", base="base_power")]
    # Can access system base when added to a system

# Generators can use system-base display when added to a System
gen = Generator(name="Gen1", base_power=100.0, p_max=0.8)
# gen._system_base is set when added to a System
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

```python
from typing import Annotated
from r2x_core import Unit

# Specification without base - stores absolute quantity
voltage: Annotated[float, Unit("kV")]

# Specification with base - stores per-unit value
# Stored as: input_value / base_mva
power_mva: Annotated[float, Unit("MVA", base="base_mva")]

# Usage in a component
from r2x_core import HasUnits
from pydantic import BaseModel

class Bus(HasUnits, BaseModel):
    name: str
    base_mva: float = 100.0

    # Absolute voltage
    voltage_kv: Annotated[float, Unit("kV")]

    # Per-unit power
    p_mva: Annotated[float, Unit("MVA", base="base_mva")]

# Natural unit input auto-conversion
bus = Bus(
    name="Bus1",
    voltage_kv=138.0,
    p_mva={"value": 50.0, "unit": "MVA"}  # 50/100 = 0.5 pu internally
)

print(bus.p_mva)  # Output: 0.5 (stored as per-unit)
print(bus.voltage_kv)  # Output: 138.0 (stored as absolute)
```

The specification integrates with Pydantic's validation system through the
`__get_pydantic_core_schema__` method. This integration allows natural unit
inputs in dictionary form to be automatically converted during model
construction. A user can provide `{"value": 150.0, "unit": "MVA"}` and the
validator converts this to per-unit by dividing by the appropriate base value.
The validator also handles type coercion from integers to floats and validates
that required base values are available.

### Unit-Aware Mixins (HasUnits and HasPerUnit)

The mixin classes provide the foundation for components to declare and manage
unit-aware fields. The `HasUnits` mixin implements the `__init_subclass__` hook
to enforce that any class using units must also inherit from Pydantic's
`BaseModel`. This ensures that the validation machinery is available. The mixin
also provides the `_get_unit_specs_map` method which introspects a class's field
annotations to build a mapping from field names to their `UnitSpec` metadata.

The `HasPerUnit` class extends this foundation with system-base tracking. It
adds a private `_system_base` attribute that stores the system base power when a
component is added to a system. The `_get_system_base` method provides access to
this value for conversion calculations. When display mode is set to system-base,
the formatting system uses this stored value to convert device-base per-unit to
system-base per-unit.

### Utility Functions and Conversions

The utility module provides pure functions for unit conversion and formatting.
The `_convert_to_internal` function takes an input value (either float or dict
with value and unit), a unit specification, and base values, then returns the
per-unit representation. This function handles the mathematical conversion
including dimensional analysis through the Pint library when unit strings differ
from base units.

The `_format_for_display` function performs the inverse operation. Given an
internal per-unit value, it consults the current display mode and converts to
the appropriate representation. In device-base mode, it returns the per-unit
value unchanged. In natural units mode, it multiplies by the base value and
appends the base unit string. In system-base mode, it converts from device base
to system base and appends the system-base indicator. This separation of
conversion logic from component code maintains clean abstractions.

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
checks if they inherit from `HasPerUnit`. For components that do, it sets their
`_system_base` attribute to the system's base power value. The system also
validates that components are not added to multiple systems with different base
values, raising an error if such a conflict is detected. This validation
prevents inconsistent state where a component's per-unit values would be
ambiguous.

During deserialization from JSON, the system must restore this relationship. The
`from_json` class method reconstructs the system and its components, then
iterates over all `HasPerUnit` components to set their `_system_base`
attributes. This ensures that system-base display mode works correctly after
reloading a saved system.

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
