"""Tests for upgrade coordination helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails, InitErrorDetails
from rust_ok import Err

from r2x_core import DataStore, PluginConfig
from r2x_core.exceptions import UpgradeError
from r2x_core.utils.upgrade import (
    UpgradeCoordinator,
    _is_missing_file_error,
    _resolve_upgrade_handler,
)


def test_is_missing_file_error_detects_exc_type() -> None:
    error: ErrorDetails = {
        "type": "value_error",
        "msg": "test error",
        "input": "ignored",
        "loc": ("fpath",),
        "ctx": {"exc_type": "FileNotFoundError"},
    }
    assert _is_missing_file_error(error)


def test_is_missing_file_error_matches_message() -> None:
    error: ErrorDetails = {
        "type": "value_error",
        "msg": "Missing required file: /tmp/foo",
        "input": "Missing required file: /tmp/foo",
        "loc": ("fpath",),
        "ctx": {"error": "Missing required file: /tmp/foo"},
    }
    assert _is_missing_file_error(error)


def test_is_missing_file_error_false_for_other_errors() -> None:
    error: ErrorDetails = {
        "type": "value_error",
        "msg": "bad input",
        "input": "bad input",
        "loc": ("fpath",),
        "ctx": {"error": "bad input"},
    }
    assert not _is_missing_file_error(error)


def test_resolve_upgrade_handler_from_property() -> None:
    def handler(*, store: DataStore) -> None:
        return None

    class PropertyConfig(PluginConfig):
        @property
        def upgrade_handler(self) -> Any:
            return handler

    config = PropertyConfig()
    assert _resolve_upgrade_handler(config) is handler


def test_resolve_upgrade_handler_from_getter() -> None:
    def handler(*, store: DataStore) -> None:
        return None

    class GetterConfig(PluginConfig):
        def get_upgrade_handler(self) -> Any:
            return handler

    config = GetterConfig()
    assert _resolve_upgrade_handler(config) is handler


def test_resolve_upgrade_handler_from_module(tmp_path: Path) -> None:
    package_dir = tmp_path / "r2x_dummy"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "upgrader.py").write_text(
        "def run_dummy_upgrades(*, store=None):\n    return None\n",
        encoding="utf-8",
    )
    (package_dir / "config.py").write_text(
        "from r2x_core import PluginConfig\n\nclass DummyConfig(PluginConfig):\n    pass\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(tmp_path))
    try:
        from r2x_dummy.config import DummyConfig  # type: ignore[import-not-found]

        config = DummyConfig()
        handler = _resolve_upgrade_handler(config)
        assert handler is not None
        assert handler.__name__ == "run_dummy_upgrades"  # type: ignore[union-attr]
    finally:
        sys.path.remove(str(tmp_path))
        for module_name in list(sys.modules):
            if module_name.startswith("r2x_dummy"):
                del sys.modules[module_name]


def test_upgrade_coordinator_runs_and_marks(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handler(*, store: DataStore) -> None:
        calls["count"] += 1
        return None

    coordinator = UpgradeCoordinator(handler=handler)
    store = DataStore(path=tmp_path)

    coordinator.run(store=store, reason="test")

    assert calls["count"] == 1
    assert coordinator.ran is True


def test_upgrade_coordinator_raises_on_err(tmp_path: Path) -> None:
    def handler(*, store: DataStore) -> Err[None, str]:
        return Err("boom")

    coordinator = UpgradeCoordinator(handler=handler)
    store = DataStore(path=tmp_path)

    with pytest.raises(UpgradeError, match="boom"):
        coordinator.run(store=store, reason="bad")


def test_upgrade_coordinator_should_attempt() -> None:
    error: InitErrorDetails = {
        "type": "value_error",
        "input": "ignored",
        "loc": ("fpath",),
        "ctx": {"error": "Missing required file: /tmp/foo", "exc_type": "FileNotFoundError"},
    }
    exc = ValidationError.from_exception_data(title="missing", line_errors=[error])

    def handler(*, store: DataStore) -> None:
        return None

    coordinator = UpgradeCoordinator(handler=handler)
    assert coordinator.should_attempt(exc)
