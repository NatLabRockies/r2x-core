"""Tests for r2x_core.utils.version.

Covers both the safe ``get_package_version`` lookup and the forward-compat
``warn_if_persisted_version_newer_than_installed`` helper.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from loguru import logger
from packaging.version import Version

import r2x_core.utils.version as version_mod
from r2x_core.utils import (
    UNKNOWN_VERSION,
    get_package_version,
    warn_if_persisted_version_newer_than_installed,
)


@pytest.fixture
def captured_warnings() -> Iterator[list[str]]:
    """Capture warnings emitted from within ``r2x_core`` for the duration of one test.

    Loguru sinks fire for messages emitted from modules that are enabled.
    ``r2x_core`` disables its own logger at import time
    (see ``r2x_core/__init__.py``), so to observe warnings that r2x_core
    code emits we temporarily re-enable the module and restore the disabled
    state on teardown; that keeps the rest of the test suite's logging
    posture identical to what it inherited on import.

    The sink captures only the formatted message text (not the full record
    with timestamp/level/module prefixes) so assertions stay stable if
    loguru's default format ever changes.
    """
    messages: list[str] = []
    logger.enable("r2x_core")
    handler_id = logger.add(
        lambda msg: messages.append(msg.record["message"]),
        level="WARNING",
    )
    try:
        yield messages
    finally:
        logger.remove(handler_id)
        # Restore the disabled state r2x_core sets at import time. If a
        # future test intentionally leaves r2x_core enabled and then uses
        # this fixture, that test should snapshot/restore its own state.
        logger.disable("r2x_core")


def test_get_package_version_returns_string_for_installed_package() -> None:
    """For an installed distribution, the helper returns its real version."""
    installed = get_package_version("r2x_core")
    assert isinstance(installed, str)
    assert installed != UNKNOWN_VERSION


def test_get_package_version_returns_fallback_for_missing_package() -> None:
    """For a distribution that isn't installed, the helper returns the fallback string."""
    assert get_package_version("definitely-not-a-real-package-xyz") == UNKNOWN_VERSION


def test_get_package_version_honors_custom_fallback() -> None:
    """The fallback keyword is honored when the package is missing."""
    assert get_package_version("definitely-not-a-real-package-xyz", fallback="n/a") == "n/a"


def test_warn_when_persisted_newer_logs_warning(captured_warnings: list[str]) -> None:
    """A persisted version newer than the installed one produces a warning."""
    warn_if_persisted_version_newer_than_installed(Version("9999.0.0"), package_name="r2x_core")
    assert any("9999.0.0" in m and "r2x_core" in m for m in captured_warnings)


def test_no_warning_when_persisted_not_newer(captured_warnings: list[str]) -> None:
    """A persisted version equal to or older than installed does not warn."""
    warn_if_persisted_version_newer_than_installed(Version("0.0.1"), package_name="r2x_core")
    assert captured_warnings == []


def test_no_warning_when_installed_version_unparseable(
    monkeypatch: pytest.MonkeyPatch, captured_warnings: list[str]
) -> None:
    """If the installed version cannot be parsed as PEP 440, the check exits quietly.

    Reachable when the package is used from a source tree with no distribution
    metadata, so ``get_package_version`` returns the ``"unknown"`` fallback.
    """
    monkeypatch.setattr(version_mod, "get_package_version", lambda _name: "unknown")
    warn_if_persisted_version_newer_than_installed(Version("9999.0.0"), package_name="r2x_core")
    assert captured_warnings == []


def test_warn_uses_configured_package_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper looks up the version for the passed package_name, not a hardcoded one."""
    calls: list[str] = []

    def _spy(name: str, *, fallback: str = UNKNOWN_VERSION) -> str:
        calls.append(name)
        return "1.0.0"

    monkeypatch.setattr(version_mod, "get_package_version", _spy)
    warn_if_persisted_version_newer_than_installed(Version("0.9.0"), package_name="some_other_package")
    assert calls == ["some_other_package"]
