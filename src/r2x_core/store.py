"""Manage file-mapping configuration and its upgrade handler."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
from loguru import logger
from pydantic import TypeAdapter, ValidationError

from .datafile import DataFile
from .plugin_config import PluginConfig
from .shared_types import PLACEHOLDER_PATTERN, FileRequirement
from .utils.upgrade import UpgradeCoordinator
from .utils.validation import filter_kwargs_for

if TYPE_CHECKING:
    from .versioning import UpgradeHandler


def _missing_file_validation_error(paths: Sequence[Path]) -> ValidationError:
    """Build the legacy validation error shape for missing required files."""
    line_errors = []
    for path in paths:
        error = FileNotFoundError(f"Missing required file: {path}")
        line_errors.append(
            {
                "type": "value_error",
                "loc": ("fpath",),
                "input": str(error),
                "ctx": {"error": error, "exc_type": "FileNotFoundError"},
            }
        )
    return ValidationError.from_exception_data("Invalid data file records", line_errors=line_errors)


class DataStore:
    """Hold a unique mapping of configured inputs relative to a folder."""

    def __init__(self, /, path: str | Path | None = None) -> None:
        """Create an empty mapping store rooted at an existing directory."""
        folder = Path.cwd() if path is None else Path(path)
        if not folder.is_dir():
            msg = f"DataStore path must be a directory: {folder}"
            raise NotADirectoryError(msg)
        self.folder = folder.resolve()
        self.data_files: dict[str, DataFile] = {}
        self.upgrade_coordinator = UpgradeCoordinator()

    def __getitem__(self, name: str) -> DataFile:
        """Return one configured input by name."""
        try:
            return self.data_files[name]
        except KeyError:
            msg = f"{name!r} not present in store. Available files: {list(self.data_files)}"
            raise KeyError(msg) from None

    def __contains__(self, name: str) -> bool:
        """Return whether an input name is configured."""
        return name in self.data_files

    def add_data(self, data_files: Sequence[DataFile], *, overwrite: bool = False) -> None:
        """Add validated input configuration, rejecting duplicate names by default."""
        if any(not isinstance(data_file, DataFile) for data_file in data_files):
            msg = "data_files must contain only DataFile instances"
            raise TypeError(msg)
        duplicates = {item.name for item in data_files} & self.data_files.keys()
        repeated = {
            item.name for item in data_files if sum(other.name == item.name for other in data_files) > 1
        }
        if (duplicates or repeated) and not overwrite:
            names = sorted(duplicates | repeated)
            msg = f"Input names already configured: {names}"
            raise KeyError(msg)
        self.data_files.update({item.name: item for item in data_files})

    def list_data(self) -> list[str]:
        """Return configured input names in stable order."""
        return sorted(self.data_files)

    def remove_data(self, *names: str) -> None:
        """Remove configured inputs by name."""
        missing = set(names) - self.data_files.keys()
        if missing:
            msg = f"Inputs not found: {sorted(missing)}"
            raise KeyError(msg)
        for name in names:
            del self.data_files[name]

    def configure_upgrades(
        self,
        *,
        plugin_config: PluginConfig,
        upgrade_handler: UpgradeHandler | None = None,
    ) -> None:
        """Configure version upgrades for this store's mapping."""
        self.upgrade_coordinator = UpgradeCoordinator(
            plugin_config=plugin_config,
            handler=upgrade_handler,
        )
        self.upgrade_coordinator.resolve()

    @classmethod
    def from_plugin_config(
        cls,
        plugin_config: PluginConfig,
        *,
        path: Path | str,
        upgrade_handler: UpgradeHandler | None = None,
    ) -> DataStore:
        """Create a store from plugin configuration for compatibility.

        New code should construct a store, configure its upgrade handler, and
        load the mapping explicitly. This factory retains the historical empty
        mapping and missing-file upgrade retry behavior for existing plugins.
        """
        mapping_path = plugin_config.fmap_path
        logger.info("Loading DataStore from plugin config: {}", type(plugin_config).__name__)
        logger.debug("File mapping path: {}", mapping_path)
        store = cls(path=path)
        store.configure_upgrades(plugin_config=plugin_config, upgrade_handler=upgrade_handler)
        if not mapping_path.exists():
            logger.warning(
                "File mapping not found for {} at {}; continuing with empty DataStore.",
                type(plugin_config).__name__,
                mapping_path,
            )
            return store

        store.load_file_mapping(mapping_path)
        missing_paths = store._missing_required_file_paths()
        if missing_paths:
            if not store.upgrade_coordinator.can_run:
                raise _missing_file_validation_error(missing_paths)
            store.remove_data(*store.list_data())
            store.upgrade_coordinator.run(store=store, reason="file mapping validation failed")
            store.load_file_mapping(mapping_path)
            missing_paths = store._missing_required_file_paths()
            if missing_paths:
                raise _missing_file_validation_error(missing_paths)
        return store

    def _missing_required_file_paths(self) -> list[Path]:
        """Return absent required physical inputs without resolving globs or templates."""
        paths: list[Path] = []
        for data_file in self.data_files.values():
            if data_file.info.requirement is FileRequirement.OPTIONAL:
                continue
            raw_path = data_file.fpath or data_file.relative_fpath
            if raw_path is None or PLACEHOLDER_PATTERN.search(str(raw_path)):
                continue
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.folder / path
            if not path.exists():
                paths.append(path)
        return paths

    def to_json(self, fpath: str | Path, **model_dump_kwargs: Any) -> None:
        """Write configured inputs as formatted JSON."""
        data = [
            item.model_dump(
                mode="json",
                round_trip=True,
                **filter_kwargs_for(item.model_dump, kwargs=model_dump_kwargs),
            )
            for item in self.data_files.values()
        ]
        Path(fpath).write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
        logger.info("Created JSON file at {}", fpath)

    def load_file_mapping(self, mapping_path: Path) -> None:
        """Validate and add a JSON file mapping."""
        data_files = TypeAdapter(list[DataFile]).validate_json(mapping_path.read_bytes())
        self.add_data(data_files)
