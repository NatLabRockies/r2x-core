---
title: "Rule Filters"
---

<span id="rule-filters"></span>

A rule filter is a discriminated union of field comparisons, getter
comparisons, and composed `any_of` or `all_of` predicates. Construct a concrete
model instead of instantiating the `RuleFilter` type alias.

## Compare component fields

```python doctest
>>> from r2x_core import FieldFilter, RuleFilter
>>> active: RuleFilter = FieldFilter(field="status", op="eq", values=["active"])
>>> active.model_dump()
{'op': 'eq', 'values': ['active'], 'casefold': True, 'on_missing': 'exclude', 'kind': 'field', 'field': 'status'}
```

The supported operators are `eq`, `neq`, `in`, `not_in`, `geq`, `startswith`,
`not_startswith`, and `endswith`. String values are case-insensitive by
default. `geq` takes exactly one value. Prefix and suffix operators take string
values in the regular `values` field.

When the filter is stored as JSON, include the `kind` discriminator:

```json
{
  "kind": "field",
  "field": "fuel_type",
  "op": "eq",
  "values": ["gas"]
}
```

## Compare getter results

Use a getter when the value must be derived from translator context or another
lookup. Getter-backed filters require the active `PluginContext` when evaluated.

```python doctest
>>> from rust_ok import Ok
>>> from r2x_core import GetterFilter
>>> fuel_filter = GetterFilter(
...     getter=lambda _source, *, context: Ok(context.metadata["fuel"]),
...     op="eq",
...     values=["gas"],
... )
>>> fuel_filter.op
'eq'
```

For filters loaded from records, register a named getter and refer to it by
name. The record includes `"kind": "getter"`:

```json
{
  "kind": "getter",
  "getter": "selected_fuel_type",
  "op": "eq",
  "values": ["gas"]
}
```

## Compose filters

`AnyOfFilter` matches when at least one child matches. `AllOfFilter` requires
all children to match. Each composition needs at least one child.

```python doctest
>>> from r2x_core import AllOfFilter, AnyOfFilter, FieldFilter
>>> filter_by_fuel_or_name = AnyOfFilter(filters=[
...     FieldFilter(field="fuel_type", op="eq", values=["gas"]),
...     FieldFilter(field="name", op="startswith", values=["plant_"]),
... ])
>>> [filter_.kind for filter_ in filter_by_fuel_or_name.filters]
['field', 'field']
>>> AllOfFilter(filters=[FieldFilter(field="status", op="eq", values=["active"])]).kind
'all_of'
```

Use the composed filter directly on a rule:

```python doctest
>>> from r2x_core import AnyOfFilter, FieldFilter, Rule
>>> selected = AnyOfFilter(filters=[
...     FieldFilter(field="fuel_type", op="eq", values=["gas"]),
...     FieldFilter(field="name", op="startswith", values=["plant_"]),
... ])
>>> rule = Rule(
...     source_type="PlantComponent",
...     target_type="StationComponent",
...     version=1,
...     filter=selected,
... )
>>> rule.filter.kind
'any_of'
```

A leaf filter's `on_missing` setting controls missing-field behavior. Its
default is `"exclude"`; set it to `"include"` only when missing values should
pass the filter.
