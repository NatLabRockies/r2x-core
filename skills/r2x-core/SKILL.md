---
name: r2x-core
description: >
  Build, debug, review, and extend r2x-core translators and their public Python
  APIs, including Plugin, PluginConfig, PluginContext, exposed transforms,
  Rule and RuleFilter translation, DataFile/DataStore/DataReader ingestion,
  HDF5 readers, unit-aware components, persistence, and upgrades. Use when a
  task mentions r2x-core, model translation, parser or exporter plugins, rule
  mappings, DataStore configuration, per-unit behavior, or r2x-core schema
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
input files -> DataStore/DataReader -> PluginContext -> Plugin lifecycle
                                      -> Rule executor -> target System
                                      -> persistence or export
```

- `PluginConfig` owns typed configuration and configuration-asset paths.
- `PluginContext` owns shared mutable execution state: config, stores, systems,
  rules, metadata, and version settings.
- `Plugin` provides optional lifecycle hooks. Hooks return `rust_ok` results;
  `Plugin.run()` updates the context and returns the context.
- `Rule` declares source-to-target component construction. The executor reads
  systems from the context and writes target components to the target system.
- `DataFile` describes one input. `DataStore` groups file specifications and
  `DataReader` performs the read and processing pipeline.
- Domain `System` / `Component` semantics remain owned by infrasys and the
  component package, not by this skill.

## Public API routing

Read [QUICKREF.md](./references/QUICKREF.md) first. Then route by task center:

| Task center                                                 | Read                                                          |
| ----------------------------------------------------------- | ------------------------------------------------------------- |
| Plugin class, config, context, exposure, lifecycle          | [PLUGINS.md](./references/PLUGINS.md)                         |
| Rule declarations, filters, getters, execution              | [RULES.md](./references/RULES.md)                             |
| Files, readers, processors, HDF5, datastore                 | [DATA_STORE.md](./references/DATA_STORE.md)                   |
| `Annotated` unit fields and display modes                   | [UNITS.md](./references/UNITS.md)                             |
| Version strategies, `UpgradeStep`, coordinator              | [VERSIONING_UPGRADES.md](./references/VERSIONING_UPGRADES.md) |
| Component extraction, creation, export, time-series helpers | [UTILITIES.md](./references/UTILITIES.md)                     |
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
3. `Plugin.run()` returns `PluginContext`, not `Result`. It raises
   `PluginError` when a hook returns `Err`.
4. `apply_rules_to_context(context)` reads rules from `context.rules`; it does
   not accept a second rules argument. `apply_single_rule(rule, *, context=...)`
   takes the rule first and returns rule-application statistics in a `Result`.
5. `DataFile` uses `info`, `reader`, and `proc_spec`. Its path source is exactly
   one of `fpath`, `relative_fpath`, or `glob`. `DataStore.add_data(...)` takes a
   sequence of files.
6. `VersionReader` is a protocol. `UpgradeStep` uses `target_version` with
   optional `min_version` and `max_version`; it does not use
   `from_version`/`to_version` constructor fields.
7. Use Pydantic v2 `PluginConfig` subclasses and explicit typed fields. Use
   `Annotated[..., Field(...)]` for new modeled fields and
   `Field(default_factory=...)` for mutable defaults.
8. Use `Ok` / `Err` at recoverable boundaries. Branch on results explicitly; do
   not unwrap live results, catch `Exception` broadly, or hide failures behind
   `None`.
9. Prefer domain models, protocols, named structured returns, and keyword-only
   configuration over loose dictionaries, `object`, casual casts, and long
   positional tuples.
10. Use the repository logging policy. Loguru is disabled by default; every
    application built on r2x-core should disable its own package namespace at
    import time and enable it explicitly at the application boundary. Use
    `setup_logging(...)` only there, select levels by operational meaning, and
    keep diagnostics structured and non-sensitive.
11. Test public behavior. Add a regression test for a bug, reuse repository
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

1. **Classify the surface:** plugin, rules, data, units, persistence, or
   upgrades. Keep pure infrasys work separate.
2. **Inspect first:** read repository instructions, `pyproject.toml`, defining
   source modules, adjacent tests, and relevant docs. Reproduce failures when
   practical.
3. **Confirm the contract:** inspect root exports and exact signatures. If the
   installed package differs from the checkout, state which one is targeted.
4. **Implement a small vertical slice:** keep configuration, domain models,
   translator logic, and boundary serialization separate. Reuse existing APIs.
5. **Validate narrowly, then expand:** run focused tests first, then the
   repository's `just` target or required `prek`/pytest checks. Round-trip real
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

The API probe checks symbol presence, not semantics. The plugin probe checks
installed entry points and import failures. The datastore probe classifies files;
it cannot prove reader options or schema correctness.

## Handoff

- **Surface:** plugin, rules, data, units, persistence, upgrades, transform,
  or logging.
- **Contract:** public symbols and return/error behavior involved.
- **Changes:** files and observable behavior.
- **Validation:** exact commands and results.
- **Risks:** source/docs mismatches, untested integrations, or follow-up work.
