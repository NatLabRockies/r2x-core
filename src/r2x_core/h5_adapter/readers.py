"""Flexible, configuration-driven HDF5 reader."""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import h5py
import numpy as np
from h5py.h5t import check_string_dtype
from loguru import logger
from pydantic import ConfigDict, Field

from ..datafile import ReaderConfig
from ..exceptions import ConfiguredGroupNotFoundError
from ..file_reader import ArraySource, DecodedSources, FileReader
from ..models import StrictConfigModel
from .type_alias import H5Label, H5Result

DEFAULT_DATETIME_COLUMN_NAME = "datetime"
DEFAULT_INDEX_NAMES_KEY = "index_names"
INDEX_COLUMN_PREFIX = "index_"
SOLVE_YEAR_COLUMN_NAME = "solve_year"
YEAR_COLUMN_NAME = "year"


class H5Reader(FileReader):
    """Base interface for HDF5 readers that return native arrays."""


def read_h5_file(*, file_path: Path, **reader_kwargs: object) -> H5Result:
    """Read an HDF5 file into column data using the configured reader options."""
    try:
        options = H5ReaderOptions.model_validate(reader_kwargs)
    except ValueError as error:
        msg = f"Invalid HDF5 reader options: {error}"
        raise ValueError(msg) from error

    logger.debug("Reading HDF5 file: {}", file_path)
    with h5py.File(str(file_path), "r") as h5_file:
        return read_h5_scope(h5_file, options=options)


class H5ReaderOptions(StrictConfigModel):
    """Validate options supported by the h5py reader without coercion."""

    model_config = ConfigDict(strict=True)

    group_key: str | None = None
    columns_as_datasets: bool = False
    data_key: Annotated[str, Field(min_length=1)] | None = None
    decode_bytes: bool = True
    index_names_key: str = DEFAULT_INDEX_NAMES_KEY
    columns_key: str | None = None
    column_name_mapping: dict[str, str] | None = None
    datetime_key: str | None = None
    datetime_column_name: str = DEFAULT_DATETIME_COLUMN_NAME
    strip_timezone: bool = True
    index_key: str | None = None
    additional_keys: list[str] = Field(default_factory=list)


class H5PyFileReader(H5Reader):
    """Read HDF5 files with h5py into named array sources."""

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        """Read one HDF5 file using the selected HDF5 implementation."""
        if format_name != "hdf5_array":
            msg = f"HDF5 reader cannot read format {format_name!r}"
            raise ValueError(msg)
        data = read_h5_file(file_path=file_path, **reader_config.options)
        return {"data": ArraySource(data, None)}


def configurable_h5_reader(h5_file: h5py.File, **reader_kwargs: object) -> H5Result:
    """Read an HDF5 dataset or a configured columnar group.

    ``data_key`` and ``columns_key`` describe row-oriented data. Set
    ``group_key`` to read within a group and ``columns_as_datasets`` when each
    column is a dataset named in ``columns_key``. ``datetime_key``,
    ``index_key``, and ``additional_keys`` add supporting columns.
    """
    options = H5ReaderOptions.model_validate(reader_kwargs)
    return read_h5_scope(h5_file, options=options)


def read_h5_scope(h5_file: h5py.Group, *, options: H5ReaderOptions) -> H5Result:
    """Read one HDF5 scope using typed, validated options."""
    scope = h5_file
    if options.group_key is not None:
        selected = h5_file.get(options.group_key)
        if selected is None:
            msg = f"HDF5 group '{options.group_key}' not found"
            raise ConfiguredGroupNotFoundError(msg)
        if not isinstance(selected, h5py.Group):
            msg = f"HDF5 path '{options.group_key}' is not a group"
            raise TypeError(msg)
        scope = selected

    if options.data_key is None and not options.columns_as_datasets:
        return read_first_dataset(scope, decode_bytes=options.decode_bytes)

    file_data: dict[str, h5py.Dataset] = {}
    index_names_dataset = get_h5_dataset(scope, file_data, options.index_names_key)
    index_names: list[H5Label] | None = None
    if index_names_dataset is not None:
        index_names = read_h5_labels(index_names_dataset, decode_bytes=options.decode_bytes)
        for index_number, index_name in enumerate(index_names):
            resolved_key = make_index_key(index_name)
            resolved_dataset = scope.get(h5_key_to_string(resolved_key))
            if not isinstance(resolved_dataset, h5py.Dataset):
                fallback_key = f"{INDEX_COLUMN_PREFIX}{index_number}"
                resolved_dataset = scope.get(fallback_key)
            if not isinstance(resolved_dataset, h5py.Dataset):
                msg = f"Missing index dataset referenced by {resolved_key}"
                raise KeyError(msg)
            file_data[resolved_key] = resolved_dataset

    result: H5Result = {}
    if options.columns_as_datasets:
        result = read_columnar_group(
            scope,
            columns_key=options.columns_key,
            decode_bytes=options.decode_bytes,
        )
    elif options.data_key is not None:
        result = read_row_oriented_data(
            scope,
            file_data,
            data_key=options.data_key,
            columns_key=options.columns_key,
            decode_bytes=options.decode_bytes,
        )

    column_mapping = options.column_name_mapping or {}
    user_column_mapping = bool(column_mapping)
    if not user_column_mapping and index_names is not None:
        column_mapping = {f"{INDEX_COLUMN_PREFIX}{i}": name for i, name in enumerate(index_names)}

    datetime_dataset = (
        get_h5_dataset(scope, file_data, options.datetime_key) if options.datetime_key is not None else None
    )
    if datetime_dataset is not None:
        dt_data = np.atleast_1d(read_h5_values(datetime_dataset, decode_bytes=options.decode_bytes))
        if dt_data.size > 0 and isinstance(dt_data[0], str):
            result[options.datetime_column_name] = parse_datetime_array(
                [str(value) for value in dt_data],
                options.strip_timezone,
            )
        else:
            result[options.datetime_column_name] = dt_data

    index_dataset = (
        get_h5_dataset(scope, file_data, options.index_key) if options.index_key is not None else None
    )
    if (
        options.index_key is not None
        and index_dataset is not None
        and options.index_key != options.datetime_key
    ):
        result[options.index_key] = read_h5_values(index_dataset, decode_bytes=options.decode_bytes)

    for key in options.additional_keys:
        additional_dataset = get_h5_dataset(scope, file_data, key)
        if additional_dataset is None:
            continue
        column_name = column_mapping.get(key)
        if column_name is None:
            column_name = format_column_name(key)
        elif not user_column_mapping:
            column_name = format_column_name(column_name)
        result[h5_key_to_string(column_name)] = read_h5_values(
            additional_dataset, decode_bytes=options.decode_bytes
        )

    return result


def read_row_oriented_data(
    scope: h5py.Group,
    file_data: dict[str, h5py.Dataset],
    *,
    data_key: str,
    columns_key: str | None,
    decode_bytes: bool,
) -> H5Result:
    """Read a row-oriented dataset and apply its optional column labels."""
    data_dataset = get_h5_dataset(scope, file_data, data_key)
    if data_dataset is None:
        msg = f"HDF5 dataset '{data_key}' not found"
        raise KeyError(msg)
    data = read_h5_values(data_dataset, decode_bytes=decode_bytes)
    columns = get_h5_dataset(scope, file_data, columns_key) if columns_key is not None else None
    if isinstance(columns, h5py.Dataset):
        column_names = read_h5_labels(columns, decode_bytes=decode_bytes)
        if data.ndim == 2:
            if len(column_names) != data.shape[1]:
                msg = (
                    f"columns_key '{columns_key}' contains {len(column_names)} names "
                    f"for data with {data.shape[1]} columns"
                )
                raise ValueError(msg)
            return {h5_key_to_string(column): data[:, i] for i, column in enumerate(column_names)}
        if len(column_names) != 1:
            msg = (
                f"columns_key '{columns_key}' must contain exactly 1 name "
                f"for 1D data, found {len(column_names)}"
            )
            raise ValueError(msg)
        return {h5_key_to_string(column_names[0]): data}
    if data.ndim == 1:
        return {data_key: data}
    return {f"{data_key}_col_{i}": data[:, i] for i in range(data.shape[1])}


def get_h5_dataset(
    scope: h5py.Group,
    datasets: dict[str, h5py.Dataset],
    key: str,
) -> h5py.Dataset | None:
    """Resolve a direct dataset, an index alias, or an HDF5 path."""
    dataset = datasets.get(key)
    if dataset is None:
        selected = scope.get(h5_key_to_string(key))
        if isinstance(selected, h5py.Dataset):
            dataset = selected
    return dataset


def read_h5_values(dataset: h5py.Dataset, *, decode_bytes: bool) -> np.ndarray:
    """Read an HDF5 dataset, decoding values only when its dtype is a string type."""
    if decode_bytes and check_string_dtype(dataset.dtype) is not None:
        return np.asarray(dataset.asstr()[()])
    return np.asarray(dataset[()])


def read_h5_labels(dataset: h5py.Dataset, *, decode_bytes: bool) -> list[H5Label]:
    """Read an HDF5 dataset of labels with optional byte-string decoding."""
    values = dataset[()]
    if decode_bytes and check_string_dtype(dataset.dtype) is not None:
        values = dataset.asstr()[()]
    labels = np.atleast_1d(values)
    if decode_bytes:
        return [str(value) for value in labels]
    return [value if isinstance(value, bytes) else str(value) for value in labels]


def make_index_key(index_name: H5Label) -> str:
    """Build the HDF5 dataset key for a named index."""
    return f"{INDEX_COLUMN_PREFIX}{h5_key_to_string(index_name)}"


def h5_key_to_string(key: H5Label) -> str:
    """Convert an HDF5 string key to the text form accepted by h5py."""
    return key.decode() if isinstance(key, bytes) else key


def read_columnar_group(
    scope: h5py.Group,
    *,
    columns_key: str | None,
    decode_bytes: bool,
) -> H5Result:
    """Read one HDF5 dataset for each name listed in a group's columns dataset."""
    if columns_key is None:
        msg = "columns_key is required when columns_as_datasets is enabled"
        raise ValueError(msg)

    columns_dataset = scope.get(columns_key)
    if columns_dataset is None:
        msg = f"HDF5 columns path '{columns_key}' not found"
        raise ValueError(msg)
    if not isinstance(columns_dataset, h5py.Dataset):
        msg = f"HDF5 columns path '{columns_key}' is not a dataset"
        raise TypeError(msg)

    result: H5Result = {}
    for column in read_h5_labels(columns_dataset, decode_bytes=decode_bytes):
        column_key = h5_key_to_string(column)
        dataset = scope.get(column_key)
        if not isinstance(dataset, h5py.Dataset):
            msg = f"HDF5 column dataset '{h5_key_to_string(column)}' not found"
            raise KeyError(msg)
        if check_string_dtype(dataset.dtype) is not None:
            values = np.atleast_1d(read_h5_values(dataset, decode_bytes=decode_bytes))
            result[column_key] = values.tolist()
        else:
            result[column_key] = np.atleast_1d(np.asarray(dataset[()]))
    return result


def read_first_dataset(scope: h5py.Group, *, decode_bytes: bool) -> H5Result:
    """Read first dataset in an HDF5 scope as the default behavior."""
    try:
        key = next(iter(scope.keys()))
    except StopIteration as exc:
        msg = "HDF5 scope contains no datasets"
        raise ValueError(msg) from exc

    dataset = scope[key]
    if not isinstance(dataset, h5py.Dataset):
        return {key: [str(dataset)]}

    data = np.atleast_1d(read_h5_values(dataset, decode_bytes=decode_bytes))
    if data.ndim == 1:
        return {key: data}
    return {f"{key}_col_{i}": data[:, i] for i in range(data.shape[1])}


def parse_datetime_array(dt_strings: Sequence[str], strip_timezone: bool) -> np.ndarray:
    """Parse ISO datetime strings into timezone-naive datetime64 values."""
    parsed: list[datetime] = []
    for i, dt_str in enumerate(dt_strings):
        try:
            dt_obj = datetime.fromisoformat(dt_str)
            if dt_obj.tzinfo is not None:
                if strip_timezone:
                    dt_obj = dt_obj.replace(tzinfo=None)
                else:
                    dt_obj = dt_obj.astimezone(UTC).replace(tzinfo=None)
            parsed.append(dt_obj)
        except (ValueError, AttributeError) as exc:
            msg = (
                f"Failed to parse datetime string at index {i}: '{dt_str}'. "
                f"Expected ISO 8601 format. Error: {exc}"
            )
            raise ValueError(msg) from exc

    return np.array(parsed, dtype="datetime64[us]")


def format_column_name(key: H5Label) -> str:
    """Format HDF5 dataset key into a clean column name."""
    if isinstance(key, bytes):
        key = key.decode()
    key_lower = key.lower()
    if "index_year" in key_lower or key_lower == SOLVE_YEAR_COLUMN_NAME:
        return SOLVE_YEAR_COLUMN_NAME
    if "year" in key_lower:
        return YEAR_COLUMN_NAME
    return key.replace(INDEX_COLUMN_PREFIX, "")
