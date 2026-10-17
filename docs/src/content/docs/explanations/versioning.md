---
title: "Data schema upgrades"
---

<span id="the-problem-we-solve"></span>

A data version describes the input schema or model state, independently of the installed package version.
An upgrade step transforms that state toward a named target version.
Keeping the transformation separate from version selection makes each step easier to exercise on a small input.

<span id="version-comparison-strategies"></span>

<span id="staged-upgrades-vs-monolithic-upgrades"></span>

<span id="staged-approach-maintainable"></span>

## Selection and execution are separate

<span id="file-vs-system-upgrades"></span>

<span id="file-upgrades-most-common"></span>

<span id="system-upgrades-less-common"></span>

`UpgradeStep` records a callable, a target version, its `FILE` or `SYSTEM` category, an optional version range, and a priority.
<span id="version-ranges-and-upgrade-applicability"></span>

A version strategy compares the current version with the target and range constraints.
<span id="semantic-versioning-most-common"></span>

<span id="git-based-versioning"></span>

<span id="custom-strategies"></span>

Semantic versions and ordered Git histories need different comparison rules; see [versioning](/r2x-core/references/versioning/) for those contracts.

`run_upgrade_step(data, *, step, upgrader_context=None)` only invokes a selected transformation.
It returns `Ok(data)` on success. For an `UpgradeError`, `OSError`, or `ValueError` raised by the transformation, it returns `Err(UpgradeError(...))` and retains the original exception as its cause.
Unexpected programming errors such as `TypeError` propagate to the caller.
It does not select steps, compare versions, sort priorities, or roll back a partially completed transformation.
<span id="priority-and-execution-order"></span>

<span id="why-priority-instead-of-dependency-graphs"></span>

Those decisions belong to the caller or the model package's upgrade coordinator.

<span id="monolithic-approach-fragile"></span>

<span id="design-trade-offs"></span>

<span id="why-not-just-update-all-data-upfront"></span>

## Mutation and recovery

A callable can mutate its input or write files before raising an exception.
Returning an expected failure in `Err` does not undo those changes; neither does propagating an unexpected exception.
Design file upgrades around copies or explicit backups when recovery is required, and test a step against a small fixture before applying it to a full dataset.

<span id="real-world-example"></span>

<span id="see-also"></span>

See [upgrader](/r2x-core/references/upgrader/) for a complete executable step and [upgrade data files](/r2x-core/how-tos/upgrade-data-files/) for data upgrade examples.
