# Upgrade Data Between Versions

Create and apply data upgrades to transform raw files and configurations between versions.

## Version Strategies

Choose a versioning strategy based on your needs:

```python doctest
>>> from r2x_core import SemanticVersioningStrategy, GitVersioningStrategy, VersionStrategy
>>> semantic = SemanticVersioningStrategy()
>>> type(semantic).__name__
'SemanticVersioningStrategy'
>>> commits = ["abc123", "def456", "ghi789"]
>>> git = GitVersioningStrategy(commits)
>>> type(git).__name__
'GitVersioningStrategy'
```

## Upgrade Types

Define what you want to upgrade:

```python doctest
>>> from r2x_core import UpgradeType
>>> print(UpgradeType.FILE)
UpgradeType.FILE
>>> print(UpgradeType.SYSTEM)
UpgradeType.SYSTEM
```

## Basic Upgrade Step

Create an upgrade step to transform data:

```python doctest
>>> from r2x_core import UpgradeStep, UpgradeType, SemanticVersioningStrategy, run_upgrade_step
>>> def upgrade_to_v2(data: dict) -> dict:
...     data = data.copy()
...     data["version"] = "2.0.0"
...     if "old_name" in data:
...         data["new_name"] = data.pop("old_name")
...     return data
>>> step = UpgradeStep(
...     name="upgrade_to_v2",
...     func=upgrade_to_v2,
...     target_version="2.0.0",
...     versioning_strategy=SemanticVersioningStrategy(),
...     upgrade_type=UpgradeType.FILE
... )
>>> data = {"version": "1.0.0", "old_name": "test"}
>>> result = run_upgrade_step(data, step=step)
>>> result.unwrap()["version"]
'2.0.0'
>>> result.unwrap()["new_name"]
'test'
```

## Best Practices

Always return a copy and handle missing fields:

```python doctest
>>> def safe_upgrade(data: dict) -> dict:
...     upgraded = data.copy()
...     upgraded.setdefault("new_field", "default")
...     return upgraded
>>> original = {"old": "value"}
>>> result = safe_upgrade(original)
>>> result["new_field"]
'default'
>>> original
{'old': 'value'}
```

## See Also

- {doc}`../references/upgrader` - Upgrade API reference
- {doc}`../references/versioning` - Versioning API reference
