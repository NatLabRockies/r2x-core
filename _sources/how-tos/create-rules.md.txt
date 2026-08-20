# Create Translation Rules

Rules describe how to convert components from one model format to another.

## Basic Rule

```python doctest
>>> from r2x_core import Rule
>>> rule = Rule(
...     source_type="Bus",
...     target_type="Node",
...     version=1,
...     field_map={"name": "name", "kv_rating": "voltage_kv"}
... )
>>> rule.source_type
'Bus'
>>> rule.version
1
```

## With Default Values

Provide defaults for fields that may be missing in source components:

```python doctest
>>> from r2x_core import Rule
>>> rule = Rule(
...     source_type="Generator",
...     target_type="ThermalUnit",
...     version=1,
...     field_map={"name": "name"},
...     defaults={"zone": "unspecified"}
... )
>>> rule.defaults
{'zone': 'unspecified'}
```

## From Records

Load multiple rules from a list of dictionaries:

```python doctest
>>> from r2x_core import Rule
>>> records = [
...     {"source_type": "Bus", "target_type": "Node", "version": 1},
...     {"source_type": "Generator", "target_type": "Unit", "version": 1}
... ]
>>> rules = Rule.from_records(records)
>>> len(rules)
2
```

## See Also

- {doc}`define-rule-mappings` - Rules overview and definitions
- {doc}`apply-rules` - Apply rules to contexts
