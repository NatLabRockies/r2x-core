"""Upgrade utilities for R2X Core.

This module provides the upgrade execution infrastructure including:

- **UpgradeType**: Enum defining FILE vs SYSTEM upgrade operations
- **UpgradeStep**: Named tuple representing a single upgrade operation
- **shall_we_upgrade()**: Version-based upgrade decision logic
- **run_datafile_upgrades()**: Execute file-based upgrades in priority order
- **run_system_upgrades()**: Execute system data upgrades in priority order

The upgrade system uses a priority queue where lower numbers execute first.
Version comparison is delegated to configurable VersionStrategy implementations.
"""

import inspect
from collections.abc import Callable
from enum import Enum
from typing import Annotated, Any

from loguru import logger
from pydantic import BaseModel, PrivateAttr
from rust_ok import Err, Ok, Result

from ..exceptions import UpgradeError
from ..versioning import VersionStrategy


class UpgradeType(str, Enum):
    """Type of upgrade operation.

    Attributes
    ----------
    FILE : str
        File system operations on raw data files (rename, move, modify).
        Applied before parser and DataStore initialization via upgrade_data().
        This is the default upgrade type used in the normal parser workflow.
    SYSTEM : str
        System object modifications for cached systems.
        Applied when loading saved systems via System.from_json(upgrader=...).
        Only used when loading cached systems, not in the default parser workflow.
    """

    FILE = "FILE"
    SYSTEM = "SYSTEM"


class UpgradeStep(BaseModel):
    """Definition of a single upgrade step.

    Attributes
    ----------
    name : str
        Unique name for the upgrade step.
    func : callable
        Function to execute the upgrade. Should accept data and return upgraded data.
        May optionally accept upgrader_context keyword argument.
    target_version : str
        The version this upgrade targets.
    upgrade_type : UpgradeType
        Type of upgrade: FILE or SYSTEM.
    priority : int, default=100
        Priority for upgrade execution (lower numbers run first).
    min_version : str | None, default=None
        Minimum version required for this upgrade.
    max_version : str | None, default=None
        Maximum version this upgrade is compatible with.
    """

    name: str
    func: Annotated[Callable[..., Any], Any]
    target_version: str
    upgrade_type: UpgradeType
    priority: int = 100
    min_version: str | None = None
    max_version: str | None = None
    _sig: inspect.Signature | None = PrivateAttr(None)


def shall_we_upgrade(
    step: UpgradeStep, *, current_version: str, strategy: VersionStrategy | None = None
) -> Result[bool, UpgradeError]:
    """Determine if upgrade step should execute based on version constraints.

    Parameters
    ----------
    step : UpgradeStep
        Upgrade step to evaluate
    current_version : str
        Current data version
    strategy : VersionStrategy | None
        Version comparison strategy; if None, always skip upgrade

    Returns
    -------
    Result[bool, UpgradeError]
        Ok(True) if upgrade needed, Ok(False) if skip, Err on failure

    Notes
    -----
    Skips upgrade if:
    - Already at or past target version
    - Below minimum required version
    - Above maximum supported version
    """
    if strategy is None:
        return Ok(False)

    logger.debug("Evaluating {}: current={}, target={}", step.name, current_version, step.target_version)

    if strategy.compare_versions(current_version, target=step.target_version) >= 0:
        logger.debug("Skipping {}: already at target version", step.name)
        return Ok(False)

    if step.min_version and strategy.compare_versions(current_version, target=step.min_version) < 0:
        logger.warning(
            "Skipping {}: current version {} below minimum {}",
            step.name,
            current_version,
            step.min_version,
        )
        return Ok(False)

    if step.max_version and strategy.compare_versions(current_version, target=step.max_version) > 0:
        logger.warning(
            "Skipping {}: current version {} above maximum {}",
            step.name,
            current_version,
            step.max_version,
        )
        return Ok(False)

    return Ok(True)


def run_upgrade_step(
    data: Any, *, step: UpgradeStep, upgrader_context: Any | None = None
) -> Result[Any, str]:
    r"""Execute a single upgrade transformation on data.

    Applies the upgrade function defined in the step, automatically detecting
    whether the function accepts an upgrader_context parameter using introspection.
    This allows flexibility in step function signatures.

    Parameters
    ----------
    data : Any
        Input data to be upgraded by the step function.
    step : UpgradeStep
        The upgrade step to execute with func, name, and target_version.
    upgrader_context : Any | None
        Optional context object passed to the upgrade function if it accepts
        upgrader_context as a parameter (detected via inspect.signature).
        Allows steps to access global upgrader state. Default is None.

    Returns
    -------
    Result[Any, str]
        Ok(upgraded_data) on success, Err(error_message) on failure.

    Raises
    ------
    (via Result)
        ValueError if step function signature detection fails (wrapped in Err)
        Other exceptions from step.func are caught and wrapped as Err with message

    Notes
    -----
    Introspection behavior:
    - If function has upgrader_context parameter: called with upgrader_context kwarg
    - If function accepts \\*\\*kwargs: called with upgrader_context kwarg
    - Otherwise: called with only data argument

    This allows upgrade steps to optionally use context without explicit interface.
    """
    logger.debug("Applying upgrade step: {}", step.name)
    try:
        # Cache the signature on the step to avoid repeated introspection
        sig = step._sig
        if sig is None:
            sig = inspect.signature(step.func)
            object.__setattr__(step, "_sig", sig)

        if "upgrader_context" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        ):
            data = step.func(data, upgrader_context=upgrader_context)
        else:
            data = step.func(data)
    except Exception as e:
        return Err(f"Failed {step.name}: {e}")
    logger.info("Successfully applied upgrade: {} -> {}", step.name, step.target_version)
    return Ok(data)
