# r2x-core API Discovery

Use this only when exact r2x-core API behavior matters, the task touches an
unfamiliar symbol, or docs and runtime behavior disagree.

## Source order

1. Installed/project source, source of truth for signatures and behavior.
2. Local skill references in this directory for workflow intent.
3. Project docs: <https://nrel.github.io/r2x-core/>
4. Source repo: <https://github.com/NREL/r2x-core>
5. infrasys docs/source for pure `System` / `Component` semantics.

## Key modules

- `r2x_core.plugin_base`: `Plugin`
- `r2x_core.plugin_config`: `PluginConfig`
- `r2x_core.plugin_context`: `PluginContext`
- `r2x_core.plugin_expose`: `expose_plugin`
- `r2x_core.rules`: `Rule`, `RuleFilter`
- `r2x_core.rules_executor`: `apply_rules_to_context`, `apply_single_rule`
- `r2x_core.store`: `DataStore`
- `r2x_core.datafile`: `DataFile`, `ReaderConfig`, processing specs
- `r2x_core.h5_readers` / `r2x_core.file_readers`: file readers
- `r2x_core.units`: `HasUnits`, `HasPerUnit`, `UnitSystem`, `Unit`
- `r2x_core.versioning`: version strategies and `VersionReader`
- `r2x_core.utils`: `UpgradeStep`, `UpgradeType`, `run_upgrade_step`
- `r2x_core.result`: `RuleResult`, `TranslationResult`
- `r2x_core.exceptions`: framework exceptions

## Fast verification

```bash
uv run python - <<'PY'
import inspect
import r2x_core
from r2x_core import DataStore, Plugin, apply_rules_to_context
print(r2x_core.__file__)
print(inspect.signature(Plugin.run))
print(inspect.signature(DataStore.add_data))
print(inspect.signature(apply_rules_to_context))
PY
```

Use `uvx --with r2x-core ...` only when intentionally checking the released
package instead of this checkout.

## Workflow

1. Identify the symbol and matching focused reference file.
2. Inspect the installed/project source for signatures, defaults, and return
   type behavior.
3. Use docs/examples only for intent and worked usage.
4. If docs and source disagree, trust source and report the mismatch.
5. In the handoff, name the decisive module or reference consulted.

## Boundary rule

If a related skill is available, use it for its domain and keep this skill on
the r2x-core translator boundary. If it is missing, continue here and verify
against the related project's docs/source. Only install external skills with
`gh skill install <repo>` when the user/runtime explicitly permits that
mutation.
