"""JSON readers and transforms preserve scalar leaves."""

import json
from pathlib import Path

import pytest

from r2x_core import DataFile, DataReader, JSONProcessing
from r2x_core.datafile import ReaderConfig
from r2x_core.json_adapter import JSONFileReader, JSONProcessingBackend
from r2x_core.json_adapter.processing import (
    json_apply_filters,
    json_drop_columns,
    json_rename_keys,
    json_select_columns,
    json_select_keys,
    process_json_data,
)
from r2x_core.processors import apply_processing
from r2x_core.types import JSONFormat, JSONValue


def test_json_processor_returns_transformed_json(tmp_path: Path) -> None:
    backend = JSONProcessingBackend()
    path = tmp_path / "input.json"
    path.touch()
    data_file = DataFile(name="input", fpath=path)
    data = {"old": [1, None]}

    result = backend.process(
        data,
        data_file=data_file,
        proc_spec=JSONProcessing(key_mapping={"old": "new"}),
    )

    assert result.is_ok()
    assert result.unwrap() == {"new": [1, None]}

    invalid_result = apply_processing(
        {"invalid": object()},
        data_file=data_file,
        proc_spec=JSONProcessing(),
    )
    assert invalid_result.is_err()
    assert "JSON-compatible data" in str(invalid_result.err())


@pytest.mark.parametrize("value", ["text", 42, 3.5, True, False, None])
def test_root_json_scalars(tmp_path: Path, value: JSONValue) -> None:
    path = tmp_path / "scalar.json"
    path.write_text(json.dumps(value))
    spec = JSONProcessing(
        key_mapping={"old": "new"}, drop_keys=["drop"], select_keys=["new"], filter_by={"new": 1}
    )
    data_file = DataFile(name="scalar", fpath=path, proc_spec=spec)

    assert JSONFileReader().read_file(JSONFormat(), file_path=path, reader_config=ReaderConfig()) == value
    assert DataReader().read_data_file(data_file, folder_path=tmp_path) == value
    assert process_json_data(value, data_file=data_file, proc_spec=spec) == value
    for transform in (
        json_rename_keys,
        json_drop_columns,
        json_select_columns,
        json_apply_filters,
        json_select_keys,
    ):
        assert transform(value, data_file=data_file, proc_spec=spec) == value


def test_nested_json_scalar_leaves(tmp_path: Path) -> None:
    value: JSONValue = {"old": ["text", 42, 3.5, True, None, {"old": False, "drop": 0}], "drop": "removed"}
    expected: JSONValue = {"new": ["text", 42, 3.5, True, None, {"new": False}]}
    path = tmp_path / "nested.json"
    path.write_text(json.dumps(value))
    spec = JSONProcessing(key_mapping={"old": "new"}, drop_keys=["drop"])
    data_file = DataFile(name="nested", fpath=path, proc_spec=spec)

    assert JSONFileReader().read_file(JSONFormat(), file_path=path, reader_config=ReaderConfig()) == value
    assert process_json_data(value, data_file=data_file, proc_spec=spec) == expected
    assert DataReader().read_data_file(data_file, folder_path=tmp_path) == expected


def test_root_json_array(tmp_path: Path) -> None:
    value: JSONValue = ["text", 42, True, None, {"old": [3.5, False]}]
    expected: JSONValue = ["text", 42, True, None, {"new": [3.5, False]}]
    path = tmp_path / "array.json"
    path.write_text(json.dumps(value))
    data_file = DataFile(name="array", fpath=path)

    assert JSONFileReader().read_file(JSONFormat(), file_path=path, reader_config=ReaderConfig()) == value
    assert (
        process_json_data(value, data_file=data_file, proc_spec=JSONProcessing(key_mapping={"old": "new"}))
        == expected
    )
