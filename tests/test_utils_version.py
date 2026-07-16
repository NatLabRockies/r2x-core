"""Tests for r2x_core.utils.version.

Covers both the safe ``get_package_version`` lookup and the forward-compat
``warn_if_persisted_version_newer_than_installed`` helper.
"""

from __future__ import annotations

import pytest
from packaging.version import Version

import r2x_core.utils.version as version_mod
from r2x_core.utils import (
    UNKNOWN_VERSION,
    get_package_version,
    warn_if_persisted_version_newer_than_installed,
)


class CapturingLogger:
    """Small logger test double that captures rendered warning messages."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.debugs: list[str] = []

    def warning(self, message: str, *args: object) -> None:
        """Capture a rendered warning message."""
        self.warnings.append(message.format(*args))

    def debug(self, message: str, *args: object) -> None:
        """Capture a rendered debug message."""
        self.debugs.append(message.format(*args))


def test_get_package_version_returns_string_for_installed_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """For an installed distribution, the helper returns its real version.

    Monkeypatches the underlying ``importlib.metadata.version`` so the test
    does not depend on how the current environment installed r2x-core (in
    a source checkout without dist metadata, the real lookup would return
    the fallback and this assertion would flap).
    """
    monkeypatch.setattr(version_mod, "version", lambda _name: "1.2.3")
    assert get_package_version("r2x_core") == "1.2.3"


def test_get_package_version_returns_fallback_for_missing_package() -> None:
    """For a distribution that isn't installed, the helper returns the fallback string."""
    assert get_package_version("definitely-not-a-real-package-xyz") == UNKNOWN_VERSION


def test_get_package_version_honors_custom_fallback() -> None:
    """The fallback keyword is honored when the package is missing."""
    assert get_package_version("definitely-not-a-real-package-xyz", fallback="n/a") == "n/a"


def test_warn_when_persisted_newer_logs_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """A persisted version newer than the installed one produces a warning.

    Pins the installed version through the helper so the test outcome does
    not depend on which r2x-core version the environment reports (or
    whether it reports one at all). Uses a logger test double instead of
    mutating global loguru enable/disable state.
    """
    logger = CapturingLogger()
    monkeypatch.setattr(version_mod, "logger", logger)
    monkeypatch.setattr(version_mod, "get_package_version", lambda _name: "1.0.0")

    warn_if_persisted_version_newer_than_installed(Version("9999.0.0"), package_name="r2x_core")

    assert any("9999.0.0" in m and "r2x_core" in m for m in logger.warnings)
    assert logger.debugs == []


def test_no_warning_when_persisted_not_newer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A persisted version equal to or older than installed does not warn."""
    logger = CapturingLogger()
    monkeypatch.setattr(version_mod, "logger", logger)
    monkeypatch.setattr(version_mod, "get_package_version", lambda _name: "1.0.0")

    warn_if_persisted_version_newer_than_installed(Version("0.0.1"), package_name="r2x_core")

    assert logger.warnings == []
    assert logger.debugs == []


def test_no_warning_when_installed_version_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the installed version cannot be parsed as PEP 440, the check exits quietly.

    Reachable when the package is used from a source tree with no distribution
    metadata, so ``get_package_version`` returns the ``"unknown"`` fallback.
    """
    logger = CapturingLogger()
    monkeypatch.setattr(version_mod, "logger", logger)
    monkeypatch.setattr(version_mod, "get_package_version", lambda _name: "unknown")

    warn_if_persisted_version_newer_than_installed(Version("9999.0.0"), package_name="r2x_core")

    assert logger.warnings == []
    assert logger.debugs == [
        "Installed r2x_core version is not PEP 440 parseable; skipping compatibility check"
    ]


def test_warn_uses_configured_package_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper looks up the version for the passed package_name, not a hardcoded one."""
    calls: list[str] = []

    def _spy(name: str, *, fallback: str = UNKNOWN_VERSION) -> str:
        calls.append(name)
        return "1.0.0"

    monkeypatch.setattr(version_mod, "get_package_version", _spy)
    warn_if_persisted_version_newer_than_installed(Version("0.9.0"), package_name="some_other_package")
    assert calls == ["some_other_package"]
