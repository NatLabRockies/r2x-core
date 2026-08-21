"""Tests for DataFile refactoring with nested FileInfo, ReaderConfig, and proc_spec."""

import json

import pytest

from r2x_core.datafile import FileInfo, JSONProcessing, ReaderConfig, TabularProcessing


def test_datafile_with_nested_structure(tmp_path):
    """Test DataFile with nested FileInfo, ReaderConfig, and proc_spec."""
    from r2x_core import DataFile

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("old_name,col2,col3\nvalue1,value2,value3\nvalue4,value5,value6")

    data_file = DataFile(
        name="test_data",
        fpath=csv_file,
        info=FileInfo(
            description="Test data file",
            is_input=True,
            is_optional=False,
            units="MW",
        ),
        reader=ReaderConfig(
            kwargs={"infer_schema_length": 1000},
            function=None,
        ),
        proc_spec=TabularProcessing(
            column_mapping={"old_name": "new_name"},
            select_columns=["new_name", "col2"],
        ),
    )

    assert data_file.name == "test_data"
    assert data_file.fpath == csv_file
    assert data_file.info is not None
    assert data_file.info.description == "Test data file"
    assert data_file.reader is not None
    assert data_file.reader.kwargs == {"infer_schema_length": 1000}
    assert data_file.proc_spec is not None
    assert isinstance(data_file.proc_spec, TabularProcessing)
    assert data_file.proc_spec.column_mapping == {"old_name": "new_name"}


def test_datafile_info_attributes(tmp_path):
    """Test FileInfo nested attributes."""
    from r2x_core import DataFile

    json_file = tmp_path / "data.json"
    json_file.write_text("{}")

    data_file = DataFile(
        name="test",
        fpath=json_file,
        info=FileInfo(
            description="Generator parameters",
            is_input=True,
            is_optional=False,
            is_timeseries=False,
            units="MW",
        ),
    )

    assert data_file.info is not None
    assert data_file.info.description == "Generator parameters"
    assert data_file.info.is_input is True
    assert data_file.info.is_optional is False
    assert data_file.info.is_timeseries is False
    assert data_file.info.units == "MW"


def test_datafile_deserialize_from_json_nested(tmp_path):
    """Test deserialize new nested JSON config."""
    from r2x_core import DataFile

    nested_config = {
        "name": "pcm_defaults",
        "fpath": str(tmp_path / "data.json"),
        "info": {
            "description": "Generator parameters",
            "is_input": True,
            "is_optional": False,
            "units": "MW",
        },
        "reader": {
            "kwargs": {"infer_schema_length": 5000},
            "function": None,
        },
        "proc_spec": {
            "column_mapping": {"forced_outage_rate": "outage_rate"},
            "drop_columns": ["internal_id"],
            "filter_by": {"status": "active"},
        },
    }

    (tmp_path / "data.json").write_text("{}")

    data_file = DataFile.model_validate(nested_config)

    assert data_file.name == "pcm_defaults"
    assert data_file.info is not None
    assert data_file.info.description == "Generator parameters"
    assert data_file.info.units == "MW"
    assert data_file.reader is not None
    assert data_file.reader.kwargs == {"infer_schema_length": 5000}


def test_datafile_tabular_transformations(tmp_path):
    """Test TabularProcessing with CSV file."""
    from r2x_core.datafile import DataFile, TabularProcessing

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("col1,col2,col3,col4\n1,2,3,a\n1,2,4,b")

    data_file = DataFile(
        name="complete",
        fpath=csv_file,
        proc_spec=TabularProcessing(
            select_columns=["col1", "col2", "col3"],
            drop_columns=["col4"],
            column_mapping={"col1": "column_1", "col2": "column_2"},
            column_schema={"column_1": "int", "column_2": "int"},
            filter_by={"column_1": 1},
            pivot_on="column_2",
            unpivot_on=None,
            group_by=["column_1"],
            aggregate_on={"column_2": "sum", "column_3": "sum"},
            sort_by={"column_1": "asc", "column_2": "desc"},
            distinct_on=["column_1"],
            replace_values={None: 0, "NaN": None},
            fill_null={"column_2": 0},
        ),
    )

    assert data_file.proc_spec is not None
    assert isinstance(data_file.proc_spec, TabularProcessing)
    proc_spec = data_file.proc_spec
    assert proc_spec.select_columns == ["col1", "col2", "col3"]
    assert proc_spec.drop_columns == ["col4"]
    assert proc_spec.column_mapping == {"col1": "column_1", "col2": "column_2"}
    assert proc_spec.column_schema == {"column_1": "int", "column_2": "int"}
    assert proc_spec.filter_by == {"column_1": 1}
    assert proc_spec.pivot_on == "column_2"
    assert proc_spec.unpivot_on is None
    assert proc_spec.group_by == ["column_1"]
    assert proc_spec.aggregate_on == {"column_2": "sum", "column_3": "sum"}
    assert proc_spec.sort_by == {"column_1": "asc", "column_2": "desc"}
    assert proc_spec.distinct_on == ["column_1"]
    assert proc_spec.replace_values == {None: 0, "NaN": None}
    assert proc_spec.fill_null == {"column_2": 0}


def test_datafile_json_transformations(tmp_path):
    """Test JSONProcessing with JSON file."""
    from r2x_core.datafile import DataFile

    json_file = tmp_path / "data.json"
    json_file.write_text(
        json.dumps(
            {
                "battery": {"avg_capacity_MW": 200.0, "old_key": "value1"},
                "solar": {"avg_capacity_MW": 100.0, "old_key": "value2"},
            }
        )
    )

    data_file = DataFile(
        name="generators",
        fpath=json_file,
        proc_spec=JSONProcessing(
            key_mapping={"old_key": "new_key", "avg_capacity_MW": "capacity"},
            rename_index="technology",
            filter_by={"status": "active"},
            drop_keys=["internal_id"],
            replace_values={None: 0},
        ),
    )

    assert data_file.proc_spec is not None
    assert isinstance(data_file.proc_spec, JSONProcessing)
    proc_spec = data_file.proc_spec
    assert proc_spec.key_mapping == {"old_key": "new_key", "avg_capacity_MW": "capacity"}
    assert proc_spec.rename_index == "technology"
    assert proc_spec.filter_by == {"status": "active"}
    assert proc_spec.drop_keys == ["internal_id"]
    assert proc_spec.replace_values == {None: 0}


def test_datafile_pcm_defaults_use_case(tmp_path):
    """Test the parent app's PCM defaults transformation use case.

    Demonstrates transforming JSON dict:
        {"battery": {"avg_capacity_MW": 200.0, "forced_outage_rate": 2.0}}
    Into indexed dict format with transformed keys.
    """
    from r2x_core.datafile import DataFile

    json_file = tmp_path / "pcm_defaults.json"
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

    data_file = DataFile(
        name="pcm_defaults",
        fpath=json_file,
        info=FileInfo(
            description="Generator default parameters by technology",
            is_input=True,
            is_optional=False,
            units="MW",
        ),
        proc_spec=JSONProcessing(
            key_mapping={"forced_outage_rate": "outage_rate"},
            drop_keys=["internal_id"],
            rename_index="tech",
        ),
    )

    assert data_file.name == "pcm_defaults"
    assert data_file.proc_spec is not None
    assert isinstance(data_file.proc_spec, JSONProcessing)
    assert data_file.proc_spec.key_mapping == {"forced_outage_rate": "outage_rate"}
    assert data_file.proc_spec.drop_keys == ["internal_id"]
    assert data_file.proc_spec.rename_index == "tech"


def test_datafile_with_reader_config(tmp_path):
    """Test ReaderConfig with custom reader function."""
    from r2x_core import DataFile

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("a,b\n1,2")

    def custom_reader(path):
        return {"custom": "data"}

    data_file = DataFile(
        name="custom",
        fpath=csv_file,
        reader=ReaderConfig(
            kwargs={"param1": "value1"},
            function=custom_reader,
        ),
    )

    assert data_file.reader is not None
    assert data_file.reader.kwargs == {"param1": "value1"}
    assert data_file.reader.function == custom_reader


def test_data_file_from_records_success(tmp_path):
    from r2x_core import DataFile

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("col1,col2\n1,2\n")

    records = [
        {"name": "test1", "fpath": "data.csv"},
        {"name": "test2", "fpath": "data.csv"},
    ]

    data_files = DataFile.from_records(records, folder_path=tmp_path)
    assert len(data_files) == 2


def test_data_file_from_records_validation_error(tmp_path):
    from pydantic import ValidationError

    from r2x_core import DataFile

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("col1,col2\n1,2\n")

    records = [
        {"fpath": "data.csv"},
    ]

    with pytest.raises(ValidationError):
        DataFile.from_records(records, folder_path=tmp_path)


def test_datafile_file_not_found_error_non_optional(tmp_path):
    """Test that DataFile raises FileNotFoundError for non-optional missing file."""
    from r2x_core import DataFile

    with pytest.raises(FileNotFoundError, match="File not found"):
        DataFile(
            name="missing",
            fpath=tmp_path / "nonexistent.csv",
        )


def test_datafile_file_type_requires_path_or_glob():
    """Test that file_type raises ValueError when no path or glob is set."""
    from r2x_core import DataFile

    df = DataFile.__new__(DataFile)
    object.__setattr__(df, "name", "test")
    object.__setattr__(df, "fpath", None)
    object.__setattr__(df, "relative_fpath", None)
    object.__setattr__(df, "glob", None)
    object.__setattr__(df, "info", None)
    object.__setattr__(df, "reader", None)
    object.__setattr__(df, "proc_spec", None)

    with pytest.raises(ValueError, match="Either fpath, relative_fpath, or glob must be set"):
        _ = df.file_type


def test_datafile_file_type_unknown_extension(tmp_path):
    """Test that file_type raises KeyError for unknown extension."""
    from r2x_core import DataFile

    unknown_file = tmp_path / "data.xyz"
    unknown_file.write_text("content")

    with pytest.raises(KeyError, match="not found on"):
        DataFile(
            name="unknown",
            fpath=unknown_file,
        )


def test_data_file_from_records_key_error(tmp_path):
    """Test from_records handles KeyError for missing fpath."""
    from pydantic import ValidationError

    from r2x_core import DataFile

    records = [
        {"name": "test1"},  # Missing fpath key
    ]

    with pytest.raises(ValidationError, match="Invalid data file records"):
        DataFile.from_records(records, folder_path=tmp_path)


def test_data_file_from_records_file_not_found(tmp_path):
    """Test from_records handles FileNotFoundError for non-existent files."""
    from pydantic import ValidationError

    from r2x_core import DataFile

    records = [
        {"name": "test1", "fpath": "nonexistent.csv"},
    ]

    with pytest.raises(ValidationError, match="Invalid data file records"):
        DataFile.from_records(records, folder_path=tmp_path)
