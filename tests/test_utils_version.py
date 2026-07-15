"""Tests for r2x_core.utils.version.

Covers both the safe ``get_package_version`` lookup and the forward-compat
``warn_if_persisted_version_newer_than_installed`` helper.
"""

from __future__ import annotations

import pytest
from loguru import logger
from packaging.version import Version

import r2x_core.utils.version as version_mod
from r2x_core.utils import (
    UNKNOWN_VERSION,
    get_package_version,
    warn_if_persisted_version_newer_than_installed,
)


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


def _capture_warnings() -> tuple[list[str], int]:
    """Add a loguru sink that records warning-level messages and return (sink, handler_id)."""
    logger.enable("r2x_core")
    messages: list[str] = []
    handler_id = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
    return messages, handler_id


def test_warn_when_persisted_newer_logs_warning() -> None:
    """A persisted version newer than the installed one produces a warning."""
    messages, handler_id = _capture_warnings()
    try:
        warn_if_persisted_version_newer_than_installed(
            Version("9999.0.0"), package_name="r2x_core"
        )
    finally:
        logger.remove(handler_id)

    assert any("9999.0.0" in m and "r2x_core" in m for m in messages)


def test_no_warning_when_persisted_not_newer() -> None:
    """A persisted version equal to or older than installed does not warn."""
    messages, handler_id = _capture_warnings()
    try:
        warn_if_persisted_version_newer_than_installed(
            Version("0.0.1"), package_name="r2x_core"
        )
    finally:
        logger.remove(handler_id)

    assert messages == []


def test_no_warning_when_installed_version_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the installed version cannot be parsed as PEP 440, the check exits quietly.

    Reachable when the package is used from a source tree with no distribution
    metadata, so ``get_package_version`` returns the ``\"unknown\"`` fallback.
    """
    monkeypatch.setattr(version_mod, "get_package_version", lambda _name: "unknown")
    messages, handler_id = _capture_warnings()
    try:
        warn_if_persisted_version_newer_than_installed(
            Version("9999.0.0"), package_name="r2x_core"
        )
    finally:
        logger.remove(handler_id)

    assert messages == []


def test_warn_uses_configured_package_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper looks up the version for the passed package_name, not a hardcoded one."""
    calls: list[str] = []

    def _spy(name: str, *, fallback: str = UNKNOWN_VERSION) -> str:
        calls.append(name)
        return "1.0.0"

    monkeypatch.setattr(version_mod, "get_package_version", _spy)
    warn_if_persisted_version_newer_than_installed(
        Version("0.9.0"), package_name="some_other_package"
    )
    assert calls == ["some_other_package"]
