"""Logging configuration for R2X Core using loguru.

When stderr is a TTY, logs render with a compact colorized layout (Rich when
available, plain text otherwise). When stderr is not a TTY, logs emit as JSON
Lines for structured ingestion.

Library consumers get silence by default (loguru is disabled in __init__.py).
Call setup_logging() to activate, works naturally from IPython, scripts, or the
CLI.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from loguru import logger as _loguru_logger

if TYPE_CHECKING:
    import loguru
    from rich.console import Console

LEVEL_NAMES = {
    "TRACE": "TRACE",
    "DEBUG": "DEBUG",
    "INFO": " INFO",
    "WARNING": " WARN",
    "ERROR": "ERROR",
    "CRITICAL": " CRIT",
}
LEVEL_COLORS = {
    "TRACE": "color(249)",  # light gray
    "DEBUG": "color(33)",  # blue
    "INFO": "color(37)",  # cyan
    "WARNING": "color(214)",  # orange
    "ERROR": "color(169)",  # pink/magenta
    "CRITICAL": "color(169) reverse",  # inverted pink
}

VERBOSITY_INFO = 0
VERBOSITY_DEBUG = 1
VERBOSITY_TRACE = 2
DEFAULT_LOG_LEVEL = "WARNING"

_VERBOSITY_TO_LEVEL = {
    VERBOSITY_TRACE: "TRACE",
    VERBOSITY_INFO: "INFO",
    VERBOSITY_DEBUG: "DEBUG",
}
JSON_LEVEL_NAMES = {
    "TRACE": "TRACE",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARN",
    "ERROR": "ERROR",
    "CRITICAL": "CRIT",
}
DEFAULT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.{ms}"

_verbosity: int = 0


@lru_cache(maxsize=1)
def _get_console() -> Console | None:
    """Return a cached Rich Console for stderr, or None if Rich is missing."""
    try:
        from rich.console import Console
    except ImportError:
        return None
    return Console(stderr=True, force_terminal=True)


def _format_timestamp(record: dict[str, Any]) -> str:
    """Format a log record's timestamp using LOG_TIME_FORMAT env var or default."""
    time_format = os.environ.get("LOG_TIME_FORMAT", DEFAULT_TIME_FORMAT)
    ms = f"{record['time'].microsecond // 1000:03d}"
    return record["time"].strftime(time_format.replace("{ms}", ms))


def _render_exception(record: dict[str, Any], console: Console | None) -> None:
    """Render exception traceback to stderr. Prefers Rich when available."""
    exc = record["exception"]
    if not exc or not exc.type or not exc.value or not exc.traceback:
        return

    if console is not None:
        try:
            from rich.traceback import Traceback
        except ImportError:
            pass
        else:
            console.print(Traceback.from_exception(exc.type, exc.value, exc.traceback))
            return

    lines = traceback.format_exception(exc.type, exc.value, exc.traceback)
    print("".join(lines), file=sys.stderr)


def _extract_extras(record: dict[str, Any]) -> dict[str, Any]:
    """Pull user-supplied extras from a record, excluding the internal 'name' key."""
    return {k: v for k, v in record["extra"].items() if k != "name"}


def format_tty(record: dict[str, Any]) -> None:
    """Format log record for terminal output."""
    level = record["level"].name
    level_name = LEVEL_NAMES.get(level, f"{level:>5}")
    extras = _extract_extras(record)
    console = _get_console()

    show_timestamp = _verbosity >= VERBOSITY_TRACE
    extras_str = "  ".join(f"{k}={v}" for k, v in extras.items()) if extras else ""

    rich_printed = False
    if console is not None:
        try:
            from rich.text import Text

            color = LEVEL_COLORS.get(level, "white")
            text = Text()
            if show_timestamp:
                text.append(_format_timestamp(record), style="dim")
                text.append(" ")
            text.append(level_name, style=f"{color} bold")
            text.append(" ")
            text.append(record["message"])
            if extras_str:
                text.append(f"  {extras_str}", style="dim")
            console.print(text)
            rich_printed = True
        except ImportError:
            pass

    if not rich_printed:
        parts: list[str] = []
        if show_timestamp:
            parts.append(_format_timestamp(record))
        parts.append(level_name)
        parts.append(record["message"])
        if extras_str:
            parts.append(extras_str)
        print(" ".join(parts), file=sys.stderr)

    _render_exception(record, console if rich_printed else None)


def format_json(record: dict[str, Any]) -> str:
    """Format log record as JSON Lines for piping."""
    level = record["level"].name
    obj: dict[str, Any] = {
        "ts": record["time"].strftime(DEFAULT_TIME_FORMAT),
        "level": JSON_LEVEL_NAMES.get(level, level),
        "msg": record["message"],
    }

    name = record["extra"].get("name") or record.get("name")
    if name:
        obj["logger"] = name

    if record.get("file"):
        obj["file"] = record["file"].path
        obj["line"] = record["line"]

    extras = _extract_extras(record)
    if extras:
        obj.update(extras)

    exc = record["exception"]
    if exc and exc.type and exc.value:
        obj["error"] = {
            "type": exc.type.__name__,
            "message": str(exc.value),
        }
        if exc.traceback:
            obj["error"]["traceback"] = traceback.format_exception(exc.type, exc.value, exc.traceback)

    return json.dumps(obj)


def structured_sink(message: Any) -> None:
    """Route logs to TTY or JSON format based on stderr detection."""
    record = message.record
    if sys.stderr.isatty():
        format_tty(record)
    else:
        print(format_json(record), file=sys.stderr)


def setup_logging(
    verbosity: int = 0,
    *,
    log_file: str | None = None,
    log_to_console: bool = True,
) -> None:
    """Configure loguru with file and optional console sinks.

    Always writes to log_file when provided (at TRACE level to capture everything).
    Only writes to console/stderr when log_to_console is True.

    Verbosity levels (for console output):
        0: WARNING and above (default)
       -v: INFO and above, no timestamps
      -vv: TRACE and above, with timestamps
    """
    if not log_file and not log_to_console:
        raise ValueError(
            "setup_logging called with no sinks: log_file is None and log_to_console is False. "
            "At least one output must be enabled."
        )

    global _verbosity

    _verbosity = verbosity

    _loguru_logger.enable("r2x_core")

    level = _VERBOSITY_TO_LEVEL.get(verbosity, DEFAULT_LOG_LEVEL)

    _loguru_logger.remove()

    if log_file:
        _loguru_logger.add(
            log_file,
            level="TRACE",
            format="[{time:YYYY-MM-DD HH:mm:ss}] [PYTHON] {level} {message}",
            backtrace=True,
            diagnose=True,
            mode="a",
        )

    if log_to_console:
        _loguru_logger.add(
            structured_sink,
            level=level,
            backtrace=True,
            diagnose=True,
        )


def get_logger(name: str) -> loguru.Logger:
    """Get a logger for a specific component or plugin."""
    return _loguru_logger.bind(name=name)
