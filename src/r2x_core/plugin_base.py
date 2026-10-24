"""Base plugin class with capability-based hooks.

This module provides the Plugin base class that all plugins inherit from.
Plugins implement only the hooks they need, and the framework calls them
in a fixed lifecycle order.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, get_args, get_origin

from loguru import logger
from rust_ok import Err, Ok, Result

from .exceptions import PluginError
from .plugin_context import PluginContext

if TYPE_CHECKING:
    from .plugin_config import PluginConfig
    from .store import DataStore
    from .system import System

ConfigT = TypeVar("ConfigT", bound="PluginConfig")


@dataclass(frozen=True, slots=True)
class HookSpec:
    """Describe one lifecycle hook and how its result affects context."""

    name: str
    phase: str
    log_level: Literal["debug", "info"]
    context_attribute: Literal["system", "target_system"] | None


HOOK_SPECS: tuple[HookSpec, ...] = (
    HookSpec("on_validate", "validation", "debug", None),
    HookSpec("on_prepare", "prepare", "debug", None),
    HookSpec("on_upgrade", "upgrade", "info", "system"),
    HookSpec("on_build", "build", "info", "system"),
    HookSpec("on_transform", "transform", "info", "system"),
    HookSpec("on_translate", "translate", "info", "target_system"),
    HookSpec("on_export", "export", "info", None),
    HookSpec("on_cleanup", "cleanup", "debug", None),
)


class Plugin(ABC, Generic[ConfigT]):
    """Base class for plugins that implement optional lifecycle hooks.

    ``run()`` calls implemented hooks in this order:
    on_validate, on_prepare, on_upgrade, on_build, on_transform, on_translate,
    on_export, on_cleanup. These hooks cover validation, preparation, upgrades,
    building, transformation, translation, export, and cleanup. Plugin
    capabilities follow the hooks provided, such as ``on_build`` for system
    creation or ``on_export`` for writing systems.

    Hooks can mutate the context directly. ``Ok(value)`` from ``on_upgrade``,
    ``on_build``, or ``on_transform`` updates ``ctx.system``; ``on_translate``
    updates ``ctx.target_system``. Success payloads from other hooks are not stored.

    Examples
    --------
    >>> from r2x_core import Plugin, PluginContext, PluginConfig, System
    >>> from rust_ok import Ok
    >>> class MyConfig(PluginConfig):
    ...     name: str
    >>> class MyPlugin(Plugin[MyConfig]):
    ...     def on_build(self):
    ...         return Ok(System(name=self.config.name))
    >>> ctx = PluginContext(config=MyConfig(name="test"))
    >>> result = MyPlugin.from_context(ctx).run()
    >>> result.system.name
    'test'
    >>> MyPlugin.get_config_type() is MyConfig
    True
    >>> sorted(MyPlugin.get_implemented_hooks())
    ['on_build']
    """

    ctx: PluginContext[ConfigT]

    def __init__(self) -> None:
        """Parameterless init for simple instantiation."""

    @property
    def config(self) -> ConfigT:
        """Required plugin configuration from the context."""
        return self.ctx.config

    @property
    def store(self) -> DataStore:
        """Return the context DataStore. Raises PluginError when it is absent."""
        if self.ctx.store is None:
            msg = "DataStore not provided in context"
            raise PluginError(msg)
        return self.ctx.store

    @property
    def system(self) -> System:
        """Return the current system. Raises PluginError when it is absent."""
        if self.ctx.system is None:
            msg = "System not provided in context"
            raise PluginError(msg)
        return self.ctx.system

    @property
    def source_system(self) -> System:
        """Return the source system. Raises PluginError when it is absent."""
        if self.ctx.source_system is None:
            msg = "Source system not provided in context"
            raise PluginError(msg)
        return self.ctx.source_system

    @property
    def target_system(self) -> System:
        """Return the translated target system. Raises PluginError when absent."""
        if self.ctx.target_system is None:
            msg = "Target system not available"
            raise PluginError(msg)
        return self.ctx.target_system

    @property
    def metadata(self) -> dict[str, Any]:
        """Mutable metadata dictionary shared with the context."""
        return self.ctx.metadata

    @classmethod
    def from_context(cls, ctx: PluginContext[ConfigT]) -> Plugin[ConfigT]:
        """Create a plugin instance bound to ``ctx`` for lifecycle execution."""
        instance = cls()
        instance.ctx = ctx
        return instance

    @classmethod
    def get_config_type(cls) -> type[Any]:
        """Return the plugin's generic config class, or ``object`` if unavailable."""
        origin = get_origin(cls)
        if origin is None:
            # cls is a concrete subclass like MyPlugin
            # Use getattr with fallback to handle classes without __orig_bases__
            bases = getattr(cls, "__orig_bases__", ())
            for base in bases:
                args = get_args(base)
                if args and len(args) > 0:
                    return args[0]
        # Fallback for edge cases
        return object

    @classmethod
    def get_implemented_hooks(cls) -> set[str]:
        """Return names of callable lifecycle hooks implemented by the class."""
        return {spec.name for spec in HOOK_SPECS if callable(getattr(cls, spec.name, None))}

    def run(self, *, ctx: PluginContext[ConfigT] | None = None) -> PluginContext[ConfigT]:
        """Run implemented hooks in lifecycle order and return the updated context.

        Uses ``ctx`` when supplied, otherwise the bound context. Hook mutations
        remain in place. ``Ok(value)`` from ``on_upgrade``, ``on_build``, or
        ``on_transform`` updates ``ctx.system``; ``on_translate`` updates
        ``ctx.target_system``. Other successful payloads are not stored. An
        ``Err`` raises ``PluginError``, chained from an exception error when
        present. Non-``Ok``/``Err`` results raise ``TypeError``; other hook
        exceptions propagate unchanged.

        Parameters
        ----------
        ctx : PluginContext[ConfigT] | None
            Context to use instead of the bound context.

        Raises
        ------
        PluginError
            If a hook returns ``Err``.
        TypeError
            If a hook returns neither ``Ok`` nor ``Err``.
        """
        if ctx is not None:
            self.ctx = ctx

        plugin_name = type(self).__name__
        logger.info("Running plugin: {}", plugin_name)

        # Lifecycle hooks are optional subclass extension points, so resolve them dynamically.
        for hook_spec in HOOK_SPECS:
            hook: Callable[[], Result[Any, Any]] | None = getattr(self, hook_spec.name, None)
            if not callable(hook):
                continue

            # Log at appropriate level
            if hook_spec.log_level == "debug":
                logger.debug("{}: {}", plugin_name, hook_spec.name)
            else:
                logger.info("{}: {}", plugin_name, hook_spec.name)

            result = hook()

            if isinstance(result, Err):
                msg = f"{plugin_name} {hook_spec.phase} failed: {result.error}"
                if isinstance(result.error, BaseException):
                    raise PluginError(msg) from result.error
                raise PluginError(msg)
            if not isinstance(result, Ok):
                msg = f"{plugin_name} {hook_spec.name} must return Ok or Err, got {type(result).__name__}"
                raise TypeError(msg)

            # Update context if this hook produces a result.
            if hook_spec.context_attribute:
                setattr(self.ctx, hook_spec.context_attribute, result.value)

        logger.info("Plugin {} completed successfully", plugin_name)
        return self.ctx
