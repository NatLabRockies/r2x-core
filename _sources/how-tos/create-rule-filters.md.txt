# Rule Filters

Rule filters declare predicate logic that restricts which source or target components a rule will process. They can be simple leaf filters or composed with `any_of`/`all_of` to form complex selection logic.

## Leaf filters

A leaf filter must set either `field` or `getter`, plus `op`, and either `values` or `prefixes`. Use `field` when the candidate value lives directly on the source component. Use `getter` when the candidate must be computed from the source component and `PluginContext`. Getter values are typically registered `@getter` names, and the loader also accepts dotted attribute paths for simple lookups.

Field-backed example:

```json
{
  "field": "fuel_type",
  "op": "eq",
  "values": ["gas"]
}
```

Getter-backed example:

```json
{
  "getter": "selected_fuel_type",
  "op": "eq",
  "values": ["gas"]
}
```

When evaluating getter-backed filters, the executor passes the current `PluginContext` into the getter so the candidate value can depend on translator state. Use this shape when the choice depends on translator metadata, supplemental attributes, or other source-system lookups that are not present as a direct source field.

### Loading getter-backed filters from records

If you load rules from JSON or another record format, store the getter name in the filter record and make sure the matching `@getter` has been registered before loading:

```python
>>> from r2x_core import Rule
>>> from r2x_core.getters import getter
>>>
>>> @getter
... def selected_fuel_type(source, *, context):
...     return context.metadata["selected_fuel_type"]
>>>
>>> rules = Rule.from_records([
...     {
...         "source_type": "PlantComponent",
...         "target_type": "StationComponent",
...         "version": 1,
...         "field_map": {"name": "name"},
...         "filter": {
...             "getter": "selected_fuel_type",
...             "op": "eq",
...             "values": ["gas"],
...         },
...     }
... ])
```

Case-insensitive matching is the default; the `casefold` flag controls whether string inputs are normalized.

## Prefix-aware filters

Operators `startswith` and `not_startswith` compare a component attribute against string prefixes. Because these comparisons require literal strings, you must supply them via the `prefixes` field:

```json
{
  "field": "name",
  "op": "startswith",
  "prefixes": ["plant_", "station_"]
}
```

`prefixes` accepts only strings and is automatically casefolded when `casefold` is true. Internally the filter keeps a cached, normalized list for repeated evaluations so the operation stays fast even on large systems.

To negate the match, use `not_startswith`:

```json
{
  "field": "name",
  "op": "not_startswith",
  "prefixes": ["deprecated_"]
}
```

## Composing filters

Combine filters with `any_of`/`all_of` to express more subtle constraints:

```json
{
  "any_of": [
    {
      "field": "fuel_type",
      "op": "eq",
      "values": ["gas"]
    },
    {
      "field": "name",
      "op": "startswith",
      "prefixes": ["plant_"]
    }
  ]
}
```

When the filter is attached to a `Rule`, the executor evaluates components lazily, so prefix-based filters only touch the components that make it past earlier predicates.
