"""Flexible, configuration-driven HDF5 reader."""

from collections.abc import Sequence
from datetime import UTC, datetime

import h5py
import numpy as np

H5Value = np.ndarray | list[str]
H5Result = dict[str, H5Value]
DEFAULT_DATETIME_COLUMN_NAME = "datetime"
DEFAULT_INDEX_NAMES_KEY = "index_names"
HDF5_STRING_KINDS = frozenset({"S", "O"})
INDEX_COLUMN_PREFIX = "index_"
SOLVE_YEAR_COLUMN_NAME = "solve_year"
YEAR_COLUMN_NAME = "year"


def configurable_h5_reader(h5_file: h5py.File, **reader_kwargs: object) -> H5Result:
    """Read an HDF5 dataset or a configured columnar group.

    ``data_key`` and ``columns_key`` describe row-oriented data. Set
    ``group_key`` to read within a group and ``columns_as_datasets`` when each
    column is a dataset named in ``columns_key``. ``datetime_key``,
    ``index_key``, and ``additional_keys`` add supporting columns.
    """
    group_key = reader_kwargs.get("group_key")
    if group_key is not None and not isinstance(group_key, str):
        raise ValueError("group_key must be a string")

    scope: h5py.Group = h5_file
    if isinstance(group_key, str):
        selected = h5_file.get(group_key)
        if selected is None:
            raise KeyError(f"HDF5 group '{group_key}' not found")
        if not isinstance(selected, h5py.Group):
            raise TypeError(f"HDF5 path '{group_key}' is not a group")
        scope = selected

    columns_as_datasets = reader_kwargs.get("columns_as_datasets", False)
    if not isinstance(columns_as_datasets, bool):
        raise ValueError("columns_as_datasets must be a boolean")

    data_key = reader_kwargs.get("data_key")
    if data_key is not None and (not isinstance(data_key, str) or not data_key):
        raise ValueError("data_key is required and must be a non-empty string")
    if data_key is None and not columns_as_datasets:
        return read_first_dataset(scope)

    index_names_key = reader_kwargs.get("index_names_key", DEFAULT_INDEX_NAMES_KEY)
    if not isinstance(index_names_key, str):
        raise ValueError("index_names_key must be a string")

    file_data: dict[str, h5py.Dataset] = {}
    for key in scope:
        dataset = scope[key]
        if not isinstance(dataset, h5py.Dataset):
            continue
        file_data[key] = dataset

    index_names_dataset = get_h5_dataset(scope, file_data, index_names_key)
    if index_names_dataset is not None:
        index_values = index_names_dataset[()]
        if index_names_dataset.dtype.kind in HDF5_STRING_KINDS:
            index_values = index_names_dataset.asstr()[()]
        index_names = [str(value) for value in np.atleast_1d(index_values)]
        for index_number, index_name in enumerate(index_names):
            resolved_key = f"{INDEX_COLUMN_PREFIX}{index_name}"
            dataset_key = resolved_key if resolved_key in scope else f"{INDEX_COLUMN_PREFIX}{index_number}"
            resolved_dataset = scope.get(dataset_key)
            if not isinstance(resolved_dataset, h5py.Dataset):
                raise KeyError(f"Missing index dataset referenced by {resolved_key}")
            file_data[resolved_key] = resolved_dataset

    columns_key = reader_kwargs.get("columns_key")
    if columns_key is not None and not isinstance(columns_key, str):
        raise ValueError("columns_key must be a string")

    decode_bytes = reader_kwargs.get("decode_bytes", True)
    if not isinstance(decode_bytes, bool):
        raise ValueError("decode_bytes must be a boolean")

    if columns_as_datasets:
        result: H5Result = read_columnar_group(
            scope,
            columns_key=columns_key,
            decode_bytes=decode_bytes,
        )
    else:
        if not isinstance(data_key, str):
            raise ValueError("data_key is required when columns_as_datasets is disabled")
        data_dataset = get_h5_dataset(scope, file_data, data_key)
        if data_dataset is None:
            raise KeyError(f"HDF5 dataset '{data_key}' not found")
        data = np.asarray(data_dataset[()])
        result = {}
        columns = get_h5_dataset(scope, file_data, columns_key) if isinstance(columns_key, str) else None
        if isinstance(columns, h5py.Dataset):
            column_values = columns.asstr()[()]
            column_names = [str(value) for value in np.atleast_1d(column_values)]
            if data.ndim == 2:
                if len(column_names) != data.shape[1]:
                    raise ValueError(
                        f"columns_key '{columns_key}' contains {len(column_names)} names "
                        f"for data with {data.shape[1]} columns"
                    )
                result = {column: data[:, i] for i, column in enumerate(column_names)}
            else:
                if len(column_names) != 1:
                    raise ValueError(
                        f"columns_key '{columns_key}' must contain exactly 1 name "
                        f"for 1D data, found {len(column_names)}"
                    )
                result[column_names[0]] = data
        elif data.ndim == 1:
            result[data_key] = data
        else:
            result = {f"{data_key}_col_{i}": data[:, i] for i in range(data.shape[1])}

    raw_mapping = reader_kwargs.get("column_name_mapping")
    column_mapping: dict[str, str] = {}
    if raw_mapping is not None:
        if not isinstance(raw_mapping, dict):
            raise ValueError("column_name_mapping must be a dictionary")
        for key, value in raw_mapping.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("column_name_mapping must map strings to strings")
            column_mapping[key] = value
    user_column_mapping = bool(column_mapping)
    if not user_column_mapping and index_names_dataset is not None:
        index_names = read_h5_strings(index_names_dataset)
        column_mapping = {f"{INDEX_COLUMN_PREFIX}{i}": name for i, name in enumerate(index_names)}

    datetime_key = reader_kwargs.get("datetime_key")
    if datetime_key is not None and not isinstance(datetime_key, str):
        raise ValueError("datetime_key must be a string")
    datetime_name = reader_kwargs.get("datetime_column_name", DEFAULT_DATETIME_COLUMN_NAME)
    if not isinstance(datetime_name, str):
        raise ValueError("datetime_column_name must be a string")
    strip_timezone = reader_kwargs.get("strip_timezone", True)
    if not isinstance(strip_timezone, bool):
        raise ValueError("strip_timezone must be a boolean")

    datetime_dataset = get_h5_dataset(scope, file_data, datetime_key) if datetime_key is not None else None
    if datetime_dataset is not None:
        dt_values = datetime_dataset[()]
        if decode_bytes and datetime_dataset.dtype.kind in HDF5_STRING_KINDS:
            dt_values = datetime_dataset.asstr()[()]
        dt_data = np.asarray(dt_values)
        if len(dt_data) > 0 and isinstance(dt_data[0], str):
            result[datetime_name] = parse_datetime_array(
                [str(value) for value in dt_data],
                strip_timezone,
            )
        else:
            result[datetime_name] = dt_data

    index_key = reader_kwargs.get("index_key")
    if index_key is not None and not isinstance(index_key, str):
        raise ValueError("index_key must be a string")
    index_dataset = get_h5_dataset(scope, file_data, index_key) if index_key is not None else None
    if isinstance(index_key, str) and index_dataset is not None and index_key != datetime_key:
        result[index_key] = np.asarray(index_dataset[()])

    raw_additional_keys = reader_kwargs.get("additional_keys", [])
    if not isinstance(raw_additional_keys, list):
        raise ValueError("additional_keys must be a list of strings")
    additional_keys: list[str] = []
    for key in raw_additional_keys:
        if not isinstance(key, str):
            raise ValueError("additional_keys must be a list of strings")
        additional_keys.append(key)
    for key in additional_keys:
        additional_dataset = get_h5_dataset(scope, file_data, key)
        if additional_dataset is None:
            continue
        column_name = column_mapping.get(key)
        if column_name is None:
            column_name = format_column_name(key)
        elif not user_column_mapping:
            column_name = format_column_name(column_name)
        result[column_name] = np.asarray(additional_dataset[()])

    return result


def get_h5_dataset(
    scope: h5py.Group,
    datasets: dict[str, h5py.Dataset],
    key: str,
) -> h5py.Dataset | None:
    """Resolve a direct dataset, an index alias, or an HDF5 path."""
    dataset = datasets.get(key)
    if dataset is None:
        selected = scope.get(key)
        if isinstance(selected, h5py.Dataset):
            dataset = selected
    return dataset


def read_h5_strings(dataset: h5py.Dataset) -> list[str]:
    """Read an HDF5 dataset of labels as Python strings."""
    values = dataset.asstr()[()] if dataset.dtype.kind in HDF5_STRING_KINDS else dataset[()]
    return [str(value) for value in np.atleast_1d(values)]


def read_columnar_group(
    scope: h5py.Group,
    *,
    columns_key: str | None,
    decode_bytes: bool,
) -> H5Result:
    """Read one HDF5 dataset for each name listed in a group's columns dataset."""
    if columns_key is None or columns_key not in scope:
        raise ValueError("columns_key is required when columns_as_datasets is enabled")

    columns_dataset = scope.get(columns_key)
    if not isinstance(columns_dataset, h5py.Dataset):
        raise TypeError(f"HDF5 columns path '{columns_key}' is not a dataset")

    result: H5Result = {}
    for column in read_h5_strings(columns_dataset):
        dataset = scope.get(column)
        if not isinstance(dataset, h5py.Dataset):
            raise KeyError(f"HDF5 column dataset '{column}' not found")
        if decode_bytes and dataset.dtype.kind in HDF5_STRING_KINDS:
            result[column] = [str(value) for value in np.atleast_1d(dataset.asstr()[()])]
        else:
            result[column] = np.atleast_1d(np.asarray(dataset[()]))
    return result


def read_first_dataset(scope: h5py.Group) -> H5Result:
    """Read first dataset in an HDF5 scope as the default behavior."""
    key = next(iter(scope.keys()))
    dataset = scope[key]
    if not isinstance(dataset, h5py.Dataset):
        return {key: [str(dataset)]}

    data = np.atleast_1d(np.asarray(dataset[()]))
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


def format_column_name(key: str) -> str:
    """Format HDF5 dataset key into a clean column name."""
    key_lower = key.lower()
    if "index_year" in key_lower or key_lower == SOLVE_YEAR_COLUMN_NAME:
        return SOLVE_YEAR_COLUMN_NAME
    if "year" in key_lower:
        return YEAR_COLUMN_NAME
    return key.replace(INDEX_COLUMN_PREFIX, "")
