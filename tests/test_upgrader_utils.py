"""Tests for :mod:`r2x_core.upgrader_utils` helpers."""

import pytest

from r2x_core import UpgradeError
from r2x_core.utils import (
    UpgradeStep,
    UpgradeType,
    run_upgrade_step,
    shall_we_upgrade,
)
from r2x_core.versioning import SemanticVersioningStrategy


def _dummy_step(
    *,
    target_version: str = "2.0",
    min_version: str | None = None,
    max_version: str | None = None,
) -> UpgradeStep:
    return UpgradeStep(
        name="dummy",
        func=lambda data: data,
        target_version=target_version,
        upgrade_type=UpgradeType.FILE,
        min_version=min_version,
        max_version=max_version,
    )


def test_shall_we_upgrade_below_minimum_returns_false():
    step = _dummy_step(target_version="3.0", min_version="2.0")
    strategy = SemanticVersioningStrategy()

    result = shall_we_upgrade(step, current_version="1.5", strategy=strategy)
    assert result.is_ok()
    assert result.unwrap() is False


def test_shall_we_upgrade_above_maximum_returns_false():
    step = _dummy_step(target_version="10.0", max_version="5.0")
    strategy = SemanticVersioningStrategy()

    result = shall_we_upgrade(step, current_version="6.0", strategy=strategy)
    assert result.is_ok()
    assert result.unwrap() is False


def test_shall_we_upgrade_within_range_returns_true():
    step = _dummy_step(target_version="3.0", min_version="1.0", max_version="4.0")
    strategy = SemanticVersioningStrategy()

    result = shall_we_upgrade(step, current_version="2.0", strategy=strategy)
    assert result.is_ok()
    assert result.unwrap() is True


def test_run_upgrade_step_passes_context_when_supported():
    def step_func(data, upgrader_context=None):
        assert upgrader_context == {"info": "value"}
        return data + 1

    step = UpgradeStep(
        name="context-step",
        func=step_func,
        target_version="1.0",
        upgrade_type=UpgradeType.FILE,
    )

    result = run_upgrade_step(41, step=step, upgrader_context={"info": "value"})
    assert result.is_ok()
    assert result.unwrap() == 42


@pytest.mark.parametrize("error_type", [UpgradeError, FileNotFoundError, ValueError])
def test_run_upgrade_step_preserves_expected_exception(error_type: type[Exception]) -> None:
    cause = error_type("boom")

    def broken_step(data: str) -> str:
        raise cause

    step = UpgradeStep(
        name="broken-step",
        func=broken_step,
        target_version="1.0",
        upgrade_type=UpgradeType.FILE,
    )

    result = run_upgrade_step("ignored", step=step)
    assert result.is_err()
    error = result.err()
    assert isinstance(error, UpgradeError)
    assert str(error) == "Failed broken-step: boom"
    assert error.__cause__ is cause


@pytest.mark.parametrize("error_type", [RuntimeError, TypeError, AttributeError, KeyError])
def test_run_upgrade_step_propagates_programming_errors(error_type: type[Exception]) -> None:
    cause = error_type("boom")

    def broken_step(data: str) -> str:
        raise cause

    step = UpgradeStep(
        name="broken-step",
        func=broken_step,
        target_version="1.0",
        upgrade_type=UpgradeType.FILE,
    )
    with pytest.raises(error_type) as exc_info:
        run_upgrade_step("ignored", step=step)
    assert exc_info.value is cause
