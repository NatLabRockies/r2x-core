# Working with Rules

The rule system provides declarative component translation between power system models. Rather than writing procedural conversion code, you describe transformations through {py:class}`~r2x_core.Rule` objects that specify source types, target types, and field mappings. The rule executor handles the mechanics of applying rules to systems.

## Create a Basic Rule

A {py:class}`~r2x_core.Rule` defines how to convert components from one type to another. The `source_type` and `target_type` specify which component classes to match and produce. The `field_map` dictionary describes how source fields become target fields.

```python doctest
>>> from r2x_core import Rule

>>> rule = Rule(
...     source_type="BusComponent",
...     target_type="NodeComponent",
...     version=1,
...     field_map={"name": "name", "kv_rating": "voltage_kv"},
... )
>>> rule.source_type
'BusComponent'
>>> rule.target_type
'NodeComponent'
>>> rule.version
1
```

The `version` field supports schema evolution. When source or target formats change, you can create new rule versions while maintaining compatibility with older data.

## Field Mapping with Defaults

When source components may be missing certain fields, the `defaults` parameter provides fallback values. This is particularly useful when translating from simpler models that lack fields required by more detailed target models.

```python doctest
>>> from r2x_core import Rule

>>> rule = Rule(
...     source_type="Generator",
...     target_type="ThermalUnit",
...     version=1,
...     field_map={"name": "name", "capacity": "rating", "zone": "area"},
...     defaults={"zone": "unspecified"},
... )
>>> rule.defaults
{'zone': 'unspecified'}
```

Defaults are applied only when the source component lacks the specified field. If the source has a value, it takes precedence over the default.

## Filter Components Before Translation

The {py:class}`~r2x_core.RuleFilter` class restricts which components a rule processes. Rather than embedding conditional logic in procedural code, you declare predicates that the rule executor evaluates.

```python doctest
>>> from r2x_core import Rule, RuleFilter

>>> # Only translate generators with status "active"
>>> rule = Rule(
...     source_type="Generator",
...     target_type="ThermalUnit",
...     version=1,
...     field_map={"name": "name"},
...     filter=RuleFilter(field="status", op="eq", values=["active"]),
... )
>>> rule.filter.field
'status'
>>> rule.filter.op
'eq'
```

Filters are evaluated before translation begins, so components that don't match are skipped entirely. This improves performance when only a subset of components needs translation.

## RuleFilter Operations

The {py:class}`~r2x_core.RuleFilter` class supports several comparison operations. String comparisons are case-insensitive by default, which handles the common case of inconsistent capitalization in source data.

```python doctest
>>> from types import SimpleNamespace
>>> from r2x_core import RuleFilter

>>> component = SimpleNamespace(name="Alpha", status="ok", count=5)

>>> # Equality check (case-insensitive)
>>> eq_filter = RuleFilter(field="name", op="eq", values=["alpha"])
>>> eq_filter.matches(component)
True

>>> # Not equal
>>> neq_filter = RuleFilter(field="status", op="neq", values=["failed"])
>>> neq_filter.matches(component)
True

>>> # In list
>>> in_filter = RuleFilter(field="name", op="in", values=["alpha", "beta"])
>>> in_filter.matches(component)
True

>>> # Greater than or equal
>>> geq_filter = RuleFilter(field="count", op="geq", values=[3])
>>> geq_filter.matches(component)
True
```

Numeric comparisons like `geq`, `leq`, `gt`, and `lt` require exactly one value in the `values` list. The filter validates this constraint during construction.

## Handle Missing Fields

The `on_missing` parameter controls filter behavior when a component lacks the filtered field. This is important for handling heterogeneous source data where some components have optional attributes.

```python doctest
>>> from types import SimpleNamespace
>>> from r2x_core import RuleFilter

>>> component = SimpleNamespace(name="Test")  # No 'status' field

>>> # Include component when field is missing
>>> filter_include = RuleFilter(
...     field="status",
...     op="eq",
...     values=["active"],
...     on_missing="include",
... )
>>> filter_include.matches(component)
True

>>> # Exclude component when field is missing (default)
>>> filter_exclude = RuleFilter(
...     field="status",
...     op="eq",
...     values=["active"],
...     on_missing="exclude",
... )
>>> filter_exclude.matches(component)
False
```

The default `on_missing="exclude"` behavior is conservative, ensuring that components without the required field are not accidentally included.

## Create Rules from Records

The {py:meth}`~r2x_core.Rule.from_records` class method creates rules from dictionary configurations. This enables loading rules from JSON files, databases, or other configuration sources.

```python doctest
>>> from r2x_core import Rule

>>> records = [
...     {
...         "source_type": "Bus",
...         "target_type": "Node",
...         "version": 1,
...         "field_map": {"name": "name", "voltage": "voltage_kv"},
...     },
...     {
...         "source_type": "Generator",
...         "target_type": "Unit",
...         "version": 1,
...         "field_map": {"name": "name"},
...     },
... ]
>>> rules = Rule.from_records(records)
>>> len(rules)
2
>>> rules[0].source_type
'Bus'
```

The method validates each record and raises :exc:`~pydantic.ValidationError` if required fields are missing or have invalid types.

## Rules Are Immutable

{py:class}`~r2x_core.Rule` instances are frozen dataclasses. This immutability prevents subtle bugs where shared rules are accidentally modified during translation, causing unexpected behavior in seemingly unrelated operations.

```python doctest
>>> from r2x_core import Rule

>>> rule = Rule(source_type="A", target_type="B", version=1)
>>> try:
...     rule.version = 2
... except Exception as e:
...     "FrozenInstanceError" in type(e).__name__
True
```

If you need a modified rule, create a new instance with the changed values. This explicit approach makes changes visible and prevents accidental mutation.

## Check Rule Properties

{py:class}`~r2x_core.Rule` provides helper methods for inspecting rule configuration. These are useful when building generic translation logic that needs to handle both single and multiple source/target scenarios.

```python doctest
>>> from r2x_core import Rule

>>> # Single source, multiple targets
>>> rule = Rule(source_type="Gen", target_type=["Thermal", "Renewable"], version=1)
>>> rule.get_source_types()
['Gen']
>>> rule.get_target_types()
['Thermal', 'Renewable']
>>> rule.has_multiple_targets()
True
>>> rule.has_multiple_sources()
False
```

Multiple targets are useful when a single source component should create multiple target components, such as splitting a combined generator into separate thermal and renewable units.

## Translation Results

The {py:func}`~r2x_core.apply_rules_to_context` function returns a {py:class}`~r2x_core.TranslationResult` containing detailed statistics about the translation. Individual rule outcomes are captured in {py:class}`~r2x_core.RuleResult` objects.

```python doctest
>>> from r2x_core import Rule, RuleResult, TranslationResult

>>> # RuleResult captures per-rule statistics
>>> rule = Rule(source_type="A", target_type="B", version=1)
>>> result = RuleResult(
...     rule=rule,
...     converted=10,
...     skipped=2,
...     success=True,
...     error=None,
... )
>>> result.converted
10
>>> result.success
True

>>> # TranslationResult aggregates all rule results
>>> translation = TranslationResult(
...     total_rules=1,
...     successful_rules=1,
...     failed_rules=0,
...     total_converted=10,
...     rule_results=[result],
...     time_series_transferred=5,
...     time_series_updated=2,
... )
>>> translation.success
True
>>> translation.total_converted
10
```

The {py:meth}`~r2x_core.TranslationResult.summary` method prints a formatted table of results, useful for logging and debugging translation workflows.

## Apply Rules to a Context

Use {py:func}`~r2x_core.apply_rules_to_context` to apply all rules in a translation context:

```python doctest
>>> from r2x_core import Rule, apply_rules_to_context
>>> # rules = [rule1, rule2, rule3]
>>> # context = TranslationContext(rules=rules, source_components=[...])
>>> # result = apply_rules_to_context(context)
>>> # result.total_converted contains the total number of components converted
```

## Apply a Single Rule

Apply one rule at a time using {py:func}`~r2x_core.apply_single_rule`:

```python doctest
>>> from r2x_core import Rule, apply_single_rule
>>> rule = Rule(source_type="Gen", target_type="Unit", version=1, field_map={"name": "name"})
>>> # result = apply_single_rule(rule, source_components=[...])
>>> # result.converted contains how many components were translated by this rule
```

## See Also

- {doc}`../explanations/rules-system` for understanding rule system design decisions
- {doc}`create-rule-filters` for advanced filter composition patterns
- {doc}`./manage-versions` for handling rule versions
- {py:class}`~r2x_core.Rule` API reference
- {py:class}`~r2x_core.RuleFilter` API reference
- {py:func}`~r2x_core.apply_rules_to_context` API reference
- {py:func}`~r2x_core.apply_single_rule` API reference
