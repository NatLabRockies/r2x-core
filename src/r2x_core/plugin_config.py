"""Configuration management for r2x plugins.

This module provides the base `PluginConfig` class for managing plugin
configuration, including paths to configuration files, component modules,
and methods to load and override configuration assets.
"""

import inspect
from collections.abc import Sequence
from copy import deepcopy
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

import orjson
from loguru import logger
from pydantic import BaseModel, Field, field_validator


class PluginConfigAsset(StrEnum):
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
    asset_overrides : dict[str, Any]
        Complete replacements for named JSON assets. Structured assets are
        replaced as a whole, not merged by position. Keys use the file stem, such as
        ``file_mapping`` or ``parser_rules``.

    Examples
    --------
    Basic usage with default configuration:

    >>> config = PluginConfig(models='my_package.models')
    >>> config.config_path
    PosixPath('.../config')
    >>> config.defaults_path
    PosixPath('.../config/defaults.json')

    Replace a complete asset and load only the selected asset:

    >>> mapping = {"files": [{"name": "buses", "relative_fpath": "buses.csv"}], "tables": []}
    >>> config = PluginConfig(asset_overrides={"file_mapping": mapping})
    >>> config.load_config(assets=[PluginConfigAsset.FILE_MAPPING])["file_mapping"] == mapping
    True
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

    asset_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Whole configuration asset replacements keyed by asset name without the .json suffix.",
    )

    @field_validator("asset_overrides")
    @classmethod
    def validate_asset_overrides(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Reject override names that do not identify known configuration assets."""
        asset_names = {Path(asset.value).stem for asset in PluginConfigAsset}
        unknown = sorted(set(value) - asset_names)
        if unknown:
            raise ValueError(f"Unknown config asset override(s): {unknown}")
        return value

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

    def load_config(
        self,
        *,
        assets: Sequence[PluginConfigAsset] | None = None,
    ) -> dict[str, Any]:
        """Load selected configuration assets from this config's resolved path.

        Asset overrides replace the complete selected asset. They are never
        merged by list position or recursively combined with packaged values.

        Parameters
        ----------
        assets : Sequence[PluginConfigAsset] | None, optional
            Assets to load. When omitted, all known configuration assets are loaded.

        Returns
        -------
        dict[str, Any]
            Loaded assets keyed by stem, such as ``file_mapping`` or ``parser_rules``.

        Raises
        ------
        FileNotFoundError
            If a selected asset has no override and is missing from ``config_path``.
        ValueError
            If an asset selection is not a PluginConfigAsset.
        """
        selected_assets = tuple(PluginConfigAsset) if assets is None else tuple(dict.fromkeys(assets))
        invalid_assets = [asset for asset in selected_assets if not isinstance(asset, PluginConfigAsset)]
        if invalid_assets:
            raise ValueError(f"Unknown config asset selection(s): {invalid_assets}")

        asset_data: dict[str, Any] = {}
        for asset in selected_assets:
            asset_name = Path(asset.value).stem
            if asset_name in self.asset_overrides:
                asset_data[asset_name] = deepcopy(self.asset_overrides[asset_name])
                continue

            asset_path = self.config_path / asset.value
            if not asset_path.exists():
                msg = f"{asset_path=} not found on Package. Check contents of config_path"
                raise FileNotFoundError(msg)
            with open(asset_path, "rb") as f_in:
                asset_data[asset_name] = orjson.loads(f_in.read())

        return asset_data

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
