"""Tests for upgrade coordination contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_core import ErrorDetails, InitErrorDetails
from rust_ok import Err

from r2x_core import DataStore, PluginConfig, PluginContext
from r2x_core.exceptions import UpgradeError
from r2x_core.utils.upgrade import UpgradeCoordinator, is_missing_file_error


def test_is_missing_file_error_detects_exception_type() -> None:
    error: ErrorDetails = {
        "type": "value_error",
        "msg": "test error",
        "input": "ignored",
        "loc": ("fpath",),
        "ctx": {"exc_type": "FileNotFoundError"},
    }
    assert is_missing_file_error(error)


def test_is_missing_file_error_requires_exception_type() -> None:
    error: ErrorDetails = {
        "type": "value_error",
        "msg": "Missing required file: /tmp/foo",
        "input": "Missing required file: /tmp/foo",
        "loc": ("fpath",),
        "ctx": {"error": "Missing required file: /tmp/foo"},
    }
    assert not is_missing_file_error(error)


def test_is_missing_file_error_false_for_other_errors() -> None:
    error: ErrorDetails = {
        "type": "value_error",
        "msg": "bad input",
        "input": "bad input",
        "loc": ("fpath",),
        "ctx": {"error": "bad input", "exc_type": "ValueError"},
    }
    assert not is_missing_file_error(error)


def test_upgrade_coordinator_resolves_handler_from_plugin_config() -> None:
    def handler(*, store: DataStore, ctx: PluginContext[Any]) -> None:
        return None

    config = PluginConfig(upgrade_handler=handler)
    coordinator = UpgradeCoordinator(plugin_config=config)
    coordinator.resolve()

    assert coordinator.handler is handler


def test_upgrade_coordinator_rejects_handler_without_plugin_config() -> None:
    def handler(*, store: DataStore, ctx: PluginContext[Any]) -> None:
        return None

    with pytest.raises(ValueError, match="plugin_config is required"):
        UpgradeCoordinator(handler=handler)


@pytest.mark.parametrize("has_configured_handler", [False, True])
def test_upgrade_coordinator_prefers_explicit_falsey_handler(
    tmp_path: Path, has_configured_handler: bool
) -> None:
    calls: list[str] = []

    def configured_handler(*, store: DataStore, ctx: PluginContext[Any]) -> None:
        calls.append("configured")

    class FalseyHandler:
        def __bool__(self) -> bool:
            return False

        def __call__(self, *, store: DataStore, ctx: PluginContext[Any]) -> None:
            calls.append("explicit")

    explicit_handler = FalseyHandler()
    config = PluginConfig(upgrade_handler=configured_handler if has_configured_handler else None)
    coordinator = UpgradeCoordinator(plugin_config=config, handler=explicit_handler)

    coordinator.run(store=DataStore(path=tmp_path), reason="test")

    assert coordinator.handler is explicit_handler
    assert calls == ["explicit"]


def test_upgrade_coordinator_runs_and_marks(tmp_path: Path) -> None:
    calls: list[tuple[DataStore, PluginContext[Any]]] = []

    def handler(*, store: DataStore, ctx: PluginContext[Any]) -> None:
        calls.append((store, ctx))

    config = PluginConfig(upgrade_handler=handler)
    coordinator = UpgradeCoordinator(plugin_config=config)
    store = DataStore(path=tmp_path)

    coordinator.run(store=store, reason="test")

    assert len(calls) == 1
    assert calls[0][0] is store
    assert calls[0][1].config is config
    assert calls[0][1].store is store
    assert coordinator.ran is True


def test_upgrade_coordinator_raises_on_result_error(tmp_path: Path) -> None:
    def handler(*, store: DataStore, ctx: PluginContext[Any]) -> Err[None, str]:
        return Err("boom")

    coordinator = UpgradeCoordinator(plugin_config=PluginConfig(upgrade_handler=handler))
    store = DataStore(path=tmp_path)

    with pytest.raises(UpgradeError, match="boom"):
        coordinator.run(store=store, reason="bad")


def test_upgrade_coordinator_should_attempt() -> None:
    error: InitErrorDetails = {
        "type": "value_error",
        "input": "ignored",
        "loc": ("fpath",),
        "ctx": {"error": "missing input", "exc_type": "FileNotFoundError"},
    }
    validation_error = ValidationError.from_exception_data(title="missing", line_errors=[error])

    def handler(*, store: DataStore, ctx: PluginContext[Any]) -> None:
        return None

    coordinator = UpgradeCoordinator(plugin_config=PluginConfig(upgrade_handler=handler))
    assert coordinator.should_attempt(validation_error)


def test_upgrade_coordinator_preserves_raised_exception_cause(tmp_path: Path) -> None:
    cause = FileNotFoundError("missing input")

    def handler(*, store: DataStore, ctx: PluginContext[Any]) -> None:
        raise cause

    coordinator = UpgradeCoordinator(plugin_config=PluginConfig(upgrade_handler=handler))
    with pytest.raises(UpgradeError) as exc_info:
        coordinator.run(store=DataStore(path=tmp_path), reason="test")

    assert exc_info.value.__cause__ is cause
    assert coordinator.ran is False


def test_upgrade_coordinator_propagates_programming_errors(tmp_path: Path) -> None:
    cause = TypeError("invalid handler")

    def handler(*, store: DataStore, ctx: PluginContext[Any]) -> None:
        raise cause

    coordinator = UpgradeCoordinator(plugin_config=PluginConfig(upgrade_handler=handler))
    with pytest.raises(TypeError) as exc_info:
        coordinator.run(store=DataStore(path=tmp_path), reason="test")

    assert exc_info.value is cause
    assert coordinator.ran is False
