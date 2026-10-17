---
title: "Data schema upgrades"
---

A data version describes the input schema or model state, independently of the installed package version.
An upgrade step transforms that state toward a named target version.
Keeping the transformation separate from version selection makes each step easier to exercise on a small input.

## Selection and execution are separate

`UpgradeStep` records a callable, a target version, its `FILE` or `SYSTEM` category, an optional version range, and a priority.
A version strategy compares the current version with the target and range constraints.
Semantic versions and ordered Git histories need different comparison rules; see [versioning](/r2x-core/references/versioning/) for those contracts.

`run_upgrade_step(data, *, step, upgrader_context=None)` only invokes a selected transformation.
It returns `Ok(data)` on success. For an `UpgradeError`, `OSError`, or `ValueError` raised by the transformation, it returns `Err(UpgradeError(...))` and retains the original exception as its cause.
Unexpected programming errors such as `TypeError` propagate to the caller.
It does not select steps, compare versions, sort priorities, or roll back a partially completed transformation.
Those decisions belong to the caller or the model package's upgrade coordinator.

## Mutation and recovery

A callable can mutate its input or write files before raising an exception.
Returning an expected failure in `Err` does not undo those changes; neither does propagating an unexpected exception.
Design file upgrades around copies or explicit backups when recovery is required, and test a step against a small fixture before applying it to a full dataset.

See [upgrader](/r2x-core/references/upgrader/) for a complete executable step and [upgrade data files](/r2x-core/how-tos/upgrade-data-files/) for data upgrade examples.
