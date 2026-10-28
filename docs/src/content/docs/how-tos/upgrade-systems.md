---
title: "Upgrade Systems Between Versions"
---

<span id="upgrade-systems-between-versions"></span>

r2x-core provides a framework for defining version upgrades using [`UpgradeStep`](/r2x-core/references/api/) and [`UpgradeType`](/r2x-core/references/api/). Upgrades are staged to handle both raw data files and system objects.

## Understand Upgrade Types

r2x-core supports two types of upgrades through [`UpgradeType`](/r2x-core/references/api/):

```python doctest
>>> from r2x_core import UpgradeType
>>>
>>> # FILE: Upgrade raw data files before loading into a system
>>> UpgradeType.FILE
# <UpgradeType.FILE: 'FILE'>
>>>
>>> # SYSTEM: Upgrade already-loaded System objects
>>> UpgradeType.SYSTEM
# <UpgradeType.SYSTEM: 'SYSTEM'>
```

**FILE upgrades** are useful when the data format or schema changes between versions. **SYSTEM upgrades** are useful when the system model structure changes.

## Inspect Upgrade Configuration

View the [`UpgradeStep`](/r2x-core/references/api/) structure to understand how upgrades are defined:

```python doctest
>>> from r2x_core import UpgradeStep, UpgradeType
>>>
>>> # Create an example upgrade step definition
>>> class_name = UpgradeStep.__name__
>>> print(f"Upgrade step class: {class_name}")
# Upgrade step class: UpgradeStep
```

## Execute a single step

Define the transformation and execute it against a small system before using it in a workflow.
This example checks the returned result and changed system name:

```python doctest
>>> from r2x_core import System, UpgradeStep, UpgradeType, run_upgrade_step
>>> def rename(system: System) -> System:
...     system.name = "upgraded"
...     return system
>>> step = UpgradeStep(name="rename", func=rename, target_version="2.0.0", upgrade_type=UpgradeType.SYSTEM)
>>> result = run_upgrade_step(System(name="original"), step=step)
>>> result.is_ok()
# True
>>> result.unwrap().name
# 'upgraded'
```
Selection, version comparison, and rollback are separate concerns. See the [upgrade error contract](/r2x-core/references/upgrader/).

## See Also

- [upgrade data files](/r2x-core/how-tos/upgrade-data-files/) - Upgrade raw data files between versions
- [manage versions](/r2x-core/how-tos/manage-versions/) - Version management strategies
- [`UpgradeStep`](/r2x-core/references/api/) - Upgrade step configuration
- [`UpgradeType`](/r2x-core/references/api/) - Upgrade type enumeration
- [`run_upgrade_step`](/r2x-core/references/api/) - Execute upgrade steps
