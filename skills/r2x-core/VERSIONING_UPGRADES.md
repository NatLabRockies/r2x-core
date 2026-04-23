# r2x-core Versioning and Upgrades Reference

Use this document when the task is about detecting dataset versions and
applying schema migrations through `UpgradeStep` chains.

## Scope in this skill

This reference covers:

- `VersionStrategy` interface and built-in implementations
  (`SemanticVersioningStrategy`, `GitVersioningStrategy`)
- `VersionReader` for detecting on-disk dataset version
- `UpgradeStep`, `UpgradeType`, and `run_upgrade_step`
- Composing deterministic upgrade chains
- Coordination with infrasys `handle_data_format_upgrade` for `System`
  schema changes

## Mental model

- **Detect version first.** Always determine the source version with a
  `VersionReader` and a `VersionStrategy` before applying upgrades.
- **Each `UpgradeStep` is small and idempotent.** Steps must be safe to
  re-run without changing the result.
- **Strategies decide ordering.** A `SemanticVersioningStrategy` orders
  steps by semver; a `GitVersioningStrategy` orders by commit ancestry.
- **r2x-core upgrades operate on r2x-core artifacts** (DataStore layouts,
  plugin config files, intermediate caches). For `System` JSON schema
  upgrades, defer to infrasys (`handle_data_format_upgrade`,
  `upgrade_handler` on `from_json`).

## Detecting the source version

```python
from r2x_core import VersionReader, SemanticVersioningStrategy

strategy = SemanticVersioningStrategy()
reader = VersionReader(strategy=strategy)
current_version = reader.read("/data/reeds")
```

(Constructor signatures track the installed package; confirm against
`r2x_core.versioning` source.)

## Defining an upgrade step

```python
from r2x_core import UpgradeStep, UpgradeType

rename_capacity_field = UpgradeStep(
    name="rename_capacity_field",
    from_version="1.0.0",
    to_version="2.0.0",
    upgrade_type=UpgradeType.SCHEMA,
    func=lambda payload: _rename(payload, "cap_mw", "capacity_mw"),
)
```

Step requirements:

- Idempotent: running twice yields the same result.
- Pure where possible: take payload, return payload (or mutate
  deterministically and return).
- Gated on `from_version`; do not silently apply to unrelated versions.

## Running an upgrade

```python
from r2x_core import run_upgrade_step

result = run_upgrade_step(rename_capacity_field, payload)
```

Returns a `Result`. On `Err`, do not retry blindly; surface the error and
abort the chain.

## Chaining upgrades

Walk steps in strategy-defined order from `current_version` to the target
version:

```python
def upgrade_chain(steps, payload, current, target, strategy):
    ordered = strategy.order_steps(steps, frm=current, to=target)
    for step in ordered:
        result = run_upgrade_step(step, payload)
        if not result.is_ok:
            raise UpgradeError(result.err)
        payload = result.ok
    return payload
```

(Method names are illustrative; verify against
`r2x_core.versioning` and `r2x_core.utils` source.)

## Coordinating with infrasys

For changes to the serialized `System` schema itself (renamed component
fields, added required fields, removed deprecated fields), prefer the
infrasys upgrade hooks:

- Subclass approach: `handle_data_format_upgrade(self, data, from_version,
  to_version)` on a `System` subclass.
- Composition approach: `System.from_json(path, upgrade_handler=fn)`.

See the `infrasys` skill's `SERIALIZATION_MIGRATION.md` for the migration
contract.

Use r2x-core `UpgradeStep` chains for upgrades to **non-`System`**
artifacts (DataStore JSON layout, plugin config files, intermediate
representations).

## Failure playbook

- `VersionReader` returns an unexpected version:
  - Confirm the `VersionStrategy` matches how the dataset stamps its
    version.
- An `UpgradeStep` fails midway:
  - Inspect `result.err`. Do not retry without first reverting the partial
    mutation; otherwise idempotency assumptions break.
- Step applied to wrong version:
  - Add the missing `from_version` gate; never run steps unconditionally.
- `System.from_json` fails after a successful r2x-core upgrade chain:
  - The `System` schema also changed; route that change through infrasys
    `handle_data_format_upgrade` or `upgrade_handler`.

## Output expectations

- Detected source version and strategy used.
- Ordered upgrade chain applied.
- Per-step success/failure outcome.
- Whether infrasys-side migration was also required.
