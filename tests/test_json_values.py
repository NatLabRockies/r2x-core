"""JSON readers and transforms preserve scalar leaves."""

import json
from pathlib import Path

import pytest

from r2x_core import DataFile, DataReader, JSONProcessing
from r2x_core.file_readers import read_file_by_type
from r2x_core.file_types import JSONFormat
from r2x_core.processors import (
    json_apply_filters,
    json_drop_columns,
    json_rename_keys,
    json_select_columns,
    json_select_keys,
    process_json_data,
)
from r2x_core.types import JSONValue


@pytest.mark.parametrize("value", ["text", 42, 3.5, True, False, None])
def test_root_json_scalars(tmp_path: Path, value: JSONValue) -> None:
    path = tmp_path / "scalar.json"
    path.write_text(json.dumps(value))
    spec = JSONProcessing(
        key_mapping={"old": "new"}, drop_keys=["drop"], select_keys=["new"], filter_by={"new": 1}
    )
    data_file = DataFile(name="scalar", fpath=path, proc_spec=spec)

    assert read_file_by_type(JSONFormat(), file_path=path) == value
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

    assert read_file_by_type(JSONFormat(), file_path=path) == value
    assert process_json_data(value, data_file=data_file, proc_spec=spec) == expected
    assert DataReader().read_data_file(data_file, folder_path=tmp_path) == expected


def test_root_json_array(tmp_path: Path) -> None:
    value: JSONValue = ["text", 42, True, None, {"old": [3.5, False]}]
    expected: JSONValue = ["text", 42, True, None, {"new": [3.5, False]}]
    path = tmp_path / "array.json"
    path.write_text(json.dumps(value))
    data_file = DataFile(name="array", fpath=path)

    assert read_file_by_type(JSONFormat(), file_path=path) == value
    assert (
        process_json_data(value, data_file=data_file, proc_spec=JSONProcessing(key_mapping={"old": "new"}))
        == expected
    )
