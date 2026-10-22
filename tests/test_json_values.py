"""JSON decoding and processing preserve scalar leaves and operation order."""

import json
from pathlib import Path

import pytest

from r2x_core import DataFile, DataReader, JSONProcessing
from r2x_core.datafile import ReaderConfig
from r2x_core.json_adapter import JSONFileReader, JSONProcessingBackend
from r2x_core.json_adapter.processing import process_json_data
from r2x_core.types import JSONValue


def read_json(path: Path) -> JSONValue:
    """Read a document through the public named-source reader contract."""
    return (
        JSONFileReader()
        .read_file("json", file_path=path, reader_config=ReaderConfig(format="json"))["data"]
        .data
    )


def test_json_processor_returns_transformed_json(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    path.touch()
    data_file = DataFile(name="input", fpath=path)
    data: JSONValue = {"old": [1, None]}
    spec = JSONProcessing(steps=[{"op": "rename_keys", "mapping": {"old": "new"}}])

    result = JSONProcessingBackend().process(data, processing=spec, sources={}, data_file=data_file)

    assert result.is_ok()
    assert result.unwrap() == {"new": [1, None]}
    invalid = JSONProcessingBackend().process(
        {"invalid": object()}, processing=JSONProcessing(), sources={}, data_file=data_file
    )
    assert invalid.is_err()
    assert "JSON-compatible data" in str(invalid.err())


@pytest.mark.parametrize("value", ["text", 42, 3.5, True, False, None])
def test_root_json_scalars(tmp_path: Path, value: JSONValue) -> None:
    path = tmp_path / "scalar.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    spec = JSONProcessing(
        steps=[
            {"op": "rename_keys", "mapping": {"old": "new"}},
            {"op": "drop_keys", "keys": ["drop"]},
            {"op": "select_keys", "keys": ["new"]},
            {"op": "filter", "where": {"new": 1}},
        ]
    )
    item = DataFile(name="scalar", fpath=path, proc_spec=spec)

    assert read_json(path) == value
    assert DataReader().read_data_files([item], folder_path=tmp_path)["scalar"].data == value
    assert process_json_data(value, steps=spec.steps) == value


def test_nested_json_scalar_leaves_and_named_processing(tmp_path: Path) -> None:
    value: JSONValue = {"old": ["text", 42, 3.5, True, None, {"old": False, "drop": 0}], "drop": "removed"}
    expected: JSONValue = {"new": ["text", 42, 3.5, True, None, {"new": False}]}
    path = tmp_path / "nested.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    spec = JSONProcessing(
        steps=[
            {"op": "rename_keys", "mapping": {"old": "new"}},
            {"op": "drop_keys", "keys": ["drop"]},
        ]
    )
    item = DataFile(name="nested", fpath=path, proc_spec=spec)

    assert read_json(path) == value
    assert process_json_data(value, steps=spec.steps) == expected
    assert DataReader().read_data_files([item], folder_path=tmp_path)["nested"].data == expected


def test_json_steps_run_in_declared_order() -> None:
    value: JSONValue = {"old": 1, "other": 2}
    spec = JSONProcessing(
        steps=[
            {"op": "rename_keys", "mapping": {"old": "new"}},
            {"op": "select_keys", "keys": ["new"]},
        ]
    )
    assert process_json_data(value, steps=spec.steps) == {"new": 1}


def test_json_replacements_recurse_through_objects_and_lists() -> None:
    value: JSONValue = {"metadata": {"status": "draft"}, "records": [{"count": 0}]}
    spec = JSONProcessing(steps=[{"op": "replace_values", "mapping": {"draft": "active", 0: 1}}])
    assert process_json_data(value, steps=spec.steps) == {
        "metadata": {"status": "active"},
        "records": [{"count": 1}],
    }


def test_json_filter_handles_empty_conditions_and_object_maps() -> None:
    value: JSONValue = {
        "active": {"status": "active"},
        "inactive": {"status": "inactive"},
        "not_a_record": 3,
    }
    empty = JSONProcessing(steps=[{"op": "filter", "where": {}}])
    selected = JSONProcessing(steps=[{"op": "filter", "where": {"status": "active"}}])
    assert process_json_data(value, steps=empty.steps) == value
    assert process_json_data(value, steps=selected.steps) == {"active": {"status": "active"}}


def test_json_filter_supports_membership_and_preserves_nested_records() -> None:
    value: JSONValue = [
        {"name": "alpha", "status": "active"},
        {"name": "beta", "status": "inactive"},
    ]
    spec = JSONProcessing(steps=[{"op": "filter", "where": {"status": ["active", "pending"]}}])
    assert process_json_data(value, steps=spec.steps) == [{"name": "alpha", "status": "active"}]


def test_rename_key_collision_returns_processing_error(tmp_path: Path) -> None:
    path = tmp_path / "collision.json"
    path.touch()
    data_file = DataFile(name="collision", fpath=path)
    spec = JSONProcessing(steps=[{"op": "rename_keys", "mapping": {"old": "new"}}])
    result = JSONProcessingBackend().process(
        {"old": 1, "new": 2}, processing=spec, sources={}, data_file=data_file
    )
    assert result.is_err()
    assert "duplicate key" in str(result.err()).lower()


def test_json_value_validation_rejects_non_string_keys_and_cycles() -> None:
    from r2x_core.json_adapter.processing import is_json_value

    list_cycle: list[object] = []
    list_cycle.append(list_cycle)
    dict_cycle: dict[str, object] = {}
    dict_cycle["self"] = dict_cycle
    assert not is_json_value({1: "invalid key"})
    assert not is_json_value(list_cycle)
    assert not is_json_value(dict_cycle)


def test_root_json_array(tmp_path: Path) -> None:
    value: JSONValue = ["text", 42, True, None, {"old": [3.5, False]}]
    expected: JSONValue = ["text", 42, True, None, {"new": [3.5, False]}]
    path = tmp_path / "array.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    spec = JSONProcessing(steps=[{"op": "rename_keys", "mapping": {"old": "new"}}])
    assert read_json(path) == value
    assert process_json_data(value, steps=spec.steps) == expected
