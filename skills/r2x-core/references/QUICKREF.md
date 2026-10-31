# r2x-core public API quick reference

Start here for every r2x-core implementation or review. These call shapes are
verified against this checkout's `src/r2x_core/__init__.py`, source modules, and
tests. If the installed package is the target, inspect its source separately.

## Core calls

```python
# plugin lifecycle
ctx = PluginContext(config=my_config)
plugin = MyPlugin.from_context(ctx)
ctx = plugin.run()  # PluginContext; a hook Err raises PluginError

# rules
ctx = ctx.evolve(
    source_system=source_system,
    target_system=target_system,
    rules=tuple(rules),
)
translation = apply_rules_to_context(ctx)
single = apply_single_rule(rule, context=ctx)

# file mapping configuration and named-source loading
from pathlib import Path
from r2x_core import DataFile, DataReader, DataStore

store = DataStore(path="/data")
store.load_file_mapping(Path("config/file_mapping.json"))
sources = DataReader().read_data_files(
    store.data_files.values(), folder_path=store.folder
)
loads = sources["loads"]  # a typed DecodedSource, not a bare frame

# configured parser construction
system = build_system(config, name="parsed", input_folder=Path("/data"))

# table assembly uses a separate mapping schema and backend
from r2x_core.polars_adapter import PolarsTabularBackend

assembled = DataReader().read_and_assemble_sources(
    store.data_files.values(),
    folder_path=store.folder,
    mapping_path=Path("config/table_mapping.json"),
    backend=PolarsTabularBackend(),
)

# logging, disabled in the package and enabled at the application boundary
from loguru import logger
from r2x_core.logger import get_logger, setup_logging

logger.disable("my_translator")  # in my_translator/__init__.py
logger.enable("my_translator")  # in the app entry point
setup_logging(verbosity=1)  # DEBUG+ console; also enables r2x_core
logger = get_logger("translator.parser")  # metadata label, not namespace
logger.info("Translation started")

# upgrades
result = run_upgrade_step(payload, step=step)

# units
set_unit_system(UnitSystem.SYSTEM_BASE)
mode = get_unit_system()
```

## Contract checklist

- `Plugin.run(*, ctx=None) -> PluginContext`, not `Result`.
- `apply_rules_to_context(context)` reads rules from `context.rules`.
- Rule execution reads `context.source_system` and writes
  `context.target_system`.
- `apply_single_rule(rule, *, context=...)` takes the rule first.
- A physical `DataFile` sets exactly one of `fpath`, `relative_fpath`, or
  `glob`. A derived `DataFile` instead sets exactly one of `source`,
  `source_selection`, or `inline_table`.
- `DataFile` fields for configuration are `info`, `reader`, and `proc_spec`.
  Native column declarations belong in `DataFile.columns`.
- `ReaderConfig` uses `format` and `options`; it does not use `kwargs` or a
  custom `function` field.
- `FileInfo.file_type` is `static` or `time_series`; `requirement` is
  `required` or `optional`.
- `DataStore` manages file-mapping configuration only. Use
  `DataReader.read_data_files(...)` to load named typed sources.
- `DataFile.proc_spec` uses ordered `steps` tagged by `op`. Table-mapping
  records use `operations` tagged by `operation`; the schemas are distinct.
- `DataStore.add_data(...)` expects a sequence of `DataFile` objects.
- `build_system(...)` reads file/parser configuration and returns a `System`;
  `build_system_from_sources(...)` uses decoded sources and typed instructions.
- `VersionReader` is a protocol with `read_version(...)`.
- `UpgradeStep` uses `target_version`, optional `min_version` / `max_version`.
- `run_upgrade_step(data, *, step=...)` returns a `Result` with
  `UpgradeError` failures.
- Loguru is disabled by default for r2x-core and each consuming application.
  Disable your application namespace in its package initializer, then enable it
  and call `setup_logging(...)` from the application entry point.
- `TRACE` internals, `DEBUG` decisions, `INFO` milestones, `WARNING`
  degradation, `ERROR` failed operations, `CRITICAL` outer unrecoverable
  failures.

## Wrong versus correct

| Wrong | Correct |
| --- | --- |
| `store.read_data("loads")` | `DataReader().read_data_files(files, folder_path=store.folder)["loads"]` |
| `DataReader().read_data_file(file, ...)` | `DataReader().read_data_files([file], folder_path=...)` |
| `ReaderConfig(kwargs={...})` | `ReaderConfig(options={...})` |
| `DataFile(reader_config=..., processing=..., file_info=...)` | `DataFile(reader=..., proc_spec=..., info=...)` |
| `apply_rules_to_context(context, rules)` | `ctx = ctx.evolve(rules=tuple(rules)); apply_rules_to_context(ctx)` |
| `apply_single_rule(context, rule)` | `apply_single_rule(rule, context=context)` |
| Instantiate the `RuleFilter` alias | Use `FieldFilter`, `GetterFilter`, `AnyOfFilter`, or `AllOfFilter` |
| `is_err(plugin.run())` | `try: ctx = plugin.run(); except PluginError: ...` |
| `VersionReader(strategy=...)` | Implement `read_version(folder_path)` |
| `UpgradeStep(from_version=..., to_version=...)` | `UpgradeStep(target_version=..., min_version=..., max_version=...)` |
| `run_upgrade_step(step, payload)` | `run_upgrade_step(payload, step=step)` |

## Minimal class plugin

```python
from r2x_core import Plugin, PluginConfig, PluginContext, System
from rust_ok import Ok, Result


class Config(PluginConfig):
    name: str = "demo"


class Build(Plugin[Config]):
    def on_build(self) -> Result[System, str]:
        return Ok(System(name=self.config.name))


context = Build.from_context(PluginContext(config=Config())).run()
assert context.system is not None
```

## Focused references

- Plugins: `PLUGINS.md`
- Rules: `RULES.md`
- Files and readers: `DATA_STORE.md`
- Parser construction: `INGESTION.md`
- Table mapping: `TABLE_MAPPING.md`
- Units: `UNITS.md`
- Upgrades: `VERSIONING_UPGRADES.md`
- Utilities: `UTILITIES.md`
- Discovery: `DISCOVERY.md`
- Cross-cutting contracts: `REFERENCE.md`
