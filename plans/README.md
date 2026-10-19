# Parser migration replan

The scoped migration is complete. See [the completion record](003-migration-completion.md) for the implemented boundary, validation, and remaining limitations. Changes remain uncommitted in both worktrees.

| Plan | Scope | Status |
| --- | --- | --- |
| [001](001-parser-architecture-replan.md) | Shared boundaries and recovery constraints | Implemented |
| [002](002-fom-contract.md) | Configured generator/FOM execution | Independently validated |
| [003](003-migration-completion.md) | Completed migration and validation | Complete |

Follow the concrete FOM contract, not the agent's earlier sprawling migration. Do not reset dirty changes or expand a new operator catalog. The user authorized completion, not another cycle of planning pauses.

The user confirmed that source-specific modeling choices are not a justification for a default ReEDS Python policy-function escape hatch. ReEDS declares those choices in configuration and core executes the shared mechanics. Astra's proposed exception is not adopted.

Astra's read-only reviews are retained at `/home/morgoth/.local/state/pi/reviews/astra-parser-plan-TxGjN1/`. Dependency execution and lifecycle support are implemented. Confirmed source snapshot, incremental registration, and removal-integrity findings have regression tests.

## Rejected approaches

- Migrating one function at a time while the application still assembles intermediate frames.
- Treating a growing JSON operator catalog as a substitute for an end-to-end data model.
- Keeping old helper APIs or alternate Python parsing paths to satisfy existing tests.
- Moving the ReEDS parser wholesale into a core module or another ReEDS helper file.
- Adding a dataset-local callback or pure-policy wrapper in ReEDS instead of demonstrating a shared contract.
- Using Python line count or isolated primitive test counts as proof that the architectural migration succeeded.
