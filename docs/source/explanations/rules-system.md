# Rule System Architecture

This document explains the design philosophy and implementation of the
rule-based translation system in R2X Core. For practical usage, see the
{doc}`../how-tos/define-rule-mappings` guide.

## Purpose and Motivation

Power system model translation involves converting components from one modeling
format to another. A generator in ReEDS has different field names, units, and
structures than a generator in PLEXOS or Sienna. The {py:class}`~r2x_core.Rule`
class provides a declarative way to express these transformations without
writing procedural code for each source-target pair.

Traditional approaches to model translation often involve hard-coded conversion
functions. Each source format requires a dedicated function that manually maps
fields, handles edge cases, and creates target components. For example:

```python
# Traditional imperative approach - code bloat and hard to maintain
def translate_model_a_to_model_b(component_a, target_system):
    if component_a.type == "TypeA" and component_a.capacity > 100:
        component_b = ComponentB(
            name=component_a.name,
            capacity=component_a.capacity,
            type="TypeA",
            location=component_a.location,
        )
        target_system.add_component(component_b)
    elif component_a.type in ["TypeB", "TypeC"]:
        component_b = ComponentB(
            name=component_a.name,
            capacity=component_a.capacity,
            type=component_a.type,
            rating=component_a.get("rating", 50.0),
        )
        target_system.add_component(component_b)
    # ... many more conditions, growing quickly

# Adding support for model_c requires new functions for same transformations
def translate_model_c_to_model_b(component_c, target_system):
    # Repeat similar logic but for model_c structure...
    # Code duplication, hard to maintain
    pass
```

This approach creates several problems. Adding a new target format requires
writing new functions for every source format. Changes to source or target
schemas require updating multiple locations. Testing becomes difficult because
conversion logic is scattered across many functions.

The rule system addresses these challenges through declarative specifications
that separate the "what" from the "how." A {py:class}`~r2x_core.Rule` declares
what transformation should happen. The
{py:func}`~r2x_core.apply_rules_to_context` executor handles how to perform it.

The same transformation expressed as a rule:

```python
from r2x_core import Rule, RuleFilter, PluginContext, apply_rules_to_context

translation_rule = Rule(
    name="translate_large_components",
    source_type="ComponentA",
    target_type="ComponentB",
    version=1,
    filter=RuleFilter(
        all_of=[
            RuleFilter(field="type", op="eq", values=["TypeA"]),
            RuleFilter(field="capacity", op="geq", values=[100.0]),
        ]
    ),
    field_map={
        "name": "name",
        "capacity": "capacity",
        "location": "location",
    },
)

# Rules travel on the context; the executor pulls components from
# context.source_system and adds the converted ones to context.target_system.
context = PluginContext(
    config=config,
    rules=(translation_rule,),
    source_system=model_a_system,
    target_system=target_system,
)
result = apply_rules_to_context(context)
```

The rule system eliminates code duplication, makes translation logic explicit
and testable, and enables configuration-driven translation: the same rule can
be expressed as a JSON record and loaded with
{py:meth}`~r2x_core.Rule.from_records`.

## Core Design Principles

### Declarative Over Imperative

Rules describe what transformation should happen rather than how to perform it
step by step. A rule declares that a `BusComponent` should become a
`NodeComponent` with field `kv_rating` mapped to `voltage_kv`. The rule executor
handles the mechanics of reading source fields, applying conversions, and
creating target instances.

This separation allows rules to be expressed in configuration files, versioned
alongside data, and validated statically before execution. The
{py:meth}`~r2x_core.Rule.from_records` method enables loading rules from JSON,
making translation logic configurable without code changes.

### Composition Through Filters

Rather than embedding conditional logic within rules, the system uses composable
{py:class}`~r2x_core.RuleFilter` objects to restrict which components a rule
processes. A filter can match components by field values, by derived values
computed through getters, or by boolean combinations using `any_of` and
`all_of`.

Filters are separate objects that rules reference, enabling reuse across
multiple rules. A filter matching "all generators with capacity above 100 MW in
region 'West'" can be defined once and applied to multiple translation rules.
Changes to selection criteria require updating only the filter definition.

### Immutability for Correctness

{py:class}`~r2x_core.Rule` instances are frozen dataclasses that cannot be
modified after creation. This immutability prevents subtle bugs where shared
rules are accidentally modified, causing unexpected behavior in seemingly
unrelated translations. Each rule application works with the exact configuration
that was defined, making behavior reproducible and debugging straightforward.

The immutability constraint also enables safe sharing of rules across threads
and processes. Concurrent translation operations cannot interfere with each
other through shared mutable state. Rule identity (equality and hashing) is
keyed on `(source_type, target_type, version)`, so two rules for the same
conversion must declare distinct versions.

## Architecture Overview

### Rule Definition

The {py:class}`~r2x_core.Rule` class encapsulates a single transformation
between source and target types. Each rule specifies the source component type
it matches, the target type (or types) it produces, and an integer `version`
for schema evolution. The `field_map` dictionary maps target field names to
source field names for direct copies; anything computed goes in `getters`.

A simple rule using only direct field mappings:

```python
from r2x_core import Rule

rule = Rule(
    name="model_a_to_model_b_generator",
    source_type="GeneratorA",
    target_type="GeneratorB",
    version=1,
    field_map={
        "name": "name",
        "capacity_mw": "capacity_mw",
        "location": "location",
    },
    defaults={"fuel_type": "natural_gas"},  # Fallback when the source lacks a value
)
```

A rule that derives target fields from computation uses `getters`. A getter is
a callable receiving the source component and the active
{py:class}`~r2x_core.PluginContext` as a keyword argument, returning a
`rust_ok` `Result`:

```python
from rust_ok import Ok
from r2x_core import Rule


def total_capacity(src, *, context):
    return Ok(src.max_capacity * src.unit_count)


def ramp_rate_per_minute(src, *, context):
    return Ok(src.ramp_up_rate * 60)


rule = Rule(
    name="model_a_to_model_b_generator_advanced",
    source_type="GeneratorA",
    target_type="GeneratorB",
    version=1,
    field_map={
        "name": "name",
        "min_up_time_hours": "min_online_time",
    },
    getters={
        "capacity_mw": total_capacity,
        "ramp_rate_mw_per_minute": ramp_rate_per_minute,
    },
    depends_on=["generator_location_mapping"],  # Run after other rules
)
```

Getters can also be referenced by name. Functions decorated with
{py:func}`~r2x_core.getter` register under their name (or a custom one), and
JSON rule records can then reference them as strings; dotted strings fall back
to nested attribute lookups. This keeps computed mappings available to fully
configuration-driven rules.

Field values are resolved with a fixed precedence: `field_map` reads the source
attribute directly, `getters` compute values, and `defaults` (keyed by target
field name) fill in whenever the mapped attribute is missing or the getter
returns nothing. A mapped field that is missing on the source with no default
is an error that fails the rule.

A few structural constraints keep rules unambiguous. A rule may declare
multiple target types (fan-out: one source component produces one target
component per type) or multiple source types, but not both. A `field_map` entry
whose source side is a list of fields requires a matching getter to combine
them. The `system` parameter (default `"source"`) selects which system the rule
reads from; `system="target"` lets a rule derive components from already
translated ones.

### Filter Predicates

The {py:class}`~r2x_core.RuleFilter` class provides a flexible predicate
language for component selection. Leaf filters compare a candidate value
against `values` using one of: `eq`, `neq`, `in`, `not_in`, `geq`,
`startswith`, `not_startswith`, `endswith`. Compound filters nest other filters
under `any_of` (OR) or `all_of` (AND).

```python
from r2x_core import RuleFilter

# Simple equality filter
filter_type_a = RuleFilter(field="component_type", op="eq", values=["TypeA"])

# Membership
filter_multiple_types = RuleFilter(
    field="component_type", op="in", values=["TypeA", "TypeB", "TypeC"]
)

# Numeric comparison - components with capacity >= 100
filter_large = RuleFilter(field="capacity", op="geq", values=[100.0])

# Prefix matching uses the dedicated `prefixes` field
filter_region = RuleFilter(field="name", op="startswith", prefixes=["Region1"])

# AND composition
filter_large_type_a = RuleFilter(
    all_of=[
        RuleFilter(field="component_type", op="eq", values=["TypeA"]),
        RuleFilter(field="capacity", op="geq", values=[50.0]),
    ]
)

# OR composition
filter_common_types = RuleFilter(
    any_of=[
        RuleFilter(field="component_type", op="in", values=["TypeA", "TypeB"]),
        RuleFilter(field="component_type", op="eq", values=["TypeC"]),
    ]
)
```

The candidate value normally comes from a component attribute (`field`), but a
filter can instead declare a `getter` to derive it from translator context,
supplemental attributes, or other source-system lookups. Two more knobs control
edge cases: `casefold` (default true) makes string comparison
case-insensitive, and `on_missing` decides whether a component lacking the
field is included or excluded (default `"exclude"`).

The filter implementation optimizes for repeated evaluation. String values are
casefolded once during filter construction rather than on every comparison.
These optimizations matter when filtering thousands of components during a
large system translation. See {doc}`../how-tos/create-rule-filters` for the
full how-to, including getter-backed filters loaded from JSON records.

### Rule Execution

The {py:func}`~r2x_core.apply_rules_to_context` function orchestrates the
translation. It takes only the {py:class}`~r2x_core.PluginContext`; rules,
source system, and target system all travel on the context:

```python
from r2x_core import Rule, PluginContext, apply_rules_to_context

rules = (
    Rule(
        name="translate_component_type_a",
        source_type="ComponentA",
        target_type="ComponentB",
        version=1,
        field_map={"name": "name", "capacity": "capacity", "location": "location"},
    ),
    Rule(
        name="translate_component_type_b",
        source_type="NodeA",
        target_type="NodeB",
        version=1,
        field_map={"name": "name", "voltage": "voltage"},
    ),
)

context = PluginContext(
    config=config,
    rules=rules,
    source_system=source_system,
    target_system=target_system,
)
result = apply_rules_to_context(context)

if result.success:
    print(f"Translation successful: {result.total_converted} components")
else:
    for rule_result in result.rule_results:
        if not rule_result.success:
            print(f"  {rule_result.rule}: {rule_result.error}")
```

Execution proceeds in well-defined stages:

1. **Dependency sorting.** Rules are topologically sorted by their
   `depends_on` declarations (Kahn's algorithm). Duplicate rule names,
   unknown dependencies, and dependency cycles are rejected up front. Unnamed
   rules without dependencies run first.
2. **Per-rule application.** For each rule, the executor resolves the source
   and target classes by name, iterates matching components from the system
   selected by `rule.system`, evaluates the filter, builds target field values,
   and constructs one target component per target type. A failing rule is
   recorded in its {py:class}`~r2x_core.RuleResult` without aborting the
   remaining rules.
3. **UUID handling.** By convention, mapping `"uuid": "uuid"` in `field_map`
   preserves the source component's identity on the target, which later stages
   rely on. When a rule declares multiple target types, the executor assigns
   each created component a fresh UUID instead, since several components cannot
   share one identity.
4. **Supplemental attribute attachment.** When a rule's target type is a
   `SupplementalAttribute` subclass, the created attribute is attached to the
   target component whose UUID matches the source component's UUID. The
   component-producing rule must therefore run first (use `depends_on`) and
   preserve the UUID.
5. **Time series transfer.** After all rules have run,
   {py:func}`~r2x_core.transfer_time_series_metadata` copies time series
   associations in bulk, matching source and target components by equal UUID
   and remapping child-owned series onto translated parents where needed. The
   counts appear on the returned result as `time_series_transferred` and
   `time_series_updated`.

The function returns a {py:class}`~r2x_core.TranslationResult` with aggregate
statistics (`total_rules`, `successful_rules`, `failed_rules`,
`total_converted`, the per-rule `rule_results`, and the time series counters).
Its `success` property is true when no rule failed, and `summary()` prints a
formatted table for logging and debugging.

### Single-Rule Application

The {py:func}`~r2x_core.apply_single_rule` function handles translation for a
single rule, useful for fine-grained control or selective application outside
the full workflow:

```python
from r2x_core import apply_single_rule
from rust_ok import Ok, Err

match apply_single_rule(rule, context=context):
    case Ok(stats):
        print(f"converted={stats.converted} skipped={stats.skipped}")
    case Err(error):
        print(f"rule failed: {error}")
```

It returns a `Result[RuleApplicationStats, ValueError]` rather than raising,
consistent with the `rust_ok` error handling used across the executor.

## Design Trade-offs

### Why Frozen Dataclasses?

Rules could have been regular mutable objects, allowing dynamic modification
during translation. However, mutable rules create subtle bugs. A rule modified
by one translation could affect subsequent translations in unexpected ways.
Debugging becomes difficult because the rule state at failure time differs from
its initial definition. Frozen dataclasses prevent these issues at the cost of
requiring new {py:class}`~r2x_core.Rule` objects for any variation. In practice,
rule objects are rarely modified after creation, making this cost acceptable.

### Why String-Based Type References?

Rules reference source and target types by string name rather than actual Python
classes. This design enables rules to be defined in JSON configuration files
where class objects cannot be represented. The executor resolves strings to
classes at runtime by searching the modules listed in the context's
`config.models`. This late binding adds flexibility but means type errors are
caught at execution rather than definition time. The trade-off favors runtime
flexibility for configuration-driven use cases.

### Why Separate Filters from Rules?

Filter logic could have been embedded directly in rule definitions. However,
separating {py:class}`~r2x_core.RuleFilter` objects provides several benefits.
Filters can be reused across multiple rules without duplication. Filter logic
can be tested independently from translation logic. Complex selection criteria
have clear ownership rather than being scattered across rule definitions. This
separation also enables future optimization such as filter merging and predicate
pushdown.

## Integration with Plugin System

Rules integrate with the broader plugin system through the
{py:class}`~r2x_core.PluginContext`. The context provides access to source and
target systems, configuration, and the model modules used for type resolution.
Translation plugins define rules as part of their configuration and invoke the
rule executor during the `on_translate` lifecycle hook. The context also
exposes lookup helpers (`list_rules`, `get_rule`, `get_rules_for_source`,
`list_available_conversions`) so plugins can discover available conversions at
runtime.

This integration enables declarative plugin configuration. A translation plugin
can be fully configured through JSON files specifying rules, filters, and field
mappings. The plugin code becomes a thin wrapper that loads configuration and
invokes {py:func}`~r2x_core.apply_rules_to_context`, with all translation logic
expressed declaratively.

## Performance Considerations

The rule system is designed for large-scale translations involving thousands of
components. Rule validation and dependency sorting happen once per translation,
not per component. Filter predicates cache normalized values to avoid repeated
computation. Component classes are resolved once per rule rather than per
component.

For very large systems, the executor could be extended to parallelize
independent rules. The current sequential execution is sufficient for typical
use cases but the architecture does not preclude parallel execution. The
immutability of rules is actually beneficial for parallelization, as there is no
need for locking or synchronization.

## Extension Points

The rule system provides several extension points for future enhancement. Custom
filter operations could be registered to extend the predicate language. Rule
inheritance could allow base rules with shared mappings that derived rules
extend. Transformation pipelines could combine rules from multiple plugins.
Round-trip (bidirectional) translation is addressed by the translation history
described in {doc}`./lossless-translation`. These extensions build on
the existing architecture without fundamental changes.

## Complete Example: ReEDS to Infrasys Translation

Here's a realistic example translating ReEDS model generators and buses to an
Infrasys system:

```python
from rust_ok import Ok
from r2x_core import Rule, RuleFilter, PluginContext, apply_rules_to_context

# Filters for selective translation
filter_large_wind = RuleFilter(
    all_of=[
        RuleFilter(field="fuel", op="eq", values=["Wind"]),
        RuleFilter(field="p_max_mw", op="geq", values=[100.0]),
    ]
)


def wind_category(src, *, context):
    return Ok("WindOnshore")


rules = (
    # Step 1: Translate all buses, preserving identity for later steps
    Rule(
        name="reeds_buses_to_infrasys",
        source_type="ReEDSBus",
        target_type="Bus",
        version=1,
        field_map={
            "uuid": "uuid",
            "name": "name",
            "voltage_kv": "voltage_kv",
            "region": "region",
        },
    ),
    # Step 2: Translate large wind generators (after buses)
    Rule(
        name="reeds_wind_generators",
        source_type="ReEDSGenerator",
        target_type="Generator",
        version=1,
        filter=filter_large_wind,
        field_map={
            "name": "name",
            "p_max_mw": "p_max_mw",
            "zone_id": "zone",
            "min_up_time": "min_online_time_minutes",
        },
        getters={"fuel": wind_category},
        depends_on=["reeds_buses_to_infrasys"],
    ),
    # Step 3: Translate conventional generators
    Rule(
        name="reeds_thermal_generators",
        source_type="ReEDSGenerator",
        target_type="ThermalGenerator",
        version=1,
        filter=RuleFilter(field="fuel", op="in", values=["Coal", "Gas"]),
        field_map={
            "name": "name",
            "p_max_mw": "p_max_mw",
            "fuel": "fuel",
            "heat_rate_mmbtu_per_mwh": "heat_rate",
        },
        defaults={"heat_rate_mmbtu_per_mwh": 10.5},  # Keyed by target field
        depends_on=["reeds_buses_to_infrasys"],
    ),
)

context = PluginContext(
    config=config,
    rules=rules,
    source_system=reeds_system,
    target_system=infrasys_system,
)

result = apply_rules_to_context(context)

result.summary()
for rule_result in result.rule_results:
    status = "ok" if rule_result.success else f"error: {rule_result.error}"
    print(f"{rule_result.rule}: converted={rule_result.converted} ({status})")
```

This example demonstrates several key concepts: selective translation through
filters, computed fields using getters, default values for missing data, UUID
preservation for cross-rule identity, and ordered execution through
dependencies. The same rule definitions could be stored in JSON and loaded from
configuration files with {py:meth}`~r2x_core.Rule.from_records`, enabling fully
declarative translation pipelines.

## See Also

- {doc}`../how-tos/define-rule-mappings` for practical usage examples
- {doc}`../how-tos/create-rule-filters` for filter composition patterns
- {doc}`./lossless-translation` for round-trip translation and the translation history
- {doc}`./plugin-system` for understanding plugin integration
- {py:class}`~r2x_core.Rule` API reference
- {py:class}`~r2x_core.RuleFilter` API reference
- {py:func}`~r2x_core.apply_rules_to_context` API reference
- {py:class}`~r2x_core.TranslationResult` API reference
