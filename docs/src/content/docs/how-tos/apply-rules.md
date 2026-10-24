---
title: "Apply Translation Rules"
---

<span id="apply-translation-rules"></span>

Execute rules to convert components between formats.

## Translation Results

Capture statistics about rule application:

```python doctest
>>> from r2x_core import Rule, RuleResult, TranslationResult
>>> rule = Rule(source_type="Bus", target_type="Node", version=1)
>>> result = RuleResult(
...     rule=rule,
...     converted=10,
...     skipped=0,
...     success=True,
...     error=None
... )
>>> result.converted
10
>>> translation = TranslationResult(
...     total_rules=1,
...     successful_rules=1,
...     failed_rules=0,
...     total_converted=10,
...     rule_results=[result],
...     time_series_transferred=0,
...     time_series_updated=0
... )
>>> translation.success
True
>>> translation.total_converted
10
```

## Apply All Rules

Use `apply_rules_to_context()` to apply all rules in a context:

This independent example supplies both systems, the model module and one named component.
It tests the executor with generic components rather than requiring an external model dataset.

```python doctest
>>> from infrasys import Component
>>> from r2x_core import PluginConfig, PluginContext, Rule, System, apply_single_rule, apply_rules_to_context
>>> source = System(name="source")
>>> target = System(name="target")
>>> source.add_component(Component(name="Alpha"))
>>> rule = Rule(source_type="Component", target_type="Component", version=1, field_map={"name": "name"})
>>> context = PluginContext(config=PluginConfig(models=("infrasys",)), source_system=source, target_system=target, rules=(rule,))
>>> result = apply_rules_to_context(context)
>>> # Expected: one rule successfully converts one generic component.
>>> result.success, result.total_converted
(True, 1)
>>> sorted(item.name for item in target.get_components(Component))
['Alpha']
```

## Apply Single Rule

Use `apply_single_rule()` to apply one rule:

```python doctest
>>> from infrasys import Component
>>> from r2x_core import PluginConfig, PluginContext, Rule, System, apply_single_rule, apply_rules_to_context
>>> source = System(name="source")
>>> target = System(name="target")
>>> source.add_component(Component(name="Alpha"))
>>> rule = Rule(source_type="Component", target_type="Component", version=1, field_map={"name": "name"})
>>> context = PluginContext(config=PluginConfig(models=("infrasys",)), source_system=source, target_system=target, rules=(rule,))
>>> result = apply_single_rule(rule, context=context)
>>> # Expected: the single-rule result records one constructed component.
>>> result.unwrap().converted
1
>>> sorted(item.name for item in target.get_components(Component))
['Alpha']
```

## Attachment rollback

Each rule-output attachment rolls back its attached outputs if attachment fails. For a component primary, rollback removes only newly stored components in that primary's composed graph. Components already present in the target system and their existing state are preserved. Cleanup failures are surfaced with the original attachment failure.

This is not a transaction over an entire rule, translation, or arbitrary callback side effects. A callback-created reference can prevent removal, in which case the affected graph branch is retained and the cleanup failure is reported. infrasys does not currently index every nested composed-component association, and r2x-core does not rebuild those indexes. Direct association behavior remains available, but nested association indexing is not guaranteed.

## See Also

- [create rules](/r2x-core/how-tos/create-rules/) - Creating rules
- [define rule mappings](/r2x-core/how-tos/define-rule-mappings/) - Rules overview and filter patterns
