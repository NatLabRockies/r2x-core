# r2x-core API Discovery

Use this when exact API behavior matters, the task touches an unfamiliar symbol,
or docs and runtime behavior disagree.

## Source order

1. Target package source, for signatures and behavior.
2. Nearby tests, for public examples and failure cases.
3. Local skill references, for workflow and known traps.
4. Project docs, for worked usage and schema details.
5. infrasys docs/source for pure `System` / `Component` semantics.

State whether the target is this checkout or an installed release. Do not use
published docs to override a different checkout without checking its source.

## Key modules

- `r2x_core.plugin_base`: `Plugin` and lifecycle behavior.
- `r2x_core.plugin_config`: `PluginConfig` and config-asset paths.
- `r2x_core.plugin_context`: `PluginContext` state.
- `r2x_core.plugin_expose`: `expose_plugin` marker.
- `r2x_core.rules`: `Rule` and concrete filter models.
- `r2x_core.rules_executor`: `apply_rules_to_context`, `apply_single_rule`.
- `r2x_core.datafile`, `r2x_core.types`, `r2x_core.models`: file and processing
  configuration, source selection, inline tables, and parser instructions.
- `r2x_core.store`: file-mapping configuration; it does not read input data.
- `r2x_core.file_reader` and `r2x_core.reader`: typed source and reader
  contracts, source loading, and dependency validation.
- `r2x_core.ingestion`: `build_system` and `build_system_from_sources`.
- `r2x_core.table_mapping` and `r2x_core.tabular_backend`: named-table schema,
  assembly, and backend contracts.
- `r2x_core.h5py_adapter`, `r2x_core.polars_adapter`, `r2x_core.json_adapter`,
  and `r2x_core.xml_adapter`: format-specific readers and processing.
- `r2x_core.units`: `HasUnits`, `HasPerUnit`, `UnitSystem`, and `Unit`.
- `r2x_core.versioning`: version strategies, `VersionReader`, and
  `UpgradeHandler`.
- `r2x_core.utils.upgrade`: `UpgradeStep`, `UpgradeType`, and upgrade runner.
- `r2x_core.result`, `r2x_core.exceptions`, and `r2x_core.logger`: result,
  error, and logging contracts.

See `src/r2x_core/__init__.py` for the root-exported API. Not every source-level
type alias is re-exported; do not claim a root import unless it appears in
`__all__`.

## Fast verification

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
import inspect
import r2x_core
from r2x_core import DataReader, DataStore, Plugin, apply_rules_to_context

print(r2x_core.__file__)
print(inspect.signature(Plugin.run))
print(inspect.signature(DataStore.add_data))
print(inspect.signature(DataReader.read_data_files))
print(inspect.signature(apply_rules_to_context))
PY

uv run python skills/r2x-core/tools/check_api_symbols.py --repo src/r2x_core
```

The symbol probe checks presence of the skill's documented public names; it does
not validate signatures or behavior. Inspect the defining source and tests for
those. Use `uvx --with r2x-core ...` only when intentionally checking a released
package instead of this checkout.

## Workflow

1. Identify the API surface and focused reference.
2. Inspect root exports, defining source, and exact signatures/defaults.
3. Read adjacent tests for return values, error behavior, and edge cases.
4. Use project docs for intent and worked examples; report source/docs drift.
5. For logging, inspect `src/r2x_core/logger.py` and `tests/test_logger.py`.
6. For CLI integration, check the current consuming `r2x-cli` behavior. The CLI
   is a separate project and can change independently.

## Boundary rule

Keep this skill on the r2x-core translator boundary. Route pure
`System`/`Component` behavior to infrasys. If an external project-specific skill
is available, use it for that layer; otherwise verify against its docs/source.
Only install external skills or tools when the user/runtime explicitly permits
that mutation.
