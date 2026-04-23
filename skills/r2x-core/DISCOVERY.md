# r2x-core Reference Discovery Protocol

This guide defines how the `r2x-core` skill should locate authoritative
references quickly and deterministically.

## Goal

When a task references unfamiliar APIs or behavior, follow a fixed discovery
sequence instead of ad-hoc searching.

## Recommended read order

1. `SKILL.md`
2. `REFERENCE.md`
3. `PLUGINS.md` (if plugin lifecycle, registration, exposure, or context is involved)
4. `RULES.md` (if `Rule`, `RuleFilter`, or rule executor is involved)
5. `DATA_STORE.md` (if `DataStore`, `DataFile`, readers, or processors are involved)
6. `UNITS.md` (if `HasUnits`, `HasPerUnit`, or unit-system selection is involved)
7. `VERSIONING_UPGRADES.md` (if `UpgradeStep`, `VersionStrategy`, or
   `VersionReader` is involved)
8. `EXAMPLES.md` (trigger and near-miss sanity checks)
9. Tools (`tools/*.py`, `tools/*.sh`) for validation and reproducibility

## Canonical external sources

Prefer these in order:

1. Installed package metadata
   - `r2x-core` on PyPI: <https://pypi.org/project/r2x-core/>
2. Project documentation site
   - <https://nrel.github.io/r2x-core/>
3. Source repository
   - <https://github.com/NREL/r2x-core>
4. Underlying modeling layer
   - infrasys docs and source for `System` / `Component` semantics.

## Installed package source code (source of truth for APIs)

You can always inspect the source of the installed Python package. Key modules:

- `r2x_core.plugin_base` (`Plugin`)
- `r2x_core.plugin_config` (`PluginConfig`)
- `r2x_core.plugin_context` (`PluginContext`)
- `r2x_core.plugin_expose` (`expose_plugin`)
- `r2x_core.rules` (`Rule`, `RuleFilter`)
- `r2x_core.rules_executor` (`apply_rules_to_context`, `apply_single_rule`)
- `r2x_core.store` (`DataStore`)
- `r2x_core.datafile` (`DataFile`, `FileInfo`, `ReaderConfig`, `TabularProcessing`, `JSONProcessing`)
- `r2x_core.reader` (`DataReader`)
- `r2x_core.file_readers` / `r2x_core.h5_readers` / `r2x_core.file_types`
- `r2x_core.system` (`System`, the r2x-core wrapper around infrasys.System)
- `r2x_core.units` (`HasUnits`, `HasPerUnit`, `UnitSystem`, `Unit`)
- `r2x_core.versioning` (`VersionStrategy`, `SemanticVersioningStrategy`,
  `GitVersioningStrategy`, `VersionReader`)
- `r2x_core.utils` (`UpgradeStep`, `UpgradeType`, `run_upgrade_step`,
  `create_component`, `components_to_records`, `export_components_to_csv`)
- `r2x_core.result` (`RuleResult`, `TranslationResult`)
- `r2x_core.exceptions` (`PluginError`, `ValidationError`, `UpgradeError`,
  `ComponentCreationError`, `CLIError`)

Quick inspection (prints module file paths):

```bash
uvx --from python --with r2x-core python - <<'PY'
import r2x_core.plugin_base as pb
import r2x_core.rules as rules
import r2x_core.store as store
import r2x_core.units as units
import r2x_core.versioning as ver
print(pb.__file__)
print(rules.__file__)
print(store.__file__)
print(units.__file__)
print(ver.__file__)
PY
```

If docs and source disagree, trust source signatures and behavior, then note
the mismatch in your output.

## Discovery workflow

1. Extract task keywords and symbol candidates.
   - Examples: `Plugin`, `expose_plugin`, `PluginContext`, `Rule`,
     `RuleFilter`, `DataStore`, `DataFile`, `ReaderConfig`, `H5Format`,
     `UpgradeStep`, `VersionStrategy`, `HasPerUnit`.
2. Open the matching skill doc in the order above.
3. Confirm symbol behavior with installed source (signatures, default args,
   return types).
4. Cross-check against `docs/source/how-tos/*.md` and
   `docs/source/explanations/*.md` for intent and worked examples.
5. Record provenance in your output (which file or module was decisive).

## Practical search strategy

- Prefer narrow, literal symbol searches before broad fuzzy search.
- Search for definitions (`def <name>`, `class <name>`) when API exactness
  matters.
- Use docs for intent and examples, source for final truth.
- Run `tools/check_api_symbols.py` after upstream upgrades to catch API drift
  in the public surface.
- Run `tools/inspect_plugins.py` to enumerate everything that registers under
  the `r2x_plugin` entry point group in the current environment.
- Run `tools/check_data_store.py` to validate a `DataStore` configuration
  before debugging reader-level issues.

## Escalation rules

Stay inside this skill and pick the right integrated reference by task
center-of-gravity:

- `PLUGINS.md` for plugin lifecycle, hook capabilities, exposure, and context
  wiring.
- `RULES.md` for rule mapping, filtering, ordering, and execution semantics.
- `DATA_STORE.md` for file-format selection, reader configuration, caching,
  and component tracking.
- `UNITS.md` for unit-system display modes and per-unit conversion semantics.
- `VERSIONING_UPGRADES.md` for upgrade chains, schema versioning, and
  on-disk version detection.

If the task is fundamentally about `System` / `Component` semantics with no
r2x-core surface area, escalate out of this skill to the `infrasys` skill.

## Output checklist (for the skill)

- APIs confirmed (exact symbol names and modules).
- Docs and source consulted (paths).
- Any docs vs source mismatches found.
- Chosen boundary between integrated references inside this skill.
