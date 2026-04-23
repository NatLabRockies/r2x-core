# r2x-core Units Reference

Use this document when the task is about per-unit conversions, unit-system
selection, or attaching units to component fields.

## Scope in this skill

This reference covers:

- `HasUnits` and `HasPerUnit` mixins for component classes
- `Unit` and `UnitSystem` enumeration
- `set_unit_system` and `get_unit_system` global selection
- Display modes: device base, natural units, and system base
- Common conversion mistakes

## Mental model

- r2x-core supports three display modes for unitful quantities:
  - **Natural units** (`UnitSystem.NATURAL_UNITS`): SI-ish absolute values
    (e.g., MW, MVA).
  - **Device base**: per-unit values relative to the device's own base
    rating.
  - **System base** (`UnitSystem.SYSTEM_BASE`): per-unit values relative
    to a chosen system MVA base.
- The chosen mode is **process-wide**, not per-component or per-call. Set
  it once at the boundary you own.
- Components opt into per-unit semantics by mixing in `HasPerUnit`.
  Components that just carry units (without per-unit conversions) use
  `HasUnits`.

## Component patterns

```python
from infrasys import Component
from pydantic import Field
from r2x_core import HasPerUnit, HasUnits, Unit

class Generator(Component, HasPerUnit):
    p_max_mw: float = Field(gt=0)
    unit: Unit = Unit.MW

class GeographicAnnotation(Component, HasUnits):
    area_km2: float = Field(gt=0)
    unit: Unit = Unit.KM2
```

(Field names track the installed version; confirm against `r2x_core.units`
source if behavior drifts.)

## Selecting a unit system

```python
from r2x_core import UnitSystem, set_unit_system, get_unit_system

set_unit_system(UnitSystem.SYSTEM_BASE)
assert get_unit_system() is UnitSystem.SYSTEM_BASE
```

Guidance:

- Set the unit system once at the application boundary (CLI entry point,
  notebook setup, test fixture), not inside individual plugins.
- If a plugin relies on a specific mode, document that requirement in its
  `PluginConfig` docstring and assert the mode in `on_validate`.
- Do not toggle the unit system mid-translation; downstream rule outputs
  become inconsistent.

## Conversion semantics

For a `HasPerUnit` field:

- Reading the field returns a value in the active unit system.
- Writing the field accepts a value in the active unit system and stores
  the canonical representation internally.
- The conversion uses the device's own `base_power` (or equivalent) and
  the configured system MVA base.

Cross-check the exact accessor names by inspecting `r2x_core.units` in the
installed package; the public surface includes `HasUnits`, `HasPerUnit`,
`Unit`, `UnitSystem`, `get_unit_system`, `set_unit_system`.

## Failure playbook

- Numerical disagreement between two plugins:
  - Confirm both plugins observe the same `get_unit_system()` value.
  - Confirm both plugins set their components' base values consistently.
- Per-unit value looks "off by base":
  - Verify the device base on the component vs. the system base used for
    conversion.
- A field returns natural-unit values when system-base was expected:
  - Confirm the component class actually mixes in `HasPerUnit`, not just
    `HasUnits`.

## Output expectations

- Active `UnitSystem` and where it was set.
- Which components use `HasPerUnit` vs. `HasUnits`.
- Numerical sanity checks across the conversion boundary.
