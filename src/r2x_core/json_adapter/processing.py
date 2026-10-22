"""Core transformations for JSON-compatible values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeGuard

from rust_ok import Err, Ok, Result

from ..datafile import DataFile
from ..file_reader import DecodedSource
from ..models import (
    DropJSONKeysStep,
    FilterJSONStep,
    JSONProcessing,
    JSONProcessingStep,
    RenameJSONKeysStep,
    ReplaceJSONValuesStep,
    SelectJSONKeysStep,
)
from ..types import FileProcessing, JSONScalar, JSONValue


def process_json_data(json_data: JSONValue, *, steps: Sequence[JSONProcessingStep]) -> JSONValue:
    """Run JSON transformations in their declared order."""
    result = json_data
    for step in steps:
        match step:
            case RenameJSONKeysStep():
                result = rename_keys(result, mapping=step.mapping)
            case DropJSONKeysStep():
                result = drop_keys(result, keys=frozenset(step.keys))
            case FilterJSONStep():
                result = filter_records(result, where=step.where)
            case ReplaceJSONValuesStep():
                result = replace_values(result, mapping=step.mapping)
            case SelectJSONKeysStep():
                result = select_keys(result, keys=frozenset(step.keys))
    return result


def rename_keys(value: JSONValue, *, mapping: dict[str, str]) -> JSONValue:
    """Rename matching object keys recursively without overwriting data."""
    if isinstance(value, dict):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            renamed_key = mapping.get(key, key)
            if renamed_key in result:
                msg = f"Key renaming creates duplicate key {renamed_key!r}"
                raise ValueError(msg)
            result[renamed_key] = rename_keys(item, mapping=mapping)
        return result
    if isinstance(value, list):
        return [rename_keys(item, mapping=mapping) for item in value]
    return value


def drop_keys(value: JSONValue, *, keys: frozenset[str]) -> JSONValue:
    """Remove selected object keys recursively."""
    if isinstance(value, dict):
        return {key: drop_keys(item, keys=keys) for key, item in value.items() if key not in keys}
    if isinstance(value, list):
        return [drop_keys(item, keys=keys) for item in value]
    return value


def filter_records(value: JSONValue, *, where: dict[str, JSONValue]) -> JSONValue:
    """Filter lists or object maps by all configured exact field values."""
    if not where:
        return value

    def matches(item: JSONValue) -> bool:
        if not isinstance(item, dict):
            return False
        return all(
            item.get(key) in expected if isinstance(expected, list) else item.get(key) == expected
            for key, expected in where.items()
        )

    if isinstance(value, list):
        return [item for item in value if matches(item)]
    if isinstance(value, dict):
        if matches(value):
            return value
        return {key: item for key, item in value.items() if matches(item)}
    return value


def replace_values(value: JSONValue, *, mapping: dict[JSONScalar, JSONValue]) -> JSONValue:
    """Replace matching scalar values recursively."""
    if isinstance(value, dict):
        return {key: replace_values(item, mapping=mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_values(item, mapping=mapping) for item in value]
    return mapping.get(value, value)


def select_keys(value: JSONValue, *, keys: frozenset[str]) -> JSONValue:
    """Keep selected keys in every JSON object recursively."""
    if isinstance(value, dict):
        return {key: select_keys(item, keys=keys) for key, item in value.items() if key in keys}
    if isinstance(value, list):
        return [select_keys(item, keys=keys) for item in value]
    return value


def is_json_value(value: object, /) -> TypeGuard[JSONValue]:
    """Return whether a value contains only JSON-compatible, acyclic values."""

    def is_valid(candidate: object, ancestors: frozenset[int]) -> bool:
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
        /,
        *,
        processing: FileProcessing,
        sources: Mapping[str, DecodedSource],
        data_file: DataFile,
    ) -> Result[JSONValue, ValueError]:
        """Apply JSON operations and reject unsupported specifications."""
        if not isinstance(processing, JSONProcessing):
            return Err(ValueError("JSONProcessingBackend requires JSONProcessing"))
        if not is_json_value(data):
            return Err(
                ValueError(f"JSONProcessingBackend requires JSON-compatible data, got {type(data).__name__}")
            )
        try:
            return Ok(process_json_data(data, steps=processing.steps))
        except ValueError as error:
            return Err(error)
