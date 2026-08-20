# Upgrade Systems Between Versions

R2X Core provides a framework for defining version upgrades using {py:class}`~r2x_core.UpgradeStep` and {py:class}`~r2x_core.UpgradeType`. Upgrades are staged to handle both raw data files and system objects.

## Understand Upgrade Types

R2X Core supports two types of upgrades through {py:class}`~r2x_core.UpgradeType`:

```python doctest
>>> from r2x_core import UpgradeType
>>>
>>> # FILE: Upgrade raw data files before loading into a system
>>> UpgradeType.FILE
<UpgradeType.FILE: 'FILE'>
>>>
>>> # SYSTEM: Upgrade already-loaded System objects
>>> UpgradeType.SYSTEM
<UpgradeType.SYSTEM: 'SYSTEM'>
```

**FILE upgrades** are useful when the data format or schema changes between versions. **SYSTEM upgrades** are useful when the system model structure changes.

## Inspect Upgrade Configuration

View the {py:class}`~r2x_core.UpgradeStep` structure to understand how upgrades are defined:

```python doctest
>>> from r2x_core import UpgradeStep, UpgradeType
>>>
>>> # Create an example upgrade step definition
>>> class_name = UpgradeStep.__name__
>>> print(f"Upgrade step class: {class_name}")
Upgrade step class: UpgradeStep
```

## See Also

- {doc}`upgrade-data-files` - Upgrade raw data files between versions
- {doc}`manage-versions` - Version management strategies
- {py:class}`~r2x_core.UpgradeStep` - Upgrade step configuration
- {py:class}`~r2x_core.UpgradeType` - Upgrade type enumeration
- {py:func}`~r2x_core.run_upgrade_step` - Execute upgrade steps
