# r2x-core logging policy

Use this reference when adding, reviewing, or debugging logs in r2x-core or a
translator built on it. The policy follows the repository's Loguru setup in
`src/r2x_core/logger.py`.

## Logging contract

- Use Loguru, not `print`, for library diagnostics.
- r2x-core logging is disabled by default in `r2x_core.__init__` with
  `logger.disable("r2x_core")`.
- Every application or package built on r2x-core should disable its own
  namespace at import time as well, for example
  `logger.disable("my_translator")`. This keeps the package silent when it is
  imported as a library.
- The application or CLI entry point explicitly enables the namespaces it owns
  before configuring sinks. `setup_logging(...)` enables the `r2x_core` namespace;
  a custom Loguru setup must enable both namespaces itself.
- Use `get_logger("component.name")` when a bound logger label is useful.
  Its `name` value is structured metadata; it does not change Loguru's record
  namespace used by `logger.disable(...)`.
- Write structured context with `logger.bind(...)` or `logger.bind(...).info(...)`.
- Use Loguru's `{}` formatting arguments, not f-strings in hot paths or when
  the message does not need eager interpolation.
- Keep stdout for a documented CLI/data contract. Logs go to stderr or a log
  file.

```python
from r2x_core.logger import get_logger, setup_logging

logger = get_logger("translator.parser")


def read_inputs(path: str) -> None:
    logger.debug("Reading input path={}", path)
    logger.info("Input read started")


if __name__ == "__main__":
    setup_logging(verbosity=0)  # INFO and above on the console
    read_inputs("inputs")
```

Library modules should not call `setup_logging()` during import. Importing a
library must remain quiet until its owner explicitly enables a sink.

## Application namespace opt-in

Each application package should establish the same silent-by-default policy in
its package initializer. Use the package namespace, not `__name__` from a CLI
module, because Loguru's disable/enable controls match logger record names:

```python
# my_translator/__init__.py
from loguru import logger

logger.disable("my_translator")
```

The application entry point opts in after argument parsing and before it runs
work. `setup_logging(...)` enables `r2x_core` and installs the repository's
console/file sinks. Enable the application's own namespace separately:

```python
# my_translator/__main__.py
from loguru import logger

from r2x_core.logger import setup_logging


def main() -> int:
    # Parse flags first, then choose verbosity and sinks.
    logger.enable("my_translator")
    setup_logging(verbosity=1, log_file="run.log")  # DEBUG and above on console
    logger.info("Application started")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The `setup_logging` call also runs `logger.enable("r2x_core")`. An application
using the helper therefore needs only `logger.enable("my_translator")` for its
own records, provided those records originate in `my_translator.*` modules.
If a CLI module is named `__main__`, use the package logger from an application
module for package diagnostics, or enable the CLI module's actual record name
as well. If the application owns a custom Loguru setup instead, enable both
namespaces and add its own sink:

```python
from loguru import logger
import sys

logger.enable("my_translator")
logger.enable("r2x_core")
logger.remove()
logger.add(sys.stderr, level="INFO", serialize=True)
```

Do not call `logger.disable("r2x_core")` after `setup_logging(...)`, and do not
expect `logger.add(...)` alone to re-enable a disabled namespace. Enabling a
namespace and adding a sink are separate operations. `setup_logging(...)`
replaces existing Loguru sinks, so call it at the application boundary and do
not call it from reusable library modules.

## Loguru levels

Loguru orders levels from least to most severe as follows:

| Level | Use when | Examples | Do not use for |
| --- | --- | --- | --- |
| `TRACE` | Need highly detailed execution evidence to diagnose a specific path. | Per-rule field decisions, resolved paths, per-component attachment, processor steps, system-base assignment. | Normal progress, large payload dumps, secrets, or one log per row in a large dataset. |
| `DEBUG` | Need developer diagnostics that explain decisions and state without being routine user output. | Starting a read, selected upgrade branch, registered getter, number of converted components, chosen file mapping. | Every loop iteration or a successful operation that users need to see by default. |
| `INFO` | Report meaningful lifecycle milestones and normal outcomes. | Plugin started/completed, file mapping loaded, upgrade applied, system serialized, time-series transfer summary. | Detailed internals, warnings, or expected per-record activity. |
| `SUCCESS` | Mark a prominent successful user operation only when the surrounding CLI/application already uses this level. | A completed top-level command with a clear user-facing outcome. | Ordinary library success. The current r2x-core formatter has no dedicated `SUCCESS` styling, so prefer `INFO` in framework/library code. |
| `WARNING` | An abnormal or degraded condition is recoverable and execution continues. | Optional file skipped, no source components matched, duplicate rows removed, fallback path selected, persisted metadata ignored. | Expected branches, validation failures that abort, or a condition that makes the result unusable. |
| `ERROR` | A specific operation failed or a recoverable boundary has an actionable failure. | One rule failed while aggregate execution records the failure, a configured upgrade step failed, an attachment cannot be made. | Logging the same exception repeatedly at every layer, or a fatal process decision that requires `CRITICAL`. |
| `CRITICAL` | The application or workflow cannot continue safely and needs operator intervention. | Corrupt required runtime state, unavailable mandatory service, unrecoverable top-level startup failure. | Library code deciding to exit the process. Raise a typed exception and let the application boundary decide. |

Use `logger.exception("...")` inside an `except` block when the traceback is
needed. It emits an `ERROR` record with exception information. Do not use
`logger.exception` for ordinary error strings outside an exception handler.

## Choosing a level

Ask these questions in order:

1. **Would a caller normally need this to understand the result?** Use `INFO`.
2. **Is it a recoverable abnormality that changes behavior?** Use `WARNING`.
3. **Did a specific operation fail?** Use `ERROR`, preserving the operation and
   relevant identifier.
4. **Would continuing risk corrupting or misrepresenting the result?** Raise a
   typed error. Use `CRITICAL` only at an application boundary that can act on
   the failure.
5. **Is this only useful for diagnosis?** Use `DEBUG` or `TRACE`, choosing
   `TRACE` for high-volume or deeply internal detail.

Log a state transition once at the boundary that owns it. Do not log the same
failure in a helper, service, plugin, and CLI unless each layer adds materially
different context.

## Verbosity and sinks

`setup_logging` configures console and optional file sinks:

```python
from r2x_core.logger import VERBOSITY_DEBUG, VERBOSITY_INFO, VERBOSITY_TRACE, setup_logging

setup_logging(verbosity=VERBOSITY_INFO)   # INFO and above
setup_logging(verbosity=VERBOSITY_DEBUG)  # console DEBUG and above
setup_logging(verbosity=VERBOSITY_TRACE)  # console TRACE and above

setup_logging(
    verbosity=VERBOSITY_INFO,
    log_file="run.log",
    log_to_console=False,
)
```

Current mappings are source-defined:

- `verbosity=0` (`VERBOSITY_INFO`, the default) shows `INFO` and above on
  the console.
- `verbosity=1` (`VERBOSITY_DEBUG`) shows `DEBUG` and above.
- `verbosity=2` (`VERBOSITY_TRACE`) shows `TRACE` and above and includes
  timestamps in TTY output.
- An unsupported verbosity value falls back to `WARNING` for console output.
- A configured file sink always captures `TRACE` and above.
- `log_to_console=False` suppresses the console sink but does not suppress a
  configured file sink.
- Calling `setup_logging` enables the `r2x_core` logger namespace and replaces
  existing Loguru sinks. The caller owns this application-level configuration.

Terminal output uses a compact Rich layout when stderr is a TTY. Non-TTY
stderr receives JSON Lines suitable for CI and ingestion. File output uses the
configured timestamped text format. Do not parse human TTY output; use the
structured non-TTY stream or a file sink when automation needs logs.

## Structured context

Bind stable identifiers instead of interpolating a long diagnostic string:

```python
logger = get_logger("rules.executor").bind(
    plugin="reeds_to_sienna",
    rule="generator_to_unit",
    run_id=run_id,
)
logger.info("Applying translation rule")
logger.debug("Rule inputs resolved", source_type=source_type, target_type=target_type)
```

With the repository formatter, bound extras appear as terminal context and as
additional JSON fields. Keep values scalar or compact and JSON-serializable:
IDs, names, counts, paths, versions, and statuses are good. Avoid binding full
systems, DataFrames, arrays, credentials, tokens, or arbitrary objects.

Use stable message text and structured fields for values:

```python
logger.warning(
    "Optional input skipped",
    file_name=data_file.name,
    path=str(path),
    reason="file not found",
)
```

The current codebase commonly uses positional Loguru formatting (`{}`) and
bound `name` fields through `get_logger`. The bound `name` is metadata shown by
structured sinks; namespace enable/disable still follows the originating
module's record name. Follow the local style of the module being changed rather
than mixing message styles in one area.

## r2x-core examples by level

```python
logger.trace("Resolved relative_fpath={} for file={}", fpath, data_file.name)
logger.debug("Applying rule: {}", rule)
logger.info("Loading file mapping from {}", mapping_path)
logger.warning("No components found for source type '{}' in rule {}", source_type, rule)
logger.error("Rule {} failed: {}", rule, error)
```

These levels match the existing framework behavior:

- Path resolution and per-component attachment are `TRACE`.
- Reader starts, rule starts, and transformation details are `DEBUG`.
- Store loading, serialization, and transfer summaries are `INFO`.
- Optional skips, no-match conditions, and recoverable cleanup are `WARNING`.
- Rule or attachment failures are `ERROR`.

## Sensitive and high-volume data

Never log secrets, credentials, access tokens, raw user data, or complete input
payloads. Redact paths or identifiers when they contain sensitive information.
For large inputs, log dimensions, names, counts, dtypes, versions, and checksums
instead of contents. Guard expensive diagnostics with the appropriate level or
move them to a bounded probe.

```python
logger.debug(
    "Loaded profile",
    rows=frame.height,
    columns=frame.width,
    column_names=frame.columns,
)
```

Do not put `repr(system)`, a complete DataFrame, or an entire rule/configuration
mapping into an INFO or WARNING message.

## Error handling and tests

- Log at the layer that can explain or handle the event.
- Preserve the original exception with `raise ... from exc` or `Err(...)`.
- If an exception is propagated unchanged, avoid logging it again at every
  caller.
- Use `logger.exception(...)` only when the traceback is useful to the current
  boundary.
- Test behavior through configured sinks when changing logging format, level
  filtering, structured fields, or exception output. Restore Loguru sinks and
  package enablement in fixtures.

## Output expectations

When changing logging, report:

- The level selected for each new event and why.
- Whether the event is library logging or an application/CLI boundary.
- Bound structured fields and any redaction/truncation decisions.
- Console/file sink and verbosity behavior validated.
- Any remaining concern about volume, sensitive data, or duplicate records.
