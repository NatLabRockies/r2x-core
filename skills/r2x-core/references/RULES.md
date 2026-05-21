# r2x-core Rules Reference

Use this when declaring, loading, filtering, ordering, or executing translation
rules.

## Contracts (source-verified)

- `apply_rules_to_context(context: PluginContext) -> TranslationResult`
- `apply_single_rule(rule: Rule, *, context: PluginContext) -> Result[RuleApplicationStats, ValueError]`
- Rule execution reads from `context.source_system` and writes to
  `context.target_system`.
- `Rule` is a frozen dataclass keyed by `source_type`, `target_type`, and
  `version`.
- `Rule.filter: RuleFilter | None`
- `RuleFilter` composes with nested `any_of` / `all_of` filters.

## Do

- Attach rules to `PluginContext.rules` before calling `apply_rules_to_context`.
- Provide both `source_system` and `target_system` on the context.
- Name rules that participate in dependency ordering.
- Use `Rule.defaults` for target fields that should get fallback values.
- Use `Rule.from_records(...)` for JSON-loaded rules with string getter specs.
- Use real callable getters when constructing `Rule(...)` directly.
- Order supplemental-attribute rules after the component rules they attach to.

## Don't

- Do not call `apply_rules_to_context(context, rules)`.
- Do not call `apply_single_rule(context, rule)`.
- Do not use `RuleFilter(lambda ...)` or operator overloads like `&`, `|`, `~`.
- Do not rely on multi-source rules; split them or write explicit custom logic.
- Do not pass string getters directly to `Rule(...)`; they are preprocessed by
  `Rule.from_records(...)`.
- Do not expect `context.system` to be used by the rule executor.

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
    defaults={"available": True},
)
```

`field_map` maps target fields to source fields. Omit fields you do not want to
set. Use `defaults` for target-side fallback values.

## Executing rules

```python
from r2x_core import PluginContext, System, apply_rules_to_context

context = PluginContext(
    config=config,
    source_system=source_system,
    target_system=System(name="translated"),
    rules=tuple(rules),
)
translation = apply_rules_to_context(context)
```

Apply one rule:

```python
from r2x_core import apply_single_rule

stats_result = apply_single_rule(translate_generators, context=context)
```

Return contracts:

- `apply_single_rule(...)` returns `Result[RuleApplicationStats, ValueError]`.
- `apply_rules_to_context(...)` returns `TranslationResult` with per-rule
  `RuleResult` records and aggregate stats/summary fields in current source.

## RuleFilter

`RuleFilter` is declarative and casefolds string comparisons by default in
current source.

```python
from r2x_core import RuleFilter

selected = RuleFilter(
    all_of=[
        RuleFilter(field="status", op="eq", values=["active"]),
        RuleFilter(field="zone", op="startswith", values=["west"]),
    ]
)
```

Supported filter fields and operators in current source:

- leaf filters: `field`, `op`, `values`, optional `prefixes`, `casefold`, and
  `on_missing`
- composition: nested `any_of` or nested `all_of`, but not both on the same
  filter
- operators: `eq`, `neq`, `in`, `not_in`, `geq`, `startswith`,
  `not_startswith`, `endswith`
- missing-field policy: `on_missing="include" | "exclude"`

Use `RuleFilter.matches(component)` when you need to evaluate one component in
ad hoc diagnostics. Verify `r2x_core.rules.RuleFilter` before adding a new op
to a package.

## Field mapping and getters

Patterns:

- 1:1 rename: `{"capacity": "p_max_mw"}`
- default value: `defaults={"available": True}`
- computed field: `getters={"name": callable}`
- multi-source field: use a getter for the target field

If a field mapping entry names multiple source fields, the target must have a
getter. Direct `field_map={"x": ["a", "b"]}` without `getters={"x": ...}` is
invalid in current source.

String getter specs such as `"child.name"` are converted to callables by
`Rule.from_records(...)`. If you instantiate `Rule(...)` directly, pass callable
getters, not strings.

## Dependencies and ordering

The executor sorts rules by dependency metadata when present.

- Duplicate named rules are errors.
- Unknown dependencies are errors.
- Circular dependencies are errors.
- Unnamed rules without dependencies run before named rules.
- Rules with dependencies should be named.

Prefer explicit `name` / `depends_on` for rules that must run after another
rule, such as a generator rule depending on buses.

## Multiple source/target behavior

- Current source rejects rules that declare both multiple source types and
  multiple target types.
- Multiple target types are supported; executor regenerates UUIDs where needed.
- Multi-source execution is limited and may warn/use only the first source type.
  Avoid it unless you have source-verified behavior and tests.

## Supplemental attributes

When a rule creates a `SupplementalAttribute`, the executor attaches it to an
existing target component matched through source UUID mapping. If no target
component exists, the rule fails.

Guidance:

- Run component-producing rules first.
- Run supplemental-attribute rules after their target component rule.
- Preserve UUID/source mapping through the rule sequence.

## Failure playbook

- Rule applied to zero records:
  - Confirm `context.source_system` contains the source component type.
  - Inspect `RuleFilter` composition and casefold behavior.
- Output system is empty:
  - Confirm `context.target_system` is set; rules do not populate
    `context.system`.
- Getter fails:
  - If loaded from JSON, use `Rule.from_records(...)`.
  - If constructed directly, pass callable getters returning the expected
    `Result`/value shape for current source.
- Dependency sort fails:
  - Check duplicate names, unknown dependencies, and cycles.
- Supplemental attribute rule fails:
  - Ensure the target component already exists and source UUID mapping is
    preserved.

## Output expectations

- Rule names, source/target types, version, defaults, and dependencies.
- Source and target systems attached to the context.
- Filter composition, missing-field policy, and records admitted.
- Getter/default decisions for computed or missing fields.
- Per-rule counts, failures, and aggregate translation summary.
