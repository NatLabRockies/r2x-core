"""Unified plugin context for all plugin operations.

This module provides the PluginContext class that serves as the common
interface for passing data to plugins. It's designed to be simple and
memory-efficient by using __slots__ and direct attribute access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from .plugin_config import PluginConfig
    from .rules import Rule
    from .store import DataStore
    from .system import System
    from .versioning import VersionStrategy

from .result import ConversionOption

ConfigT = TypeVar("ConfigT", bound="PluginConfig")


class PluginContext(Generic[ConfigT]):
    """Unified context for all plugin operations.

    A simple, memory-efficient context that plugins use to access configuration,
    data stores, systems, and metadata. Uses __slots__ to minimize memory overhead.

    Attributes
    ----------
    config : ConfigT
        Plugin configuration (always required). The generic type ConfigT
        allows type-safe access to plugin-specific config fields.
    store : DataStore | None
        Optional data store for file I/O operations. Used by plugins
        that read/write files.
    system : System | None
        Optional system object. Created by build plugins, consumed by
        transform/export plugins, or provided from previous step via stdin.
    source_system : System | None
        Optional source system for translation. Used by translate plugins
        that convert from one format to another.
    target_system : System | None
        Optional target system (output of translation). Set after a
        translate plugin runs.
    rules : tuple[Rule, ...]
        Transformation rules for translation. Empty tuple by default.
    metadata : dict[str, Any]
        Arbitrary metadata key-value pairs that plugins can use.
    skip_validation : bool
        Skip Pydantic validation when creating components (faster but less safe).
        Parser option. Default is False.
    auto_add_composed_components : bool
        Whether to automatically add composed components to the system.
        Parser option. Default is True.
    current_version : str | None
        Current version of the system being upgraded. Used by on_upgrade() hooks.
    target_version : str | None
        Target version after upgrade. Used by on_upgrade() hooks.
    version_strategy : VersionStrategy | None
        Strategy for handling version upgrades. Used by on_upgrade() hooks.

    Examples
    --------
    Create a context with configuration:

    >>> from r2x_core.plugin_context import PluginContext
    >>> from r2x_core.plugin_config import PluginConfig

    >>> class MyConfig(PluginConfig):
    ...     name: str

    >>> ctx = PluginContext(config=MyConfig(name="test"))
    >>> ctx.config.name
    'test'

    Update context fields directly:

    >>> from r2x_core.system import System
    >>> system = System(name="my_system")
    >>> ctx.system = system
    >>> ctx.system.name
    'my_system'
    """

    __slots__ = (
        "_cache",
        "auto_add_composed_components",
        "config",
        "current_version",
        "metadata",
        "rules",
        "skip_validation",
        "source_system",
        "store",
        "system",
        "target_system",
        "target_version",
        "version_strategy",
    )

    def __init__(
        self,
        config: ConfigT,
        *,
        store: DataStore | None = None,
        system: System | None = None,
        source_system: System | None = None,
        target_system: System | None = None,
        rules: tuple[Rule, ...] = (),
        metadata: dict[str, Any] | None = None,
        skip_validation: bool = False,
        auto_add_composed_components: bool = True,
        current_version: str | None = None,
        target_version: str | None = None,
        version_strategy: VersionStrategy | None = None,
    ) -> None:
        """Initialize plugin context.

        Parameters
        ----------
        config : ConfigT
            Plugin configuration (required).
        store : DataStore | None
            Optional data store for file I/O.
        system : System | None
            Optional system object.
        source_system : System | None
            Optional source system for translation.
        target_system : System | None
            Optional target system.
        rules : tuple[Rule, ...]
            Transformation rules. Default is empty tuple.
        metadata : dict[str, Any] | None
            Arbitrary metadata. Default is empty dict.
        skip_validation : bool
            Skip Pydantic validation. Default is False.
        auto_add_composed_components : bool
            Auto-add composed components. Default is True.
        current_version : str | None
            Current version for upgrades. Default is None.
        target_version : str | None
            Target version for upgrades. Default is None.
        version_strategy : VersionStrategy | None
            Version strategy for upgrades. Default is None.
        """
        self.config = config
        self.store = store
        self.system = system
        self.source_system = source_system
        self.target_system = target_system
        self.rules = rules
        self.metadata = metadata if metadata is not None else {}
        self.skip_validation = skip_validation
        self.auto_add_composed_components = auto_add_composed_components
        self.current_version = current_version
        self.target_version = target_version
        self.version_strategy = version_strategy
        self._cache: dict[str, Any] = {}

    def evolve(self, **kwargs: Any) -> PluginContext[ConfigT]:
        """Create a new context with updated fields.

        Memory-efficient method to create a new context with only the specified
        fields changed. All other fields are copied from the current context.

        Parameters
        ----------
        **kwargs : Any
            Fields to update (config, store, system, source_system, target_system,
            rules, metadata, skip_validation, auto_add_composed_components,
            current_version, target_version, version_strategy).

        Returns
        -------
        PluginContext[ConfigT]
            A new context with the specified updates.

        Examples
        --------
        Create a new context with updated system:

        >>> from r2x_core.plugin_context import PluginContext
        >>> from r2x_core.plugin_config import PluginConfig
        >>> from r2x_core.system import System

        >>> class MyConfig(PluginConfig):
        ...     pass

        >>> ctx = PluginContext(config=MyConfig())
        >>> system = System(name="my_system")
        >>> ctx2 = ctx.evolve(system=system)
        >>> ctx2.system.name
        'my_system'

        Update metadata:

        >>> ctx3 = ctx2.evolve(metadata={"key": "value"})
        >>> ctx3.metadata
        {'key': 'value'}
        """
        return PluginContext(
            config=kwargs.get("config", self.config),
            store=kwargs.get("store", self.store),
            system=kwargs.get("system", self.system),
            source_system=kwargs.get("source_system", self.source_system),
            target_system=kwargs.get("target_system", self.target_system),
            rules=kwargs.get("rules", self.rules),
            metadata=kwargs.get("metadata", self.metadata),
            skip_validation=kwargs.get("skip_validation", self.skip_validation),
            auto_add_composed_components=kwargs.get(
                "auto_add_composed_components", self.auto_add_composed_components
            ),
            current_version=kwargs.get("current_version", self.current_version),
            target_version=kwargs.get("target_version", self.target_version),
            version_strategy=kwargs.get("version_strategy", self.version_strategy),
        )

    def list_rules(self) -> list[Rule]:
        """List all available transformation rules.

        Returns
        -------
        list[Rule]
            List of all rules in this context.
        """
        return list(self.rules)

    def get_rule(
        self,
        source_type: str,
        *,
        target_type: str,
        version: int | None = None,
    ) -> Rule:
        """Retrieve a transformation rule by source type, target type, and version.

        Parameters
        ----------
        source_type : str
            Source component type name.
        target_type : str
            Target component type name.
        version : int | None
            Rule version. If None, uses active_versions from config if available,
            otherwise defaults to version 1.

        Returns
        -------
        Rule
            The matching rule.

        Raises
        ------
        KeyError
            If no rule matches the specified source/target types and version.
        """
        if version is None:
            active_versions = getattr(self.config, "active_versions", {})
            version = active_versions.get(source_type, 1)

        for rule in self.rules:
            if (
                source_type in rule.get_source_types()
                and target_type in rule.get_target_types()
                and rule.version == version
            ):
                return rule

        raise KeyError(f"No rule found for {source_type} → {target_type} (v{version})")

    def list_available_conversions(self) -> dict[str, list[ConversionOption]]:
        """List available conversions by source type.

        Returns
        -------
        dict[str, list[ConversionOption]]
            Mapping of source types to list of ConversionOption objects,
            sorted by target type and version.
        """
        conversions: dict[str, list[ConversionOption]] = {}
        for rule in self.rules:
            for source_type in rule.get_source_types():
                if source_type not in conversions:
                    conversions[source_type] = []
                for target_type in rule.get_target_types():
                    conversions[source_type].append(
                        ConversionOption(target_type=target_type, version=rule.version)
                    )
        for targets in conversions.values():
            targets.sort(key=lambda opt: (opt.target_type, opt.version))
        return conversions

    def get_rules_for_source(self, source_type: str) -> list[Rule]:
        """Get all rules for a specific source type.

        Parameters
        ----------
        source_type : str
            Source component type name.

        Returns
        -------
        list[Rule]
            List of all rules matching the source type, sorted by target type and version.
        """
        matching = [r for r in self.rules if source_type in r.get_source_types()]
        matching.sort(key=lambda r: (str(r.target_type), r.version))
        return matching

    def get_rules_for_conversion(self, source_type: str, *, target_type: str) -> list[Rule]:
        """Get all versions of a conversion between two types.

        Parameters
        ----------
        source_type : str
            Source component type name.
        target_type : str
            Target component type name.

        Returns
        -------
        list[Rule]
            List of all rules for this conversion, sorted by version.
        """
        matching = [
            r
            for r in self.rules
            if source_type in r.get_source_types() and target_type in r.get_target_types()
        ]
        matching.sort(key=lambda r: r.version)
        return matching
