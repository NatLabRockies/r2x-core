"""Tests for DataStore class."""

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from r2x_core import DataStore


@pytest.fixture
def folder_with_data(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "file1.csv").write_text("col1,col2\n1,2\n3,4")
    (folder / "file2.csv").write_text("a,b\nx,y\nz,w")
    return folder


@pytest.fixture
def data_store_example(folder_with_data) -> "DataStore":
    from r2x_core import DataFile, DataStore

    df_01 = DataFile(name="test1", fpath=folder_with_data / "file1.csv")
    df_02 = DataFile(name="test2", fpath=folder_with_data / "file2.csv")

    store = DataStore(folder_with_data)
    store.add_data([df_01, df_02])
    return store


def test_datastore_folder_operations(data_store_example, folder_with_data):
    store = data_store_example
    assert store.folder == folder_with_data.resolve()
    assert store.folder.exists()


def test_instance_fails_with_nonexistent_folder():
    from r2x_core import DataStore

    with pytest.raises(FileNotFoundError):
        DataStore("/nonexistent/path")


def test_datastore_from_mapping_file(tmp_path):
    from r2x_core import DataStore

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    csv_file = inputs / "file.csv"
    csv_file.write_text("a,b\n1,2\n3,4\n")

    mapping_path = tmp_path / "file_mapping.json"
    mapping_path.write_text(json.dumps([{"name": "table", "fpath": "inputs/file.csv"}]))

    store = DataStore(path=mapping_path)
    assert "table" in store.list_data()


def test_optional_file_missing_in_mapping(tmp_path):
    from r2x_core import DataStore

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    required = inputs / "required.csv"
    required.write_text("col\n1\n")

    mapping_path = tmp_path / "file_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {"name": "required", "fpath": "inputs/required.csv"},
                {
                    "name": "optional",
                    "fpath": "inputs/optional.csv",
                    "info": {"is_optional": True},
                },
            ]
        )
    )

    store = DataStore(path=mapping_path)

    assert sorted(store.list_data()) == ["optional", "required"]
    assert store.read_data("optional") is None


def test_add_data_overwrite_datafile(data_store_example, folder_with_data):
    from r2x_core import DataFile

    store = data_store_example

    new_file = DataFile(name="test1", fpath=folder_with_data / "file2.csv")
    store.add_data([new_file], overwrite=True)
    assert store["test1"].fpath == folder_with_data / "file2.csv"

    with pytest.raises(KeyError):
        store.add_data([new_file])


def test_store_accessing_data(data_store_example):
    store = data_store_example
    assert "test1" in store
    retrieved = store["test1"]
    assert retrieved.name == "test1"

    assert "nonexistent" not in store
    with pytest.raises(KeyError):
        store["nonexistent"]


def test_list_data_sorted(data_store_example):
    store = data_store_example
    assert store.list_data() == ["test1", "test2"]


def test_remove_data_files(data_store_example, folder_with_data):
    from r2x_core import DataFile

    store = data_store_example
    file_to_remove = DataFile(name="file_to_remove", fpath=folder_with_data / "file2.csv")
    store.add_data([file_to_remove])

    assert "file_to_remove" in store
    store.remove_data("file_to_remove")
    assert "file_to_remove" not in store

    with pytest.raises(KeyError):
        store.remove_data("nonexistent")


def test_clear_cache(folder_with_data):
    from r2x_core import DataFile, DataStore

    store = DataStore(folder_with_data)
    df_01 = DataFile(name="test_1", fpath=folder_with_data / "file1.csv")
    store.add_data([df_01])
    assert store.list_data() == ["test_1"]


def test_reader_operations(data_store_example):
    from r2x_core import DataReader

    store = data_store_example
    assert isinstance(store.reader, DataReader)


def test_read_data(data_store_example):
    store = data_store_example
    data = store.read_data("test1")
    assert data is not None
    with pytest.raises(KeyError):
        store.read_data("nonexistent")


def test_read_data_cache(data_store_example, folder_with_data):
    """Test that reading files always returns fresh data.

    Since most file formats return lazy frames (e.g., polars.LazyFrame),
    actual I/O happens at collection time. There is no caching, so each
    read always gets the current file content.
    """
    store = data_store_example

    # First read
    data1 = store.read_data("test1").collect()
    assert data1 is not None
    assert len(data1) == 2

    # Modify the file
    (folder_with_data / "file1.csv").write_text("col1,col2\n10,20")

    # Read again - should get modified content (no caching)
    data2 = store.read_data("test1").collect()
    assert len(data2) == 1, "Should read modified file content"


def test_ordered_sources_round_trip_through_datastore_json(tmp_path):
    import h5py

    from r2x_core import (
        DataFile,
        DataFileCandidate,
        DataStore,
        ReaderConfig,
        TabularProcessing,
    )

    data_folder = tmp_path / "data"
    data_folder.mkdir()
    with h5py.File(data_folder / "outputs.h5", "w") as h5_file:
        h5_file.create_group("other")
    (data_folder / "prices.csv").write_text("value\n3\n")
    data_file = DataFile(
        name="prices",
        sources=[
            DataFileCandidate(
                relative_fpath="outputs.h5",
                reader=ReaderConfig(kwargs={"group_key": "prices"}),
            ),
            DataFileCandidate(relative_fpath="prices.csv"),
        ],
        proc_spec=TabularProcessing(scale={"value": 2.0}),
    )
    store = DataStore(data_folder)
    store.add_data([data_file])
    mapping_path = tmp_path / "mapping.json"
    store.to_json(mapping_path)

    serialized = json.loads(mapping_path.read_text())
    loaded_store = DataStore.from_json(mapping_path, path=data_folder)

    assert len(serialized[0]["sources"]) == 2
    assert serialized[0]["sources"][0]["reader"]["kwargs"] == {"group_key": "prices"}
    loaded_file = loaded_store["prices"]
    assert loaded_file.sources is not None
    assert [source.fpath.name for source in loaded_file.sources] == ["outputs.h5", "prices.csv"]
    assert loaded_file.sources[0].reader.kwargs == {"group_key": "prices"}
    assert loaded_store.read_data("prices").collect().to_dicts() == [{"value": 6.0}]


def test_to_json_serialization(data_store_example, tmp_path, folder_with_data):
    from r2x_core import DataStore

    store = data_store_example
    json_path = tmp_path / "config.json"
    store.to_json(fpath=json_path)
    assert json_path.exists()

    with open(json_path) as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["name"] == "test1"

    new_store = DataStore.from_json(json_path, path=folder_with_data)
    assert "test1" in new_store
    assert "test2" in new_store


def test_from_data_files_constructor(data_store_example, folder_with_data):
    from r2x_core import DataFile, DataStore

    df_01 = DataFile(name="test1", fpath=folder_with_data / "file1.csv")
    df_02 = DataFile(name="test2", fpath=folder_with_data / "file2.csv")
    store = DataStore.from_data_files(data_files=[df_01, df_02])
    assert "test1" in store
    assert "test2" in store

    data = store.read_data("test1")
    assert data is not None


def test_from_data_files_constructor_with_relative_paths(data_store_example, folder_with_data, caplog):
    from pathlib import Path

    import polars as pl

    from r2x_core import DataFile, DataStore

    (Path.cwd() / "local_file.csv").write_text("col1,col2\n1,2\n3,4")
    df_01 = DataFile(name="test1", relative_fpath="file1.csv")
    df_02 = DataFile(name="test2", relative_fpath="file2.csv")
    df_03 = DataFile(name="test3", fpath=Path("local_file.csv"))
    store = DataStore.from_data_files(data_files=[df_01, df_02, df_03], path=folder_with_data)
    assert "test1" in store
    assert "test2" in store
    assert "test3" in store

    for data in [df_01, df_02, df_03]:
        d = store.read_data(data.name)
        assert d is not None
        assert isinstance(d, pl.LazyFrame)
        assert not d.collect().is_empty()


def test_load_data_file(tmp_path):
    from r2x_core import DataStore

    (tmp_path / "file1.csv").write_text("col1,col2\n1,2\n3,4")

    result = DataStore.load_file(tmp_path / "file1.csv").collect()
    assert result.shape == (2, 2)

    with pytest.raises(FileNotFoundError):
        DataStore.load_file(tmp_path / "nota file")


def test_from_plugin_config_missing_file_mapping(tmp_path, caplog):
    from r2x_core import DataStore
    from r2x_core.plugin_config import PluginConfig

    class DummyConfig(PluginConfig):
        pass

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = DummyConfig(config_path_override=config_dir)

    with caplog.at_level("WARNING"):
        store = DataStore.from_plugin_config(cfg, path=tmp_path)

    assert store.list_data() == []
    assert "File mapping not found" in caplog.text


def test_load_file_with_json_transform_rename_keys(tmp_path):
    """Test load_file with JSONProcessing to rename keys in JSON."""
    from r2x_core import DataStore
    from r2x_core.datafile import JSONProcessing

    json_file = tmp_path / "generators.json"
    json_file.write_text(
        json.dumps(
            {
                "battery": {"avg_capacity_MW": 200.0, "forced_outage_rate": 2.0},
                "solar": {"avg_capacity_MW": 100.0, "forced_outage_rate": 0.5},
            }
        )
    )

    proc_spec = JSONProcessing(key_mapping={"forced_outage_rate": "outage_rate"})
    result = DataStore.load_file(json_file, proc_spec=proc_spec)

    assert "battery" in result
    assert "outage_rate" in result["battery"]
    assert result["battery"]["outage_rate"] == 2.0
    assert "forced_outage_rate" not in result["battery"]


def test_load_file_with_json_transform_drop_columns(tmp_path):
    """Test load_file with JSONProcessing to drop keys in JSON."""
    from r2x_core import DataStore
    from r2x_core.datafile import JSONProcessing

    json_file = tmp_path / "generators.json"
    json_file.write_text(
        json.dumps(
            {
                "battery": {
                    "avg_capacity_MW": 200.0,
                    "forced_outage_rate": 2.0,
                    "internal_id": 123,
                },
                "solar": {
                    "avg_capacity_MW": 100.0,
                    "forced_outage_rate": 0.5,
                    "internal_id": 456,
                },
            }
        )
    )

    proc_spec = JSONProcessing(drop_keys=["internal_id"])
    result = DataStore.load_file(json_file, proc_spec=proc_spec)

    assert "battery" in result
    assert "internal_id" not in result["battery"]
    assert "avg_capacity_MW" in result["battery"]


def test_load_file_accepts_tabular_processing_model(tmp_path):
    from r2x_core import DataStore
    from r2x_core.datafile import TabularProcessing

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("c1,c2\n1,2\n3,4\n")

    lazy = DataStore.load_file(csv_file, proc_spec=TabularProcessing(drop_columns=["c2"]))
    assert "c2" not in lazy.collect().columns


def test_load_file_with_json_transform_filter_by(tmp_path):
    """Test load_file with JSONProcessing to filter JSON dict."""
    from r2x_core import DataStore
    from r2x_core.datafile import JSONProcessing

    json_file = tmp_path / "generators.json"
    json_file.write_text(
        json.dumps(
            {
                "battery": {"avg_capacity_MW": 200.0, "status": "active"},
                "solar": {"avg_capacity_MW": 100.0, "status": "inactive"},
                "wind": {"avg_capacity_MW": 150.0, "status": "active"},
            }
        )
    )

    proc_spec = JSONProcessing(filter_by={"status": "active"})
    result = DataStore.load_file(json_file, proc_spec=proc_spec)

    assert "battery" in result
    assert "wind" in result
    assert "solar" not in result


@pytest.mark.parametrize(
    ("proc_spec", "expected"),
    [
        pytest.param(
            {},
            {
                "battery": {"status": "active", "internal_id": 1},
                "solar": {"status": "inactive", "internal_id": 2},
            },
            id="empty-spec",
        ),
        pytest.param(
            {"filter_by": {"status": "active"}},
            {"battery": {"status": "active", "internal_id": 1}},
            id="shared-filter-field",
        ),
        pytest.param(
            {"drop_keys": ["internal_id"]},
            {"battery": {"status": "active"}, "solar": {"status": "inactive"}},
            id="json-specific-field",
        ),
    ],
)
def test_load_file_parses_processing_dict_for_json(tmp_path, proc_spec, expected):
    from r2x_core import DataStore

    json_file = tmp_path / "generators.json"
    json_file.write_text(
        json.dumps(
            {
                "battery": {"status": "active", "internal_id": 1},
                "solar": {"status": "inactive", "internal_id": 2},
            }
        )
    )

    assert DataStore.load_file(json_file, proc_spec=proc_spec) == expected


def test_load_file_parses_processing_dict_for_csv(tmp_path):
    from r2x_core import DataStore

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("c1,c2\n1,2\n")

    result = DataStore.load_file(csv_file, proc_spec={"drop_columns": ["c2"]})

    assert result.collect().to_dicts() == [{"c1": 1}]


def test_load_file_with_csv_transform_rename_and_select(tmp_path):
    """Test load_file with TabularProcessing on CSV file."""
    from r2x_core import DataStore
    from r2x_core.datafile import TabularProcessing

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("old_name,col2,col3\nvalue1,value2,value3\nvalue4,value5,value6")

    proc_spec = TabularProcessing(
        column_mapping={"old_name": "new_name"}, select_columns=["new_name", "col2"]
    )
    result = DataStore.load_file(csv_file, proc_spec=proc_spec).collect()

    assert "new_name" in result.columns
    assert "old_name" not in result.columns
    assert "col3" not in result.columns
    assert len(result.columns) == 2


def test_load_file_with_json_processing_model(tmp_path):
    """Apply a JSONProcessing model through DataStore.load_file."""
    from r2x_core import DataStore
    from r2x_core.datafile import JSONProcessing

    json_file = tmp_path / "generators.json"
    json_file.write_text(
        json.dumps(
            {
                "battery": {"avg_capacity_MW": 200.0, "old_key": "drop_me"},
                "solar": {"avg_capacity_MW": 100.0, "old_key": "drop_me"},
            }
        )
    )

    result = DataStore.load_file(json_file, proc_spec=JSONProcessing(drop_keys=["old_key"]))

    assert "battery" in result
    assert "old_key" not in result["battery"]
    assert "avg_capacity_MW" in result["battery"]


def test_load_file_with_combined_transforms(tmp_path):
    """Test load_file with multiple transformations chained together."""
    from r2x_core import DataStore
    from r2x_core.datafile import JSONProcessing

    json_file = tmp_path / "generators.json"
    json_file.write_text(
        json.dumps(
            {
                "battery": {
                    "avg_capacity_MW": 200.0,
                    "outage_rate": 2.0,
                    "status": "active",
                    "temp_id": 1,
                },
                "solar": {
                    "avg_capacity_MW": 100.0,
                    "outage_rate": 0.5,
                    "status": "inactive",
                    "temp_id": 2,
                },
            }
        )
    )

    proc_spec = JSONProcessing(
        key_mapping={"avg_capacity_MW": "capacity"},
        drop_keys=["temp_id"],
        filter_by={"status": "active"},
    )
    result = DataStore.load_file(json_file, proc_spec=proc_spec)

    assert "battery" in result
    assert "solar" not in result
    assert "capacity" in result["battery"]
    assert "avg_capacity_MW" not in result["battery"]
    assert "temp_id" not in result["battery"]


def test_load_file_mapping_validation_error(tmp_path):
    from pydantic import ValidationError

    from r2x_core import DataStore

    csv = tmp_path / "file.csv"
    csv.write_text("a,b\n1,2\n")

    store = DataStore(path=tmp_path)
    bad_mapping = tmp_path / "bad.json"
    bad_mapping.write_text(json.dumps([{"name": 123, "fpath": "file.csv"}]))

    with pytest.raises(ValidationError):
        store._load_file_mapping(bad_mapping)


def test_store_load_file_csv_with_processing(tmp_path):
    from r2x_core import DataStore, TabularProcessing

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,value,status\nitem1,100,active\nitem2,50,inactive\n")

    proc_spec = TabularProcessing(
        filter_by={"status": "active"},
        column_mapping={"value": "amount"},
    )
    result = DataStore.load_file(csv_file, proc_spec=proc_spec)

    assert result is not None


def test_store_load_file_json_missing_file():
    import pytest

    from r2x_core import DataStore

    with pytest.raises(FileNotFoundError):
        DataStore.load_file("/nonexistent/file.json")


def test_store_load_file_invalid_json(tmp_path):
    import pytest

    from r2x_core import DataStore

    json_file = tmp_path / "invalid.json"
    json_file.write_text("{ invalid json }")

    with pytest.raises(ValueError):
        DataStore.load_file(json_file)


def test_store_from_json_missing_folder(tmp_path):
    import pytest

    from r2x_core import DataStore

    json_file = tmp_path / "config.json"
    json_file.write_text("[]")

    with pytest.raises(FileNotFoundError):
        DataStore.from_json(json_file, path="/nonexistent")


def test_store_from_json_missing_config_file(tmp_path):
    import pytest

    from r2x_core import DataStore

    with pytest.raises(FileNotFoundError):
        DataStore.from_json(tmp_path / "nonexistent.json", path=tmp_path)


def test_store_from_json_not_array(tmp_path):
    import pytest

    from r2x_core import DataStore

    json_file = tmp_path / "config.json"
    json_file.write_text('{"not": "array"}')

    with pytest.raises(TypeError):
        DataStore.from_json(json_file, path=tmp_path)


def test_store_add_data_invalid_type(tmp_path):
    import pytest

    from r2x_core import DataStore

    store = DataStore(tmp_path)

    with pytest.raises(TypeError):
        store.add_data(["not_a_datafile"])  # type: ignore[arg-type]


def test_store_add_data_duplicate_without_overwrite(tmp_path):
    import pytest

    from r2x_core import DataFile, DataStore

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("col1,col2\n1,2\n")

    store = DataStore(tmp_path)
    data_file = DataFile(name="test", fpath=csv_file)

    store.add_data([data_file])

    with pytest.raises(KeyError):
        store.add_data([data_file], overwrite=False)


def test_store_add_data_duplicate_with_overwrite(tmp_path):
    from r2x_core import DataFile, DataStore

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("col1,col2\n1,2\n")

    store = DataStore(tmp_path)
    data_file = DataFile(name="test", fpath=csv_file)

    store.add_data([data_file])
    store.add_data([data_file], overwrite=True)

    assert store["test"] is not None


def test_store_add_multiple_data_invalid_type(tmp_path):
    import pytest

    from r2x_core import DataStore

    store = DataStore(tmp_path)

    with pytest.raises(TypeError):
        store.add_data(["not_datafile"])  # type: ignore[arg-type]
