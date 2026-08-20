# r2x-core trigger examples

Use these prompts to tune activation and routing. They are not a substitute for
reading the focused reference.

## Should trigger

1. "Build a typed r2x-core translator plugin that loads CSVs and builds a
   System."
2. "Why does `Plugin.run()` fail even though my hook returns `Err`?"
3. "Show the public API call shape for `apply_single_rule` and fix my caller."
4. "Map source generators to target units with a versioned Rule and filter."
5. "Configure DataFile and DataStore for CSV, JSON, Parquet, and HDF5 inputs."
6. "Debug an HDF5 reader returning generic columns instead of solve_year."
7. "Add an Annotated per-unit field and test natural-unit input."
8. "Add an upgrade step for an old file mapping and verify idempotency."
9. "Check which r2x-core plugins are discoverable in the active environment."
10. "Review this r2x-core change for public API, Result, typing, and regression
    risks."

## Should not trigger

1. "Design a generic Pydantic model unrelated to r2x-core." (use data-model)
2. "Inspect an infrasys System and attach time series without translation."
   (use infrasys)
3. "Write a standalone Python CLI." (use Python/CLI guidance)
4. "Explain PLEXOS XML semantics without framework code." (use domain guidance)
5. "Review an unrelated pull request." (use review guidance)
6. "Commit the current changes." (use repository/forge workflow)

## Borderline routing

- A translator component schema belongs to the component package or infrasys;
  use this skill only for the r2x-core plugin/rule/store boundary.
- A `System.from_json` migration belongs to infrasys when it changes the
  foundational serialized schema; use this skill for r2x-core file/config
  upgrades around that boundary.
- A generic reader belongs to Python guidance; use this skill when it extends
  `DataReader`, `DataFile`, `DataStore`, or HDF5 handling.
