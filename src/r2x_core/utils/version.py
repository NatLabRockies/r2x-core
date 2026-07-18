"""Utilities for looking up and comparing installed package versions safely."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any

from loguru import logger
from packaging.version import InvalidVersion, Version
from pydantic import BeforeValidator

UNKNOWN_VERSION = "unknown"


def coerce_version(value: Any) -> Version:
    """Accept a Version or PEP 440 string; raise a clear error otherwise.

    Parameters
    ----------
    value : Any
        A :class:`packaging.version.Version` or a PEP 440 version string.

    Returns
    -------
    Version
        The coerced version.
    """
    if isinstance(value, Version):
        return value
    if isinstance(value, str):
        try:
            return Version(value)
        except InvalidVersion as exc:
            raise ValueError(f"{value!r} is not a valid PEP 440 version") from exc
    raise TypeError(f"expected str or packaging.version.Version, got {type(value).__name__}")


VersionField = Annotated[Version, BeforeValidator(coerce_version)]
"""A pydantic field type that accepts a Version or PEP 440 string."""


def get_package_version(package_name: str, *, fallback: str = UNKNOWN_VERSION) -> str:
    """Return the installed version of ``package_name`` or ``fallback`` if unavailable.

    A resilient wrapper around :func:`importlib.metadata.version` that avoids
    raising when the package metadata is missing. That case shows up in
    practice when the code is exercised from a source tree without an
    accompanying ``pip install`` / ``uv sync``.

    Parameters
    ----------
    package_name : str
        Distribution name to look up (e.g. ``"r2x_core"``).
    fallback : str
        Value returned when the package's metadata cannot be found. Defaults
        to ``"unknown"``.

    Returns
    -------
    str
        The installed version string, or ``fallback``.

    Examples
    --------
    >>> from r2x_core.utils.version import get_package_version
    >>> installed = get_package_version("r2x_core")
    >>> isinstance(installed, str)
    True
    >>> get_package_version("definitely-not-installed-xyz")
    'unknown'
    """
    try:
        return version(package_name)
    except PackageNotFoundError:
        return fallback


def warn_if_persisted_version_newer_than_installed(
    persisted: Version,
    *,
    package_name: str,
) -> None:
    """Log a warning if ``persisted`` is a newer version than the one installed.

    Intended for forward-compatibility checks on serialized artifacts: an
    artifact carries the version of the package that produced it, and on load
    we want to warn (not fail) if the installed package is older than the one
    that wrote the file.

    Non-fatal by design: forward-incompatible metadata should degrade to "we
    do not fully understand this" rather than "we refuse to open it".

    If the installed version is not PEP 440 parseable (e.g. the package is
    running from a source checkout with no distribution metadata and
    :func:`get_package_version` returned its fallback), the check exits
    quietly at debug level.

    Parameters
    ----------
    persisted : Version
        The version recorded in the persisted artifact.
    package_name : str
        Distribution name to look up the installed version for.

    Examples
    --------
    >>> from packaging.version import Version
    >>> from r2x_core.utils.version import warn_if_persisted_version_newer_than_installed
    >>> # No-op when the persisted version is not newer.
    >>> warn_if_persisted_version_newer_than_installed(Version("0.0.1"), package_name="r2x_core")
    """
    try:
        installed = Version(get_package_version(package_name))
    except InvalidVersion:
        logger.debug(
            "Installed {} version is not PEP 440 parseable; skipping compatibility check",
            package_name,
        )
        return

    if persisted > installed:
        logger.warning(
            "Artifact was produced by {} {} but {} {} is installed; "
            "persisted data may reference features this version does not handle.",
            package_name,
            persisted,
            package_name,
            installed,
        )
