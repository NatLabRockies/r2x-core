---
name: r2x-core
description: |
  Build and maintain r2x-core translators across plugin lifecycle, rule
  mapping, DataStore ingestion, units, and upgrades. Use when tasks mention
  r2x-core plugins/rules/datastore/unit-system/versioning, translator
  discovery, model conversion pipelines, schema migrations, or function
  transforms built on infrasys System/Component models.
license: BSD-3-Clause
metadata:
  author: r2x-core team
  version: "0.2.0"
  category: power-system-translation
  companion_skills:
    - name: infrasys
      source: pesap/agents
      use_when: Pure System/Component modeling, serialization, time series, supplemental attributes, or component graph behavior.
      fallback: Use infrasys docs/source.
    - name: python-developer
      source: pesap/agents
      use_when: Python typing, pytest, packaging, or implementation mechanics around r2x-core code.
      fallback: Use project Python standards and local tests.
    - name: data-model
      source: pesap/agents
      use_when: PluginConfig, Pydantic schemas, or typed configuration contracts.
      fallback: Use Pydantic v2 docs and existing config models.
---

# r2x-core

Operational skill for r2x-core, the application translation layer on top of
infrasys `System` / `Component` primitives.

## Use when

- Authoring, debugging, or extending an r2x-core `Plugin` or translator.
- Wiring `PluginConfig`, `PluginContext`, `@expose_plugin`, or entry points.
- Designing or auditing declarative `Rule` mappings, `RuleFilter`
  composition, or rule executor behavior.
- Configuring a `DataStore`, `DataFile`, readers, processors, or HDF5 input.
- Working with `Ok` / `Err` / `Result`, `RuleResult`, or `TranslationResult`.
- Handling `HasUnits`, `HasPerUnit`, `UnitSystem`, or per-unit conversions.
- Defining `UpgradeStep` chains, version readers, or dataset/schema upgrades.
- Building r2x-core function transforms over infrasys systems.

## Avoid when

- The task is only about infrasys `System` / `Component` internals with no
  r2x-core translator surface.
- The task is generic Python packaging, CLI, docs, or testing with no
  r2x-core surface area.
- The task is purely an end-user model semantics question, such as PLEXOS XML
  details, without touching the r2x-core translator boundary.

## Companion skills

Some tasks are better handled by a companion skill. Use a companion skill when
it is available; otherwise stay in this skill and verify from the companion
project's docs/source. The same companion list is also declared in frontmatter
metadata for runtimes that can inspect skill metadata.

| Task center                                                                                                            | Preferred companion | Fallback when unavailable                       |
| ---------------------------------------------------------------------------------------------------------------------- | ------------------- | ----------------------------------------------- |
| Pure `System` / `Component` modeling, serialization, time series, supplemental attributes, or component graph behavior | `infrasys`          | Use infrasys docs/source                        |
| Python typing, pytest, packaging, or implementation mechanics around r2x-core code                                     | `python-developer`  | Use project Python standards and local tests    |
| `PluginConfig`, Pydantic schemas, or typed configuration contracts                                                     | `data-model`        | Use Pydantic v2 docs and existing config models |

If the runtime supports GitHub skill installation and the user/runtime permits
installing external skills, install/select missing companion skills from the
shared skills repository:

```bash
gh skill install pesap/agents
# choose the companion skill named above
```

If both this skill and a companion apply, use this skill for the r2x-core
translator boundary and the companion skill/docs for the underlying concern.

## Read order

Start here, then load only the focused reference needed for the task:

1. Fast API map: [references/QUICKREF.md](./references/QUICKREF.md)
2. Cross-cutting contracts: [references/REFERENCE.md](./references/REFERENCE.md)
3. API/source validation protocol: [references/DISCOVERY.md](./references/DISCOVERY.md)
4. Plugin lifecycle: [references/PLUGINS.md](./references/PLUGINS.md)
5. Rules: [references/RULES.md](./references/RULES.md)
6. Data ingestion: [references/DATA_STORE.md](./references/DATA_STORE.md)
7. Units: [references/UNITS.md](./references/UNITS.md)
8. Versioning/upgrades: [references/VERSIONING_UPGRADES.md](./references/VERSIONING_UPGRADES.md)
9. Shared utilities: [references/UTILITIES.md](./references/UTILITIES.md)
10. Trigger checks: [evals/TRIGGER_PROMPTS.md](./evals/TRIGGER_PROMPTS.md)

## Authoritative contracts

- `Plugin.run(*, ctx: PluginContext | None = None) -> PluginContext` and
  raises `PluginError` on hook `Err`.
- `apply_rules_to_context(context: PluginContext) -> TranslationResult`.
- `apply_single_rule(rule: Rule, *, context: PluginContext) -> Result[RuleApplicationStats, ValueError]`.
- `DataStore.add_data(data_files: Sequence[DataFile], *, overwrite: bool = False) -> None`.
- `run_upgrade_step(data, *, step: UpgradeStep, upgrader_context=None) -> Result[Any, str]`.

## Do

- Inspect installed source when exact signatures matter, especially after
  r2x-core upgrades. Use `references/DISCOVERY.md`.
- Keep configuration typed with `PluginConfig` subclasses, not loose dicts.
- Implement only lifecycle hooks the translator actually needs.
- Return `Ok(value)` / `Err(error)` from plugin hooks and upgrade helpers.
- Put file-reading concerns at the `DataFile` / `DataStore` boundary.
- Prefer declarative `Rule` + `RuleFilter` mapping over ad-hoc translator
  branches when the mapping is data-shaped.
- Round-trip produced systems through infrasys serialization when persistence
  is part of the task.
- Report which reference docs and source modules were decisive.

## Don't

- Do not call `apply_rules_to_context(context, rules)`. Attach rules to the
  context, then call `apply_rules_to_context(context)`.
- Do not call `apply_single_rule(context, rule)`. Use
  `apply_single_rule(rule, context=context)`.
- Do not treat `plugin.run()` as a `Result`; catch `PluginError` at the
  orchestration boundary if needed.
- Do not use `RuleFilter(lambda ...)`; use declarative field/op/value filters.
- Do not pass `DataFile(reader_config=..., processing=..., file_info=...)`;
  use `reader=...`, `proc_spec=...`, and `info=...` for current APIs.
- Do not use `VersionReader(strategy=...)`; implement the protocol.
- Do not define `UpgradeStep(from_version=..., to_version=...)`; use
  `target_version` with optional `min_version` / `max_version`.
- Do not add compatibility import fallbacks around `r2x_core` APIs in repo
  code unless the user explicitly asks for multi-version support.

## Workflow

1. Classify the surface: plugin, rules, datastore, units, versioning,
   function transforms, or infrasys boundary.
2. Load the matching reference document from `references/`.
3. Verify exact APIs from installed/project source when behavior is uncertain.
4. Make the smallest change that preserves public translator contracts.
5. Validate with targeted tests, source inspection, or round-trip checks.
6. In the handoff, include touched surface, APIs validated, docs consulted,
   result/error behavior, and any public symbols changed.

## Output expectations

- Surface touched: plugin / rules / store / units / versioning / transform.
- Exact APIs inspected or called for validation.
- Reference files consulted and why.
- Result-type usage and error propagation decisions.
- Persistence, upgrade, or round-trip checks performed when relevant.
- Public symbols or entry points changed, including `__all__` when applicable.
