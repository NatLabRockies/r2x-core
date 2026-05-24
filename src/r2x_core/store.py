"""Data Storage for managing R2X data files and their metadata.

Provides a high-level interface for managing data file configurations,
loading data, caching.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import orjson
from loguru import logger
from pydantic import ValidationError

from .datafile import DataFile, FileProcessing, TabularProcessing
from .plugin_config import PluginConfig
from .reader import DataReader
from .utils import filter_valid_kwargs
from .utils._upgrade_coordinator import UpgradeCoordinator


class DataStore:
    """Container for managing data file mappings and loading data.

    The :class:`DataStore` provides a high-level interface for managing
    a collection of :class:`DataFile` instances, including loading data,
    caching, and executing version upgrades. It can be initialized from
    a folder path, JSON configuration, or :class:`PluginConfig`.

    Parameters
    ----------
    path : str | Path | None, optional
        Path to the folder containing data files or a ``file_mapping.json``.
        If None, uses current working directory. Default is None.
    reader : DataReader | None, optional
        Custom :class:`DataReader` instance. If None, a default reader
        is created. Default is None.
    upgrade_handler : Callable[..., Any] | None, optional
        Optional upgrade handler to run when missing files require migration.

    Attributes
    ----------
    folder : Path
        The resolved folder path containing the data files.
    reader : DataReader
        The data reader instance used to load data.

    Methods
    -------
    from_data_files(data_files, path)
        Create a DataStore from a list of DataFile instances.
    from_json(json_fpath, path)
        Create a DataStore from a JSON configuration file.
    from_plugin_config(plugin_config, path)
        Create a DataStore from a PluginConfig instance.
    add_data(*data_files, overwrite)
        Add one or more DataFile instances to the store.
    read_data(name, placeholders)
        Load data from a file by name.
    list_data()
        List all data file names in the store.
    remove_data(*names)
        Remove one or more data files from the store.
    to_json(fpath, **model_dump_kwargs)
        Export store configuration to JSON.

    See Also
    --------
    :class:`DataFile` : Individual data file configuration.
    :class:`DataReader` : Reader for loading data files.
    :class:`PluginConfig` : Plugin configuration source.

    Notes
    -----
    All data file names must be unique within a store. The reader cache
    is managed separately from the file configuration cache.
    """

    def __init__(
        self,
        /,
        path: str | Path | None = None,
        *,
        reader: DataReader | None = None,
        upgrade_handler: Callable[..., Any] | None = None,
    ) -> None:
        """Initialize the DataStore."""
        if path is None:
            logger.debug("Starting store in current directory: {}", str(Path.cwd()))
            resolved_path = Path.cwd()
        else:
            resolved_path = Path(path)

        if not resolved_path.exists():
            raise FileNotFoundError(f"Path does not exist: {resolved_path}")

        mapping_path: Path | None = None
        if resolved_path.is_file():
            mapping_path = resolved_path
            folder_path = resolved_path.parent
        else:
            folder_path = resolved_path

        self._reader = reader or DataReader()
        self._folder = folder_path.resolve()
        self._cache: dict[str, DataFile] = {}
        self._upgrade = UpgradeCoordinator(handler=upgrade_handler)
        logger.debug("Initialized DataStore with folder: {}", self.folder)

        if mapping_path is not None:
            self._load_file_mapping(mapping_path)

    @property
    def folder(self) -> Path:
        """Return the resolved folder path containing data files."""
        return self._folder

    @property
    def reader(self) -> DataReader:
        """Return the :class:`DataReader` instance."""
        return self._reader

    def __getitem__(self, key: str) -> DataFile:
        """Access data file by name. Equivalent to :meth:`_get_data_file_by_name`."""
        return self._get_data_file_by_name(name=key)

    def __contains__(self, name: str) -> bool:
        """Check if a :class:`DataFile` exists in the store."""
        return name in self._cache

    @classmethod
    def from_data_files(
        cls,
        data_files: list[DataFile],
        *,
        path: Path | str | None = None,
        upgrade_handler: Callable[..., Any] | None = None,
    ) -> DataStore:
        """Create a :class:`DataStore` from a list of :class:`DataFile` instances.

        Parameters
        ----------
        data_files : list[DataFile]
            List of DataFile instances to add to the store.
        path : Path | str | None, optional
            Path to the folder containing data files. Default is None.
        upgrade_handler : Callable[..., Any] | None, optional
            Optional upgrade handler for missing files during reads.

        Returns
        -------
        DataStore
            New DataStore instance with provided data files.
        """
        store = cls(path=path, upgrade_handler=upgrade_handler)
        store.add_data(data_files)
        return store

    @classmethod
    def from_json(
        cls,
        json_fpath: Path | str,
        *,
        path: Path | str | None = None,
        upgrade_handler: Callable[..., Any] | None = None,
    ) -> DataStore:
        """Create a :class:`DataStore` from a JSON configuration file.

        Parameters
        ----------
        json_fpath : Path | str
            Path to the JSON file containing data file configurations.
        path : Path | str | None
            Path to the folder containing data files. Defaults to the JSON's parent folder.
        upgrade_handler : Callable[..., Any] | None, optional
            Optional upgrade handler for missing files during reads.

        Returns
        -------
        DataStore
            New DataStore instance with data files from JSON.

        Raises
        ------
        FileNotFoundError
            If the data folder or json_fpath does not exist.
        TypeError
            If JSON file is not a JSON array.
        ValidationError
            If data files in JSON are invalid.
        """
        json_fpath = Path(json_fpath)

        if not json_fpath.exists():
            raise FileNotFoundError(f"Configuration file not found: {json_fpath}")
        folder_path = Path(path) if path is not None else json_fpath.parent

        if not folder_path.exists():
            raise FileNotFoundError(f"Data folder not found: {folder_path}")

        store = cls(path=folder_path, upgrade_handler=upgrade_handler)
        store._load_file_mapping(json_fpath)
        return store

    @classmethod
    def from_plugin_config(
        cls,
        plugin_config: PluginConfig,
        *,
        path: Path | str,
        upgrade_handler: Callable[..., Any] | None = None,
    ) -> DataStore:
        """Create a :class:`DataStore` from a :class:`PluginConfig` instance.

        Parameters
        ----------
        plugin_config : PluginConfig
            Plugin configuration containing file mappings.
        path : Path | str
            Path to the folder containing data files.
        upgrade_handler : Callable[..., Any] | None, optional
            Optional upgrade handler to run if file mappings fail to validate.
            If None, the store attempts to resolve a handler from the plugin package.

        Returns
        -------
        DataStore
            New DataStore instance with data files from plugin config.
        """
        json_fpath = plugin_config.fmap_path
        logger.info("Loading DataStore from plugin config: {}", type(plugin_config).__name__)
        logger.debug("File mapping path: {}", json_fpath)
        store = cls(path=path)
        store.configure_upgrades(plugin_config=plugin_config, upgrade_handler=upgrade_handler)
        if not json_fpath.exists():
            logger.warning(
                "File mapping not found for {} at {}; continuing with empty DataStore.",
                type(plugin_config).__name__,
                json_fpath,
            )
            return store
        try:
            store._load_file_mapping(json_fpath)
        except ValidationError as exc:
            if store._upgrade.should_attempt(exc):
                store._upgrade.run(store=store, reason="file mapping validation failed")
                store._load_file_mapping(json_fpath)
            else:
                raise
        return store

    @classmethod
    def load_file(
        cls,
        fpath: str | Path,
        *,
        name: str | None = None,
        proc_spec: FileProcessing | None = None,
    ) -> Any:
        """Load a single data file conveniently without creating a full DataStore.

        This is a convenience method for loading a single file with minimal setup.
        For complex use cases with multiple files, use the full DataStore API.

        Parameters
        ----------
        fpath : str | Path
            Path to the data file to load.
        name : str | None, optional
            Name identifier for the file. If None, uses the file stem (name without extension).
            Default is None.
        proc_spec : FileProcessing | None, optional
            Process to apply to the file data. Can be a TabularProcessing or JSONProcessing
            instance, or a dictionary with transformation parameters. Default is None.

        Returns
        -------
        Any
            Loaded data from the file (type depends on file format).

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        Exception
            If the file cannot be read.
        """
        fpath = Path(fpath)

        if not fpath.exists():
            raise FileNotFoundError(f"File not found: {fpath}")

        if name is None:
            name = fpath.stem

        store = cls(path=fpath.parent)

        if proc_spec and isinstance(proc_spec, dict):
            proc_spec = TabularProcessing.model_validate(proc_spec)

        data_file = DataFile(
            name=name,
            fpath=fpath,
            proc_spec=proc_spec,
        )
        store.add_data([data_file])

        return store.read_data(name=name)

    def add_data(self, data_files: Sequence[DataFile], *, overwrite: bool = False) -> None:
        """Add one or more :class:`DataFile` instances to the store.

        Parameters
        ----------
        data_files : Sequence[DataFile]
            DataFile instances to add.
        overwrite : bool, optional
            If True, overwrite existing data files with the same name.
            Default is False.

        Raises
        ------
        TypeError
            If any item is not a DataFile instance.
        KeyError
            If a data file with the same name exists and overwrite is False.
        """
        return self._add_data_file(data_files, overwrite=overwrite)

    def list_data(self) -> list[str]:
        """List all data file names in the store.

        Returns
        -------
        list[str]
            Sorted list of all data file names.
        """
        return sorted(self._cache.keys())

    def read_data(self, name: str, *, placeholders: dict[str, Any] | None = None) -> Any:
        """Load data from a file using the configured :class:`DataReader`.

        Parameters
        ----------
        name : str
            Name of the data file to load.
        placeholders : dict[str, Any] | None, optional
            Placeholder values for template substitution. Default is None.

        Returns
        -------
        Any
            Loaded data from the file.

        Raises
        ------
        KeyError
            If the data file name is not in the store.
        """
        return self._read_data_file_by_name(name=name, placeholders=placeholders)

    def configure_upgrades(
        self,
        *,
        plugin_config: PluginConfig | None = None,
        upgrade_handler: Callable[..., Any] | None = None,
    ) -> None:
        """Configure upgrade handling for this store."""
        self._upgrade = UpgradeCoordinator(
            plugin_config=plugin_config,
            handler=upgrade_handler,
        )
        self._upgrade.resolve()

    def remove_data(self, *names: str) -> None:
        """Remove one or more data files from the store.

        Parameters
        ----------
        *names : str
            Data file names to remove.
            Example: remove_data("file1", "file2")

        Raises
        ------
        KeyError
            If any data file name is not in the store.
        """
        for name in names:
            if name not in self._cache:
                raise KeyError(f"Data file '{name}' not found in store.")

        for name in names:
            del self._cache[name]
            logger.debug("Removed data file '{}' from store", name)

    def to_json(self, fpath: str | Path, **model_dump_kwargs: dict[str, Any]) -> None:
        """Save the :class:`DataStore` configuration to a JSON file.

        Parameters
        ----------
        fpath : str | Path
            Path where JSON file will be written.
        **model_dump_kwargs : dict[str, Any]
            Additional keyword arguments passed to :meth:`DataFile.model_dump`.

        Notes
        -----
        Output JSON is formatted with 2-space indentation and includes Unicode.
        """
        json_data = [
            data_file.model_dump(
                mode="json",
                round_trip=True,
                **filter_valid_kwargs(data_file.model_dump, kwargs=model_dump_kwargs),
            )
            for data_file in self._cache.values()
        ]

        with open(fpath, "wb") as f:
            f.write(orjson.dumps(json_data, option=orjson.OPT_INDENT_2))

        logger.info("Created JSON file at {}", fpath)

    def _add_data_file(
        self,
        data_files: Sequence[DataFile],
        *,
        overwrite: bool = False,
    ) -> None:
        """Add :class:`DataFile` instances to the store (internal).

        Parameters
        ----------
        data_files : Sequence[DataFile]
            DataFile instances to add.
        overwrite : bool, optional
            If True, overwrite existing data files. Default is False.
        """
        if any(not isinstance(data_file, DataFile) for data_file in data_files):
            raise TypeError

        if any(data_file.name in self._cache for data_file in data_files) and not overwrite:
            msg = "Some data files already exists with the same name. "
            msg += "Pass overwrite=True to replace it."
            raise KeyError(msg)

        for data_file in data_files:
            self._cache[data_file.name] = data_file
            logger.debug("Added data file '{}' to store", data_file.name)
        return

    def _get_data_file_by_name(self, name: str) -> DataFile:
        """Retrieve a :class:`DataFile` configuration by name (internal).

        Parameters
        ----------
        name : str
            Name of the data file.

        Returns
        -------
        DataFile
            The requested data file.

        Raises
        ------
        KeyError
            If the data file name is not in the store.
        """
        if name not in self._cache:
            available_files = list(self._cache.keys())
            raise KeyError(f"'{name}' not present in store. Available files: {available_files}")

        return self._cache[name]

    def _read_data_file_by_name(self, /, *, name: str, placeholders: dict[str, Any] | None = None) -> Any:
        """Load data from a file by name (internal).

        Parameters
        ----------
        name : str
            Name of the data file.
        placeholders : dict[str, Any] | None, optional
            Placeholder values for substitution. Default is None.

        Returns
        -------
        Any
            Loaded data.

        Raises
        ------
        KeyError
            If the data file name is not in the store.
        """
        if name not in self:
            raise KeyError(f"'{name}' not present in store.")

        data_file = self._cache[name]
        try:
            return self.reader.read_data_file(
                data_file,
                folder_path=self.folder,
                placeholders=placeholders,
            )
        except FileNotFoundError as exc:
            if not self._upgrade.can_run:
                raise
            logger.warning("Missing data file; attempting upgrade before retrying: {}", exc)
            self._upgrade.run(store=self, reason="missing data file during read")
            return self.reader.read_data_file(
                data_file,
                folder_path=self.folder,
                placeholders=placeholders,
            )

    def _load_file_mapping(self, mapping_path: Path) -> None:
        """Load DataFile definitions from a file-mapping JSON."""
        logger.info("Loading file mapping from {}", mapping_path)
        with open(mapping_path, "rb") as f:
            data_files_json = orjson.loads(f.read())

        if not isinstance(data_files_json, list):
            msg = f"JSON file `{mapping_path}` is not a JSON array."
            raise TypeError(msg)

        data_files = DataFile.from_records(data_files_json, folder_path=self.folder)
        self.add_data(data_files)
