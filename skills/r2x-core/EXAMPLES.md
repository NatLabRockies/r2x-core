# r2x-core Skill Trigger Examples

Use these prompts to validate when this skill should activate.

## Should trigger

1. "Add a new translator plugin for ReEDS that loads CSVs from a data
   directory and produces an infrasys `System`."
2. "My `Plugin.on_translate` is raising instead of returning `Err`. Refactor
   the lifecycle to use `Result` end to end."
3. "Register `MyTranslator` so `r2x_plugin` entry-point discovery picks it up
   without a manual import."
4. "Define a `Rule` mapping `SourceGenerator -> Generator` with a
   `RuleFilter` that excludes retired units, then wire it into the executor."
5. "Configure a `DataStore` that reads `gen.csv`, `load.parquet`, and
   `regions.h5` with the right `ReaderConfig` and `H5Format` per file."
6. "Convert a model that exposes natural-unit values into the per-unit
   system using `HasPerUnit`, with `UnitSystem.SYSTEM_BASE` for display."
7. "Build an `UpgradeStep` chain to migrate datasets from v1 to v2 using
   `SemanticVersioningStrategy` and `VersionReader`."
8. "Inspect which plugins are discoverable in the current environment and
   show their `PluginConfig` fields and implemented hooks."

## Near-miss (should NOT trigger)

1. "Help me design a generic Python package without any r2x-core surface
   area." (use general Python guidance)
2. "Pick a UI framework for a power system dashboard." (out of scope)
3. "Explain the PLEXOS XML schema in detail." (model-specific, not r2x-core)
4. "Pure infrasys `System` introspection question with no r2x-core plugin,
   rule, store, units, or versioning context." (use the `infrasys` skill)

## Borderline prompts (trigger + integrated reference)

1. "Migrate an old DataStore JSON layout to the new schema."
   - Trigger this skill, then use `VERSIONING_UPGRADES.md` and
     `DATA_STORE.md`.
2. "Plugin entry point is not discovered after install."
   - Trigger this skill, then use `PLUGINS.md` (registration / exposure
     section) and `tools/inspect_plugins.py`.
3. "Rule mapping silently skips a component class."
   - Trigger this skill, then use `RULES.md` (filter and dependency
     sections) and `REFERENCE.md` (executor contract).
4. "HDF5 reader returns the wrong shape for a time-indexed dataset."
   - Trigger this skill, then use `DATA_STORE.md` (HDF5 + `H5Format`
     section). Round-trip with `tools/check_data_store.py`.
5. "Per-unit conversion mismatches between two plugins."
   - Trigger this skill, then use `UNITS.md` and confirm both plugins use
     the same `set_unit_system(...)` configuration.
