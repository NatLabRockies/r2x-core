# Complete the configured generator and FOM path

Status: implemented and independently validated. All 13 FOM edge cases, six control cases, and five generator edge cases pass. See `003-migration-completion.md` for the full scoped completion record.

## Chosen boundary

ReEDS declares physical schemas, source names, keys, category definitions, precedence, eligibility, and output mappings. Existing core DataStore evaluates named datasets, then existing Rule machinery constructs components. There is no ReEDS policy callback, source-derived placeholder dictionary, or application frame pipeline.

Astra's bounded proof is retained at `/home/morgoth/.local/state/pi/reviews/astra-parser-plan-TxGjN1/fom-contract.md`. Its proposed validation-marker workaround is rejected. Use the existing explicit `reject_rows` contract.

## Named dataflow

```text
switches -> validated unique controls -> singleton controls
scalars ------------------------------> singleton scalar
controls + physical optional water --> checked enabled water links

configured capacity source
  -> categories and storage inputs
  -> fuel inputs
  -> controls + scalar + standard/water upgrade identities
  -> keyed plant, characteristic, hydro and hintage rates
  -> current, eligibility-year and strict-prior retrofit rates
  -> configured FOM selection and validation
  -> configured exclusions and grouping
  -> final variable/non-variable generator records
  -> existing RuleMapping construction
```

These are named dependencies, not Python calls passing frames between stages. Reuse the materialization scope across final output branches.

## Minimal missing contracts

1. Complete existing DataStore dependency execution, optionality, request-local reuse, and dependency-safe mutation. Dependency validation already exists.
2. Typed singleton broadcast joins, mutually exclusive with keyed joins. The declared singleton side must contain exactly one row, even if the other side is empty. Existing empty optional water data must be representable without pretending it is absent.
3. Conditional join requiredness, evaluated against the prepared left result. Only actual absence invokes missing-source admission. Present malformed data is an error. Evaluate the condition and resolve the source in one authoritative join loop, never by replaying a partial table.
4. Enforce control uniqueness and singleton shape before lossy pivoting or selection. Do not silently choose the first or last duplicate control.

No new policy interpreter, registry, SQL layer, generic pipeline manager, or application callback is authorized.

## Specific decisions

- Current configuration explicitly prioritizes a standard upgrade link over a matching water link. Preserve that declared choice and add a public overlap regression.
- Water input is physically optional. When WaterMain is enabled, absent water input fails. Existing empty input succeeds. A controls-rooted availability branch enforces this independently of capacity rows.
- Control values remain typed data, not application-extracted variables. Characteristic costs retain all years and join against the characteristic-year column. Eligibility history joins against the eligibility-year column.
- Keep the characteristic source independently overridable. A source containing 2028 rate62000 and 2032 rate99999 must yield62000 for the controlled initial upgrade.
- Capacity source selection is declarative configuration. Remove obsolete Python source-selection special cases and compatibility APIs rather than adding another conditional-source language.
- Effective application configuration may be bound once through shared core integration. No source rows may be extracted into Python parameters by ReEDS.

## Preservation gates

Use the public lifecycle cases in `test_fom_policy_edges.py`, `test_fom_control_contract.py`, `test_generator_policy_edges.py`, `test_parser_fom.py`, and affected builder tests.

Preserve known zero versus unknown, hydro0 as non-override, null initial target propagation, current nonzero retrofit without carry eligibility, eligible strictly prior nonzero carry, initial/new-vintage cost-year differences, global upgrade rejection, required upgrade/DPV rates, FOM-before-weighting, separate VOM mean, generator capacities, names, and references.

The new control-contract file establishes four passing baseline water cases and two intentionally red duplicate-control cases. The latter must become green through source uniqueness/singleton validation, not ignored rows.

## Completion gate

The ReEDS generator preparation entry point consumes final named datasets only. It does not load individual FOM sources, iterate switches, index scalar arrays, construct input dictionaries, perform joins/calculations, or sequence intermediate frames. The old helper path is removed, not wrapped.

Run the focused core contracts, the complete agreed ReEDS generator/FOM public selection, scoped Ruff lint/format, both source type checks, and diff hygiene. Independently review and rerun the meaningful behavior selection before marking this milestone complete.
