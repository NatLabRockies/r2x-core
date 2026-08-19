# r2x-core cross-cutting reference

Use this reference when a task spans multiple r2x-core surfaces or when a
public contract, result boundary, or persistence decision is unclear. Start
with [QUICKREF.md](./QUICKREF.md) for exact calls, then load the focused file.

## Mental model

r2x-core is the translator framework around infrasys:

```text
DataFile definitions -> DataStore/DataReader -> PluginContext
                                      -> Plugin hooks
                                      -> Rule executor
                                      -> target System -> export/persistence
```

It owns plugin lifecycle, rule execution, file ingestion, units, and upgrades.
It does not own domain `System` / `Component` definitions.

For execution through the Rust `r2x` CLI, read [R2X_CLI.md](./R2X_CLI.md).

## Public root surface

Use root imports when exported by `src/r2x_core/__init__.py`:

```python
from r2x_core import (
    CLIError, ComponentCreationError, DataFile, DataReader, DataStore, Err,
    FileInfo, FileFormat, GitVersioningStrategy, H5Format, HasPerUnit,
    HasUnits, JSONProcessing, Ok, Plugin, PluginConfig, PluginContext,
    PluginError, ReaderConfig, Result, Rule, RuleFilter, RuleResult,
    SemanticVersioningStrategy, System, TabularProcessing, TranslationResult,
    Unit, UnitSystem, UpgradeError, UpgradeStep, UpgradeType, ValidationError,
    VersionReader, VersionStrategy, apply_rules_to_context, apply_single_rule,
    components_to_records, create_component, export_components_to_csv,
    expose_plugin, get_unit_system, getter, h5_readers, is_err, is_ok,
    run_upgrade_step, set_unit_system,
)
```

If the symbol is not in `__all__`, treat it as private unless you are extending
r2x-core itself. Do not create local fallback imports to hide API drift.

## Contract matrix

| Surface | Public boundary | Success/failure |
| --- | --- | --- |
| Plugin lifecycle | `Plugin.from_context(ctx).run()` | `PluginContext`; hook `Err` raises `PluginError` |
| Function transform | `@expose_plugin` + explicit call | usually `Result[System, E]` |
| All rules | `apply_rules_to_context(context)` | `TranslationResult` with `RuleResult` records |
| One rule | `apply_single_rule(rule, *, context=...)` | `Result[RuleApplicationStats, ValueError]` |
| File read | `DataReader.read_data_file(...)` | format-specific payload or exception |
| Store read | `DataStore.read_data(name, ...)` | format-specific payload or exception |
| Unit setting | `set_unit_system(...)` | process-global display state |
| Logging | Loguru + `setup_logging(...)` | disabled by default; application-owned sinks |
| One upgrade | `run_upgrade_step(data, *, step=...)` | `Result[Any, str]` |
| Component creation | `create_component(component_class, *, skip_none=True, skip_validation=False, **field_values)` | `Result[Component, pydantic.ValidationError]` |

## Result and exception boundaries

Use the project's established boundary, not a universal rule:

- Hook and upgrade functions return `Ok`/`Err` when the framework contract says
  `Result`.
- `Plugin.run()` deliberately raises `PluginError` after a hook returns `Err`.
  Catch that only at an outer orchestration boundary.
- `apply_rules_to_context` returns a rich result and records individual rule
  failures; inspect `translation.rule_results`.
- `DataFile`/`DataStore` validation and file reads use Pydantic and ordinary
  exceptions such as `ValidationError`, `FileNotFoundError`, `KeyError`, or
  `ReaderError` according to the source path.
- `create_component` returns `Err(PydanticValidationError)` rather than raising
  a validation error for normal invalid input.

Do not bare-unwrap result values in production code. Do not catch broad
`Exception` to continue a translation, hide an API mismatch, or return `None`.
Catch narrow exceptions at the boundary that can add useful context.

## Logging policy

Use [LOGGING.md](./LOGGING.md) for the complete level and sink policy. The
short version is:

- Use Loguru, not `print`, for library diagnostics.
- `r2x_core` logging is disabled by default. Every application built on top of
  it should also call `logger.disable("my_application")` in its package
  initializer, then call `logger.enable("my_application")` at its application
  entry point. Enable r2x-core and configure sinks with `setup_logging(...)` at
  the application boundary, never during import.
- Use `TRACE` for high-volume internals, `DEBUG` for developer diagnostics,
  `INFO` for meaningful lifecycle milestones, `WARNING` for recoverable degraded
  behavior, `ERROR` for a failed operation, and `CRITICAL` only at an outer
  boundary that can act on an unrecoverable condition.
- Keep logs structured with `get_logger(...).bind(...)` or bound extras. Do not
  log secrets, complete payloads, or high-volume records.
- TTY output is human-oriented; non-TTY stderr is JSON Lines and file sinks
  capture `TRACE` and above. Do not parse TTY text in automation.

## Typed Python patterns

Follow the repository's Python standards around r2x-core APIs:

```python
from pathlib import Path
from typing import Annotated
from pydantic import Field


def resolve_input(
    path: Path,
    *,
    base_folder: Path,
    must_exist: bool = True,
) -> Path:
    ...


class InputConfig(PluginConfig):
    folder: Annotated[Path, Field(description="Input folder")]
    year: Annotated[int, Field(ge=2020, description="Planning year")]
```

Prefer canonical r2x-core, infrasys, or component models over duplicate local
schemas. Use `Annotated`, constrained fields, Pydantic v2 validators, named
structured returns, and protocols. Keep CLI parsing at the process boundary.

## Public API workflow

1. Identify the canonical owner of the model/data/system concept.
2. Read root exports and the defining module.
3. Read nearby tests for exact arguments, result access, and failure behavior.
4. Use the focused skill reference for workflow and known traps.
5. Implement the smallest public behavior change.
6. Add a test through the public interface and run it.
7. Round-trip persistence or real file readers when the boundary changed.

## Persistence

`r2x_core.System` extends infrasys `System` with R2X-specific base power and
provenance behavior. Use:

```python
system.to_json("system.json", overwrite=True)
loaded = System.from_json("system.json")
```

When a model or serialized field changes, assert the loaded system's public
fields, component counts, associations, units, and time-series metadata as
applicable. Route foundational serialized schema migrations through infrasys
upgrade hooks. Use r2x-core `UpgradeStep` for r2x-core files, mappings, and
intermediate artifacts.

## Public API anti-patterns

- Treating a context return as a `Result`.
- Passing rules/components as positional extras to rule executors.
- Replacing `RuleFilter` records with a callable constructor.
- Using stale `DataFile` names (`reader_config`, `processing`, `file_info`).
- Treating file format markers as enums or configuration objects.
- Constructing `VersionReader(strategy=...)`.
- Adding `versioning_strategy` to `UpgradeStep`.
- Import fallbacks that mask a source/docs mismatch.
- Raw file I/O in plugin code when a `DataStore` boundary applies.
- Handwritten component construction where `create_component` is the contract.
- Calling `setup_logging()` from a library module or import side effect.
- Using `INFO` for per-row/per-component diagnostics or `ERROR` for an expected
  branch.

## Handoff checklist

- Surface and canonical owner identified.
- Root symbols and exact signatures verified.
- Public call pattern shown or corrected.
- Result/error contract described.
- Public behavior test added or run.
- Persistence/file/unit boundary checked when relevant.
- Source/docs mismatch called out explicitly.
