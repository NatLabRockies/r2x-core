"""Core transformations for JSON-compatible values."""

from __future__ import annotations

from typing import Any, Protocol, TypeGuard

from loguru import logger
from rust_ok import Err, Ok, Result

from ..datafile import DataFile, JSONProcessing
from ..types import JSONValue


class JSONProcessor(Protocol):
    """Process JSON values with an application-selected implementation."""

    def process(
        self,
        data: JSONValue,
        *,
        data_file: DataFile,
        proc_spec: JSONProcessing,
    ) -> Result[JSONValue, ValueError]:
        """Apply JSON transformations to one data value."""
        ...


def process_json_data(json_data: JSONValue, *, data_file: DataFile, proc_spec: JSONProcessing) -> JSONValue:
    """Apply JSON data transformations sequentially.

    Executes a pipeline of transformations (rename_keys, drop_columns, select_columns,
    filter, select_keys) on nested dict/list structures per JSONProcessing configuration.
    Transformations work recursively on nested structures.

    Parameters
    ----------
    json_data : JSONValue
        Input JSON data (dict, list of dicts, or nested structures).
    data_file : DataFile
        File configuration providing context for logging and validation.
    proc_spec : JSONProcessing
        Processing specification defining the transformations to apply.

    Returns
    -------
    JSONValue
        Transformed JSON data with all operations applied in sequence.

    See Also
    --------
    :func:`json_rename_keys` : Apply key name mapping recursively.
    :func:`json_drop_columns` : Remove specified keys recursively.
    :func:`json_apply_filters` : Filter dicts by key-value criteria.
    """
    pipeline = [
        json_rename_keys,
        json_drop_columns,
        json_select_columns,
        json_apply_filters,
        json_select_keys,
    ]
    result = json_data
    for transform_func in pipeline:
        result = transform_func(result, data_file=data_file, proc_spec=proc_spec)

    return result


def json_rename_keys(json_data: JSONValue, *, data_file: DataFile, proc_spec: JSONProcessing) -> JSONValue:
    """Rename keys based on key mapping from JSONProcessing.

    Applies renaming recursively to nested dictionaries.
    """
    if not proc_spec.key_mapping:
        return json_data

    mapping = proc_spec.key_mapping

    def rename_keys_recursive(obj: JSONValue) -> JSONValue:
        """Recursively rename keys in nested JSON structure."""
        if isinstance(obj, dict):
            return {mapping.get(key, key): rename_keys_recursive(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [rename_keys_recursive(item) for item in obj]
        return obj

    logger.debug("Applying key mapping {} to {}", mapping, data_file.name)
    return rename_keys_recursive(json_data)


def json_drop_columns(json_data: JSONValue, *, data_file: DataFile, proc_spec: JSONProcessing) -> JSONValue:
    """Drop specified columns or keys from JSON data recursively."""
    if not proc_spec.drop_keys:
        return json_data

    drop_keys = proc_spec.drop_keys

    def drop_keys_recursive(obj: JSONValue) -> JSONValue:
        """Recursively remove specified keys from nested JSON structure."""
        if isinstance(obj, dict):
            return {key: drop_keys_recursive(value) for key, value in obj.items() if key not in drop_keys}
        if isinstance(obj, list):
            return [drop_keys_recursive(item) for item in obj]
        return obj

    logger.debug("Dropping columns {} from {}", drop_keys, data_file.name)
    return drop_keys_recursive(json_data)


def json_select_columns(json_data: JSONValue, *, data_file: DataFile, proc_spec: JSONProcessing) -> JSONValue:
    """Select specific columns or keys from JSON data recursively."""
    if not proc_spec.select_keys:
        return json_data

    columns_to_select = proc_spec.select_keys

    def select_keys_recursive(obj: JSONValue) -> JSONValue:
        """Recursively select specified keys in nested JSON structure."""
        if isinstance(obj, dict):
            return {
                key: select_keys_recursive(value) for key, value in obj.items() if key in columns_to_select
            }
        if isinstance(obj, list):
            return [select_keys_recursive(item) for item in obj]
        return obj

    logger.trace("Selecting keys {} from {}", columns_to_select, data_file.name)
    return select_keys_recursive(json_data)


def json_apply_filters(
    json_data: JSONValue,
    *,
    data_file: DataFile,
    proc_spec: JSONProcessing,
) -> JSONValue:
    """Filter JSON data by key-value pairs."""
    if not proc_spec.filter_by:
        return json_data

    filters = proc_spec.filter_by

    def matches(obj: JSONValue) -> bool:
        """Return whether an object matches every filter condition."""
        if not isinstance(obj, dict):
            return False
        return all(matches_json_filter(obj.get(key), filter_value=value) for key, value in filters.items())

    logger.trace("Applying filter {} to {}", filters, data_file.name)

    if isinstance(json_data, list):
        return [obj for obj in json_data if matches(obj)]

    if isinstance(json_data, dict):
        if matches(json_data):
            return json_data
        return {key: value for key, value in json_data.items() if matches(value)}

    return json_data


def json_select_keys(
    json_data: JSONValue,
    *,
    data_file: DataFile,
    proc_spec: JSONProcessing,
) -> JSONValue:
    """Select specific keys from JSON objects and lists of objects."""
    if not proc_spec.select_keys:
        return json_data

    keys = set(proc_spec.select_keys)
    logger.trace("Selecting keys {} from {}", keys, data_file.name)

    if isinstance(json_data, list):
        return [
            {key: value for key, value in item.items() if key in keys}
            for item in json_data
            if isinstance(item, dict)
        ]

    if isinstance(json_data, dict):
        return {key: value for key, value in json_data.items() if key in keys}

    return json_data


def matches_json_filter(value: Any, *, filter_value: Any) -> bool:
    """Return whether a JSON value matches a scalar or list filter."""
    if isinstance(filter_value, list):
        return bool(value in filter_value)
    return bool(value == filter_value)


def is_json_value(value: object, /) -> TypeGuard[JSONValue]:
    """Return whether a value contains only JSON-compatible values."""

    def is_valid(candidate: object, ancestors: frozenset[int]) -> bool:
        """Return whether a candidate is JSON-compatible and acyclic."""
        if candidate is None or isinstance(candidate, str | int | float | bool):
            return True
        if isinstance(candidate, list):
            identity = id(candidate)
            if identity in ancestors:
                return False
            nested_ancestors = ancestors | {identity}
            return all(is_valid(item, nested_ancestors) for item in candidate)
        if isinstance(candidate, dict):
            identity = id(candidate)
            if identity in ancestors:
                return False
            nested_ancestors = ancestors | {identity}
            return all(
                isinstance(key, str) and is_valid(item, nested_ancestors) for key, item in candidate.items()
            )
        return False

    return is_valid(value, frozenset())


class JSONProcessingBackend:
    """Apply the core JSON transformations to JSON-compatible values."""

    def process(
        self,
        data: JSONValue,
        *,
        data_file: DataFile,
        proc_spec: JSONProcessing,
    ) -> Result[JSONValue, ValueError]:
        """Apply JSON transformations and reject values outside the JSON domain."""
        if not is_json_value(data):
            return Err(
                ValueError(f"JSONProcessingBackend requires JSON-compatible data, got {type(data).__name__}")
            )
        return Ok(process_json_data(data, data_file=data_file, proc_spec=proc_spec))


def default_json_processor() -> JSONProcessor:
    """Create the default JSON processor."""
    return JSONProcessingBackend()
