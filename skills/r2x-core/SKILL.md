---
name: r2x-core
description: |
  Build, extend, and operate r2x-core model translators using its plugin
  system, declarative rule engine, DataStore-driven file ingestion, and
  unit/versioning machinery. r2x-core sits on top of infrasys
  System/Component primitives and provides the application-level translator
  scaffolding for power system models (ReEDS, PLEXOS, Sienna, SWITCH, ...).
license: MIT
allowed-tools: Read Edit Grep Glob Bash Write
metadata:
  author: r2x-core team
  version: "0.1.0"
  category: power-system-translation
---

# r2x-core

## Use when

- Authoring or extending an r2x-core `Plugin` (translator, parser, exporter, builder).
- Wiring a `PluginConfig` and exposing it through `@expose_plugin` / entry points.
- Designing or auditing declarative `Rule` mappings, `RuleFilter` composition, or
  rule executor behavior.
- Configuring a `DataStore` with `DataFile` entries and choosing the right reader
  (CSV, Parquet, JSON, XML, HDF5) plus `ReaderConfig` / `TabularProcessing` /
  `JSONProcessing` / `H5Format`.
- Returning typed results via `rust_ok` (`Ok` / `Err` / `Result`,
  `RuleResult`, `TranslationResult`) instead of raising for control flow.
- Working with the per-unit system (`HasUnits`, `HasPerUnit`, `UnitSystem`,
  `set_unit_system`, `get_unit_system`).
- Defining or applying `UpgradeStep` chains, `VersionStrategy` implementations
  (semver, git), or detecting on-disk dataset versions with `VersionReader`.

## Avoid when

- Pure infrasys `System` / `Component` modeling questions with no r2x-core
  surface area, use the `infrasys` skill instead.
- Generic Python packaging or unrelated framework questions.
- Tasks that are purely about end-user model semantics (e.g. PLEXOS XML
  internals) without touching the r2x-core translator boundary.

## Quick start: which doc first?

- Plugin lifecycle, hooks, capabilities, registration: [PLUGINS.md](./PLUGINS.md)
- Rule definition, filters, executor, dependencies: [RULES.md](./RULES.md)
- DataStore, DataFile, readers, processors: [DATA_STORE.md](./DATA_STORE.md)
- Per-unit system and conversions: [UNITS.md](./UNITS.md)
- Upgrade steps and version strategies: [VERSIONING_UPGRADES.md](./VERSIONING_UPGRADES.md)
- Cross-cutting API contracts and call patterns: [REFERENCE.md](./REFERENCE.md)
- Discovery protocol for unfamiliar APIs: [DISCOVERY.md](./DISCOVERY.md)
- Trigger and near-miss prompts: [EXAMPLES.md](./EXAMPLES.md)

## Additional documentation

- [tools/check_api_symbols.py](./tools/check_api_symbols.py), API drift checker for
  the key `r2x_core` public symbols (checks the installed package by default).
- [tools/check_data_store.py](./tools/check_data_store.py), validates a
  `DataStore` JSON/folder layout and lists registered `DataFile` entries.
- [tools/inspect_plugins.py](./tools/inspect_plugins.py), enumerates plugins
  discoverable through the `r2x_plugin` entry point group, including their
  `PluginConfig` fields and implemented hooks.

## Workflow

1. Inspect first, change second.
   - Identify which surface the task touches: plugin lifecycle, rules,
     DataStore, units, or versioning.
   - For an existing translator, run `tools/inspect_plugins.py` to enumerate
     registered plugins and their declared hooks/config schema.
   - For an existing dataset, run `tools/check_data_store.py` to confirm
     `DataFile` entries resolve and readers match the file format.
   - Follow [DISCOVERY.md](./DISCOVERY.md) to confirm exact API behavior from
     installed source when docs and behavior disagree.

2. Define boundaries before code.
   - Express configuration as a typed `PluginConfig` subclass (Pydantic v2),
     not loose dicts.
   - Choose only the lifecycle hooks the plugin actually needs
     (`on_validate`, `on_prepare`, `on_build`, `on_transform`, `on_translate`,
     `on_export`, `on_cleanup`); do not stub unused hooks.
   - Use `Rule` + `RuleFilter` for declarative mapping between source and
     target component types instead of inlining transformation logic.

3. Apply minimal changes.
   - Return `Ok(value)` / `Err(error)` from hooks; never raise for control
     flow inside lifecycle methods.
   - Keep readers configured at the `DataFile` boundary (`ReaderConfig`,
     `TabularProcessing`, `JSONProcessing`, `H5Format`), not inside plugin
     code.
   - Reuse `create_component`, `components_to_records`,
     `export_components_to_csv`, and other utilities from `r2x_core.utils`
     instead of reinventing them.

4. Verify behavior.
   - Round-trip serialize the produced `System` (`to_json`/`from_json` from
     infrasys) and confirm critical components and time series survive.
   - For upgrades, run the `UpgradeStep` chain forward against fixture data
     and assert the post-upgrade structure.
   - For unit changes, exercise both `UnitSystem.NATURAL_UNITS` and
     `UnitSystem.SYSTEM_BASE` (or device-base where relevant) and confirm the
     numerical conversion matches expectations.

5. Respect extension hooks.
   - Use `@expose_plugin` (and the `r2x_plugin` entry point) for discovery,
     no compatibility try/except fallbacks (per repo convention).
   - For per-unit semantics, prefer `HasPerUnit` mixin over ad-hoc unit
     conversion helpers.
   - For schema migrations, prefer composing `UpgradeStep` instances driven
     by a `VersionStrategy` (`SemanticVersioningStrategy`,
     `GitVersioningStrategy`) over hand-rolled version branching.

## Output expectations

- What surface was touched (plugin / rules / store / units / versioning).
- Exact APIs called for inspection and validation.
- New or changed public symbols (mention the affected `__all__` entries).
- Result-type usage (`Ok` / `Err`) and error mapping decisions.
- Persistence and round-trip checks performed.
- Which integrated references were consulted and why.
