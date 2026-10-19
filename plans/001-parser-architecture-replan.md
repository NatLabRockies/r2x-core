# Replan the parser migration around complete data contracts

Status: the scoped implementation and validation are complete. See `003-migration-completion.md` for current results. The sections below retain the agreed scope, original starting-state findings, and execution gates.

Core checkout: `/home/morgoth/worktrees/r2x-core/fix-csv-contruct-291`, HEAD `0458cef`.
ReEDS checkout: `/home/morgoth/worktrees/r2x-reeds/fix-r2x-core-hp2`, HEAD `e68ad38`.
Both checkouts contain substantial uncommitted changes. HEAD alone is not the starting state.

## Goal

Make the application parser a thin declaration of source schemas, modeling policy, and outputs. Core owns data loading, dataset evaluation, component construction, reference resolution, and profile attachment. ReEDS must not retain a second implementation of those operations.

This is not a target Python line count. Moving Python branches into a larger configuration interpreter is not success.

The user rejected a presumed escape hatch for small pure ReEDS policy functions. Source-specific choices belong in ReEDS configuration and do not, by themselves, justify ReEDS-specific Python computation. Core executes the shared mechanics. Any proposed exception must demonstrate a concrete operation that cannot fit the shared contract and receive explicit approval. Do not add a batch-callback seam or renamed policy helper to bypass this requirement.

## Why the attempt failed

1. We migrated functions before agreeing on an end-to-end execution contract. Each local obstacle produced another processing option.
2. Table composition is only partially implemented. `FileMapping` accepts table dependencies and rejects cycles, but `DataStore.prepare_table` still resolves dependencies as physical files. Python therefore sequences intermediate frames even after the arithmetic moves into configuration.
3. Source loading, field derivation, component mapping, and profile attachment have no agreed separation. `TabularProcessing` is absorbing responsibilities from all four.
4. We treated preserving helper tests and adding more configuration as progress. The actual plugin remained responsible for orchestration and source interpretation.
5. We expanded several partially validated slices at once. The working tree now contains incomplete contracts and intentionally failing tests.

## Grounded starting points

- `src/r2x_core/store.py:440`, `DataStore.prepare_table`, resolves physical sources and runtime frames.
- `src/r2x_core/prepared_tables.py:90`, `PreparedTable`, describes joins and processing. `FileMapping` now accepts table dependencies and validates cycles, but execution, optionality, and dependency-safe table removal remain incomplete.
- `src/r2x_core/rules.py:241`, `RuleMapping`, already describes construction and supplemental attributes.
- `src/r2x_core/rules_executor.py:92`, `RulePlan`, already resolves mappings, source types, and ordered construction stages.
- ReEDS `src/r2x_reeds/parser.py:1336` still manually sequences generator datasets and extracts FOM switches/scalars.
- PLEXOS `src/r2x_plexos/parser.py:293` groups object properties and builds memberships. Its profile path at line 339 resolves several kinds of references. This is a materially different source shape, not another ReEDS CSV reader.
- ReEDS `docs/src/content/docs/explanation/architecture.md` separates source semantics, the source component graph, optional modifiers, target translation, and export. Preserve these boundaries. Do not introduce target-specific translation assumptions into parsing.

## Architectural direction

Keep three responsibility boundaries, not one growing bag of dataframe options. These boundaries do not authorize three new frameworks or plan types.

| Contract | Responsibility | Not its responsibility |
| --- | --- | --- |
| Named datasets | Physical source schemas, declared dependencies, normalized records, input validation, provenance | Constructing components or attaching time series |
| Model mappings | Existing Rule machinery constructs components, references, and supplemental attributes from normalized records | Reading files or preparing intermediate frames |
| Profiles | Values, time axis, owner identity, variable, units, scenario metadata, and attachment policy | ReEDS-specific technology names or hidden calendar guesses |

```text
source definitions + effective configuration
                    |
             named datasets
                    |
          normalized source records
              /             \
       model mappings     profile definitions
              \             /
               source System
                    |
        existing translation/export stages
```

The dataset executor must own dependency evaluation. A plugin must not pass a dictionary of physical inputs or manually pipe ten intermediate frames between calls. Extend the existing DataStore/Rule architecture only where its contract is genuinely missing. Do not introduce a parallel workflow interpreter.

Configuration declares source selection, keys, policy values, precedence, mappings, and required outputs. Native Polars remains the implementation engine. Do not keep translating individual Python statements into new JSON operators.

Prove complex field derivation with the complete FOM dataflow below before selecting another public API. Reuse DataStore and RuleMapping rather than introducing another executor. Arbitrary callbacks, SQL strings, a new expression DSL, and a general profile manager are not approved solutions.

## Phase 1: reconcile the interrupted state

Preserve the existing dirty work while completing the approved shared contracts. No reset or whole-file restoration is authorized. The abandoned standalone `tests/test_profiles.py` experiment may be removed only after confirming its content and ownership. Do not implement its guessed API merely because the test exists.

Classify the dirty diff into pre-existing work, independently useful validated changes, and abandoned or incomplete experiments. Propose exact hunks/files to retain or remove. Never reset either checkout or restore a whole file over unrelated changes.

Known incomplete work:

- Three core composition tests are red. Dependency validation exists, but table execution and lifecycle behavior are incomplete.
- `tests/test_profiles.py` references an unimplemented `r2x_core.profiles` module. This is an unfinished experiment, not release evidence.
- The application still contains generator orchestration, synthetic hour-map behavior, reserve preparation, calendar expansion, and profile attachment logic.
- The most recent broad working-tree state has not passed a complete relevant validation selection.

Deliverable: a reconciled starting patch and a reproducible green baseline. The existing table composition contract is the first bounded completion, rather than deleting its red tests. Do not stack unrelated partially implemented capabilities on top.

## Phase 2: prove the complete FOM dataflow

Do not start with a framework for every parser. Produce one complete generator/FOM example with exact typed inputs, output schema, effective configuration, and the resulting application entry point.

The proof must cover this whole path:

1. Select the configured normal or degraded capacity dataset.
2. Resolve declared cost, hydro, hintage, upgrade-link, technology-membership, switch, and scalar inputs through core. Trace solve year, characteristic year, and eligibility year to their declared origins.
3. Resolve upgrade source/target identities and configured FOM precedence. Preserve pumped-storage scalar precedence, retrofit conditions, characteristic-year initial upgrades, solve-year new upgrades, nonzero regional hydro overrides, distributed-PV hintage, and base costs.
4. Preserve null versus zero. Prior retrofit lookup is strictly earlier than the row's solve year and ignores zero rates. Carry eligibility does not gate a nonzero current rate. A missing initial target cost stays unknown even when a hydro adder exists.
5. Return normalized generator rows with stable technology, region, year, vintage, capacity, and resolved FOM, without losing other generator attributes.
6. Apply configured renewable grouping and FOM weighting before existing RuleMapping construction. Preserve annual cost and the separate VOM mean.

Required deliverables:

- A named dependency diagram with source schemas, keys, cardinalities, and control-value origins.
- A complete configuration example, not a proposed new operator list or pseudocode that conceals an application callback.
- The smallest demonstrated missing core contracts, each traced to this dataflow.
- The resulting ReEDS entry point. It must not read individual FOM files, extract switch rows, pass physical-input dictionaries, sequence intermediate frames, or run dataframe calculations.
- A direct mapping from each semantic decision to a public lifecycle assertion.

Review gates:

- DataStore owns dependency evaluation, optionality, and request-local reuse, including missing references and cycles before I/O.
- Configuration declares source and modeling choices. Core executes them without ReEDS names or switch-specific branches.
- Required missing data fails rather than generating synthetic data.
- RuleMapping remains the construction contract, including its existing computed-record entry point.
- A read-only PLEXOS object/property example can still use the record construction boundary without being forced into a CSV-only design. This is a boundary check, not another migration or framework-design phase.
- RESOLVE remains an explicitly unverified future consumer. Do not invent schema compatibility.

Reject the design before coding if it requires another ReEDS-specific Python policy function, a collection of artificial intermediate flags, or a second mapping/execution engine. Profiles, resources, and reserves wait until the FOM/generator path is complete and green.

## Phase 3: one complete generator migration

Implement the minimum shared contract established by the FOM proof for the complete generator workload. Switch ReEDS to it and delete the replaced helper APIs and code paths in the same bounded migration. The user has authorized completion, so do not pause again for approval of each already-scoped milestone.

Do not retain optional-store execution, optional-FOM execution, old argument factories, renamed parsing wrappers, or compatibility aliases. Do not expand to profiles or reserves until this end-to-end path is green and the application orchestration is actually gone.

Preserve independently established behavior unless a modeling change is explicitly approved:

- Known zero versus unknown FOM and hydro's zero non-override convention.
- Characteristic-year versus solve-year cost selection and configurable physical sources.
- Current versus strictly prior nonzero retrofit rates and carry eligibility.
- FOM before capacity-weighted aggregation. VOM retains its separate configured mean.
- Fuel base-name matching, storage duration precedence, thermal-only heat-rate filling, capacities, identities, and references.

## Phase 4: apply the reviewed contracts to remaining outputs

Migrate resource datasets, reserve preparation, and profiles one complete output path at a time. Each path includes configuration, core execution, application deletion, and public integration tests.

Preserve resource source/candidate/selected precedence explicitly. A configured source preference is not permission for guessed legacy filenames or permissive alias detection.

Share representative-period expansion mechanics used by ReEDS sysmod consumers and update the real callers directly. Do not retain a ReEDS re-export wrapper or presume a general profile framework is needed. Keep profile meaning, scaling choices, ownership, time axis, and metadata explicit in configuration. Leave unrelated sysmod modeling algorithms and existing format-upgrade functionality out of this migration.

## Verification

Use the existing environments without installing dependencies or modifying lockfiles:

```bash
export TMPDIR=/home/morgoth/.cache/pi/validation-tmp
export UV_NO_SYNC=1
```

Core, from its checkout:

```bash
export UV_PROJECT_ENVIRONMENT=/home/morgoth/dev/r2x-core/.venv
just test <approved affected tests> --no-cov
just lint <changed Python files>
just format --check <changed Python files>
just type
git diff --check
```

ReEDS, from its checkout:

```bash
export UV_PROJECT_ENVIRONMENT=/home/morgoth/dev/r2x-reeds/.venv
export PYTHONPATH=/home/morgoth/worktrees/r2x-core/fix-csv-contruct-291/src:/home/morgoth/worktrees/r2x-reeds/fix-r2x-core-hp2/src
just test <approved affected tests> --no-cov
just lint <changed Python files>
just format --check <changed Python files>
uv run ty check src/
git diff --check
```

ReEDS `just type` invokes an undeclared mypy executable. Use the configured ty checker directly. Core's six `test_datafile_filter_by.py` cases already fail against HEAD because their mapping fixtures use the obsolete list envelope. Record those separately, never add a compatibility fallback to satisfy them.

Public integration evidence includes `test_fom_policy_edges.py`, `test_generator_policy_edges.py`, `test_resource_policy_edges.py`, and the unfinished characterization in `test_profile_policy_edges.py`. Fixture setup may move to the approved new configuration contract. Numerical, identity, source-selection, and precedence assertions must not be weakened to accommodate the implementation.

Final acceptance requires the complete agreed regression selection, not only new primitive unit tests. Include the full parser lifecycle with reserves enabled, profile timestamps, resolution, and solve-year metadata. The small independent generator/resource/profile cases disable unrelated reserve products and do not replace that combined acceptance test. No current aggregate test count establishes that this interrupted state is green.

## Stop conditions

- The next change exists only to encode another ReEDS branch in a generic-looking operator.
- Core needs ReEDS names, technology families, switches, or a ReEDS-specific manager.
- The proposed application still sequences frames, reconstructs source-input dictionaries, or hides parsing in a ReEDS-specific policy callback.
- A domain choice, calendar policy, or data interpretation is not established by source/tests. Ask rather than invent a fallback.
- Recovery would overwrite unrelated dirty changes.
- The implementation diverges from the concrete shared contract instead of closing a demonstrated gap.

Implementation is authorized by the user's instruction to complete the work until finished. Preserve unrelated changes and report actual validation, not intention.
