# r2x-core public API quick reference

Start here for every r2x-core implementation or review. These call shapes are
verified against this checkout's `src/r2x_core/__init__.py`, source modules, and
tests. If the installed package is the target, inspect its source separately.

## Core calls

```python
# plugin
ctx = PluginContext(config=my_config)
plugin = MyPlugin.from_context(ctx)
ctx = plugin.run()  # returns PluginContext, raises PluginError on hook Err

# rules
ctx = ctx.evolve(
    source_system=source_system,
    target_system=target_system,
    rules=tuple(rules),
)
translation = apply_rules_to_context(ctx)
single = apply_single_rule(rule, context=ctx)

# datastore
store = DataStore(path="/data")
store.add_data([DataFile(name="loads", relative_fpath="load.csv")])
loads = store.read_data("loads")

# logging, disabled in the package and enabled at the application boundary
from loguru import logger
from r2x_core.logger import get_logger, setup_logging
logger.disable("my_translator")  # in my_translator/__init__.py
logger.enable("my_translator")  # in the app entry point
setup_logging(verbosity=1)  # DEBUG+ console, also enables r2x_core
logger = get_logger("translator.parser")  # metadata label, not namespace
logger.info("Translation started")

# upgrades
result = run_upgrade_step(payload, step=step)

# units
set_unit_system(UnitSystem.SYSTEM_BASE)
mode = get_unit_system()
```

## Contract checklist

- `Plugin.run(*, ctx=None) -> PluginContext`, not `Result`
- `apply_rules_to_context(context)`, rules come from `context.rules`
- Rule execution reads `context.source_system` and writes `context.target_system`
- `apply_single_rule(rule, *, context=...)`
- `DataFile` path source is exactly one of `fpath`, `relative_fpath`, `glob`
- `DataFile` options are `info`, `reader`, and `proc_spec`
- `DataStore.add_data(...)` expects a sequence of `DataFile`
- `VersionReader` is a protocol with `read_version(...)`
- `UpgradeStep` uses `target_version`, optional `min_version` / `max_version`
- `run_upgrade_step(data, *, step=...)`
- Loguru is disabled by default for r2x-core and each consuming application
- Disable your application namespace in its package initializer, then enable it
  and call `setup_logging(...)` from the application entry point
- `TRACE` internals, `DEBUG` decisions, `INFO` milestones, `WARNING` degradation,
  `ERROR` failed operations, `CRITICAL` outer unrecoverable failures

## Wrong versus correct

| Wrong                                                        | Correct                                                             |
| ------------------------------------------------------------ | ------------------------------------------------------------------- |
| `RuleFilter(lambda x: ...)`                                  | `RuleFilter(field="status", op="eq", values=["active"])`            |
| `apply_rules_to_context(context, rules)`                     | `ctx = ctx.evolve(rules=tuple(rules)); apply_rules_to_context(ctx)` |
| `apply_single_rule(context, rule)`                           | `apply_single_rule(rule, context=context)`                          |
| `is_err(plugin.run())`                                       | `try: ctx = plugin.run(); except PluginError: ...`                  |
| `DataFile(reader_config=..., processing=..., file_info=...)` | `DataFile(reader=..., proc_spec=..., info=...)`                     |
| `VersionReader(strategy=...)`                                | Implement `read_version(folder_path)`                               |
| `UpgradeStep(from_version=..., to_version=...)`              | `UpgradeStep(target_version=..., min_version=..., max_version=...)` |
| `run_upgrade_step(step, payload)`                            | `run_upgrade_step(payload, step=step)`                              |

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

## Minimal rule context

```python
from r2x_core import PluginConfig, PluginContext, Rule, System, apply_rules_to_context

rule = Rule(
    name="bus_to_node",
    source_type="BusComponent",
    target_type="NodeComponent",
    version=1,
    field_map={"name": "name", "kv_rating": "voltage_kv"},
)
context = PluginContext(
    config=PluginConfig(models=("source_models", "target_models")),
    source_system=source_system,
    target_system=System(name="target"),
    rules=(rule,),
)
translation = apply_rules_to_context(context)
```

## Focused references

- Plugins: `PLUGINS.md`
- Rules: `RULES.md`
- Data: `DATA_STORE.md`
- Units: `UNITS.md`
- Upgrades: `VERSIONING_UPGRADES.md`
- Utilities: `UTILITIES.md`
- Discovery: `DISCOVERY.md`
- Cross-cutting contracts: `REFERENCE.md`
