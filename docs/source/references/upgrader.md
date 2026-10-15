# Upgrade steps

`UpgradeStep` describes a callable transformation and its target version.
Its required fields are `name`, `func`, `target_version`, and `upgrade_type`.
`priority` defaults to `100`; `min_version` and `max_version` default to `None`.
`UpgradeType` has two values: `FILE` for file operations and `SYSTEM` for system changes.
See [api](/r2x-core/references/api/) for generated types and the pinned source link.

## Execute a step

`run_upgrade_step(data, *, step, upgrader_context=None)` returns `Result[Any, str]`.
It invokes `step.func(data)`, passing `upgrader_context` when the callable accepts it.
The helper returns `Ok(transformed_data)` on success or `Err("Failed ...")` if the callable raises an exception.
It does not roll back mutations or filesystem writes and does not itself compare versions.

```python
from r2x_core import System, UpgradeStep, run_upgrade_step
from r2x_core.utils import UpgradeType


def rename(system: System) -> System:
    system.name = "upgraded"
    return system


step = UpgradeStep(
    name="rename",
    func=rename,
    target_version="2.0.0",
    upgrade_type=UpgradeType.SYSTEM,
)
result = run_upgrade_step(System(name="original"), step=step)
assert result.is_ok()
assert result.unwrap().name == "upgraded"
```

Run the example in the project environment from [install](/r2x-core/install/).
Version selection belongs to the upgrade coordinator and its version strategy.
Inspect [versioning](/r2x-core/references/versioning/) before composing multiple version transitions.
