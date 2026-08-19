"""File readers by file type."""

import json
from functools import singledispatch
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from h5py import File as h5pyFile
from loguru import logger
from polars import DataFrame, LazyFrame, scan_csv

from .file_types import H5Format, JSONFormat, TableFormat, XMLFormat


@singledispatch
def read_file_by_type(file_type_instance: Any, *, file_path: Path, **reader_kwargs: dict[str, Any]) -> Any:
    """Read file based on FileFormat instance using single dispatch.

    This is the main dispatch function that routes to specific readers
    based on the file format instance.

    Parameters
    ----------
    file_type_instance : FileFormat
        FileFormat instance to dispatch on (TableFormat(), H5Format(), etc.).
    file_path : Path
        Path to the file to read.
    reader_kwargs: dict[str, Any]
        Additional kwargs for reader function.

    Returns
    -------
    Any
        Raw file data in the appropriate format.

    Raises
    ------
    NotImplementedError
        If no reader is implemented for the given file type.
    """
    msg = f"No reader implemented for file type: {file_type_instance}"
    raise NotImplementedError(msg)


@read_file_by_type.register
def _(file_type_class: TableFormat, *, file_path: Path, **reader_kwargs: Any) -> LazyFrame:
    """Read CSV/TSV files as LazyFrame.

    Parameters
    ----------
    file_type_class : TableFormat
        TableFormat class (not used, but required for dispatch).
    file_path : Path
        Path to the CSV/TSV file.
    reader_kwargs: dict[str, Any]
        Additional kwargs for reader function.

    Returns
    -------
    pl.LazyFrame
        Lazy DataFrame containing the tabular data.
    """
    logger.debug("Scanning {}", file_path)
    if file_path.suffix.lower() == ".tsv":
        return scan_csv(file_path, separator="\t", **reader_kwargs)
    return scan_csv(file_path, **reader_kwargs)


@read_file_by_type.register
def _(file_type_class: H5Format, *, file_path: Path, **reader_kwargs: Any) -> LazyFrame:
    """Read HDF5 files as LazyFrame.

    Parameters
    ----------
    file_type_class : H5Format
        H5Format instance.
    file_path : Path
        Path to the HDF5 file.
    reader_kwargs: dict[str, Any]
        Configuration describing the H5 file structure. Common options:

        - **group_key** (str): Optional HDF5 group to read from.
        - **data_key** (str): Key for main data array.
        - **columns_key** (str): Key for column names dataset.
        - **columns_as_datasets** (bool): Treat each column name as a dataset in the selected group.
        - **index_key** (str): Key for index data.
        - **datetime_key** (str): Key for datetime strings that need parsing.
        - **additional_keys** (list[str]): Additional datasets to include as columns
        - **decode_bytes** (bool): Whether to decode byte strings (default: True)
        - **strip_timezone** (bool): Whether to strip timezone info (default: True)

    Returns
    -------
    pl.LazyFrame
        Lazy DataFrame containing the HDF5 data.

    Examples
    --------
    >>> from r2x_core.file_types import H5Format
    >>> # Default reader (reads first dataset)
    >>> df = read_file_by_type(H5Format(), Path("data.h5"))
    >>>
    >>> # Describe file structure with configuration
    >>> df = read_file_by_type(
    ...     H5Format(),
    ...     Path("load.h5"),
    ...     data_key="data",
    ...     columns_key="columns",
    ...     datetime_key="index_datetime",
    ...     additional_keys=["index_year"]
    ... )
    >>>
    >>> # Custom tabular format
    >>> df = read_file_by_type(
    ...     H5Format(),
    ...     Path("data.h5"),
    ...     data_key="values",
    ...     columns_key="col_names",
    ...     index_key="timestamps"
    ... )
    """
    # Lazily import the HDF5 helper module to avoid package-level import cycles
    # and to keep this module lightweight when only non-HDF5 readers are used.
    import importlib

    h5_readers = importlib.import_module(".h5_readers", package=__package__)

    logger.debug("Reading H5 file: {}", file_path)
    with h5pyFile(str(file_path), "r") as f:
        # Use configurable reader with reader_kwargs
        data_dict = h5_readers.configurable_h5_reader(f, **reader_kwargs)
        df = DataFrame(data_dict)
        return df.lazy()


@read_file_by_type.register
def _(file_type_class: JSONFormat, *, file_path: Path, **reader_kwargs: Any) -> dict[str, Any]:
    """Read JSON files as dictionary.

    Parameters
    ----------
    file_type_class : JSONFormat
        JSONFormat class (not used, but required for dispatch).
    file_path : Path
        Path to the JSON file.
    reader_kwargs: dict[str, Any]
        Additional kwargs for reader function.

    Returns
    -------
    dict[str, Any]
        Dictionary containing the JSON data.
    """
    logger.debug("Reading JSON file: {}", file_path)
    with open(file_path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


@read_file_by_type.register
def _(file_type_class: XMLFormat, *, file_path: Path, **reader_kwargs: dict[str, Any]) -> ElementTree.Element:
    """Read XML files and return the root element.

    Parameters
    ----------
    file_type_class : XMLFormat
        XMLFormat class (not used, but required for dispatch).
    file_path : Path
        Path to the XML file.
    reader_kwargs: dict[str, Any]
        Additional kwargs for reader function.

    Returns
    -------
    ElementTree.Element
        Root element of the XML document.
    """
    logger.debug("Reading XML file: {}", file_path)
    tree = ElementTree.parse(str(file_path))
    return tree.getroot()
