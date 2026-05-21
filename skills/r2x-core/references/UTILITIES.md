# r2x-core Utilities Reference

Use this when translator code needs common component extraction, safe component
creation, CSV export, getter helpers, or time-series metadata transfer.

## Public utility surface

Verify exports in `src/r2x_core/__init__.py` before importing from root.
Common public utilities include:

- `components_to_records(...)`
- `export_components_to_csv(...)`
- `create_component(...)`
- `getter(...)`
- `transfer_time_series_metadata(...)`

Some helpers live under submodules only. Import submodule-only helpers from the
source module intentionally, and mention that in the handoff.

## Do

- Reuse utility functions before writing bespoke component loops.
- Preserve UUID/name identity when extracting and re-creating components.
- Treat `create_component(...)` as a safer boundary for component construction
  and error reporting.
- Use `getter(...)` for nested/composed values when rule field mapping would be
  too blunt.
- Use `transfer_time_series_metadata(...)` when translation preserves components
  with associated time series.

## Don't

- Do not duplicate export/extraction code in every plugin.
- Do not ignore `Result`-style failures from utility helpers.
- Do not assume duplicate component names are safe for getter lookups; verify
  current source behavior.
- Do not move time-series metadata by hand unless the utility cannot express the
  mapping.

## Common patterns

### Extract records

```python
from r2x_core import components_to_records

records = components_to_records(system)
```

Use records for tabular export, debugging, and rule fixture construction.

### Export components

```python
from r2x_core import export_components_to_csv

export_components_to_csv(system, file_path="components.csv")
```

Prefer the utility over hand-rolled CSV export so field handling remains
consistent with r2x-core expectations.

### Create components safely

```python
from r2x_core import create_component

result = create_component(Generator, name="gen1", p_max=100.0)
if result.is_err():
    raise ValueError(result.err())
generator = result.ok()
```

Current root export signature is `create_component(component_class, **field_values)`
with optional `skip_none` and `skip_validation` keyword controls. The important
pattern is to keep component construction errors at a single typed boundary
instead of scattering bare constructors through rules.

### Getter helpers

Use getter helpers for nested or composed attributes referenced by rules. When a
rule is loaded from records, string getter specs may be converted to callables;
when constructing `Rule(...)` directly, pass callable getters.

### Time-series metadata transfer

When source and target systems preserve time-series associations, use
`transfer_time_series_metadata(...)` instead of manually copying association
rows. Report counts/errors from the transfer result in the handoff.

## Source modules to verify on drift

- `r2x_core.utils`: public helper exports and upgrade helpers.
- `r2x_core.getters`: getter construction and duplicate-name behavior.
- `r2x_core.time_series`: time-series metadata transfer.
- `docs/source/tutorials/plugin-utilities.md`: user-facing examples.

## Output expectations

- Utility chosen and why.
- Source/target component types and identity mapping.
- `Result` handling for utility failures.
- Time-series transfer counts when relevant.
