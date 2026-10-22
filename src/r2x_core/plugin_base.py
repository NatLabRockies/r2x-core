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
    """Base class for all plugins with capability-based hooks.

    Plugins implement only the hooks they need. The run() method executes
    hooks in a fixed order, skipping any that aren't implemented.

    Plugin capabilities are determined by which hooks are implemented:
    - on_build()     -> Plugin that creates systems from data
    - on_transform() -> Plugin that modifies existing systems
    - on_translate() -> Plugin that converts source → target systems
    - on_export()    -> Plugin that writes systems to files

    Required context fields are indicated by property return types:
    - Non-Optional return type (e.g., -> System) = field is required
    - Optional return type (e.g., -> System | None) = field is optional

    Lifecycle (fixed order, all optional)
    --------------------------------------
    1. on_validate()  ->  Validate inputs/config
    2. on_prepare()   ->  Load data, setup
    3. on_upgrade()   ->  Upgrade system to target version
    4. on_build()     ->  Create system from scratch
    5. on_transform() ->  Modify existing system
    6. on_translate() ->  Source -> Target system
    7. on_export()    ->  Write system to files
    8. on_cleanup()   ->  Cleanup resources

    Examples
    --------
    A simple build plugin:

    >>> from r2x_core import Plugin, PluginContext, PluginConfig, System
    >>> from rust_ok import Ok

    >>> class MyConfig(PluginConfig):
    ...     name: str

    >>> class MyPlugin(Plugin[MyConfig]):
    ...     def on_build(self):
    ...         system = System(name=self.config.name)
    ...         return Ok(system)

    >>> ctx = PluginContext(config=MyConfig(name="test"))
    >>> plugin = MyPlugin.from_context(ctx)
    >>> result_ctx = plugin.run()
    >>> result_ctx.system.name
    'test'

    Config type can be extracted via introspection for discovery:

    >>> from typing import get_args, get_origin
    >>> config_type = MyPlugin.get_config_type()
    >>> config_type.__name__
    'MyConfig'
    """

    ctx: PluginContext[ConfigT]

    def __init__(self) -> None:
        """Parameterless init for simple instantiation."""

    @property
    def config(self) -> ConfigT:
        """Plugin configuration. Always required.

        Returns
        -------
        ConfigT
            The plugin configuration from the context.
        """
        return self.ctx.config

    @property
    def store(self) -> DataStore:
        """Data store for file I/O. Required if return type is non-Optional.

        Returns
        -------
        DataStore
            The data store from the context.

        Raises
        ------
        PluginError
            If store is not provided in context.
        """
        if self.ctx.store is None:
            msg = "DataStore not provided in context"
            raise PluginError(msg)
        return self.ctx.store

    @property
    def system(self) -> System:
        """Current system. Required for transform/export plugins.

        Returns
        -------
        System
            The system from the context.

        Raises
        ------
        PluginError
            If system is not provided in context.
        """
        if self.ctx.system is None:
            msg = "System not provided in context"
            raise PluginError(msg)
        return self.ctx.system

    @property
    def source_system(self) -> System:
        """Source system for translation. Required for translate plugins.

        Returns
        -------
        System
            The source system from the context.

        Raises
        ------
        PluginError
            If source_system is not provided in context.
        """
        if self.ctx.source_system is None:
            msg = "Source system not provided in context"
            raise PluginError(msg)
        return self.ctx.source_system

    @property
    def target_system(self) -> System:
        """Target system after translation.

        Returns
        -------
        System
            The target system from the context.

        Raises
        ------
        PluginError
            If target_system is not available in context.
        """
        if self.ctx.target_system is None:
            msg = "Target system not available"
            raise PluginError(msg)
        return self.ctx.target_system

    @property
    def metadata(self) -> dict[str, Any]:
        """Metadata dict. Always available.

        Returns
        -------
        dict[str, Any]
            The metadata dictionary from the context.
        """
        return self.ctx.metadata

    @classmethod
    def from_context(cls, ctx: PluginContext[ConfigT]) -> Plugin[ConfigT]:
        """Create plugin instance from context.

        This is the recommended way to instantiate plugins.

        Parameters
        ----------
        ctx : PluginContext[ConfigT]
            The context to use for plugin execution.

        Returns
        -------
        Plugin[ConfigT]
            New plugin instance with context set.

        Examples
        --------
        >>> from r2x_core import Plugin, PluginContext, PluginConfig
        >>> class Config(PluginConfig):
        ...     pass
        >>> ctx = PluginContext(config=Config())
        >>> plugin = Plugin.from_context(ctx)  # Would instantiate subclass in practice
        """
        instance = cls()
        instance.ctx = ctx
        return instance

    @classmethod
    def get_config_type(cls) -> type[Any]:
        """Extract the config type from generic parameters.

        Returns
        -------
        type[Any]
            The PluginConfig subclass used for this plugin.

        Examples
        --------
        >>> from r2x_core import Plugin, PluginConfig
        >>> class MyConfig(PluginConfig):
        ...     value: int
        >>> class MyPlugin(Plugin[MyConfig]):
        ...     pass
        >>> MyPlugin.get_config_type().__name__
        'MyConfig'
        """
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
        """Get the set of implemented hook methods.

        Returns
        -------
        set[str]
            Names of implemented hooks (e.g., {'on_validate', 'on_build'}).

        Examples
        --------
        >>> from r2x_core import Plugin, PluginConfig
        >>> from rust_ok import Ok
        >>> class MyConfig(PluginConfig):
        ...     value: int
        >>> class MyPlugin(Plugin[MyConfig]):
        ...     def on_validate(self):
        ...         return Ok(None)
        ...     def on_build(self):
        ...         return Ok(None)
        >>> sorted(MyPlugin.get_implemented_hooks())
        ['on_build', 'on_validate']
        """
        return {spec.name for spec in HOOK_SPECS if callable(getattr(cls, spec.name, None))}

    def run(self, *, ctx: PluginContext[ConfigT] | None = None) -> PluginContext[ConfigT]:
        """Execute plugin lifecycle.

        Hooks are called in fixed order. Unimplemented hooks are skipped.
        If any hook returns Err, execution stops and PluginError is raised.
        Context is updated in-place for memory efficiency.

        Parameters
        ----------
        ctx : PluginContext[ConfigT] | None
            Context to use. If None, uses context from from_context().

        Returns
        -------
        PluginContext[ConfigT]
            The context (updated in-place).

        Raises
        ------
        PluginError
            If any hook fails.

        Examples
        --------
        >>> from r2x_core import Plugin, PluginContext, PluginConfig, System
        >>> from rust_ok import Ok

        >>> class Config(PluginConfig):
        ...     pass

        >>> class MyPlugin(Plugin[Config]):
        ...     def on_build(self):
        ...         return Ok(System(name="test"))

        >>> ctx = PluginContext(config=Config())
        >>> result = MyPlugin.from_context(ctx).run()
        >>> result.system.name
        'test'
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
