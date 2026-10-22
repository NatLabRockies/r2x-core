"""Tests for public logging behavior."""

import json
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

import pytest
from loguru import logger as loguru_logger

import r2x_core.logger as logger_module
from r2x_core.logger import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_TIME_FORMAT,
    LEVEL_COLORS,
    LEVEL_NAMES,
    VERBOSITY_DEBUG,
    VERBOSITY_INFO,
    VERBOSITY_TRACE,
    console,
    format_json,
    format_timestamp,
    format_tty,
    get_logger,
    render_exception,
    setup_logging,
    structured_sink,
)


class LogMessage(Protocol):
    """The public Loguru sink message fields used by formatters."""

    record: dict[str, object]


@pytest.fixture(autouse=True)
def reset_logger_state() -> Iterator[None]:
    """Keep Loguru sinks and formatter state isolated between tests."""
    loguru_logger.remove()
    loguru_logger.disable("r2x_core")
    logger_module.current_verbosity = VERBOSITY_INFO
    console.cache_clear()
    yield
    loguru_logger.remove()
    loguru_logger.disable("r2x_core")
    logger_module.current_verbosity = VERBOSITY_INFO
    console.cache_clear()


@pytest.fixture
def log_messages() -> Iterator[list[LogMessage]]:
    """Capture real Loguru records through its public sink API."""
    messages: list[LogMessage] = []
    sink_id = loguru_logger.add(messages.append, level="TRACE")
    loguru_logger.enable("r2x_core")
    try:
        yield messages
    finally:
        loguru_logger.remove(sink_id)


def log_exception(error: Exception, *, with_traceback: bool) -> None:
    """Emit an exception record through Loguru's public ``opt`` API."""
    if with_traceback:
        try:
            raise error
        except Exception:
            loguru_logger.opt(exception=True).error("exception record")
    else:
        loguru_logger.opt(exception=(type(error), error, None)).error("exception record")


@pytest.mark.parametrize(
    ("timestamp", "time_format", "expected"),
    [
        pytest.param(
            datetime(2026, 1, 18, 10, 30, 45, 123456),
            None,
            "2026-01-18T10:30:45.123",
            id="default-format",
        ),
        pytest.param(
            datetime(2026, 1, 18, 10, 30, 45, 123456),
            "%Y-%m-%d %H:%M:%S.{ms}",
            "2026-01-18 10:30:45.123",
            id="custom-format",
        ),
        pytest.param(
            datetime(2026, 1, 18, 10, 30, 45, 500000),
            None,
            "2026-01-18T10:30:45.500",
            id="milliseconds",
        ),
    ],
)
def test_format_timestamp(
    log_messages: list[LogMessage],
    monkeypatch: pytest.MonkeyPatch,
    timestamp: datetime,
    time_format: str | None,
    expected: str,
) -> None:
    if time_format is None:
        monkeypatch.delenv("LOG_TIME_FORMAT", raising=False)
    else:
        monkeypatch.setenv("LOG_TIME_FORMAT", time_format)

    loguru_logger.patch(lambda record: record.update(time=timestamp)).info("timestamp")

    assert format_timestamp(log_messages[0].record) == expected


@pytest.mark.parametrize(
    "state", ["missing", "incomplete", "no-traceback"], ids=["none", "partial", "no-traceback"]
)
def test_render_exception_skips_unusable_records(
    log_messages: list[LogMessage], capsys: pytest.CaptureFixture[str], state: str
) -> None:
    if state == "no-traceback":
        log_exception(ValueError("without traceback"), with_traceback=False)
        record = log_messages[0].record
    else:
        loguru_logger.info("no exception")
        record = log_messages[0].record
        if state == "incomplete":
            record["exception"] = SimpleNamespace(type=None, value=None, traceback=None)

    render_exception(record, None)

    assert capsys.readouterr().err == ""


def test_render_exception_prints_plain_traceback(
    log_messages: list[LogMessage], capsys: pytest.CaptureFixture[str]
) -> None:
    log_exception(ValueError("plain traceback"), with_traceback=True)

    render_exception(log_messages[0].record, None)

    output = capsys.readouterr().err
    assert "ValueError" in output
    assert "plain traceback" in output


def test_render_exception_uses_rich_when_available(
    log_messages: list[LogMessage], capsys: pytest.CaptureFixture[str]
) -> None:
    log_exception(ValueError("rich traceback"), with_traceback=True)
    rich_console = console()

    render_exception(log_messages[0].record, rich_console)

    output = capsys.readouterr().err
    assert "ValueError" in output
    assert "rich traceback" in output


@pytest.mark.parametrize(
    "console_mode",
    [pytest.param("default-console", id="default-console"), pytest.param("plain", id="plain")],
)
@pytest.mark.parametrize(
    ("level", "message", "extra", "verbosity", "timestamp", "present", "absent"),
    [
        pytest.param("INFO", "test message", {}, 0, None, ("INFO", "test message"), (), id="basic"),
        pytest.param(
            "DEBUG",
            "debug message",
            {},
            VERBOSITY_TRACE,
            datetime(2026, 1, 18, 10, 30, 45, 123456),
            ("DEBUG", "debug message", "2026-01-18T10:30:45.123"),
            (),
            id="timestamp",
        ),
        pytest.param(
            "WARNING",
            "warn message",
            {"user_id": 123, "action": "login", "name": "ignored"},
            0,
            None,
            ("WARN", "warn message", "user_id=123", "action=login"),
            ("ignored", "2026-01-18"),
            id="extras-without-timestamp",
        ),
        pytest.param(
            "INFO",
            "test with everything",
            {"request_id": "12345", "user": "alice", "name": "ignored"},
            VERBOSITY_TRACE,
            datetime(2026, 1, 18, 10, 30, 45, 123456),
            ("INFO", "test with everything", "2026-01-18T10:30:45.123", "request_id=12345", "user=alice"),
            ("ignored",),
            id="timestamp-and-extras",
        ),
        pytest.param(
            "WARNING",
            "warning with extras",
            {"code": 500, "retries": 3, "name": "ignored"},
            0,
            None,
            ("warning with extras", "WARN", "code=500", "retries=3"),
            ("ignored", "2026-01-18"),
            id="extras-only",
        ),
    ],
)
def test_format_tty_records(
    log_messages: list[LogMessage],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    console_mode: str,
    level: str,
    message: str,
    extra: dict[str, object],
    verbosity: int,
    timestamp: datetime | None,
    present: tuple[str, ...],
    absent: tuple[str, ...],
) -> None:
    if console_mode == "plain":
        monkeypatch.setattr(logger_module, "console", lambda: None)
    logger_module.current_verbosity = verbosity
    bound_logger = loguru_logger.bind(**extra)
    if timestamp is not None:
        bound_logger = bound_logger.patch(lambda record: record.update(time=timestamp))
    bound_logger.log(level, message)

    format_tty(log_messages[0].record)

    output = capsys.readouterr().err
    assert all(expected in output for expected in present)
    assert all(unexpected not in output for unexpected in absent)


@pytest.mark.parametrize(
    ("level", "message", "extra", "include_file", "expected"),
    [
        pytest.param("INFO", "test message", {}, False, {"level": "INFO", "msg": "test message"}, id="basic"),
        pytest.param(
            "DEBUG", "debug msg", {"name": "my.logger"}, False, {"logger": "my.logger"}, id="logger-name"
        ),
        pytest.param("ERROR", "error msg", {}, True, {}, id="file-and-line"),
        pytest.param(
            "WARNING",
            "warning",
            {"request_id": "abc123", "status": 404, "name": "ignored"},
            False,
            {"request_id": "abc123", "status": 404, "logger": "ignored"},
            id="extras",
        ),
    ],
)
def test_format_json_actual_records(
    log_messages: list[LogMessage],
    level: str,
    message: str,
    extra: dict[str, object],
    include_file: bool,
    expected: dict[str, object],
) -> None:
    timestamp = datetime(2026, 1, 18, 10, 30, 45, 123456)
    loguru_logger.patch(lambda record: record.update(time=timestamp)).bind(**extra).log(level, message)
    record = log_messages[0].record
    if not include_file:
        record["file"] = None

    payload = json.loads(format_json(record))

    assert payload["ts"].startswith("2026-01-18T10:30:45.")
    assert all(payload[key] == value for key, value in expected.items())
    assert ("file" in payload) is include_file
    assert ("line" in payload) is include_file
    assert "name" not in payload
    if include_file:
        assert Path(payload["file"]).name == Path(__file__).name
        assert payload["line"] > 0


@pytest.mark.parametrize("with_traceback", [True, False], ids=["traceback", "without-traceback"])
def test_format_json_exception(log_messages: list[LogMessage], with_traceback: bool) -> None:
    log_exception(RuntimeError("Test error"), with_traceback=with_traceback)

    payload = json.loads(format_json(log_messages[0].record))

    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["message"] == "Test error"
    assert ("traceback" in payload["error"]) is with_traceback
    if with_traceback:
        assert any("Test error" in line for line in payload["error"]["traceback"])


@pytest.mark.parametrize("is_tty", [False, True], ids=["json", "tty"])
def test_structured_sink_selects_format(
    log_messages: list[LogMessage],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    is_tty: bool,
) -> None:
    monkeypatch.setattr(sys.stderr, "isatty", lambda: is_tty)
    if is_tty:
        monkeypatch.setattr(logger_module, "console", lambda: None)

    loguru_logger.info("structured message")
    structured_sink(log_messages[0])

    output = capsys.readouterr().err.strip()
    if is_tty:
        assert "structured message" in output
        assert "INFO" in output
        assert "{" not in output
    else:
        payload = json.loads(output)
        assert payload["msg"] == "structured message"
        assert payload["level"] == "INFO"


@pytest.mark.parametrize("name", ["component1", "component2"], ids=["first", "second"])
def test_get_logger_binds_component_name(log_messages: list[LogMessage], name: str) -> None:
    logger_instance = get_logger(name)
    assert callable(logger_instance.info)
    logger_instance.info("bound logger")

    assert log_messages[0].record["extra"]["name"] == name
    assert log_messages[0].record["message"] == "bound logger"


def test_level_constants_and_console_cache() -> None:
    expected_colors = {
        "TRACE": "color(249)",
        "DEBUG": "color(33)",
        "INFO": "color(37)",
        "WARNING": "color(214)",
        "ERROR": "color(169)",
        "CRITICAL": "color(169) reverse",
    }
    levels = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    assert {loguru_logger.level(name).name for name in levels} == levels
    assert set(LEVEL_NAMES) == levels
    assert set(LEVEL_COLORS) == levels
    assert expected_colors == LEVEL_COLORS
    assert DEFAULT_LOG_LEVEL == "WARNING"
    assert VERBOSITY_INFO == 0
    assert VERBOSITY_DEBUG == 1
    assert VERBOSITY_TRACE == 2
    assert DEFAULT_TIME_FORMAT == "%Y-%m-%dT%H:%M:%S.{ms}"

    first = console()
    assert console() is first
    assert first is None or callable(first.print)


@pytest.mark.parametrize(
    ("verbosity", "expected"),
    [
        pytest.param(VERBOSITY_TRACE, VERBOSITY_TRACE, id="trace"),
        pytest.param(VERBOSITY_INFO, VERBOSITY_INFO, id="info"),
        pytest.param(0, VERBOSITY_INFO, id="default"),
    ],
)
def test_setup_logging_verbosity(verbosity: int, expected: int) -> None:
    setup_logging(verbosity=verbosity)

    assert logger_module.current_verbosity == expected


def test_setup_logging_requires_a_sink() -> None:
    with pytest.raises(ValueError, match="no sinks"):
        setup_logging(verbosity=VERBOSITY_INFO, log_file=None, log_to_console=False)


@pytest.mark.parametrize(
    ("file_enabled", "console_enabled"),
    [
        pytest.param(False, True, id="console-only"),
        pytest.param(True, False, id="file-only"),
        pytest.param(True, True, id="both"),
    ],
)
def test_setup_logging_routes_console_and_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    file_enabled: bool,
    console_enabled: bool,
) -> None:
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    log_file = tmp_path / "test.log" if file_enabled else None
    setup_logging(
        verbosity=VERBOSITY_TRACE,
        log_file=str(log_file) if log_file else None,
        log_to_console=console_enabled,
    )
    loguru_logger.info("sink routing message")
    loguru_logger.complete()

    console_output = capsys.readouterr().err
    if console_enabled:
        assert json.loads(console_output)["msg"] == "sink routing message"
    else:
        assert console_output == ""
    if log_file is not None:
        contents = log_file.read_text()
        assert "[PYTHON]" in contents
        assert "sink routing message" in contents


def test_file_sink_captures_all_levels_independent_of_console_verbosity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    log_file = tmp_path / "trace.log"
    setup_logging(verbosity=VERBOSITY_INFO, log_file=str(log_file), log_to_console=True)
    loguru_logger.trace("trace level message")
    loguru_logger.debug("debug level message")
    loguru_logger.warning("warning level message")
    loguru_logger.complete()

    contents = log_file.read_text()
    assert "trace level message" in contents
    assert "debug level message" in contents
    assert "warning level message" in contents
    console_records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [record["msg"] for record in console_records] == ["warning level message"]
