# r2x-core Reference

## When to use

Use this skill for concrete r2x-core operations that touch its public
surface: declaring plugins, wiring `PluginContext`, defining rules and
filters, configuring a `DataStore`, applying per-unit semantics, or running
upgrade steps. r2x-core is a translation framework built on top of infrasys;
keep infrasys-internal modeling questions in the `infrasys` skill.

## Avoid when

- Task is purely an infrasys `System` / `Component` modeling question.
- Task is generic Python or unrelated tooling.

## Additional reference documents

- [PLUGINS.md](./PLUGINS.md), plugin lifecycle, hook capabilities, exposure,
  registration, and `PluginContext`.
- [RULES.md](./RULES.md), `Rule`, `RuleFilter`, and rule executor semantics.
- [DATA_STORE.md](./DATA_STORE.md), `DataStore`, `DataFile`, `ReaderConfig`,
  HDF5 readers.
- [UNITS.md](./UNITS.md), per-unit system and display modes.
- [VERSIONING_UPGRADES.md](./VERSIONING_UPGRADES.md), upgrade steps and
  version strategies.
- [DISCOVERY.md](./DISCOVERY.md), how to find authoritative sources.
- [EXAMPLES.md](./EXAMPLES.md), should-trigger and near-miss prompts.
- [tools/check_api_symbols.py](./tools/check_api_symbols.py), public symbol
  drift checker.
- [tools/inspect_plugins.py](./tools/inspect_plugins.py), entry-point plugin
  enumeration.
- [tools/check_data_store.py](./tools/check_data_store.py), DataStore layout
  validator.

## Mental model

- r2x-core is the **translator framework**: it owns plugin lifecycle, rule
  execution, file ingestion, units, and versioning. It does **not** own the
  domain `System` / `Component` schema, that is infrasys.
- Translation flows in stages: **prepare** (load inputs) -> **build** (create
  the `System`) -> **transform / translate** (apply `Rule`s) -> **export**
  (emit artifacts) -> **cleanup**.
- All lifecycle hooks return `Result[T, E]` from `rust_ok`. Never raise for
  control flow.
- Configuration is **typed**, always a `PluginConfig` subclass (Pydantic v2)
  rather than loose `dict[str, Any]`.

## Public API surface (high-signal entry points)

```python
from r2x_core import (
    # Plugin system
    Plugin, PluginConfig, PluginContext, PluginError, expose_plugin,
    # Rules
    Rule, RuleFilter, RuleResult, TranslationResult,
    apply_rules_to_context, apply_single_rule,
    # Data
    DataStore, DataFile, DataReader, FileInfo,
    ReaderConfig, TabularProcessing, JSONProcessing,
    FileFormat, H5Format,
    # System (r2x-core wrapper around infrasys.System)
    System,
    # Units
    HasUnits, HasPerUnit, Unit, UnitSystem,
    get_unit_system, set_unit_system,
    # Versioning and upgrades
    VersionStrategy, SemanticVersioningStrategy, GitVersioningStrategy,
    VersionReader,
    UpgradeStep, UpgradeType, run_upgrade_step,
    # Result helpers
    Ok, Err, Result, is_ok, is_err,
    # Utilities
    create_component, components_to_records, export_components_to_csv,
    getter, h5_readers,
    # Errors
    CLIError, ComponentCreationError, ValidationError, UpgradeError,
)
```

The full `__all__` lives in `src/r2x_core/__init__.py`. If a symbol you need
is not re-exported there, treat it as private and avoid importing from a
submodule unless you are extending the framework itself.

## Core call patterns

### 1. Define a typed config and a plugin

```python
from r2x_core import Plugin, PluginConfig, Ok, Err

class ReEDSConfig(PluginConfig):
    input_folder: str
    model_year: int
    scenario: str = "base"

class ReEDSTranslator(Plugin[ReEDSConfig]):
    def on_prepare(self):
        # load inputs into self.context as needed
        return Ok(None)

    def on_build(self):
        from r2x_core import System
        system = System(name=f"{self.config.scenario}_{self.config.model_year}")
        return Ok(system)
```

### 2. Wire context and run

```python
from r2x_core import PluginContext

config = ReEDSConfig(input_folder="/data/reeds", model_year=2030)
context = PluginContext(config=config)
plugin = ReEDSTranslator.from_context(context)
result = plugin.run()
```

`plugin.run()` returns a `Result`. Check it with `is_ok` / `is_err` rather
than truthiness.

### 3. Expose for entry-point discovery

```python
from r2x_core import expose_plugin

@expose_plugin
class ReEDSTranslator(Plugin[ReEDSConfig]):
    ...
```

Plus in `pyproject.toml`:

```toml
[project.entry-points.r2x_plugin]
reeds_translator = "my_pkg.plugins:ReEDSTranslator"
```

Per repo convention: use `PluginConfig` and `@expose_plugin` directly. Do
**not** add compatibility `try/except` fallbacks around the import.

### 4. Configure a `DataStore`

```python
from r2x_core import DataStore, DataFile, ReaderConfig, TabularProcessing

store = DataStore(path="/data/reeds")
store.add_data(
    DataFile(name="generators", fpath="gen.csv"),
    DataFile(name="loads", fpath="load.parquet"),
)
df = store.read_data("generators")
```

For HDF5 layouts, configure via `H5Format` and the H5 readers; see
[DATA_STORE.md](./DATA_STORE.md).

### 5. Declare and run rules

```python
from r2x_core import Rule, apply_rules_to_context

rules = [
    Rule(
        name="translate_generators",
        source_type="SourceGenerator",
        target_type="Generator",
        version=1,
        field_map={"name": "name", "capacity": "p_max_mw"},
    ),
]
result = apply_rules_to_context(context, rules)
```

For a single rule pass, use `apply_single_rule(context, rule)`.

## API contracts (high-signal behavior)

- `Plugin.run()` orchestrates implemented hooks in order; missing hooks are
  skipped. The first `Err` short-circuits the chain.
- `Plugin.get_implemented_hooks()` returns the list of hook names actually
  overridden on the subclass; use it for capability reporting.
- `Plugin.get_config_type()` returns the resolved `PluginConfig` subclass.
- `PluginContext` carries the config and the in-progress `System`. Use it as
  the single shared-state object passed between hooks and rule executors.
- `apply_rules_to_context(context, rules)` returns a `TranslationResult`
  aggregating per-rule `RuleResult` records.
- `RuleFilter` composes with `&`, `|`, `~` to build composite predicates over
  source records.
- `DataStore.read_data(name)` returns the materialized payload using the
  reader chosen for the registered `DataFile`.
- `DataStore.list_data()` returns the names of registered files; use this
  for inventory.
- HDF5 access goes through `r2x_core.h5_readers`; use `H5Format` to declare
  layout intent rather than reading raw datasets in plugin code.
- `set_unit_system(UnitSystem.X)` is process-wide. Plugins should set it at
  the boundary they own and not toggle it mid-translation.
- `run_upgrade_step(step, payload)` applies a single `UpgradeStep` and
  returns a `Result`; chain steps deterministically using a
  `VersionStrategy`.

## Failure playbook

- `PluginError` raised on registration:
  - Confirm `@expose_plugin` decoration and entry-point string in
    `pyproject.toml`.
  - Run `tools/inspect_plugins.py` to confirm visibility in the active env.
- `ValidationError` from `PluginConfig`:
  - Inspect the Pydantic error tree; do not catch and reformat. Fix the
    config schema or input.
- Hook returns `Err` and translation halts:
  - Surface the contained error type; do not unwrap blindly. Use
    `is_err(result)` and pattern-match.
- Rule silently skips components:
  - Inspect `RuleFilter` composition (precedence) and rule `version`.
  - Confirm `source_type` actually exists in the source records.
- DataStore raises on `read_data`:
  - Verify `DataFile.fpath` resolves under `DataStore.path`.
  - Confirm the file extension maps to a known `FileFormat`; otherwise
    declare `ReaderConfig` explicitly.
  - Run `tools/check_data_store.py` to enumerate registered files and
    formats.
- Unit conversions disagree across plugins:
  - Confirm `set_unit_system(...)` is called once at process boundary, not
    per-plugin.
  - Confirm components mix in `HasPerUnit` consistently.
- Upgrade chain fails mid-step:
  - Verify `VersionReader` reports the expected source version.
  - Confirm each `UpgradeStep` is idempotent and gated on `from_version`.

## Serialization and deserialization

The translated `System` is an infrasys `System`. Persist with infrasys APIs:

```python
system.to_json("system.json")
loaded = System.from_json("system.json")
```

For deeper serialization and migration semantics (composed references,
`__metadata__`, time series storage backends), see the `infrasys` skill's
`SERIALIZATION_MIGRATION.md`.

## Output expectations

- Which surface was touched: plugin / rule / store / units / versioning.
- Specific APIs invoked for inspection or validation.
- Result-type usage (`Ok` / `Err`) and how errors propagate through
  `Plugin.run()`.
- Persistence and round-trip checks performed.
- Which integrated references inside this skill were used and why.
