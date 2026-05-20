# r2x-core QUICKREF

One-page fast reference for the most-used r2x-core APIs.

## Core calls

```python
# plugin
ctx = PluginContext(config=my_config)
plugin = MyPlugin.from_context(ctx)
ctx = plugin.run()  # raises PluginError on first hook Err

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

# upgrades
result = run_upgrade_step(payload, step=step)

# units
set_unit_system(UnitSystem.SYSTEM_BASE)
mode = get_unit_system()
```

## Contract checklist

- `Plugin.run(*, ctx=None) -> PluginContext` (not `Result`)
- `apply_rules_to_context(context)` only, rules come from `context.rules`
- rule execution reads `context.source_system` and writes `context.target_system`
- `apply_single_rule(rule, *, context=...)`
- `DataFile` path source is exactly one of `fpath`, `relative_fpath`, `glob`
- `DataStore.add_data(...)` expects a sequence of `DataFile`
- `VersionReader` is a protocol, implement `read_version(...)`
- `UpgradeStep` uses `target_version`, optional `min_version` / `max_version`
- `run_upgrade_step(data, *, step=...)`

## Wrong vs correct

| Wrong                                                        | Correct                                                                         |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| `RuleFilter(lambda x: ...)`                                  | `RuleFilter(field="status", op="eq", values=["active"])`                        |
| `apply_rules_to_context(context, rules)`                     | `context = context.evolve(rules=tuple(rules)); apply_rules_to_context(context)` |
| `apply_single_rule(context, rule)`                           | `apply_single_rule(rule, context=context)`                                      |
| `is_err(plugin.run())`                                       | `try: ctx = plugin.run(); except PluginError: ...`                              |
| `DataFile(reader_config=..., processing=..., file_info=...)` | `DataFile(reader=..., proc_spec=..., info=...)`                                 |
| `VersionReader(strategy=...)`                                | `class MyReader(VersionReader): ...`                                            |
| `UpgradeStep(from_version=..., to_version=...)`              | `UpgradeStep(target_version=..., min_version=..., max_version=...)`             |
| `run_upgrade_step(step, payload)`                            | `run_upgrade_step(payload, step=step)`                                          |

## Pick the right doc

- Plugin lifecycle and registration: `PLUGINS.md`
- Rules and filters: `RULES.md`
- Data loading and readers: `DATA_STORE.md`
- Units and display modes: `UNITS.md`
- Versioning and upgrades: `VERSIONING_UPGRADES.md`
- Shared utilities: `UTILITIES.md`
- Full cross-cutting guide: `REFERENCE.md`
