"""Data reading and processing pipeline for multiple file formats.

The DataReader is the main entry point for loading data files. It handles:
- Path resolution (absolute, relative, and glob patterns)
- File type detection based on extension
- Optional file handling (returns None instead of raising errors)
- Custom reader function delegation
- Automatic data processing and transformations (filtering, type casting, etc.)
- Placeholder substitution in filter specifications

File type support is determined by EXTENSION_MAPPING, with custom readers
available via the reader parameter in DataFile configurations.

See Also
--------
:class:`~r2x_core.datafile.DataFile` : File configuration with metadata and processing specs.
:class:`~r2x_core.file_readers.read_file_by_type` : Singledispatch file readers by type.
:func:`~r2x_core.processors.apply_processing` : Data transformation pipeline.
:func:`~r2x_core.datafile_utils.get_file_path` : Path resolution and validation.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger
from rust_ok import Ok

from .datafile import DataFile
from .exceptions import ReaderError
from .file_readers import read_file_by_type
from .file_types import EXTENSION_MAPPING
from .processors import apply_processing, register_transformation
from .utils._datafile import get_fpath


class DataReader:
    """Reader class for loading data files with automatic processing.

    The DataReader handles the complete reading pipeline: file discovery,
    format detection, reading, and transformations. File-type-specific
    reading logic is delegated via singledispatch based on file extension.

    See Also
    --------
    :class:`~r2x_core.datafile.DataFile` : File configuration with specs.
    :func:`read_data_file` : Main method for reading data with processing.
    """

    def __init__(self) -> None:
        """Initialize the data reader.

        No configuration needed; the reader is stateless and uses configuration
        from DataFile objects and optional placeholders at read time.
        """

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
            Used to substitute placeholders like {solve_year} in filter_by.
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
            in filter_by but no placeholders dict provided.
        MultipleFileError
            If a glob pattern matches multiple files (subclass of ValueError).

        See Also
        --------
        :func:`~r2x_core.file_readers.read_file_by_type` : File-type-specific reading.
        :func:`~r2x_core.processors.apply_processing` : Transformation pipeline.
        :func:`~r2x_core.datafile_utils.get_file_path` : Path resolution.
        """
        logger.debug("Starting reading for data_file={}", data_file.name)
        is_optional = data_file.info.is_optional if data_file.info else False  # By default files are no-opt

        fpath_result = get_fpath(data_file, folder_path=folder_path, info=data_file.info)
        if fpath_result.is_err():
            error = fpath_result.err()
            if isinstance(error, FileNotFoundError) and is_optional:
                logger.info("Skipping optional file: {}", data_file.name)
                return None
            raise error
        assert isinstance(fpath_result, Ok), "Result should be Ok after error check"
        fpath = fpath_result.value

        reader = data_file.reader
        reader_kwargs = reader.kwargs if reader else {}
        if reader and reader.function:
            logger.debug(
                "Attempting to read data_file{} with reader_function={}",
                data_file.name,
                data_file.reader,
            )
            raw_data = reader.function(fpath, **reader_kwargs)
            if data_file.proc_spec is not None:
                processed_data = apply_processing(
                    raw_data,
                    data_file=data_file,
                    proc_spec=data_file.proc_spec,
                    placeholders=placeholders,
                )

                if processed_data.is_err():
                    raise ReaderError(processed_data.error)
                assert isinstance(processed_data, Ok), "Result should be Ok after error check"
                processed_data = processed_data.value
            else:
                processed_data = raw_data

            return processed_data

        file_type_instance = data_file.file_type
        logger.trace(
            "Attempting to read data_file={} with {}", data_file.name, type(file_type_instance).__name__
        )
        raw_data = read_file_by_type(file_type_instance, file_path=fpath, **reader_kwargs)
        if data_file.proc_spec is not None:
            processed_data = apply_processing(
                raw_data, data_file=data_file, proc_spec=data_file.proc_spec, placeholders=placeholders
            )
            if processed_data.is_err():
                raise ReaderError(processed_data.error)
            assert isinstance(processed_data, Ok), "Result should be Ok after error check"
            processed_data = processed_data.value
        else:
            processed_data = raw_data
        return processed_data

    _SUPPORTED_FILE_TYPES: list[str] | None = None

    def get_supported_file_types(self) -> list[str]:
        """Get list of supported file extensions.

        Returns
        -------
        list[str]
            List of supported file extensions.
        """
        if self._SUPPORTED_FILE_TYPES is None:
            type(self)._SUPPORTED_FILE_TYPES = list(EXTENSION_MAPPING.keys())
        # Type checker does not narrow the class-level attribute after the if.
        result = type(self)._SUPPORTED_FILE_TYPES
        assert result is not None
        return result

    def register_custom_transformation(
        self,
        data_types: type | tuple[type, ...],
        *,
        transform_func: Callable[[DataFile, Any], Any],
    ) -> None:
        """Register a custom transformation function.

        Parameters
        ----------
        data_types : type or tuple of types
            Data type(s) the function can handle.
        transform_func : callable
            Function that transforms data given a DataFile configuration.
            Signature: (data_file: DataFile, data: Any) -> Any

        Examples
        --------
        >>> def my_transform(data_file: DataFile, data: MyClass) -> MyClass:
        ...     # Custom logic here
        ...     return data
        >>> reader.register_custom_transformation(MyClass, transform_func=my_transform)
        """
        register_transformation(data_types, func=transform_func)
