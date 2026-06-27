# Rule Filters

Rule filters declare predicate logic that restricts which source or target components a rule will process. They can be simple leaf filters or composed with `any_of`/`all_of` to form complex selection logic.

## Leaf filters

A leaf filter must set `field`, `op`, and either `values` or `prefixes`. The `values` list works for equality, inequality, membership, and numeric comparisons:

```json
{
  "field": "fuel_type",
  "op": "eq",
  "values": ["gas"]
}
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
