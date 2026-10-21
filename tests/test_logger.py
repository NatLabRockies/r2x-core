"""Tests for logging."""

import json
import sys
from datetime import datetime
from unittest import mock

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


def test_format_timestamp_default_format():
    """Test timestamp formatting with default format."""
    record = {
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
    }
    result = format_timestamp(record)
    assert "2026-01-18T10:30:45.123" in result


def test_format_timestamp_custom_format(monkeypatch):
    """Test timestamp formatting with custom format."""
    monkeypatch.setenv("LOG_TIME_FORMAT", "%Y-%m-%d %H:%M:%S.{ms}")
    record = {
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
    }
    result = format_timestamp(record)
    assert "2026-01-18 10:30:45.123" in result


def test_format_timestamp_with_milliseconds():
    """Test timestamp formatting with correct millisecond calculation."""
    record = {
        "time": datetime(2026, 1, 18, 10, 30, 45, 500000),  # 500ms
    }
    result = format_timestamp(record)
    assert "500" in result


def test_render_exception_with_no_exception():
    """Test render_exception with no exception."""
    record = {"exception": None}
    render_exception(record, None)


def test_render_exception_with_incomplete_exception():
    """Test render_exception with incomplete exception info."""
    exc = mock.Mock()
    exc.type = None
    record = {"exception": exc}
    render_exception(record, None)


def test_render_exception_with_traceback_no_rich(capsys):
    """Test render_exception with traceback when Rich unavailable."""
    try:
        raise ValueError("Test error")
    except ValueError:
        exc_info = sys.exc_info()
        record = {
            "exception": mock.Mock(
                type=exc_info[0],
                value=exc_info[1],
                traceback=exc_info[2],
            )
        }
        render_exception(record, None)

        output = capsys.readouterr().err
        assert "ValueError" in output or "Test error" in output


def test_format_tty_basic(capsys):
    """Test TTY formatting basic output."""
    import r2x_core.logger as logger_module

    logger_module._verbosity = 0

    level_mock = mock.Mock()
    level_mock.name = "INFO"

    record = {
        "level": level_mock,
        "message": "test message",
        "extra": {},
        "exception": None,
    }
    format_tty(record)
    output = capsys.readouterr().err
    assert "INFO" in output
    assert "test message" in output


def test_format_tty_with_timestamp(capsys):
    """Test TTY formatting with timestamp when verbosity >= 2."""
    import r2x_core.logger as logger_module

    logger_module._verbosity = VERBOSITY_TRACE

    level_mock = mock.Mock()
    level_mock.name = "DEBUG"

    record = {
        "level": level_mock,
        "message": "debug message",
        "extra": {},
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "exception": None,
    }
    format_tty(record)
    output = capsys.readouterr().err
    assert "DEBUG" in output
    assert "debug message" in output


def test_format_tty_with_extras(capsys):
    """Test TTY formatting with extra fields."""
    import r2x_core.logger as logger_module

    logger_module._verbosity = 0

    level_mock = mock.Mock()
    level_mock.name = "WARNING"

    record = {
        "level": level_mock,
        "message": "warn message",
        "extra": {"user_id": 123, "action": "login", "name": "ignored"},
        "exception": None,
    }
    format_tty(record)
    output = capsys.readouterr().err
    assert "WARN" in output
    assert "warn message" in output


def test_format_json_basic():
    """Test JSON formatting with basic record."""
    level_mock = mock.Mock()
    level_mock.name = "INFO"

    record = {
        "level": level_mock,
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "message": "test message",
        "extra": {},
        "file": None,
        "exception": None,
    }
    result = format_json(record)
    payload = json.loads(result)

    assert payload["msg"] == "test message"
    assert payload["level"] == "INFO"
    assert "ts" in payload


def test_format_json_with_logger_name():
    """Test JSON formatting with logger name."""
    level_mock = mock.Mock()
    level_mock.name = "DEBUG"

    record = {
        "level": level_mock,
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "message": "debug msg",
        "extra": {"name": "my.logger"},
        "file": None,
        "exception": None,
    }
    result = format_json(record)
    payload = json.loads(result)

    assert payload["logger"] == "my.logger"


def test_format_json_with_file_info():
    """Test JSON formatting with file information."""
    file_mock = mock.Mock()
    file_mock.path = "/path/to/file.py"

    level_mock = mock.Mock()
    level_mock.name = "ERROR"

    record = {
        "level": level_mock,
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "message": "error msg",
        "extra": {},
        "file": file_mock,
        "line": 42,
        "exception": None,
    }
    result = format_json(record)
    payload = json.loads(result)

    assert payload["file"] == "/path/to/file.py"
    assert payload["line"] == 42


def test_format_json_with_exception():
    """Test JSON formatting with exception."""
    try:
        raise RuntimeError("Test error")
    except RuntimeError:
        exc_info = sys.exc_info()

        level_mock = mock.Mock()
        level_mock.name = "ERROR"

        record = {
            "level": level_mock,
            "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
            "message": "error occurred",
            "extra": {},
            "file": None,
            "exception": mock.Mock(
                type=exc_info[0],
                value=exc_info[1],
                traceback=exc_info[2],
            ),
        }
        result = format_json(record)
        payload = json.loads(result)

        assert "error" in payload
        assert payload["error"]["type"] == "RuntimeError"
        assert payload["error"]["message"] == "Test error"
        assert "traceback" in payload["error"]


def test_format_json_with_extras():
    """Test JSON formatting with extra fields."""
    level_mock = mock.Mock()
    level_mock.name = "WARNING"

    record = {
        "level": level_mock,
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "message": "warning",
        "extra": {"request_id": "abc123", "status": 404, "name": "ignored"},
        "file": None,
        "exception": None,
    }
    result = format_json(record)
    payload = json.loads(result)

    assert payload["request_id"] == "abc123"
    assert payload["status"] == 404
    assert "name" not in payload


def test_structured_sink_json_mode(monkeypatch, capsys):
    """Test structured_sink in JSON mode."""
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)

    level_mock = mock.Mock()
    level_mock.name = "INFO"

    record = {
        "level": level_mock,
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "message": "json message",
        "extra": {},
        "file": None,
        "exception": None,
    }

    message = mock.Mock()
    message.record = record

    structured_sink(message)
    output = capsys.readouterr().err.strip()
    payload = json.loads(output)
    assert payload["msg"] == "json message"


def test_get_logger_returns_bound_logger():
    """Test that get_logger returns a bound logger."""
    custom_logger = get_logger("my.component")
    assert custom_logger is not None
    assert hasattr(custom_logger, "info")
    assert hasattr(custom_logger, "debug")


def test_get_logger_with_different_names():
    """Test get_logger with different component names."""
    logger1 = get_logger("component1")
    logger2 = get_logger("component2")

    assert logger1 is not None
    assert logger2 is not None


def test_level_names_coverage():
    """Test that LEVEL_NAMES contains expected levels."""
    expected_levels = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert set(LEVEL_NAMES.keys()) == expected_levels


def test_level_colors_coverage():
    """Test that LEVEL_COLORS contains expected levels."""
    expected_levels = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert set(LEVEL_COLORS.keys()) == expected_levels


def test_default_constants():
    """Test default constants are set correctly."""
    assert DEFAULT_LOG_LEVEL == "WARNING"
    assert VERBOSITY_INFO == 0
    assert VERBOSITY_DEBUG == 1
    assert VERBOSITY_TRACE == 2
    assert DEFAULT_TIME_FORMAT == "%Y-%m-%dT%H:%M:%S.{ms}"


def test_console_returns_console_or_none():
    """Test console returns a Console (if Rich installed) or None."""
    console.cache_clear()
    result = console()
    if result is not None:
        assert hasattr(result, "print")


def test_console_is_cached():
    """Test console returns the same instance on repeated calls."""
    console.cache_clear()
    first = console()
    second = console()
    assert first is second


def test_format_tty_with_rich_text_output(capsys):
    """Test TTY formatting produces rich text output when Rich is available."""
    import r2x_core.logger as logger_module

    logger_module._verbosity = 0
    console.cache_clear()

    level_mock = mock.Mock()
    level_mock.name = "ERROR"

    record = {
        "level": level_mock,
        "message": "error message",
        "extra": {"key": "value"},
        "exception": None,
    }

    format_tty(record)
    output = capsys.readouterr().err
    assert "error message" in output
    assert "ERROR" in output or "key" in output


def test_format_tty_fallback_no_rich(monkeypatch, capsys):
    """Test TTY formatting fallback when Rich is not available."""
    import r2x_core.logger as logger_module

    logger_module._verbosity = 0
    console.cache_clear()
    monkeypatch.setattr("r2x_core.logger.console", lambda: None)

    level_mock = mock.Mock()
    level_mock.name = "DEBUG"

    record = {
        "level": level_mock,
        "message": "debug output",
        "extra": {},
        "exception": None,
    }

    format_tty(record)
    output = capsys.readouterr().err
    assert "debug output" in output
    assert "DEBUG" in output


def test_render_exception_with_traceback_and_rich(capsys):
    """Test exception rendering with Rich traceback."""
    console.cache_clear()
    console_instance = console()

    try:
        raise ValueError("Test exception")
    except ValueError:
        exc_info = sys.exc_info()
        record = {
            "exception": mock.Mock(
                type=exc_info[0],
                value=exc_info[1],
                traceback=exc_info[2],
            ),
        }
        render_exception(record, console_instance)


def test_structured_sink_tty_mode(monkeypatch, capsys):
    """Test structured_sink in TTY mode."""
    import r2x_core.logger as logger_module

    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    logger_module._verbosity = 0
    console.cache_clear()
    monkeypatch.setattr("r2x_core.logger.console", lambda: None)

    level_mock = mock.Mock()
    level_mock.name = "INFO"

    record = {
        "level": level_mock,
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "message": "tty message",
        "extra": {},
        "exception": None,
    }

    message = mock.Mock()
    message.record = record

    structured_sink(message)
    output = capsys.readouterr().err
    assert "tty message" in output
    assert "{" not in output


def test_setup_logging_with_verbosity_trace():
    """Test setup_logging with TRACE verbosity."""
    import r2x_core.logger as logger_module

    setup_logging(verbosity=VERBOSITY_TRACE)
    assert logger_module._verbosity == VERBOSITY_TRACE


def test_setup_logging_with_verbosity_info():
    """Test setup_logging with INFO verbosity."""
    import r2x_core.logger as logger_module

    setup_logging(verbosity=VERBOSITY_INFO)
    assert logger_module._verbosity == VERBOSITY_INFO


def test_setup_logging_default_verbosity():
    """Test setup_logging with default verbosity."""
    import r2x_core.logger as logger_module

    setup_logging(verbosity=0)
    assert logger_module._verbosity == 0


def test_format_tty_fallback_with_timestamp_and_extras(monkeypatch, capsys):
    """Test fallback TTY formatting with both timestamp and extras."""
    import r2x_core.logger as logger_module

    logger_module._verbosity = VERBOSITY_TRACE
    console.cache_clear()
    monkeypatch.setattr("r2x_core.logger.console", lambda: None)

    level_mock = mock.Mock()
    level_mock.name = "INFO"

    record = {
        "level": level_mock,
        "message": "test with everything",
        "extra": {"request_id": "12345", "user": "alice", "name": "ignored"},
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "exception": None,
    }

    format_tty(record)
    output = capsys.readouterr().err
    assert "test with everything" in output
    assert "INFO" in output
    assert "2026-01" in output or "10:30" in output
    assert "request_id" in output or "12345" in output


def test_format_tty_fallback_only_extras(monkeypatch, capsys):
    """Test fallback TTY formatting with extras but no timestamp."""
    import r2x_core.logger as logger_module

    logger_module._verbosity = 0
    console.cache_clear()
    monkeypatch.setattr("r2x_core.logger.console", lambda: None)

    level_mock = mock.Mock()
    level_mock.name = "WARNING"

    record = {
        "level": level_mock,
        "message": "warning with extras",
        "extra": {"code": 500, "retries": 3, "name": "ignored"},
        "exception": None,
    }

    format_tty(record)
    output = capsys.readouterr().err
    assert "warning with extras" in output
    assert "WARN" in output
    assert "code" in output or "500" in output


def test_format_json_with_no_file():
    """Test JSON formatting when file info is missing."""
    level_mock = mock.Mock()
    level_mock.name = "TRACE"

    record = {
        "level": level_mock,
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "message": "trace message",
        "extra": {},
        "file": None,
        "exception": None,
    }
    result = format_json(record)
    payload = json.loads(result)

    assert payload["msg"] == "trace message"
    assert "file" not in payload
    assert "line" not in payload


def test_render_exception_no_traceback():
    """Test render_exception with exception but no traceback does nothing."""
    exc = mock.Mock()
    exc.type = ValueError
    exc.value = ValueError("test")
    exc.traceback = None

    record = {"exception": exc}
    render_exception(record, None)


def test_format_json_with_exception_no_traceback():
    """Test JSON formatting with exception but no traceback."""
    level_mock = mock.Mock()
    level_mock.name = "ERROR"

    exc = mock.Mock()
    exc.type = RuntimeError
    exc.value = RuntimeError("No trace")
    exc.traceback = None

    record = {
        "level": level_mock,
        "time": datetime(2026, 1, 18, 10, 30, 45, 123456),
        "message": "error without traceback",
        "extra": {},
        "file": None,
        "exception": exc,
    }
    result = format_json(record)
    payload = json.loads(result)

    assert "error" in payload
    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["message"] == "No trace"
    assert "traceback" not in payload["error"]


def test_setup_logging_no_sinks_raises():
    """Test that setup_logging raises ValueError when both sinks are disabled."""
    import pytest

    with pytest.raises(ValueError, match="no sinks"):
        setup_logging(verbosity=0, log_file=None, log_to_console=False)


def test_setup_logging_with_log_file(tmp_path):
    """Test setup_logging writes to file when log_file is provided."""
    from loguru import logger as loguru_logger

    log_file = tmp_path / "test.log"
    setup_logging(verbosity=VERBOSITY_TRACE, log_file=str(log_file))

    loguru_logger.enable("r2x_core")
    loguru_logger.info("file sink test message")

    import time

    time.sleep(0.1)

    contents = log_file.read_text()
    assert "file sink test message" in contents
    assert "[PYTHON]" in contents


def test_setup_logging_without_log_file():
    """Test setup_logging works without log_file (no file sink added)."""
    import r2x_core.logger as logger_module

    setup_logging(verbosity=VERBOSITY_INFO)
    assert logger_module._verbosity == VERBOSITY_INFO


def test_setup_logging_log_to_console_false_no_stderr(tmp_path, capsys):
    """Test setup_logging with log_to_console=False produces no stderr output."""
    from loguru import logger as loguru_logger

    log_file = tmp_path / "console_off.log"
    setup_logging(verbosity=VERBOSITY_TRACE, log_file=str(log_file), log_to_console=False)

    loguru_logger.enable("r2x_core")
    loguru_logger.info("should not appear on console")

    output = capsys.readouterr().err
    assert "should not appear on console" not in output


def test_setup_logging_log_to_console_true_has_stderr(monkeypatch, capsys):
    """Test setup_logging with log_to_console=True writes to stderr."""
    console.cache_clear()
    monkeypatch.setattr("r2x_core.logger.console", lambda: None)

    from loguru import logger as loguru_logger

    setup_logging(verbosity=VERBOSITY_TRACE, log_to_console=True)

    loguru_logger.enable("r2x_core")
    loguru_logger.info("should appear on console")

    output = capsys.readouterr().err
    assert "should appear on console" in output


def test_setup_logging_file_and_console(tmp_path, monkeypatch, capsys):
    """Test setup_logging with both file and console sinks active."""
    console.cache_clear()
    monkeypatch.setattr("r2x_core.logger.console", lambda: None)

    from loguru import logger as loguru_logger

    log_file = tmp_path / "both.log"
    setup_logging(
        verbosity=VERBOSITY_TRACE,
        log_file=str(log_file),
        log_to_console=True,
    )

    loguru_logger.enable("r2x_core")
    loguru_logger.info("dual sink message")

    import time

    time.sleep(0.1)

    contents = log_file.read_text()
    assert "dual sink message" in contents

    output = capsys.readouterr().err
    assert "dual sink message" in output


def test_setup_logging_file_captures_all_levels(tmp_path):
    """Test that the file sink captures TRACE level even when console would filter."""
    from loguru import logger as loguru_logger

    log_file = tmp_path / "trace.log"
    setup_logging(
        verbosity=0,  # Console would only show WARNING+
        log_file=str(log_file),
        log_to_console=False,
    )

    loguru_logger.enable("r2x_core")
    loguru_logger.trace("trace level message")
    loguru_logger.debug("debug level message")
    loguru_logger.warning("warning level message")

    import time

    time.sleep(0.1)

    contents = log_file.read_text()
    assert "trace level message" in contents
    assert "debug level message" in contents
    assert "warning level message" in contents
