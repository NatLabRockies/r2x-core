# Parser migration completion

Status: the scoped migration is implemented and validated. Both worktrees retain uncommitted changes.

## Implemented boundary

ReEDS declares physical inputs, constraints, ordered source admission, generator/FOM policy, resource precedence, reserve products and exclusions, profile scaling, ownership, and metadata in `config/file_mapping.json`, `config/defaults.json`, and `config/parser_rules.json`.

Core executes named dependencies with request-local materialization, calendar/configuration/System sources, relational preparation, shared component mappings, and time-series attachment through public Infrasys APIs. No ReEDS callback, source-specific core coordinator, or second execution framework was added.

Key implementation points:

- `src/r2x_core/store.py`: dependency execution, source admission, input validation, and mutation integrity.
- `src/r2x_core/sources.py`: typed calendar, configuration-record, ordered-selection, and System projection sources.
- `src/r2x_core/rules.py` and `rules_executor.py`: shared mapping references and typed time-series targets.
- `src/r2x_core/grid.py`: representative-period expansion shared directly with ReEDS sysmod consumers.
- ReEDS `parser.py`: lifecycle and configured construction boundaries. Its final generator entry point consumes named output datasets rather than individual source dictionaries.

The obsolete ReEDS `parser_utils.py`, `parser_checks.py`, `parser_types.py`, and `data_readers.py` modules are removed. Source-derived FOM placeholders, manual profile/reserve/resource pipelines, old capacity selection, and parallel reserve-default dictionaries are removed. Resource activation uses the configured execution stage. Identity, enum, reference, and geographical boundary getters remain.

PLEXOS and RESOLVE were not edited. The existing record-construction boundary remains available for non-CSV producers. No RESOLVE schema compatibility is claimed. Existing format-upgrade algorithms and unrelated sysmod modeling remain outside this migration.

## Independent validation

Validated on Linux using the existing Python 3.12 core environment and Python 3.13 ReEDS environment. No dependencies were installed and no lockfiles were changed.

- 466 affected core tests passed across datafile, prepared-table, processor, reader, store, grid, source, calendar, Rule, and context contracts.
- All 38 independently owned whole-parser ReEDS regressions passed in completed serial batches. These cover FOM precedence and unknown values, strict prior costs, controls and conditional water sources, storage/fuel/heat-rate policy, resource precedence, complete/incomplete hydro, primary weather-year selection, profile arrays and metadata, reserve membership, short/missing contributors, and cost-source admission.
- Scoped Ruff lint and format checks passed for all changed and new Python files in both worktrees.
- Both source ty checks and both `git diff --check` checks passed.

The coding agent also reports completed batches of 40 ReEDS builder/basic/sysmod cases, 26 FOM lifecycle/resource/config cases, and an earlier 118-case lifecycle/edge batch with one expected xfail. These overlap the independent selection and are not additive totals.

Use the established environments from plan 001. Run these ReEDS selections serially, not concurrently with another parser suite:

```bash
just test tests/test_fom_policy_edges.py --no-cov --tb=short --durations=5
just test tests/test_fom_control_contract.py --no-cov --tb=short --durations=10
just test tests/test_generator_policy_edges.py tests/test_resource_policy_edges.py tests/test_profile_policy_edges.py tests/test_reserve_profile_contract.py --no-cov --tb=short --durations=5
```

The completed batches took 91.58 seconds, 29.41 seconds, and 56.67 seconds respectively. Earlier overlapping 38-case runs hit their 240-second bounds and are not counted as passing runs.

## Review and limitations

Astra's bounded FOM executor review passed. A subsequent source review identified request-cache admission and incremental mapping-registration defects. Both were independently reproduced, repaired, and covered by passing regressions. Independently identified invalid resolved Rule copies, path-placeholder admission, reserved metadata handling, and dangling source removal are also covered.

Full repository suites were not run. Six `test_datafile_filter_by.py` failures were independently reproduced against core HEAD using obsolete mapping fixtures and left unchanged. No compatibility path was added to satisfy them.

The ReEDS Polars 1.43 environment emits an `explode` deprecation warning about a future Polars 2.0 default. The supported core Polars 1.37 environment remains validated. No version-detection shim or dependency change was introduced to suppress the warning.
