# r2x-core cross-cutting reference

Use this when a task spans multiple r2x-core surfaces or when a public contract,
result boundary, or persistence decision is unclear. Start with
[QUICKREF.md](./QUICKREF.md), then load the focused reference.

## Contents

- [Mental model](#mental-model)
- [Public root surface](#public-root-surface)
- [Contract matrix](#contract-matrix)
- [Result and exception boundaries](#result-and-exception-boundaries)
- [Logging policy](#logging-policy)
- [Persistence](#persistence)
- [Public API workflow](#public-api-workflow)

## Mental model

r2x-core has two related workflows around infrasys:

```text
DataFile -> DataReader -> optional table mapping -> parser instructions -> System
source System -> PluginContext -> Rule executor -> target System
```

It owns plugin lifecycle, rule execution, file ingestion, optional table
assembly, units, and upgrades. It does not own domain `System` / `Component`
definitions.

For system construction, read [INGESTION.md](./INGESTION.md). For named table
assembly, read [TABLE_MAPPING.md](./TABLE_MAPPING.md). For execution through the
Rust `r2x` CLI, read [R2X_CLI.md](./R2X_CLI.md).

## Public root surface

Import root-exported symbols from `r2x_core`. Representative APIs for the main
surfaces are:

```python
from r2x_core import (
    AllOfFilter, AnyOfFilter, ArraySource, ComponentInstruction,
    ComponentReference, DataFile, DataReader, DataStore, DecodedSource,
    DecodedSources, DocumentSource, Err, FieldFilter, FileInfo, FileProcessing,
    FileReader, FileRequirement, FileType, GetterFilter, H5PyFileReader,
    H5Reader, HasPerUnit, HasUnits, InlineTable, InputColumn, JSONProcessing,
    Ok, Plugin, PluginConfig, PluginContext, PluginError, ReaderConfig,
    RegularTimeAxis, Rule, RuleFilter, RuleResult, SourceAvailability,
    SourcePredicate, SourceSelection, SupplementalAttributeInstruction,
    System, TableMappingBackend, TableMappingRecord, TableOperation,
    TabularProcessing, TabularSource, TimeSeriesInstruction, TranslationResult,
    Unit, UnitSystem, UpgradeError, UpgradeStep, UpgradeType, VersionReader,
    VersionStrategy, apply_rules_to_context, apply_single_rule,
    assemble_table_records, assemble_tables, build_system,
    build_system_from_sources, components_to_records,
    export_components_to_csv, expose_plugin, get_unit_system, getter,
    is_err, is_ok, run_upgrade_step, set_unit_system,
    transfer_time_series_metadata,
)
```

Check `src/r2x_core/__init__.py` before relying on additional root imports.
Some implementation type aliases, including `ParserInstruction`, are not
re-exported. Prefer the concrete root-exported instruction models unless a
source-level annotation is specifically needed.

## Contract matrix

| Surface | Public boundary | Success/failure |
| --- | --- | --- |
| Plugin lifecycle | `Plugin.from_context(ctx).run()` | `PluginContext`; hook `Err` raises `PluginError` |
| Function transform | `@expose_plugin` + explicit call | Usually `Result[System, E]` |
| All rules | `apply_rules_to_context(context)` | `TranslationResult` with per-rule results |
| One rule | `apply_single_rule(rule, *, context=...)` | `Result[RuleApplicationStats, ValueError]` |
| File read | `DataReader.read_data_files(...)` | Named `DecodedSource` mapping or exception |
| DataStore | `DataStore` mapping methods | File-mapping configuration; it does not read files |
| Parser build | `build_system(...)` | Configured input-to-`System` construction |
| Prepared parser build | `build_system_from_sources(...)` | `System` from decoded sources and instructions |
| Table assembly | `assemble_tables(...)` / `assemble_table_records(...)` | Named `TabularSource` outputs |
| Cross-boundary read | `DataReader.read_and_assemble_sources(...)` | Decoded files plus scheduled tables |
| Unit setting | `set_unit_system(...)` | Process-global display state |
| Logging | Loguru + `setup_logging(...)` | Disabled by default; application-owned sinks |
| One upgrade | `run_upgrade_step(data, *, step=...)` | `Result[Any, UpgradeError]` |

## Result and exception boundaries

Use the boundary defined by the public operation, not a universal rule:

- Lifecycle hooks and function transforms return `Ok` / `Err` when their
  contract says `Result`. `Plugin.run()` deliberately raises `PluginError`
  after a hook returns `Err`. Catch it at an outer orchestration boundary.
- `apply_rules_to_context` returns a rich result and records individual rule
  failures; inspect `translation.rule_results` and aggregate counts.
- `apply_single_rule` returns `Result[RuleApplicationStats, ValueError]`.
- `DataFile` and `DataStore` validation use Pydantic and ordinary exceptions.
  `DataReader` returns typed sources and may raise path, validation, or
  `ReaderError` failures. Processing failures are chained as the cause of
  `ReaderError`.
- `build_system` and `build_system_from_sources` return a `System` or raise
  validation, source, or construction errors. They do not return `Result`.
- Table-mapping records are strict. Unknown names, invalid operations,
  undeclared dependencies, and invalid projections fail rather than falling
  back to guesses.
- Upgrade steps return `Result[Any, UpgradeError]`. A configured upgrade
  handler returns `None` or `Ok(None)` on success and `Err(error)` on failure.

Do not unwrap live results in production code. Do not catch broad `Exception`
to continue a translation, hide an API mismatch, or return `None`. Catch narrow
exceptions only at a boundary that can add useful context.

## Logging policy

Use [LOGGING.md](./LOGGING.md) for the full level and sink policy. In short:

- Use Loguru, not `print`, for library diagnostics.
- `r2x_core` logging is disabled by default. Applications should disable their
  own namespace in the package initializer and enable it at the application
  boundary. Configure sinks with `setup_logging(...)` there, never during
  import.
- Use `TRACE` for high-volume internals, `DEBUG` for decisions, `INFO` for
  lifecycle milestones, `WARNING` for recoverable degradation, `ERROR` for a
  failed operation, and `CRITICAL` only at an outer boundary that can act on an
  unrecoverable condition.
- Keep logs structured and non-sensitive. Do not log secrets, full systems,
  DataFrames, or unbounded records.
- TTY output is human-oriented; non-TTY stderr is JSON Lines. Do not parse TTY
  text in automation.

## Persistence

`r2x_core.System` extends infrasys `System` with R2X-specific behavior. Use the
public serialization methods:

```python
system.to_json("system.json", overwrite=True)
loaded = System.from_json("system.json")
```

When a serialized field changes, test public fields, component counts,
associations, units, and time-series metadata after reload. Route foundational
serialized `System` schema migrations through infrasys upgrade hooks. Use
r2x-core `UpgradeStep` for file mappings, plugin configs, and intermediate
artifacts.

## Public API workflow

1. Identify which package owns each model, data, or system concept.
2. Read root exports, defining source, and adjacent tests for exact signatures
   and failure behavior.
3. Use the focused skill reference for workflow and known traps.
4. Keep `DataFile.proc_spec` and table-mapping schemas separate.
5. Implement the smallest public behavior change and test it through the public
   interface.
6. Round-trip persistence or real file readers when that boundary changes.
7. Report source/docs mismatches explicitly.

## Public API anti-patterns

- Treating a context return as a `Result`.
- Passing rules/components as positional extras to rule executors.
- Instantiating the `RuleFilter` union instead of a concrete filter model.
- Calling `DataStore.read_data(...)` or `DataReader.read_data_file(...)`.
- Using `ReaderConfig(kwargs=...)`; the field is `options`.
- Mixing table-mapping `operations` with `DataFile.proc_spec.steps`.
- Treating reader format names as enums or configuration objects.
- Constructing `VersionReader(strategy=...)` or adding
  `versioning_strategy` to `UpgradeStep`.
- Adding import fallbacks that mask a source/docs mismatch.
- Calling `setup_logging()` from a library module or import side effect.
- Using `INFO` for per-row/per-component diagnostics or `ERROR` for an expected
  branch.

## Handoff checklist

- API surface and model owner identified.
- Root symbols and exact signatures verified.
- Public call pattern shown or corrected.
- Result/error contract described.
- Public behavior test added or run.
- Persistence, file, table, or unit boundary checked when relevant.
- Source/docs mismatch called out explicitly.
