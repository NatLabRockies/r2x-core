"""Upgrade infrastructure: steps, coordination, and version-based execution."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any

from loguru import logger
from pydantic import BaseModel
from rust_ok import Err, Ok, Result

from ..exceptions import UpgradeError
from ..plugin_context import PluginContext
from ..versioning import UpgradeHandler, VersionStrategy

if TYPE_CHECKING:
    from ..plugin_config import PluginConfig
    from ..store import DataStore


# ── Upgrade types and steps ────────────────────────────────────────


class UpgradeType(str, Enum):
    """Type of upgrade operation.

    * FILE  — file system operations on raw data files
    * SYSTEM — system object modifications for cached systems
    """

    FILE = "FILE"
    SYSTEM = "SYSTEM"


class UpgradeStep(BaseModel):
    """Definition of a single upgrade step."""

    name: str
    func: Annotated[Callable[..., Any], Any]
    target_version: str
    upgrade_type: UpgradeType
    priority: int = 100
    min_version: str | None = None
    max_version: str | None = None


def shall_we_upgrade(
    step: UpgradeStep, *, current_version: str, strategy: VersionStrategy | None = None
) -> Result[bool, UpgradeError]:
    """Determine if an upgrade step should execute based on version constraints."""
    if strategy is None:
        return Ok(False)

    logger.debug("Evaluating {}: current={}, target={}", step.name, current_version, step.target_version)

    if strategy.compare_versions(current_version, target=step.target_version) >= 0:
        logger.debug("Skipping {}: already at target version", step.name)
        return Ok(False)

    if step.min_version and strategy.compare_versions(current_version, target=step.min_version) < 0:
        logger.warning(
            "Skipping {}: current version {} below minimum {}", step.name, current_version, step.min_version
        )
        return Ok(False)

    if step.max_version and strategy.compare_versions(current_version, target=step.max_version) > 0:
        logger.warning(
            "Skipping {}: current version {} above maximum {}", step.name, current_version, step.max_version
        )
        return Ok(False)

    return Ok(True)


def run_upgrade_step(
    data: Any, *, step: UpgradeStep, upgrader_context: Any | None = None
) -> Result[Any, UpgradeError]:
    """Execute a single upgrade transformation on data.

    Automatically detects whether the step function accepts an upgrader_context
    parameter via introspection. Expected upgrade, file I/O, and invalid-data
    failures return an UpgradeError retaining the original exception as its
    cause. Unexpected programming errors propagate to the caller.
    """
    logger.debug("Applying upgrade step: {}", step.name)
    sig = inspect.signature(step.func)

    accepts_context = "upgrader_context" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    try:
        data = step.func(data, upgrader_context=upgrader_context) if accepts_context else step.func(data)
    except (UpgradeError, OSError, ValueError) as exc:
        msg = f"Failed {step.name}: {exc}"
        error = UpgradeError(msg)
        error.__cause__ = exc
        return Err(error)
    logger.info("Successfully applied upgrade: {} -> {}", step.name, step.target_version)
    return Ok(data)


# ── Coordinator ─────────────────────────────────────────────────────


@dataclass
class UpgradeCoordinator:
    """Coordinate upgrade execution for a DataStore instance."""

    plugin_config: PluginConfig | None = None
    handler: UpgradeHandler | None = None
    ran: bool = False

    def __post_init__(self) -> None:
        """Require plugin configuration whenever a handler is provided directly."""
        if self.handler is not None and self.plugin_config is None:
            msg = "plugin_config is required when an upgrade handler is provided"
            raise ValueError(msg)

    def resolve(self) -> None:
        """Resolve the configured handler from the plugin config if needed."""
        if self.handler is None:
            self.handler = self.plugin_config.upgrade_handler if self.plugin_config is not None else None

    @property
    def can_run(self) -> bool:
        """Return True when upgrades are configured and not yet executed."""
        return self.handler is not None and not self.ran

    def run(self, *, store: DataStore, reason: str) -> None:
        """Run the upgrade handler and mark upgrades as completed."""
        self.resolve()
        if not self.can_run or self.handler is None:
            return

        logger.info("Running upgrade handler for DataStore (reason: {})", reason)

        if self.plugin_config is None:
            msg = "plugin_config is required to run an upgrade handler"
            raise ValueError(msg)

        ctx = PluginContext(config=self.plugin_config, store=store)
        result: Result[None, str] | None
        try:
            result = self.handler(store=store, ctx=ctx)
        except (UpgradeError, OSError, ValueError) as exc:
            msg = f"Upgrade handler failed: {exc}"
            raise UpgradeError(msg) from exc

        if isinstance(result, Err):
            error = result.err()
            if isinstance(error, Exception):
                raise error
            msg = str(error)
            raise UpgradeError(msg)

        self.ran = True
