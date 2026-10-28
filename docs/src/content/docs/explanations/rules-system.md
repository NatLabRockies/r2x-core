---
title: "Why rules describe translation contracts"
---

<span id="rule-system-architecture"></span>

A `Rule` separates the mapping between component schemas from the mechanics of
finding source components and constructing target components. Model packages
still define those schemas and the physical meaning of mapped values.
A syntactically valid mapping does not establish scientific equivalence.

## Match fields explicitly

`source_type` and `target_type` identify component classes, and `field_map`
associates source field names with target field names. Filters restrict the
source population; defaults supply configured fallback values.
Use the [rule guides](/r2x-core/how-tos/define-rule-mappings/) for their precise syntax.

## A minimal complete translation

This example deliberately uses the generic `infrasys.Component` on both sides,
so it needs no ReEDS, PLEXOS or Sienna classes. It checks execution and the target
name rather than pretending to translate a real model's electrical fields.

```python doctest
>>> from infrasys import Component
>>> from r2x_core import PluginConfig, PluginContext, Rule, System, apply_single_rule
>>> source = System(name="source")
>>> target = System(name="target")
>>> source.add_component(Component(name="Alpha"))
>>> rule = Rule(source_type="Component", target_type="Component", version=1, field_map={"name": "name"})
>>> context = PluginContext(config=PluginConfig(models=("infrasys",)), source_system=source, target_system=target, rules=(rule,))
>>> result = apply_single_rule(rule, context=context)
>>> # Expected: one matched source component becomes one named target component.
>>> result.unwrap().converted
# 1
>>> sorted(component.name for component in target.get_components(Component))
# ['Alpha']
```

## Resolve types within a model configuration

The executor resolves named classes through the configured `models` modules.
Keeping resolution scoped to those modules prevents a class from another model
configuration being selected merely because its name matches.
Missing classes, fields and incompatible values need a specific correction;
they are not repaired by changing a type name in serialized metadata.

## Keep unit conversion and validation visible

A field mapping describes which values feed the target model. It is not a
universal unit or calendar converter. Use typed component constraints and
explicit getters/transforms for those operations, then verify target invariants.
See [rule filters](/r2x-core/how-tos/create-rule-filters/),
[apply rules](/r2x-core/how-tos/apply-rules/) and
[workflow boundaries](/r2x-core/explanations/workflow-boundaries/).

<span id="purpose-and-motivation"></span>

<span id="core-design-principles"></span>

<span id="declarative-over-imperative"></span>

<span id="composition-through-filters"></span>

<span id="immutability-for-correctness"></span>

<span id="architecture-overview"></span>

<span id="rule-definition"></span>

<span id="filter-predicates"></span>

<span id="rule-execution"></span>

<span id="single-rule-application"></span>

<span id="design-trade-offs"></span>

<span id="why-frozen-dataclasses"></span>

<span id="why-string-based-type-references"></span>

<span id="why-separate-filters-from-rules"></span>

<span id="integration-with-plugin-system"></span>

<span id="performance-considerations"></span>

<span id="extension-points"></span>

<span id="complete-example-reeds-to-infrasys-translation"></span>

<span id="see-also"></span>
