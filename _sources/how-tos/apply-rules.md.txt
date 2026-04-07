# Apply Translation Rules

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

```python doctest
>>> from r2x_core import apply_rules_to_context
>>> # result = apply_rules_to_context(context)
>>> # result.total_converted
```

## Apply Single Rule

Use `apply_single_rule()` to apply one rule:

```python doctest
>>> from r2x_core import apply_single_rule, Rule
>>> rule = Rule(source_type="Gen", target_type="Unit", version=1)
>>> # result = apply_single_rule(rule, context=context)
```

## See Also

- {doc}`create-rules` - Creating rules
- {doc}`define-rule-mappings` - Rules overview and filter patterns
