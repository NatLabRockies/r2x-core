"""Upgrade infrastructure: steps, coordination, and version-based execution."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from typing import TYPE_CHECKING, Annotated, Any

from loguru import logger
from pydantic import BaseModel, PrivateAttr, ValidationError
from pydantic_core import ErrorDetails
from rust_ok import Err, Ok, Result

from ..exceptions import UpgradeError
from ..plugin_config import PluginConfig
from ..plugin_context import PluginContext
from ..versioning import VersionStrategy
from .validation import filter_valid_kwargs

if TYPE_CHECKING:
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
    _sig: inspect.Signature | None = PrivateAttr(None)


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
) -> Result[Any, str]:
    """Execute a single upgrade transformation on data.

    Automatically detects whether the step function accepts an upgrader_context
    parameter via introspection.
    """
    logger.debug("Applying upgrade step: {}", step.name)
    try:
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


# ── Coordinator ─────────────────────────────────────────────────────


def _resolve_upgrade_handler(plugin_config: PluginConfig) -> Callable[..., Any] | None:
    """Resolve an upgrade handler based on plugin config conventions."""
    handler = getattr(plugin_config, "upgrade_handler", None)
    if callable(handler):
        return handler

    getter = getattr(plugin_config, "get_upgrade_handler", None)
    if callable(getter):
        handler = getter()
        if callable(handler):
            return handler

    module_name = plugin_config.__class__.__module__
    root_package = module_name.split(".")[0]
    short_name = root_package.removeprefix("r2x_")

    for candidate in (f"{root_package}.upgrader", f"{root_package}.upgrade"):
        try:
            module = import_module(candidate)
        except ModuleNotFoundError:
            continue

        handler = getattr(module, f"run_{short_name}_upgrades", None)
        if callable(handler):
            return handler

        handler = getattr(module, "run_upgrades", None)
        if callable(handler):
            return handler

    return None


def _is_missing_file_error(error: ErrorDetails) -> bool:
    """Return True if an error indicates missing input files."""
    ctx = error.get("ctx") or {}
    if ctx.get("exc_type") == "FileNotFoundError":
        return True

    message = str(ctx.get("error") or error.get("input") or "")
    missing_markers = (
        "Missing required file",
        "No files found matching pattern",
        "does not exist",
    )
    return any(marker in message for marker in missing_markers)


@dataclass
class UpgradeCoordinator:
    """Coordinate upgrade execution for a DataStore instance."""

    plugin_config: PluginConfig | None = None
    handler: Callable[..., Any] | None = None
    ran: bool = False

    def resolve(self) -> None:
        """Resolve an upgrade handler from the plugin config if needed."""
        if self.handler is None and self.plugin_config is not None:
            self.handler = _resolve_upgrade_handler(self.plugin_config)

    @property
    def can_run(self) -> bool:
        """Return True when upgrades are configured and not yet executed."""
        return self.handler is not None and not self.ran

    def should_attempt(self, exc: ValidationError) -> bool:
        """Return True if validation errors indicate missing files."""
        self.resolve()
        if not self.can_run:
            return False

        return any(_is_missing_file_error(err) for err in exc.errors())

    def run(self, *, store: DataStore, reason: str) -> None:
        """Run the upgrade handler and mark upgrades as completed."""
        self.resolve()
        if not self.can_run or self.handler is None:
            return

        logger.info("Running upgrade handler for DataStore (reason: {})", reason)

        ctx: PluginContext[PluginConfig] | None = None
        if self.plugin_config is not None:
            ctx = PluginContext(config=self.plugin_config, store=store)

        kwargs: dict[str, Any] = {
            "store": store,
            "ctx": ctx,
            "config": self.plugin_config,
            "plugin_config": self.plugin_config,
            "path": store.folder,
            "folder": store.folder,
        }

        result: Any
        try:
            result = self.handler(**filter_valid_kwargs(self.handler, kwargs=kwargs))
        except Exception as exc:
            raise UpgradeError(f"Upgrade handler failed: {exc}") from exc

        if isinstance(result, Err):
            raise UpgradeError(str(result.err()))

        self.ran = True
