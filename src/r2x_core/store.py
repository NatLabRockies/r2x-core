"""Manage file-mapping configuration and its upgrade handler."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
from loguru import logger
from pydantic import TypeAdapter

from .datafile import DataFile
from .plugin_config import PluginConfig
from .utils.upgrade import UpgradeCoordinator
from .utils.validation import filter_kwargs_for

if TYPE_CHECKING:
    from .versioning import UpgradeHandler


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
