# r2x-core Versioning and Upgrades Reference

Use this when detecting dataset versions or applying schema/data migrations with
`UpgradeStep` chains.

## Contracts (source-verified)

- `VersionStrategy.compare_versions(current, *, target) -> int`
- `VersionReader.read_version(folder_path: Path) -> str | None` (protocol)
- `UpgradeStep(name, func, target_version, upgrade_type, priority=100, min_version=None, max_version=None)`
- `run_upgrade_step(data, *, step: UpgradeStep, upgrader_context=None) -> Result[Any, str]`
- `shall_we_upgrade(step, *, current_version, strategy) -> Result[bool, UpgradeError]` lives in `r2x_core.utils`, not top-level `r2x_core`.

## Do

- Detect the current version before applying upgrades.
- Use a `VersionStrategy` matching the dataset version scheme.
- Gate steps with `shall_we_upgrade(...)` or equivalent `target_version`,
  `min_version`, and `max_version` checks.
- Keep steps small and idempotent.
- Let upgrade functions accept `upgrader_context` only when they need it.
- Treat `run_upgrade_step(...)` failures as `Err(...)` result values.

## Don't

- Do not instantiate `VersionReader(strategy=...)`; implement the protocol.
- Do not define `UpgradeStep(from_version=..., to_version=...)`; use
  `target_version`, optional `min_version`, and optional `max_version`.
- Do not call `run_upgrade_step(step, payload)`.
- Do not sort only by `priority` and ignore version guards.
- Do not use semver suffixes unless source has added support; current semantic
  comparison expects numeric dot components.

## Detecting the source version

```python
from pathlib import Path

from r2x_core import VersionReader


class MarkerFileVersionReader(VersionReader):
    def read_version(self, folder_path: Path) -> str | None:
        marker = folder_path / ".version"
        if not marker.exists():
            return None
        return marker.read_text(encoding="utf-8").strip()


reader = MarkerFileVersionReader()
current_version = reader.read_version(Path("/data/reeds"))
```

## Defining an upgrade step

```python
from r2x_core import UpgradeStep, UpgradeType

rename_capacity_field = UpgradeStep(
    name="rename_capacity_field",
    target_version="2.0.0",
    upgrade_type=UpgradeType.FILE,
    min_version="1.0.0",
    max_version="1.9.99",
    func=lambda payload: _rename(payload, "cap_mw", "capacity_mw"),
)
```

Step requirements:

- Idempotent: running twice yields the same result.
- Pure where practical: take payload, return payload.
- Constrained: set `min_version` / `max_version` when a step only applies to a
  version range.

## Running one step

```python
from r2x_core import run_upgrade_step

result = run_upgrade_step(payload, step=rename_capacity_field)
if result.is_err():
    raise RuntimeError(result.err())
payload = result.ok()
```

`run_upgrade_step(...)` catches exceptions and returns `Err("Failed <step>: ...")`.
It passes `upgrader_context=` only when the step function accepts an
`upgrader_context` parameter or `**kwargs`.

## Chaining upgrades

Use `shall_we_upgrade(...)` from `r2x_core.utils` to respect `target_version`,
`min_version`, and `max_version`. It returns `Result[bool, UpgradeError]`.

```python
from r2x_core import UpgradeError, run_upgrade_step
from r2x_core.utils import shall_we_upgrade


def upgrade_chain(steps, payload, current_version, strategy, upgrader_context=None):
    ordered = sorted(steps, key=lambda step: (step.target_version, step.priority))

    for step in ordered:
        decision = shall_we_upgrade(step, current_version=current_version, strategy=strategy)
        if decision.is_err():
            raise UpgradeError(decision.err())
        if not decision.ok():
            continue

        result = run_upgrade_step(
            payload,
            step=step,
            upgrader_context=upgrader_context,
        )
        if result.is_err():
            raise UpgradeError(result.err())

        payload = result.ok()
        current_version = step.target_version

    return payload
```

If the strategy is not lexical/semver-compatible with sorting by target string,
use strategy-aware ordering from the caller or an explicit ordered list. Priority
alone is not a version gate.

## Coordinating with infrasys

Use r2x-core `UpgradeStep` chains for non-`System` artifacts such as DataStore
JSON layouts, plugin config files, and intermediate representations.

For serialized `System` schema changes, prefer infrasys migration hooks:

- Subclass hook: `handle_data_format_upgrade(self, data, from_version, to_version)`.
- Composition hook: `System.from_json(path, upgrade_handler=fn)`.

If the `infrasys` skill is unavailable, verify against infrasys docs/source.

## Failure playbook

- `VersionReader` returns an unexpected version:
  - Confirm the marker file/source and `VersionStrategy` match the dataset.
- Step applied to the wrong version:
  - Add or fix `min_version` / `max_version`; use `shall_we_upgrade(...)`.
- Upgrade function needs context but receives none:
  - Add an `upgrader_context` parameter and pass context to
    `run_upgrade_step(...)`.
- Step fails midway:
  - Inspect `result.err()`. Do not retry without checking idempotency and
    partial mutation state.
- `System.from_json` fails after r2x-core upgrades:
  - Route the serialized system schema change through infrasys migration.

## Output expectations

- Detected source version and strategy.
- Ordered upgrade steps considered and applied/skipped.
- Version guards used (`target_version`, `min_version`, `max_version`).
- Per-step `Ok` / `Err` outcome.
- Whether infrasys-side migration was also required.
