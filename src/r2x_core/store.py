"""Data Storage for managing R2X data files and their metadata.

Provides a high-level interface for managing data file configurations,
loading data, caching.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
import polars as pl
from loguru import logger
from pydantic import ValidationError
from rust_ok import Err, Ok

from .datafile import DataFile, FileProcessing
from .exceptions import ReaderError
from .plugin_config import PluginConfig, PluginConfigAsset
from .prepared_tables import (
    FileMapping,
    FileMappingDocument,
    PreparedTable,
    PreparedTableError,
    prepare_table_frames,
)
from .reader import DataReader
from .sources import (
    CalendarSource,
    ConfigRecordsSource,
    FirstPresentSource,
    RuntimeSource,
    SystemFrameSource,
)
from .utils import filter_valid_kwargs
from .utils.upgrade import UpgradeCoordinator

if TYPE_CHECKING:
    from .plugin_context import PluginContext


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
    load_file_mapping(mapping_data, mapping_path)
        Load a files/tables mapping envelope into the store.
    add_data(data_files, overwrite)
        Add one or more DataFile instances to the store.
    add_tables(tables, overwrite)
        Add prepared tables whose sources are registered files, tables, or frames.
    read_data(name, placeholders)
        Read a physical file or prepared table by name.
    read_table(name, placeholders)
        Read and validate a prepared table.
    is_optional(name)
        Return whether a physical source or table root may be absent.
    list_data()
        List all physical file and prepared table names in the store.
    list_files()
        List physical data file names in the store.
    list_tables()
        List prepared table names in the store.
    remove_data(*names)
        Remove unreferenced physical data files from the store.
    remove_table(*names)
        Remove tables not referenced by any remaining table.
    to_json(fpath, **model_dump_kwargs)
        Export store configuration to JSON.

    See Also
    --------
    :class:`DataFile` : Individual data file configuration.
    :class:`DataReader` : Reader for loading data files.
    :class:`PluginConfig` : Plugin configuration source.

    Notes
    -----
    Physical file and prepared table names must be unique within a store. Prepared
    tables may reference physical files, other prepared tables, and declared
    named-frame inputs. The reader cache is managed separately from the mapping.
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
        self.prepared_tables: dict[str, PreparedTable] = {}
        self.sources: dict[str, RuntimeSource] = {}
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
        """Access a physical data file by name."""
        return self.get_data_file(key)

    def __contains__(self, name: str) -> bool:
        """Check whether a physical file or prepared table is registered."""
        return name in self._cache or name in self.prepared_tables or name in self.sources

    def get_data_file(self, name: str) -> DataFile:
        """Return one physical file mapping."""
        if name not in self._cache:
            available_files = sorted(self._cache)
            raise KeyError(f"{name!r} not present in store. Available files: {available_files}")
        return self._cache[name]

    def is_optional(self, name: str) -> bool:
        """Return whether a physical input or table root may be absent."""
        if name in self.sources:
            source = self.sources[name]
            return isinstance(source, FirstPresentSource) and source.missing == "none"
        if name in self.prepared_tables:
            source = self.prepared_tables[name].source
            if source in self.prepared_tables:
                return self.is_optional(source)
            if source in self.sources:
                return self.is_optional(source)
            if source not in self._cache:
                return False
            name = source
        data_file = self.get_data_file(name)
        return bool(data_file.info and data_file.info.is_optional)

    def get_table(self, name: str) -> PreparedTable:
        """Return one prepared-table mapping."""
        try:
            return self.prepared_tables[name]
        except KeyError:
            raise KeyError(
                f"Prepared table {name!r} not present. Available tables: {sorted(self.prepared_tables)}"
            ) from None

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
            Path to a JSON mapping envelope containing ``files`` and ``tables``.
        path : Path | str | None
            Path to the folder containing data files. Defaults to the JSON's parent folder.
        upgrade_handler : Callable[..., Any] | None, optional
            Optional upgrade handler for missing files during reads.

        Returns
        -------
        DataStore
            New DataStore instance with physical files and prepared tables from JSON.

        Raises
        ------
        FileNotFoundError
            If the data folder or json_fpath does not exist.
        ValidationError
            If the mapping envelope, physical files, prepared tables, or their references are invalid.
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
        try:
            file_mapping = plugin_config.load_config(assets=[PluginConfigAsset.FILE_MAPPING])["file_mapping"]
        except FileNotFoundError:
            logger.warning(
                "File mapping not found for {} at {}; continuing with empty DataStore.",
                type(plugin_config).__name__,
                json_fpath,
            )
            return store

        try:
            store.load_file_mapping(file_mapping, mapping_path=json_fpath)
        except ValidationError as exc:
            if store._upgrade.should_attempt(exc):
                store._upgrade.run(store=store, reason="file mapping validation failed")
                file_mapping = plugin_config.load_config(assets=[PluginConfigAsset.FILE_MAPPING])[
                    "file_mapping"
                ]
                store.load_file_mapping(file_mapping, mapping_path=json_fpath)
            else:
                raise
        return store

    @classmethod
    def load_file(
        cls,
        fpath: str | Path,
        *,
        name: str | None = None,
        proc_spec: FileProcessing | dict[str, Any] | None = None,
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
        proc_spec : FileProcessing | dict[str, Any] | None, optional
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

        data_file = DataFile.model_validate({"name": name, "fpath": fpath, "proc_spec": proc_spec})
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

    def add_tables(self, tables: Sequence[PreparedTable], *, overwrite: bool = False) -> None:
        """Add prepared tables after validating names and file/frame references."""
        if any(not isinstance(table, PreparedTable) for table in tables):
            raise TypeError("tables must contain PreparedTable instances")
        names = [table.name for table in tables]
        if len(set(names)) != len(names):
            raise KeyError("Prepared table names must be unique")
        if set(names) & set(self._cache):
            raise KeyError("Prepared table names cannot collide with physical file names")
        existing = set(names) & set(self.prepared_tables)
        if existing and not overwrite:
            raise KeyError(f"Prepared tables already exist: {sorted(existing)}")

        updated_tables = dict(self.prepared_tables)
        updated_tables.update((table.name, table) for table in tables)
        FileMapping.model_validate(
            {
                "files": list(self._cache.values()),
                "tables": list(updated_tables.values()),
                "sources": list(self.sources.values()),
            }
        )
        self.prepared_tables = updated_tables

    def list_tables(self) -> list[str]:
        """List all prepared table names in sorted order."""
        return sorted(self.prepared_tables)

    def list_sources(self) -> list[str]:
        """List configured calendar and System projection sources."""
        return sorted(self.sources)

    def list_files(self) -> list[str]:
        """List physical file names for reader and upgrade operations."""
        return sorted(self._cache)

    def list_data(self) -> list[str]:
        """List physical, runtime, and prepared data names in sorted order.

        Use :meth:`list_files` when physical file mappings are required.
        """
        return sorted([*self._cache, *self.sources, *self.prepared_tables])

    def read_data(
        self,
        name: str,
        *,
        placeholders: dict[str, Any] | None = None,
        context: PluginContext | None = None,
    ) -> Any:
        """Read a physical file or configured prepared table by name.

        Parameters
        ----------
        name : str
            Name of the data file to load.
        placeholders : dict[str, Any] | None, optional
            Placeholder values for template substitution. Default is None.

        Returns
        -------
        Any
            Loaded data, typically a Polars LazyFrame, or ``None`` for an absent optional input.

        Raises
        ------
        KeyError
            If the data file name is not in the store.
        """
        if name in self.prepared_tables:
            return self.read_table(name, placeholders=placeholders, context=context)
        if name in self.sources:
            return self._materialize_runtime_source(
                name,
                context=context,
                placeholders=placeholders,
                cache={},
            )
        return self._read_data_file_by_name(name=name, placeholders=placeholders)

    def validate_input_data(self, *, placeholders: dict[str, Any] | None = None) -> None:
        """Validate required physical input tables against their file declarations."""
        from .processors import substitute_placeholders

        for name, data_file in self._cache.items():
            info = data_file.info
            if info is not None and not info.is_input:
                continue
            validation = data_file.validation
            is_optional = info.is_optional if info is not None else False
            if is_optional and validation is None:
                continue

            try:
                data = self.read_data(name, placeholders=placeholders)
            except (KeyError, OSError, ReaderError, ValueError, pl.exceptions.PolarsError) as error:
                raise ValueError(
                    f"Input dataset {name!r} at {data_file.fpath} could not be read: {error}"
                ) from error
            if data is None:
                if is_optional:
                    continue
                raise ValueError(f"Required input dataset {name!r} at {data_file.fpath} is absent")

            if not isinstance(data, pl.DataFrame | pl.LazyFrame):
                if validation is not None and (validation.required_columns or validation.required_values):
                    raise ValueError(
                        f"Input dataset {name!r} declares tabular constraints but is not a Polars frame"
                    )
                if (
                    validation.non_empty
                    if validation and validation.non_empty is not None
                    else not is_optional
                ) and not data:
                    raise ValueError(f"Required input dataset {name!r} at {data_file.fpath} is empty")
                continue

            schema = data.collect_schema() if isinstance(data, pl.LazyFrame) else data.schema
            available_columns = set(schema.names())
            required_columns = set(validation.required_columns) if validation is not None else set()
            if validation is not None:
                required_columns.update(item.column for item in validation.required_values)
            missing_columns = sorted(required_columns - available_columns)
            if missing_columns:
                raise ValueError(
                    f"Input dataset {name!r} at {data_file.fpath} is missing required columns {missing_columns}; "
                    f"available columns: {sorted(available_columns)}"
                )

            non_empty = (
                validation.non_empty if validation and validation.non_empty is not None else not is_optional
            )
            if non_empty:
                sample = data.limit(1).collect() if isinstance(data, pl.LazyFrame) else data.head(1)
                if sample.is_empty():
                    raise ValueError(f"Required input dataset {name!r} at {data_file.fpath} is empty")

            if validation is None:
                continue
            for constraint in validation.required_values:
                match substitute_placeholders(constraint.values, placeholders=placeholders):
                    case Err(error):
                        raise ValueError(
                            f"Input dataset {name!r} required values for column {constraint.column!r}: {error}"
                        ) from error
                    case Ok(values):
                        required_values = values if isinstance(values, list) else [values]
                if isinstance(data, pl.LazyFrame):
                    actual_values = (
                        data.select(constraint.column).unique().collect()[constraint.column].to_list()
                    )
                else:
                    actual_values = data.select(constraint.column).unique()[constraint.column].to_list()
                missing_values = [value for value in required_values if value not in actual_values]
                if missing_values:
                    label = constraint.label or name
                    raise ValueError(
                        f"{label} {missing_values!r} not found in {data_file.fpath} "
                        f"({name}.{constraint.column}); available values: {actual_values!r}"
                    )

    def prepare_tables(
        self,
        names: Sequence[str],
        /,
        *,
        inputs: Mapping[str, pl.DataFrame | pl.LazyFrame | None] | None = None,
        placeholders: dict[str, Any] | None = None,
        context: PluginContext | None = None,
    ) -> dict[str, pl.LazyFrame | None]:
        """Execute several prepared tables with one request-local source cache.

        Named table dependencies use the same table executor. Materialized
        sources are shared only during this call, including across output roots.
        Declared frame inputs may be transitive dependencies.
        """
        requested_names = tuple(names)
        if not requested_names:
            return {}
        if len(set(requested_names)) != len(requested_names):
            raise ValueError("prepared table request names must be unique")
        for table_name in requested_names:
            self.get_table(table_name)

        supplied = dict(inputs or {})
        source_cache: dict[str, pl.DataFrame | None] = {}
        active_tables: set[str] = set()

        def declared_frame_inputs(table_name: str, visited: set[str] | None = None) -> set[str]:
            """Return all named frame inputs reachable from one configured table."""
            visited = set() if visited is None else visited
            if table_name in visited:
                return set()
            visited.add(table_name)
            current = self.get_table(table_name)
            sources = {current.source, *(join.source for join in current.joins)}
            frame_names = set(current.frame_sources)
            for source in sources & self.prepared_tables.keys():
                frame_names.update(declared_frame_inputs(source, visited))
            return frame_names

        allowed_frames = set().union(*(declared_frame_inputs(name) for name in requested_names))
        allowed_frames.difference_update(self.sources)
        unknown_frames = sorted(set(supplied) - allowed_frames)
        if unknown_frames:
            raise PreparedTableError(
                f"Prepared table request {requested_names!r} received undeclared frame source(s): {unknown_frames}"
            )

        def materialize_source(
            source: str,
            data: object,
            *,
            table_name: str,
        ) -> pl.DataFrame | None:
            """Snapshot one in-memory source for this complete table request."""
            if data is None:
                return None
            if isinstance(data, pl.DataFrame):
                return data
            if isinstance(data, pl.LazyFrame):
                try:
                    return data.collect()
                except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
                    raise PreparedTableError(
                        f"Prepared table {table_name!r} failed while collecting source {source!r}: {exc}"
                    ) from exc
            raise PreparedTableError(
                f"Prepared table {table_name!r} source {source!r} returned {type(data).__name__}, "
                "expected a Polars DataFrame or LazyFrame"
            )

        def resolve_source(
            source: str,
            *,
            table_name: str,
            is_root: bool,
        ) -> pl.DataFrame | None:
            """Resolve one configured file, table, or caller-provided frame."""
            if source in self.prepared_tables:
                if source in source_cache:
                    return source_cache[source]
                try:
                    return resolve_table(source)
                except PreparedTableError as exc:
                    raise PreparedTableError(
                        f"Prepared table {table_name!r} dependency {source!r} failed: {exc}"
                    ) from exc

            if source in self.sources:
                if source in source_cache:
                    return source_cache[source]
                try:
                    data = self._materialize_runtime_source(
                        source,
                        context=context,
                        placeholders=placeholders,
                        cache=source_cache,
                    )
                except PreparedTableError as exc:
                    raise PreparedTableError(
                        f"Prepared table {table_name!r} could not resolve runtime source {source!r}: {exc}"
                    ) from exc
                return data

            if source in allowed_frames:
                if source in source_cache:
                    data = source_cache[source]
                elif source not in supplied:
                    data = None
                    source_cache[source] = None
                else:
                    data = materialize_source(source, supplied[source], table_name=table_name)
                    source_cache[source] = data
                if data is None and is_root:
                    if source not in supplied:
                        raise PreparedTableError(
                            f"Prepared table {table_name!r} requires named frame input(s): {[source]}"
                        )
                    raise PreparedTableError(
                        f"Prepared table {table_name!r} required source {source!r}, but it returned no data"
                    )
                return data

            if source not in self._cache:
                raise PreparedTableError(
                    f"Prepared table {table_name!r} references unknown source {source!r}"
                )

            if source in source_cache:
                data = source_cache[source]
                data_file = self.get_data_file(source)
                if data is None and is_root and not (data_file.info and data_file.info.is_optional):
                    raise PreparedTableError(
                        f"Prepared table {table_name!r} required source {source!r}, but it returned no data"
                    )
                return data

            data_file = self.get_data_file(source)
            try:
                raw_data = self._read_data_file_by_name(name=source, placeholders=placeholders)
            except (OSError, ValueError, KeyError, ReaderError, pl.exceptions.PolarsError) as exc:
                raise PreparedTableError(
                    f"Prepared table {table_name!r} could not read source {source!r}: {exc}"
                ) from exc
            if raw_data is None:
                if data_file.info and data_file.info.is_optional:
                    source_cache[source] = None
                    return None
                raise PreparedTableError(
                    f"Prepared table {table_name!r} required source {source!r}, but it returned no data"
                )
            data = materialize_source(source, raw_data, table_name=table_name)
            source_cache[source] = data
            return data

        class TableSources(Mapping[str, pl.DataFrame | pl.LazyFrame | None]):
            """Resolve declared table inputs only when the join loop requests them."""

            def __init__(self, table: PreparedTable, root: pl.DataFrame) -> None:
                self.names = tuple(dict.fromkeys([table.source, *(join.source for join in table.joins)]))
                self.table = table
                self.root = root

            def __getitem__(self, source: str) -> pl.DataFrame | None:
                if source not in self.names:
                    raise KeyError(source)
                if source == self.table.source:
                    return self.root
                return resolve_source(source, table_name=self.table.name, is_root=False)

            def __iter__(self) -> Iterator[str]:
                return iter(self.names)

            def __len__(self) -> int:
                return len(self.names)

        def resolve_table(table_name: str) -> pl.DataFrame | None:
            """Execute a table once and cache its materialized result for this call."""
            if table_name in source_cache:
                return source_cache[table_name]
            if table_name in active_tables:
                raise PreparedTableError(f"Prepared table dependency cycle includes {table_name!r}")
            table = self.get_table(table_name)
            active_tables.add(table_name)
            try:
                root = resolve_source(table.source, table_name=table.name, is_root=True)
                if root is None:
                    source_cache[table_name] = None
                    return None

                required_frames = {
                    join.source
                    for join in table.joins
                    if join.missing_source == "error"
                    and join.source in table.frame_sources
                    and join.source not in self.sources
                }
                missing_frames = sorted(required_frames - set(supplied))
                if missing_frames:
                    raise PreparedTableError(
                        f"Prepared table {table.name!r} requires named frame input(s): {missing_frames}"
                    )

                frames = TableSources(table, root)
                prepared = prepare_table_frames(table, frames, placeholders=placeholders)
                result = prepared.collect() if prepared is not None else None
                source_cache[table_name] = result
                return result
            finally:
                active_tables.remove(table_name)

        results: dict[str, pl.LazyFrame | None] = {}
        for table_name in requested_names:
            result = resolve_table(table_name)
            results[table_name] = result.lazy() if result is not None else None
        return results

    def _materialize_runtime_source(
        self,
        name: str,
        /,
        *,
        context: PluginContext | None,
        placeholders: dict[str, Any] | None,
        cache: dict[str, pl.DataFrame | None],
    ) -> pl.DataFrame | None:
        """Resolve one configured runtime source into a request-local snapshot."""
        if name in cache:
            return cache[name]
        try:
            source = self.sources[name]
            if isinstance(source, CalendarSource):
                frame = source.to_frame(placeholders=placeholders)
            elif isinstance(source, ConfigRecordsSource):
                if context is None:
                    raise ValueError("Configuration record sources require a PluginContext")
                frame = source.to_frame(context=context)
            elif isinstance(source, FirstPresentSource):
                frame = None
                for candidate in source.candidates:
                    if candidate in cache:
                        frame = cache[candidate]
                    elif candidate in self._cache:
                        data_file = self.get_data_file(candidate)
                        try:
                            self.reader.resolve_path(
                                data_file,
                                folder_path=self.folder,
                                placeholders=placeholders,
                            )
                        except FileNotFoundError as error:
                            if data_file.info and data_file.info.is_optional:
                                cache[candidate] = None
                                continue
                            raise ValueError(
                                f"Physical candidate {candidate!r} cannot be resolved: {error}"
                            ) from error
                        try:
                            raw = self._read_data_file_by_name(name=candidate, placeholders=placeholders)
                            if raw is None:
                                raise ValueError("reader returned no data for a present file")
                            if isinstance(raw, pl.LazyFrame):
                                frame = raw.collect()
                            elif isinstance(raw, pl.DataFrame):
                                frame = raw
                            else:
                                raise TypeError(
                                    f"reader returned {type(raw).__name__}, expected a Polars frame"
                                )
                        except (
                            OSError,
                            ReaderError,
                            TypeError,
                            ValueError,
                            pl.exceptions.PolarsError,
                        ) as error:
                            raise ValueError(
                                f"Selected physical candidate {candidate!r} failed: {error}"
                            ) from error
                        cache[candidate] = frame
                    else:
                        frame = self._materialize_runtime_source(
                            candidate,
                            context=context,
                            placeholders=placeholders,
                            cache=cache,
                        )
                    if frame is not None and (source.empty == "select" or not frame.is_empty()):
                        break
                    frame = None
                if frame is None and source.missing == "error":
                    raise ValueError(
                        f"No configured source is present for first-present source {source.name!r}: "
                        f"{source.candidates}"
                    )
            elif isinstance(source, SystemFrameSource):
                if context is None:
                    raise ValueError("System frame sources require a PluginContext")
                frame = source.to_frame(context=context, placeholders=placeholders)
            else:
                raise TypeError(f"Unsupported runtime source {type(source).__name__}")
        except (KeyError, OSError, ReaderError, TypeError, ValueError, pl.exceptions.PolarsError) as error:
            raise PreparedTableError(f"Could not resolve runtime source {name!r}: {error}") from error
        cache[name] = frame
        return frame

    def prepare_table(
        self,
        name: str,
        /,
        *,
        inputs: Mapping[str, pl.DataFrame | pl.LazyFrame | None] | None = None,
        placeholders: dict[str, Any] | None = None,
        context: PluginContext | None = None,
    ) -> pl.LazyFrame | None:
        """Execute one prepared-table recipe with request-local source resolution."""
        return self.prepare_tables((name,), inputs=inputs, placeholders=placeholders, context=context)[name]

    def read_table(
        self,
        name: str,
        *,
        placeholders: dict[str, Any] | None = None,
        context: PluginContext | None = None,
    ) -> pl.LazyFrame | None:
        """Resolve file, runtime, and table dependencies for one prepared table."""
        return self.prepare_table(name, inputs={}, placeholders=placeholders, context=context)

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

        dependencies = {
            table.name
            for table in self.prepared_tables.values()
            if table.source in names or any(join.source in names for join in table.joins)
        }
        if dependencies:
            raise KeyError(
                f"Cannot remove physical file(s) referenced by prepared table(s): {sorted(dependencies)}"
            )

        source_dependencies = {
            source.name: sorted(set(source.candidates) & set(names))
            for source in self.sources.values()
            if isinstance(source, FirstPresentSource) and set(source.candidates) & set(names)
        }
        if source_dependencies:
            raise KeyError(
                "Cannot remove physical file(s) referenced by configured first-present source(s): "
                f"{source_dependencies}"
            )

        for name in names:
            del self._cache[name]
            logger.debug("Removed data file '{}' from store", name)

    def remove_table(self, *names: str) -> None:
        """Remove prepared tables not referenced by any remaining table."""
        removing = set(names)
        missing = sorted(removing - self.prepared_tables.keys())
        if missing:
            raise KeyError(f"Prepared table(s) not found in store: {missing}")

        dependencies = {
            table.name: sorted({table.source, *(join.source for join in table.joins)} & removing)
            for table in self.prepared_tables.values()
            if table.name not in removing
        }
        dependencies = {name: sources for name, sources in dependencies.items() if sources}
        if dependencies:
            raise KeyError(
                f"Cannot remove prepared table(s) referenced by remaining prepared table(s): {dependencies}"
            )

        for name in sorted(removing):
            del self.prepared_tables[name]
            logger.debug("Removed prepared table '{}' from store", name)

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
        json_data = {
            "files": [
                data_file.model_dump(
                    mode="json",
                    round_trip=True,
                    **filter_valid_kwargs(data_file.model_dump, kwargs=model_dump_kwargs),
                )
                for data_file in self._cache.values()
            ],
            "tables": [
                table.model_dump(
                    mode="json",
                    round_trip=True,
                    **filter_valid_kwargs(table.model_dump, kwargs=model_dump_kwargs),
                )
                for table in self.prepared_tables.values()
            ],
        }
        if self.sources:
            json_data["sources"] = [source.model_dump(mode="json") for source in self.sources.values()]

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
            raise TypeError("data_files must contain DataFile instances")

        names = [data_file.name for data_file in data_files]
        if len(set(names)) != len(names):
            raise KeyError("Physical file names must be unique")
        if set(names) & set(self.prepared_tables):
            raise KeyError("Physical file names cannot collide with prepared table names")
        if any(data_file.name in self._cache for data_file in data_files) and not overwrite:
            msg = "Some data files already exists with the same name. "
            msg += "Pass overwrite=True to replace it."
            raise KeyError(msg)

        updated_files = dict(self._cache)
        updated_files.update((data_file.name, data_file) for data_file in data_files)
        FileMapping.model_validate(
            {
                "files": list(updated_files.values()),
                "tables": list(self.prepared_tables.values()),
                "sources": list(self.sources.values()),
            }
        )
        self._cache = updated_files
        for data_file in data_files:
            logger.debug("Added data file '{}' to store", data_file.name)
        return

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
        if name not in self._cache:
            if name in self.prepared_tables:
                raise ValueError(f"{name!r} is a prepared table; use read_data() to read configured datasets")
            raise KeyError(f"'{name}' not present in store. Available files: {sorted(self._cache)}")

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
        """Load physical files and prepared tables from a file-mapping JSON."""
        logger.info("Loading file mapping from {}", mapping_path)
        with open(mapping_path, "rb") as f:
            data_files_json = orjson.loads(f.read())
        self.load_file_mapping(data_files_json, mapping_path=mapping_path)

    def load_file_mapping(self, mapping_data: Mapping[str, object], *, mapping_path: Path) -> None:
        """Load physical files and prepared tables from a mapping envelope."""
        document = FileMappingDocument.model_validate(mapping_data)
        data_files = DataFile.from_records(document.files, folder_path=self.folder)
        complete_mapping = FileMapping(
            files=[*self._cache.values(), *data_files],
            tables=[*self.prepared_tables.values(), *document.tables],
            sources=[*self.sources.values(), *document.sources],
        )
        self._cache = {data_file.name: data_file for data_file in complete_mapping.files}
        self.prepared_tables = {table.name: table for table in complete_mapping.tables}
        self.sources = {source.name: source for source in complete_mapping.sources}
        logger.debug(
            "Loaded {} physical files and {} prepared tables from {}",
            len(data_files),
            len(document.tables),
            mapping_path,
        )
