"""Configuration management for r2x plugins.

This module provides the base `PluginConfig` class for managing plugin
configuration, including paths to configuration files, component modules,
and methods to load and override configuration assets.
"""

import inspect
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

import orjson
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from .utils.overrides import override_dictionary


class PluginConfigAsset(str, Enum):
    """Enum describing configuration assets."""

    FILE_MAPPING = "file_mapping.json"
    DEFAULTS = "defaults.json"
    TRANSLATION_RULES = "translation_rules.json"
    PARSER_RULES = "parser_rules.json"
    EXPORTER_RULES = "exporter_rules.json"


class PluginConfig(BaseModel):
    """Pure Pydantic base configuration class for plugins.

    This class provides a base configuration schema for plugins, managing paths to
    configuration files and component modules. It supports both default and custom
    configuration paths, with validation and override capabilities.

    Attributes
    ----------
    CONFIG_DIR : str
        Class variable specifying the default configuration directory name.
        Default is "config".
    models : tuple[str, ...]
        Module path(s) for component classes. Examples: 'r2x_sienna.models',
        'my_package.components'. If omitted, defaults to an empty tuple.
    config_path_override : Path | None
        Optional override for the configuration path. When provided, this path
        is used instead of the default package configuration directory.

    Examples
    --------
    Basic usage with default configuration:

    >>> config = PluginConfig(models='my_package.models')
    >>> config.config_path
    PosixPath('.../config')
    >>> config.defaults_path
    PosixPath('.../config/defaults.json')
    """

    CONFIG_DIR: ClassVar[str] = "config"

    models: tuple[str, ...] = Field(
        default_factory=tuple,
        description=(
            "Module path(s) for component classes, e.g. 'r2x_sienna.models'. "
            "If omitted, rules will use an empty module list."
        ),
    )

    config_path_override: Path | None = Field(
        default=None,
        description="Override for the configuration path. This is used if you want to point to a different place than the `CONFIG_DIR`",
    )

    @field_validator("models", mode="before")
    @classmethod
    def _coerce_models(cls, value: Any | None) -> tuple[str, ...]:
        """Coerce models input into a normalized tuple.

        Accepts string, iterable, or None inputs and normalizes them to a tuple.

        Parameters
        ----------
        value : Any | None
            The input value to coerce. Can be a string, list, tuple, set, or None.

        Returns
        -------
        tuple[str, ...]
            Normalized tuple of module paths. Returns empty tuple if value is None.

        Raises
        ------
        TypeError
            If value is not a string, iterable of strings, or None.
        """
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, list | tuple | set):
            return tuple(value)
        raise TypeError("models must be a string or iterable of strings")

    @property
    def config_path(self) -> Path:
        """Get the resolved configuration directory path.

        Returns the configuration path from the override if set, otherwise computes
        the path relative to the package module. Logs a warning if the path does
        not exist.

        Returns
        -------
        Path
            The configuration directory path. May not exist on the package.

        Notes
        -----
        A warning is logged if the returned path does not exist on the filesystem.
        """
        config_path = self.config_path_override or self._package_config_path()

        if not config_path.exists():
            msg = "Config path={} doe not exist on the Package."
            logger.warning(msg, config_path)
        return config_path

    @property
    def fmap_path(self) -> Path:
        """Get path to file mapping configuration file.

        Returns
        -------
        Path
            Path to file_mapping.json in config directory
        """
        return self.config_path / PluginConfigAsset.FILE_MAPPING.value

    @property
    def defaults_path(self) -> Path:
        """Get path to defaults configuration file.

        Returns
        -------
        Path
            Path to defaults.json in config directory
        """
        return self.config_path / PluginConfigAsset.DEFAULTS.value

    @property
    def exporter_rules_path(self) -> Path:
        """Get path to exporter rules configuration file.

        Returns
        -------
        Path
            Path to exporter_rules.json in config directory
        """
        return self.config_path / PluginConfigAsset.EXPORTER_RULES.value

    @property
    def parser_rules_path(self) -> Path:
        """Get path to parser rules configuration file.

        Returns
        -------
        Path
            Path to parser_rules.json in config directory
        """
        return self.config_path / PluginConfigAsset.PARSER_RULES.value

    @property
    def translation_rules_path(self) -> Path:
        """Get path to translation rules configuration file.

        Returns
        -------
        Path
            Path to translation_rules.json in config directory
        """
        return self.config_path / PluginConfigAsset.TRANSLATION_RULES.value

    @classmethod
    def load_config(
        cls,
        *,
        config_path: Path | str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Load plugin configuration assets with optional overrides.

        Loads all configuration assets (defaults, file mappings, rules) from the
        specified config directory and optionally merges them with override values.

        Parameters
        ----------
        config_path : Path | str | None, optional
            Optional override for the config directory to load assets from.
            If None, uses the default package configuration path.
        overrides : dict[str, Any], optional
            Values to merge with loaded assets. For list values, items are
            appended and deduplicated. For scalar values, they replace defaults.

        Returns
        -------
        dict[str, Any]
            Merged assets keyed by asset stem (defaults, file_mapping, etc.).

        Raises
        ------
        FileNotFoundError
            If any expected configuration asset file is not found in config_path.
        """
        resolved_config_path = Path(config_path) if config_path is not None else cls._package_config_path()
        asset_data: dict[str, Any] = {}
        for asset in PluginConfigAsset:
            asset_path = resolved_config_path / asset.value
            if not asset_path.exists():
                msg = f"{asset_path=} not found on Package. Check contents of config_path"
                raise FileNotFoundError(msg)
            with open(asset_path, "rb") as f_in:
                data = orjson.loads(f_in.read())
            asset_data[asset_path.stem] = data

        if not overrides:
            return asset_data

        return override_dictionary(base=asset_data, overrides=overrides)

    @classmethod
    def _package_config_path(cls) -> Path:
        """Compute the config directory path relative to the defining package.

        Locates the module file for the class and returns the path to the
        configuration directory alongside it. If the module directory itself
        is named 'config', returns that directory. Otherwise appends 'config'
        to the module directory path.

        Returns
        -------
        Path
            Path to the configuration directory. May not exist on the filesystem.
        """
        try:
            module_file = inspect.getfile(cls)
        except (TypeError, AttributeError):
            # For classes defined in doctest or other special contexts,
            # return a path based on current working directory
            return Path.cwd() / cls.CONFIG_DIR
        module_dir = Path(module_file).parent
        if module_dir.name == cls.CONFIG_DIR:
            return module_dir
        return module_dir / cls.CONFIG_DIR
