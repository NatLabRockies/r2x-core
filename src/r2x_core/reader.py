"""Data reading and processing pipeline for multiple file formats.

The DataReader is the main entry point for loading data files. It handles:
- Path resolution (absolute, relative, and glob patterns)
- File type detection based on extension
- Optional file handling (returns None instead of raising errors)
- Custom reader function delegation
- Automatic data processing and transformations (filtering, type casting, etc.)
- Placeholder substitution in data file paths and processing specifications

File type support is determined by EXTENSION_MAPPING. Tabular files are read
by selected FileReader adapters and processed by a selected TabularBackend.
JSON and XML use the same FileReader contract as tabular formats.

See Also
--------
:class:`~r2x_core.datafile.DataFile` : File configuration with metadata and processing specs.
:class:`~r2x_core.file_reader.FileReader` : File-format reader interface.
:class:`~r2x_core.tabular_backend.TabularBackend` : Tabular processing interface.
:class:`~r2x_core.json_adapter.JSONProcessor` : JSON processing interface.
:class:`~r2x_core.json_adapter.JSONFileReader` : Built-in JSON reader.
:class:`~r2x_core.xml_adapter.XMLFileReader` : Built-in XML reader.
:func:`~r2x_core.processors.apply_processing` : Transformation pipeline.
:func:`~r2x_core.utils.files.get_fpath` : Path resolution and validation.
"""

from collections.abc import Sequence
from functools import cached_property
from pathlib import Path
from typing import Any

from loguru import logger
from rust_ok import is_err, is_ok

from .datafile import DataFile, ReaderConfig
from .exceptions import ConfiguredGroupNotFoundError, ReaderError
from .file_reader import FileReader, default_tabular_file_reader
from .json_adapter import JSONFileReader, JSONProcessor, default_json_processor
from .models import JSONProcessing, TabularProcessing
from .processors import apply_processing, substitute_placeholders
from .tabular_backend import TabularBackend, default_tabular_backend
from .types import EXTENSION_MAPPING, FileFormat, FileRequirement, TableDataFormat
from .utils.files import get_fpath
from .xml_adapter import XMLFileReader


class DataReader:
    """Reader class for loading data files with automatic processing.

    The DataReader handles the complete reading pipeline: file discovery,
    format detection, reading, and transformations. File reading is delegated
    to selected format adapters, and tabular processing to a selected backend.

    See Also
    --------
    :class:`~r2x_core.datafile.DataFile` : File configuration with specs.
    :meth:`read_data_file` : Main method for reading data with processing.
    """

    def __init__(
        self,
        *,
        file_readers: Sequence[FileReader[Any]] | None = None,
        tabular_backend: TabularBackend[Any] | None = None,
        json_processor: JSONProcessor | None = None,
    ) -> None:
        """Initialize with optional file readers and processing adapters.

        Custom readers take precedence over built-ins. The default Polars
        reader and tabular backend are loaded only when requested.
        """
        configured_file_readers = () if file_readers is None else tuple(file_readers)
        self.file_readers: tuple[FileReader[Any], ...] = (
            *configured_file_readers,
            JSONFileReader(),
            XMLFileReader(),
        )
        if tabular_backend is not None:
            self.tabular_backend = tabular_backend
        if json_processor is not None:
            self.json_processor = json_processor

    @cached_property
    def tabular_backend(self) -> TabularBackend[Any]:
        """Lazily create the default backend when none was configured."""
        return default_tabular_backend()

    @cached_property
    def json_processor(self) -> JSONProcessor:
        """Lazily create the default JSON processor when none was configured."""
        return default_json_processor()

    @cached_property
    def tabular_file_reader(self) -> FileReader[Any]:
        """Lazily create the default tabular file reader."""
        return default_tabular_file_reader()

    def select_file_reader(self, file_type: FileFormat, /) -> FileReader[Any]:
        """Select the first configured reader that supports a file format.

        The default Polars reader is loaded lazily for tabular formats when no
        configured reader supports the format.

        Raises
        ------
        ValueError
            If no configured or default reader supports the format.
        """
        for file_reader in self.file_readers:
            if file_reader.supports_file_type(file_type):
                return file_reader

        if isinstance(file_type, TableDataFormat):
            return self.tabular_file_reader

        msg = f"No file reader configured for {type(file_type).__name__}"
        raise ValueError(msg)

    def read_data_file(
        self,
        data_file: DataFile,
        *,
        folder_path: Path,
        placeholders: dict[str, Any] | None = None,
    ) -> Any:
        """Read a data file.

        Parameters
        ----------
        data_file : DataFile
            Data file configuration with metadata.
        folder_path : Path
            Base directory containing the data files.
        placeholders : dict[str, Any] | None, optional
            Dictionary mapping placeholder variable names to their values.
            Used to substitute placeholders in file paths and processing values.
            Default is None.

        Returns
        -------
        Any
            The loaded data, type depends on file type.

        Raises
        ------
        FileNotFoundError
            If a required file does not exist or if a glob pattern matches no files.
        ValueError
            If glob pattern is malformed (no wildcards) or if placeholders are found
            without a corresponding value in ``placeholders``.
        MultipleFileError
            If a glob pattern matches multiple files (subclass of ValueError).

        See Also
        --------
        :class:`~r2x_core.file_reader.FileReader` : File-format reader interface.
        :class:`~r2x_core.tabular_backend.TabularBackend` : Tabular processing interface.
        :class:`~r2x_core.json_adapter.JSONProcessor` : JSON processing interface.
        :meth:`select_file_reader` : File-format adapter selection.
        :func:`~r2x_core.processors.apply_processing` : Transformation pipeline.
        :func:`~r2x_core.utils.files.get_fpath` : Path resolution.
        """
        logger.debug("Starting reading for data_file={}", data_file.name)
        data_file = self.substitute_path_placeholders(data_file, placeholders=placeholders)
        is_optional = data_file.info.requirement is FileRequirement.OPTIONAL

        fpath_result = get_fpath(data_file, folder_path=folder_path)
        if is_ok(fpath_result):
            fpath = fpath_result.value
        else:
            error = fpath_result.err()
            if isinstance(error, FileNotFoundError) and is_optional:
                logger.info("Skipping optional file: {}", data_file.name)
                return None
            raise error

        reader = data_file.reader
        reader_kwargs = dict(reader.kwargs) if reader else {}
        if reader and reader.function:
            logger.debug(
                "Attempting to read data_file{} with reader_function={}",
                data_file.name,
                data_file.reader,
            )
            raw_data = reader.function(fpath, **reader_kwargs)
        else:
            file_type_instance = data_file.file_format
            logger.trace(
                "Attempting to read data_file={} with {}", data_file.name, type(file_type_instance).__name__
            )
            try:
                file_reader = self.select_file_reader(file_type_instance)
                raw_data = file_reader.read_file(
                    file_type_instance,
                    file_path=fpath,
                    reader_config=reader if reader is not None else ReaderConfig(kwargs={}),
                )
            except ConfiguredGroupNotFoundError:
                if is_optional:
                    logger.debug("Skipping optional file with missing configured group: {}", data_file.name)
                    return None
                raise

        processor = None
        if isinstance(data_file.proc_spec, TabularProcessing):
            processor = self.tabular_backend
        elif isinstance(data_file.proc_spec, JSONProcessing):
            processor = self.json_processor
        processed_data = apply_processing(
            raw_data,
            data_file=data_file,
            proc_spec=data_file.proc_spec,
            placeholders=placeholders,
            processor=processor,
        )
        if is_err(processed_data):
            raise ReaderError(processed_data.err())
        return processed_data.unwrap()

    @staticmethod
    def substitute_path_placeholders(
        data_file: DataFile,
        *,
        placeholders: dict[str, Any] | None,
    ) -> DataFile:
        """Substitute placeholders in a DataFile path source before resolution."""

        def substituted(value: Path | str | None) -> str | None:
            """Substitute placeholders in one optional path source."""
            if value is None or "{" not in str(value):
                return None
            result = substitute_placeholders(str(value), placeholders=placeholders)
            if is_err(result):
                raise result.err()
            return str(result.unwrap())

        updates: dict[str, Path | str] = {}
        fpath = substituted(data_file.fpath)
        if fpath is not None:
            updates["fpath"] = Path(fpath)
        relative_fpath = substituted(data_file.relative_fpath)
        if relative_fpath is not None:
            updates["relative_fpath"] = relative_fpath
        glob = substituted(data_file.glob)
        if glob is not None:
            updates["glob"] = glob
        return data_file.model_copy(update=updates) if updates else data_file

    def get_supported_file_types(self) -> list[str]:
        """Get list of supported file extensions.

        Returns
        -------
        list[str]
            List of supported file extensions.
        """
        return list(EXTENSION_MAPPING)
