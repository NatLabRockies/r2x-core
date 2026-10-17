# Upgrade steps

`UpgradeStep` describes a callable transformation and its target version.
Its required fields are `name`, `func`, `target_version`, and `upgrade_type`.
`priority` defaults to `100`; `min_version` and `max_version` default to `None`.
`UpgradeType` has two values: `FILE` for file operations and `SYSTEM` for system changes.
See [api](/r2x-core/references/api/) for generated types and the pinned source link.

## Execute a step

`run_upgrade_step(data, *, step, upgrader_context=None)` returns `Result[Any, UpgradeError]`.
It invokes `step.func(data)`, passing `upgrader_context` when the callable accepts it.
The helper returns `Ok(transformed_data)` on success.
An `UpgradeError`, `OSError`, or `ValueError` raised by the transformation returns `Err(UpgradeError(...))`, with the original exception retained as `result.error.__cause__`.
Other exceptions, including `TypeError`, propagate to the caller instead of becoming an `Err`.
It does not roll back mutations or filesystem writes and does not itself compare versions.

For a checked runnable example, see [execute a single system upgrade](/r2x-core/how-tos/upgrade-systems/#execute-a-single-step).


Run the example in the project environment from [install](/r2x-core/install/).
Version selection belongs to the upgrade coordinator and its version strategy.
Inspect [versioning](/r2x-core/references/versioning/) before composing multiple version transitions.
