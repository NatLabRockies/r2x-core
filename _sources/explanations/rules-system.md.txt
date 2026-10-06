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
conversion logic is scattered across many functions. Operator precedence and
evaluation order can become ambiguous as the number of translation paths grows.

The rule system addresses these challenges through declarative specifications
that separate the "what" from the "how." A {py:class}`~r2x_core.Rule` declares
what transformation should happen. The
{py:func}`~r2x_core.apply_rules_to_context` executor handles how to perform it.

With the rule system, the same rules work for any source format:

```python
# Rule-based approach - single definition, works for all formats
translation_rule = Rule(
    name="translate_large_components",
    source_type="ComponentA",
    target_type="ComponentB",
    filter=RuleFilter(
        operation="all_of",
        predicates=[
            RuleFilter(field="type", operation="eq", values=["TypeA"]),
            RuleFilter(field="capacity", operation="geq", values=[100.0]),
        ]
    ),
    field_map={
        "name": "name",
        "capacity": "capacity",
        "type": lambda src: "TypeA_Translated",
        "location": "location",
    }
)

# Apply to any source format - same rule works for all
apply_rules_to_context(context, [translation_rule], model_a_components)
apply_rules_to_context(context, [translation_rule], model_c_components)
apply_rules_to_context(context, [translation_rule], model_x_components)
```

The rule system eliminates code duplication, makes translation logic explicit
and testable, and enables configuration-driven translation.

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
processes. A filter can match components by field values, by name prefixes, or
by complex boolean combinations using `any_of` and `all_of`.

Filters are separate objects that rules reference, enabling reuse across
multiple rules. A filter matching "all generators with capacity above 100 MW in
region 'West'" can be defined once and applied to multiple translation rules.
Changes to selection criteria require updating only the filter definition. This
composition avoids the combinatorial explosion that would result from hardcoding
each source/target/filter combination.

### Immutability for Correctness

{py:class}`~r2x_core.Rule` instances are frozen dataclasses that cannot be
modified after creation. This immutability prevents subtle bugs where shared
rules are accidentally modified, causing unexpected behavior in seemingly
unrelated translations. Each rule application works with the exact configuration
that was defined, making behavior reproducible and debugging straightforward.

The immutability constraint also enables safe sharing of rules across threads
and processes. Concurrent translation operations cannot interfere with each
other through shared mutable state. This is particularly important in enterprise
environments where translation pipelines run continuously on large numbers of
systems.

## Architecture Overview

### Rule Definition

The {py:class}`~r2x_core.Rule` class encapsulates a single transformation
between source and target types. Each rule specifies the source component type
(or types) it matches, the target type (or types) it produces, and a version
number for schema evolution. The `field_map` dictionary describes how source
fields become target fields, supporting both simple one-to-one mappings and
complex multi-field derivations through getter functions.

Here's a simple example converting a model_a generator to a model_b generator:

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
        "fuel_type": lambda src: src.fuel_type.lower(),  # Transform fuel type
        "location": "location",
    },
    defaults={"fuel_type": "natural_gas"},  # Fallback if fuel is missing
)
```

A more complex example showing multi-field derivation:

```python
rule = Rule(
    name="model_a_to_model_b_generator_advanced",
    source_type="GeneratorA",
    target_type="GeneratorB",
    version=1,
    field_map={
        "name": "name",
        "capacity_mw": lambda src: src.max_capacity * src.unit_count,
        "min_up_time_hours": "min_online_time",
        "ramp_rate_mw_per_minute": lambda src: src.ramp_up_rate * 60,
    },
    depends_on=["generator_location_mapping"],  # Wait for other rules
)
```

Rules support several advanced features. The `defaults` parameter provides
fallback values when source fields are missing, enabling translation from
simpler models that lack detail. The `depends_on` parameter ensures rules
execute in the correct order when target fields come from previously translated
components. The `filter` parameter references a {py:class}`~r2x_core.RuleFilter`
that restricts which source components the rule processes.

### Filter Predicates

The {py:class}`~r2x_core.RuleFilter` class provides a flexible predicate
language for component selection. Leaf filters compare a component field against
values using operations like equality, membership, numeric comparison, or prefix
matching. Compound filters combine multiple predicates with `any_of` (OR) or
`all_of` (AND) semantics.

Here are some practical filter examples:

```python
from r2x_core import RuleFilter

# Simple equality filter
filter_type_a = RuleFilter(
    field="component_type",
    operation="eq",
    values=["TypeA"]
)

# Multiple values (membership)
filter_multiple_types = RuleFilter(
    field="component_type",
    operation="in",
    values=["TypeA", "TypeB", "TypeC"]
)

# Numeric comparison - components above 100 capacity
filter_large = RuleFilter(
    field="capacity",
    operation="geq",
    values=[100.0]
)

# Prefix matching - all components starting with "Region1"
filter_region = RuleFilter(
    field="name",
    operation="startswith",
    values=["Region1"]
)

# Complex combinations
filter_large_type_a = RuleFilter(
    operation="all_of",
    predicates=[
        RuleFilter(field="component_type", operation="eq", values=["TypeA"]),
        RuleFilter(field="capacity", operation="geq", values=[50.0]),
    ]
)

# OR combinations - TypeA OR TypeB
filter_common_types = RuleFilter(
    operation="any_of",
    predicates=[
        RuleFilter(field="component_type", operation="in", values=["TypeA", "TypeB"]),
        RuleFilter(field="component_type", operation="eq", values=["TypeC"]),
    ]
)
```

The filter implementation optimizes for repeated evaluation. String values are
casefolded once during filter construction rather than on every comparison.
Prefix lists are cached in normalized form. These optimizations matter when
filtering thousands of components during a large system translation.

### Rule Execution

The {py:func}`~r2x_core.apply_rules_to_context` function orchestrates the
translation process. It first validates rules for consistency, checking for
duplicate names and unresolved dependencies. Rules are then topologically sorted
so that dependencies execute before dependents. Each rule is applied to all
matching source components, creating target components that are added to the
target system.

Here's how to apply rules to translate components:

```python
from r2x_core import apply_rules_to_context, Rule, PluginContext

# Define rules for translation
rules = [
    Rule(
        name="translate_component_type_a",
        source_type="ComponentA",
        target_type="ComponentB",
        version=1,
        field_map={
            "name": "name",
            "capacity": "capacity",
            "location": "location",
        }
    ),
    Rule(
        name="translate_component_type_b",
        source_type="NodeA",
        target_type="NodeB",
        version=1,
        field_map={
            "name": "name",
            "voltage": "voltage",
        }
    ),
]

# Apply rules within a plugin context
result = apply_rules_to_context(
    context=plugin_context,
    rules=rules,
    source_components=source_system.get_components(),
)

# Check results
if result.is_complete():
    print(f"Translation successful: {result.total_components} components")
else:
    print(f"Some translations failed:")
    for rule_result in result.rule_results:
        if rule_result.is_err():
            print(f"  {rule_result.rule_name}: {rule_result.error}")
```

For single-rule application with fine-grained control:

```python
from r2x_core import apply_single_rule

# Apply one rule to specific components
result = apply_single_rule(
    context=plugin_context,
    rule=rules[0],
    source_components=source_system.get_components()[:10],  # First 10 only
)

if result.is_ok():
    created = result.value()
    target_system.add_components(created)
```

The function returns a {py:class}`~r2x_core.TranslationResult` containing
detailed statistics. Individual rule outcomes are captured in
{py:class}`~r2x_core.RuleResult` objects, providing visibility into what
succeeded, what failed, and why. This detailed reporting enables debugging of
translation workflows and monitoring of translation quality.

### Single-Rule Application

The {py:func}`~r2x_core.apply_single_rule` function handles translation for a
single rule. It resolves source and target types, evaluates filters, builds
target field values, and creates target components. This function is useful when
you need fine-grained control over the translation process or want to apply
rules selectively outside the full workflow.

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
classes at runtime using the {py:class}`~r2x_core.PluginContext` model registry.
This late binding adds flexibility but means type errors are caught at execution
rather than definition time. The trade-off favors runtime flexibility for
configuration-driven use cases.

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
target systems, configuration, and the model registry for type resolution.
Translation plugins define rules as part of their configuration and invoke the
rule executor during the `on_translate` lifecycle hook.

This integration enables declarative plugin configuration. A translation plugin
can be fully configured through JSON files specifying rules, filters, and field
mappings. The plugin code becomes a thin wrapper that loads configuration and
invokes {py:func}`~r2x_core.apply_rules_to_context`, with all translation logic
expressed declaratively.

## Performance Considerations

The rule system is designed for large-scale translations involving thousands of
components. Rule validation and dependency sorting happen once per translation,
not per component. Filter predicates cache normalized values to avoid repeated
computation. The executor minimizes object allocation by reusing context objects
across rule applications.

For very large systems, the executor could be extended to parallelize
independent rules. The current sequential execution is sufficient for typical
use cases but the architecture does not preclude parallel execution. The
immutability of rules is actually beneficial for parallelization, as there is no
need for locking or synchronization.

## Extension Points

The rule system provides several extension points for future enhancement. Custom
filter operations could be registered to extend the predicate language. Rule
inheritance could allow base rules with shared mappings that derived rules
extend. Bidirectional rules could support round-trip translation by defining
both directions in a single specification. Transformation pipelines could
combine rules from multiple plugins. These extensions would build on the
existing architecture without fundamental changes.

## Complete Example: ReEDS to Infrasys Translation

Here's a realistic example translating ReEDS model generators and buses to an
Infrasys system:

```python
from r2x_core import (
    Rule, RuleFilter, apply_rules_to_context, PluginContext
)

# Define filters for selective translation
filter_wind = RuleFilter(field="fuel", operation="eq", values=["Wind"])
filter_large = RuleFilter(field="p_max_mw", operation="geq", values=[100.0])
filter_large_wind = RuleFilter(
    operation="all_of",
    predicates=[filter_wind, filter_large]
)

# Define translation rules
rules = [
    # Step 1: Translate all buses
    Rule(
        name="reeds_buses_to_infrasys",
        source_type="ReEDSBus",
        target_type="Bus",
        version=1,
        field_map={
            "name": "name",
            "voltage_kv": "voltage_kv",
            "region": "region",
        }
    ),

    # Step 2: Translate large wind generators (depends on buses)
    Rule(
        name="reeds_wind_generators",
        source_type="ReEDSGenerator",
        target_type="Generator",
        version=1,
        filter=filter_large_wind,  # Only generators >100MW with wind fuel
        field_map={
            "name": "name",
            "p_max_mw": "p_max_mw",
            "fuel": lambda src: "WindOnshore",
            "zone_id": "zone",
            "min_up_time": "min_online_time_minutes",
        },
        depends_on=["reeds_buses_to_infrasys"],
    ),

    # Step 3: Translate conventional generators
    Rule(
        name="reeds_thermal_generators",
        source_type="ReEDSGenerator",
        target_type="ThermalGenerator",
        version=1,
        filter=RuleFilter(
            operation="any_of",
            predicates=[
                RuleFilter(field="fuel", operation="eq", values=["Coal"]),
                RuleFilter(field="fuel", operation="eq", values=["Gas"]),
            ]
        ),
        field_map={
            "name": "name",
            "p_max_mw": "p_max_mw",
            "fuel": "fuel",
            "heat_rate_mmbtu_per_mwh": "heat_rate",
        },
        defaults={"heat_rate": 10.5},  # Default if missing
        depends_on=["reeds_buses_to_infrasys"],
    ),
]

# Apply rules in order
context = PluginContext(
    source_system=reeds_system,
    target_system=infrasys_system,
)

result = apply_rules_to_context(
    context=context,
    rules=rules,
    source_components=reeds_system.components,
)

# Examine results
for rule_result in result.rule_results:
    print(f"{rule_result.rule_name}:")
    print(f"  Components processed: {rule_result.components_processed}")
    print(f"  Successfully translated: {rule_result.components_translated}")
    if rule_result.is_err():
        print(f"  Error: {rule_result.error}")
```

This example demonstrates several key concepts: selective translation through
filters, field transformation using lambda functions, default values for missing
data, and ordered execution through dependencies. The same rule definitions could
be stored in JSON and loaded from configuration files, enabling fully declarative
translation pipelines.

## See Also

- {doc}`../how-tos/define-rule-mappings` for practical usage examples
- {doc}`./plugin-system` for understanding plugin integration
- {py:class}`~r2x_core.Rule` API reference
- {py:class}`~r2x_core.RuleFilter` API reference
- {py:func}`~r2x_core.apply_rules_to_context` API reference
- {py:class}`~r2x_core.TranslationResult` API reference
