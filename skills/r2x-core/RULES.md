# r2x-core Rules Reference

Use this document when the task is about declaring, filtering, ordering, or
executing translation rules.

## Scope in this skill

This reference covers:

- `Rule` declaration and field mapping
- `RuleFilter` composition for selective application
- `apply_rules_to_context` and `apply_single_rule` execution semantics
- `RuleResult` and `TranslationResult` aggregation
- Rule dependencies and ordering

## Mental model

- A `Rule` is a **declarative mapping** between a source-record type and a
  target component type, optionally gated by a `RuleFilter`.
- Rules are executed against a `PluginContext`. They read source records
  staged on the context and write components into the in-progress `System`.
- Prefer many small rules with explicit names over one mega-rule. Each rule
  should be independently testable.

## Minimal rule

```python
from r2x_core import Rule

translate_generators = Rule(
    name="translate_generators",
    source_type="SourceGenerator",
    target_type="Generator",
    version=1,
    field_map={
        "name": "name",
        "capacity": "p_max_mw",
        "location": "zone",
    },
)
```

## RuleFilter

`RuleFilter` is a composable predicate over source records. Use it to keep
rule logic declarative.

```python
from r2x_core import RuleFilter

active_only = RuleFilter(lambda r: r.status == "active")
not_retired = ~RuleFilter(lambda r: r.status == "retired")
in_west = RuleFilter(lambda r: r.zone.startswith("WEST"))

selected = active_only & in_west
```

Composition operators:

- `&` logical AND
- `|` logical OR
- `~` logical NOT

Attach to a rule via the rule's `filter` field (or whatever the constructor
exposes in your version, confirm against installed source if drifted):

```python
Rule(
    name="translate_active_western_generators",
    source_type="SourceGenerator",
    target_type="Generator",
    version=1,
    field_map={...},
    filter=selected,
)
```

## Executing rules

Apply a list of rules:

```python
from r2x_core import apply_rules_to_context

result = apply_rules_to_context(context, rules)
```

Apply one rule:

```python
from r2x_core import apply_single_rule

rule_result = apply_single_rule(context, translate_generators)
```

Both return result objects rather than raising:

- `apply_single_rule` -> `RuleResult` (per-rule outcome, success counts,
  error details).
- `apply_rules_to_context` -> `TranslationResult` (aggregate of per-rule
  `RuleResult` records).

Inspect aggregate outcomes:

```python
for rr in result.rule_results:
    if rr.is_err:
        print(f"{rr.name}: failed -> {rr.error}")
    else:
        print(f"{rr.name}: applied {rr.applied_count}")
```

(Field names follow the version installed; verify against
`r2x_core.result` source if behavior surprises you.)

## Rule ordering and dependencies

- Order matters when one rule produces components referenced by another
  (e.g., `Bus` rules before `Generator` rules that reference buses).
- Express ordering by listing rules in the desired sequence in the input to
  `apply_rules_to_context`.
- For rules that genuinely depend on the output of an earlier rule, either:
  - Run the producing rule first and confirm the `RuleResult` succeeded
    before scheduling the dependent rule, or
  - Encode the dependency in the rule executor configuration if your
    version exposes a dependency declaration on `Rule`.

## Field mapping patterns

- 1:1 rename: `{"capacity": "p_max_mw"}`
- Drop a field: omit it from `field_map`; do not add a `None` mapping.
- Computed field: prefer a small transform function attached to the rule
  (where supported) over inline `lambda` chains in the mapping.
- Cross-component reference: ensure the referenced target component already
  exists in the `System` (run the producing rule first).

## Failure playbook

- Rule applied to zero records:
  - Confirm `source_type` matches the staged record class name.
  - Inspect `RuleFilter` composition; an `&` chain may be over-restrictive.
- Rule produced wrong number of components:
  - Inspect the source records actually visible to the executor (usually
    on the `PluginContext`).
- Rule raised inside transform:
  - Wrap or refactor; rule transforms should produce typed components, not
    raise. Surface failures via the `RuleResult`.
- Aggregate `TranslationResult` succeeded but downstream code sees missing
  components:
  - Verify dependent rules ran after the producing rule.
  - Verify referenced names match exactly (case-sensitive).

## Output expectations

- Rule names, source/target types, and version.
- Filter composition (and the records it admits).
- Execution order and any cross-rule dependencies.
- Per-rule outcome counts and any aggregate errors.
