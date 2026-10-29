---
name: r2x-core
description: >
  Build, debug, review, and extend r2x-core translators and public Python APIs,
  including plugins, rules, typed file ingestion, parser construction, named
  table mappings, HDF5 readers, unit-aware components, persistence, and upgrades.
  Use for r2x-core, model translation, parser or exporter plugins, rule mappings,
  DataStore configuration, table assembly, per-unit behavior, or r2x-core schema
  upgrades. Do not use for standalone Python guidance or foundational infrasys
  modeling with no r2x-core surface.
---

# r2x-core

Operational guidance for the r2x-core translation layer on top of infrasys
`System` and `Component` models. Treat the public API examples in
[QUICKREF.md](./references/QUICKREF.md) as the first stop for every task. Load
only the focused reference needed for the task.

## Mental model

```text
files -> DataReader -> optional table assembly -> parser instructions -> System
System -> PluginContext -> Rule executor -> target System -> export/persistence
```

- `PluginConfig` owns typed configuration and configuration-asset paths.
- `DataStore` holds file-mapping configuration. `DataReader` reads files and
  returns named, typed sources.
- `build_system(...)` reads configured inputs and parser instructions to build
  a `System`; `build_system_from_sources(...)` builds from already decoded data.
- Table mappings optionally assemble named tables between file reading and
  parser construction. They are separate from `DataFile.proc_spec` operations.
- `PluginContext` owns shared execution state: config, stores, systems, rules,
  metadata, and version settings.
- `Plugin` provides optional lifecycle hooks. Hooks return `rust_ok` results;
  `Plugin.run()` updates and returns the context, or raises `PluginError` for a
  hook `Err`.
- `Rule` declares source-to-target component construction. The executor reads
  systems from the context and writes target components to the target system.
- Domain `System` / `Component` semantics remain owned by infrasys and the
  component package, not by this skill.

## Public API routing

Read [QUICKREF.md](./references/QUICKREF.md) first. Then route by task center:

| Task center                                                 | Read                                                          |
| ----------------------------------------------------------- | ------------------------------------------------------------- |
| Plugin class, config, context, exposure, lifecycle          | [PLUGINS.md](./references/PLUGINS.md)                         |
| Rule declarations, filters, getters, execution              | [RULES.md](./references/RULES.md)                             |
| Files, readers, processors, HDF5, DataStore                 | [DATA_STORE.md](./references/DATA_STORE.md)                   |
| Parser instructions and configured System construction      | [INGESTION.md](./references/INGESTION.md)                     |
| Named-table mappings and cross-boundary assembly             | [TABLE_MAPPING.md](./references/TABLE_MAPPING.md)             |
| `Annotated` unit fields and display modes                   | [UNITS.md](./references/UNITS.md)                             |
| Version strategies, `UpgradeStep`, coordinator              | [VERSIONING_UPGRADES.md](./references/VERSIONING_UPGRADES.md) |
| Component extraction, export, time-series helpers           | [UTILITIES.md](./references/UTILITIES.md)                     |
| Source/signature verification or docs drift                 | [DISCOVERY.md](./references/DISCOVERY.md)                     |
| Logging levels, sinks, structured context, or diagnostics   | [LOGGING.md](./references/LOGGING.md)                         |
| `r2x` CLI orchestration and plugin validation               | [R2X_CLI.md](./references/R2X_CLI.md)                         |
| Cross-cutting design and failure contracts                  | [REFERENCE.md](./references/REFERENCE.md)                     |

## Public API rules

Use these rules to prevent the unreliable call patterns this skill is intended
to eliminate:

1. Import from `r2x_core` when the symbol is in `src/r2x_core/__init__.py`.
   Do not invent a second abstraction or use private internals to avoid the
   public API.
2. Verify unfamiliar signatures against root exports, defining source, nearby
   tests, and project docs. Source and tests outrank stale documentation.
3. `Plugin.run()` returns `PluginContext`, not `Result`. It raises `PluginError`
   when a hook returns `Err`.
4. `apply_rules_to_context(context)` reads rules from `context.rules`; it does
   not accept a second rules argument. `apply_single_rule(rule, *, context=...)`
   takes the rule first and returns rule-application statistics in a `Result`.
5. A physical `DataFile` sets exactly one of `fpath`, `relative_fpath`, or
   `glob`. A derived input instead sets exactly one of `source`,
   `source_selection`, or `inline_table`. Reader settings apply only to physical
   files. `DataStore` stores mappings; use `DataReader` to read them.
6. `ReaderConfig` uses `format` and `options`. `DataFile.proc_spec` uses ordered
   `steps` tagged by `op`; table-mapping records use ordered `operations` tagged
   by `operation`. Do not mix these two schemas.
7. `VersionReader` is a protocol. `UpgradeStep` uses `target_version` with
   optional `min_version` and `max_version`; it does not use
   `from_version`/`to_version` constructor fields.
8. Use Pydantic v2 `PluginConfig` subclasses and explicit typed fields. Use
   `Annotated[..., Field(...)]` for new modeled fields and
   `Field(default_factory=...)` for mutable defaults.
9. Use `Ok` / `Err` at recoverable boundaries. Branch on results explicitly; do
   not unwrap live results, catch `Exception` broadly, or hide failures behind
   `None`.
10. Prefer domain models, protocols, named structured returns, and keyword-only
    configuration over loose dictionaries, `object`, casual casts, and long
    positional tuples.
11. Use the repository logging policy. Loguru is disabled by default; every
    application built on r2x-core should disable its own package namespace at
    import time and enable it explicitly at the application boundary. Use
    `setup_logging(...)` only there, select levels by operational meaning, and
    keep diagnostics structured and non-sensitive.
12. Test public behavior. Add a regression test for a bug, reuse repository
    fixtures, and round-trip persistence changes through serialization.

## Minimal public examples

A class plugin is constructed from a typed context and returns that context:

```python
from pydantic import Field
from rust_ok import Ok, Result

from r2x_core import Plugin, PluginConfig, PluginContext, System


class BuildConfig(PluginConfig):
    name: str = Field(default="demo", min_length=1, description="System name")


class BuildPlugin(Plugin[BuildConfig]):
    def on_build(self) -> Result[System, str]:
        return Ok(System(name=self.config.name))


context = PluginContext(config=BuildConfig(name="western_grid"))
result_context = BuildPlugin.from_context(context).run()
assert result_context.system is not None
assert result_context.system.name == "western_grid"
```

A function transform is called explicitly. `@expose_plugin` marks the function;
it does not wrap, instantiate, inject, or execute it:

```python
from pydantic import Field
from rust_ok import Ok, Result

from r2x_core import PluginConfig, System, expose_plugin


class RenameConfig(PluginConfig):
    suffix: str = Field(default="_v2", description="Suffix to append")


@expose_plugin
def rename_system(system: System, config: RenameConfig) -> Result[System, str]:
    system.name = f"{system.name}{config.suffix}"
    return Ok(system)
```

## Workflow

1. **Classify the surface:** plugin, rules, file ingestion, parser construction,
   table mapping, units, persistence, upgrades, or transform. Keep pure infrasys
   work separate.
2. **Inspect first:** read repository instructions, `pyproject.toml`, defining
   source modules, adjacent tests, and relevant docs. Reproduce failures when
   practical.
3. **Confirm the contract:** inspect root exports and exact signatures. If the
   installed package differs from the checkout, state which one is targeted.
4. **Implement a small vertical slice:** keep configuration, domain models,
   translator logic, and boundary serialization separate. Reuse existing APIs.
5. **Validate narrowly, then expand:** run focused tests first, then the
   repository's `mise run` task or required `prek`/pytest checks. Round-trip real
   systems when persistence is involved.
6. **Report evidence:** include public behaviors changed, exact commands and
   outcomes, assumptions, and remaining risks.

For logging changes, load [LOGGING.md](./references/LOGGING.md) and validate
namespace disable/enable behavior, level filtering, sink behavior, structured
fields, and exception output.

## Validation helpers

Run these from the r2x-core checkout when appropriate:

```bash
uv run python skills/r2x-core/tools/check_api_symbols.py
uv run python skills/r2x-core/tools/check_api_symbols.py --repo src/r2x_core
uv run python skills/r2x-core/tools/inspect_plugins.py --group r2x_plugin
uv run python skills/r2x-core/tools/check_data_store.py <data-root> --list-unknown
```

The API probe checks documented symbol presence, not signatures or semantics.
The plugin probe inspects installed entry points in the active Python
environment and imports class targets; it does not inspect source-tree metadata
or function transforms. This r2x-core checkout does not define an `r2x_plugin`
entry point, so running the probe here without an installed translator should
report no entries. Run it in the environment that contains the plugin package
you want to inspect; otherwise that result is expected. The datastore probe
classifies extension-based format inference only; it cannot prove reader
options, custom readers, or schema correctness.

## Handoff

- **Surface:** plugin, rules, data, parser ingestion, table mapping, units,
  persistence, upgrades, transform, or logging.
- **Contract:** public symbols and return/error behavior involved.
- **Changes:** files and observable behavior.
- **Validation:** exact commands and results.
- **Risks:** source/docs mismatches, untested integrations, or follow-up work.
