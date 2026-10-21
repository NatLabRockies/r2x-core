"""Tests for DataFile refactoring with nested FileInfo, ReaderConfig, and proc_spec."""

import json

import pytest
from pydantic import ValidationError

from r2x_core import DataFile
from r2x_core.datafile import FileInfo, ReaderConfig
from r2x_core.models import (
    DropJSONKeysStep,
    FilterJSONStep,
    JSONProcessing,
    RenameColumnsStep,
    RenameJSONKeysStep,
    SelectColumnsStep,
    SplitColumnSpec,
    TabularProcessing,
)
from r2x_core.types import FileRequirement, FileType


def test_datafile_with_nested_structure(tmp_path):
    """Test DataFile with nested FileInfo, ReaderConfig, and proc_spec."""
    from r2x_core import DataFile

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("old_name,col2,col3\nvalue1,value2,value3\nvalue4,value5,value6")

    data_file = DataFile(
        name="test_data",
        fpath=csv_file,
        info=FileInfo(description="Test data file", units="MW"),
        reader=ReaderConfig(
            kwargs={"infer_schema_length": 1000},
            function=None,
        ),
        proc_spec=TabularProcessing(
            steps=[
                RenameColumnsStep(op="rename_columns", column_mapping={"old_name": "new_name"}),
                SelectColumnsStep(op="select_columns", select_columns=["new_name", "col2"]),
            ]
        ),
    )

    assert data_file.name == "test_data"
    assert data_file.fpath == csv_file
    assert data_file.info.description == "Test data file"
    assert data_file.reader.kwargs == {"infer_schema_length": 1000}
    assert data_file.reader is not None
    assert data_file.reader.kwargs == {"infer_schema_length": 1000}
    assert data_file.proc_spec is not None
    assert isinstance(data_file.proc_spec, TabularProcessing)
    assert [step.op for step in data_file.proc_spec.steps] == ["rename_columns", "select_columns"]


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
            file_type=FileType.STATIC,
            requirement=FileRequirement.REQUIRED,
            units="MW",
        ),
    )

    assert data_file.info.description == "Generator parameters"
    assert data_file.info.file_type is FileType.STATIC
    assert data_file.info.requirement is FileRequirement.REQUIRED
    assert data_file.info.units == "MW"


def test_datafile_deserialize_from_json_nested(tmp_path):
    """Test deserialize new nested JSON config."""
    from r2x_core import DataFile

    nested_config = {
        "name": "pcm_defaults",
        "fpath": str(tmp_path / "data.json"),
        "info": {
            "description": "Generator parameters",
            "file_type": "static",
            "requirement": "required",
            "units": "MW",
        },
        "reader": {
            "kwargs": {"infer_schema_length": 5000},
            "function": None,
        },
        "proc_spec": {
            "kind": "json",
            "steps": [
                {"op": "rename_keys", "mapping": {"forced_outage_rate": "outage_rate"}},
                {"op": "drop_keys", "keys": ["internal_id"]},
                {"op": "filter", "where": {"status": "active"}},
            ],
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
    """Tabular processing stores an ordered, discriminated operation list."""
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("col1,col2,col3,col4\n1,2,3,a\n1,2,4,b")

    data_file = DataFile.model_validate(
        {
            "name": "complete",
            "fpath": csv_file,
            "proc_spec": {
                "kind": "tabular",
                "steps": [
                    {"op": "select_columns", "select_columns": ["col1", "col2", "col3", "col4"]},
                    {"op": "drop_columns", "drop_columns": ["col4"]},
                    {"op": "rename_columns", "column_mapping": {"col1": "column_1", "col2": "column_2"}},
                    {"op": "cast_columns", "column_schema": {"column_1": "int", "column_2": "int"}},
                    {"op": "filter_columns", "filter_by": {"column_1": 1}},
                    {"op": "sort", "by": {"column_1": "asc", "column_2": "desc"}},
                ],
            },
        }
    )

    assert isinstance(data_file.proc_spec, TabularProcessing)
    assert [step.op for step in data_file.proc_spec.steps] == [
        "select_columns",
        "drop_columns",
        "rename_columns",
        "cast_columns",
        "filter_columns",
        "sort",
    ]
    assert data_file.proc_spec.steps[2].column_mapping == {"col1": "column_1", "col2": "column_2"}


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
            steps=[
                RenameJSONKeysStep(
                    op="rename_keys", mapping={"old_key": "new_key", "avg_capacity_MW": "capacity"}
                ),
                FilterJSONStep(op="filter", where={"status": "active"}),
                DropJSONKeysStep(op="drop_keys", keys=["internal_id"]),
            ]
        ),
    )

    assert data_file.proc_spec is not None
    assert isinstance(data_file.proc_spec, JSONProcessing)
    proc_spec = data_file.proc_spec
    assert [step.op for step in proc_spec.steps] == ["rename_keys", "filter", "drop_keys"]
    assert proc_spec.steps[0].mapping == {"old_key": "new_key", "avg_capacity_MW": "capacity"}


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
        info=FileInfo(description="Generator default parameters by technology", units="MW"),
        proc_spec=JSONProcessing(
            steps=[
                RenameJSONKeysStep(op="rename_keys", mapping={"forced_outage_rate": "outage_rate"}),
                DropJSONKeysStep(op="drop_keys", keys=["internal_id"]),
            ]
        ),
    )

    assert data_file.name == "pcm_defaults"
    assert data_file.proc_spec is not None
    assert isinstance(data_file.proc_spec, JSONProcessing)
    assert [step.op for step in data_file.proc_spec.steps] == ["rename_keys", "drop_keys"]


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


def test_data_file_from_records_resolves_relative_paths_and_preserves_globs(tmp_path):
    from r2x_core import DataFile

    (tmp_path / "relative.csv").write_text("value\n1\n")
    (tmp_path / "scenario_2030.csv").write_text("value\n2\n")
    records = [
        {"name": "relative", "relative_fpath": "relative.csv"},
        {"name": "scenario", "glob": "scenario_*.csv"},
    ]

    data_files = DataFile.from_records(records, folder_path=tmp_path)

    assert data_files[0].fpath == tmp_path / "relative.csv"
    assert data_files[0].relative_fpath is None
    assert data_files[1].glob == "scenario_*.csv"
    assert data_files[1].fpath is None


def test_data_file_from_record_allows_placeholder_paths(tmp_path):
    from r2x_core import DataFile

    data_file = DataFile.from_record(
        {"name": "scenario", "relative_fpath": "scenario_{year}.csv"},
        folder_path=tmp_path,
    )

    assert data_file.fpath == tmp_path / "scenario_{year}.csv"


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


def test_extension_for_path_source_without_path():
    from r2x_core.datafile import extension_for_path_source

    assert extension_for_path_source(None) is None


def test_datafile_file_type_unknown_extension(tmp_path):
    """Test that DataFile rejects unknown extensions."""
    from r2x_core import DataFile

    unknown_file = tmp_path / "data.xyz"
    unknown_file.write_text("content")

    with pytest.raises(ValidationError, match="Unsupported file extension"):
        DataFile(name="unknown", fpath=unknown_file)


@pytest.mark.parametrize(
    ("into", "message"),
    [(["year", " "], "cannot be blank"), (["year", "year"], "must be unique")],
)
def test_split_column_requires_distinct_non_empty_output_names(into, message):
    with pytest.raises(ValueError, match=message):
        SplitColumnSpec(separator="|", into=into)


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"op": "scale_columns", "scale": {"value": float("inf")}}, "scale values must be finite"),
        ({"op": "strip_characters", "strip_chars": {"value": [""]}}, "at least 1 character"),
    ],
)
def test_tabular_processing_rejects_invalid_cleanup_options(step, message):
    with pytest.raises(ValidationError, match=message):
        TabularProcessing.model_validate({"steps": [step]})


@pytest.mark.parametrize(
    "step",
    [
        {"op": "aggregate", "aggregate_on": {"value": "sum{"}},
        {
            "op": "pivot",
            "pivot_on": "year",
            "group_by": ["id"],
            "aggregate_on": {"value": "sum{"},
        },
        {"op": "sort", "by": {"value": "descending{"}},
    ],
)
def test_tabular_processing_rejects_malformed_placeholders(step):
    with pytest.raises(ValidationError):
        TabularProcessing.model_validate({"steps": [step]})


def test_tabular_processing_accepts_valid_placeholders():
    processing = TabularProcessing.model_validate(
        {
            "steps": [
                {"op": "aggregate", "aggregate_on": {"value": "{function}"}},
                {"op": "sort", "by": {"value": "{direction}"}},
            ]
        }
    )

    assert processing.steps[0].aggregate_on == {"value": "{function}"}
    assert processing.steps[1].by == {"value": "{direction}"}


def test_datafile_rejects_processing_models_for_the_wrong_format():
    with pytest.raises(ValueError, match="Tabular files require TabularProcessing"):
        DataFile.model_validate(
            {"name": "tabular", "relative_fpath": "data.csv", "proc_spec": JSONProcessing()}
        )
    with pytest.raises(ValueError, match="JSON files require JSONProcessing"):
        DataFile.model_validate(
            {"name": "json", "relative_fpath": "data.json", "proc_spec": TabularProcessing()}
        )

    json_filter = DataFile.model_validate(
        {
            "name": "json-filter",
            "relative_fpath": "data.json",
            "proc_spec": {"kind": "json", "steps": [{"op": "filter", "where": {"status": "active"}}]},
        }
    )
    assert isinstance(json_filter.proc_spec, JSONProcessing)

    tabular_record = {
        "kind": "tabular",
        "steps": [{"op": "filter_columns", "filter_by": {"status": "active"}}],
    }
    tabular_filter = DataFile.model_validate(
        {"name": "tabular-filter", "relative_fpath": "data.csv", "proc_spec": tabular_record}
    )
    assert isinstance(tabular_filter.proc_spec, TabularProcessing)

    glob_filter = DataFile.model_validate(
        {"name": "glob-filter", "glob": "data_*.csv", "proc_spec": tabular_record}
    )
    assert isinstance(glob_filter.proc_spec, TabularProcessing)

    with pytest.raises(ValueError, match="do not support processing specifications"):
        DataFile.model_validate({"name": "xml", "relative_fpath": "data.xml", "proc_spec": JSONProcessing()})


def test_datafile_processing_format_parser_defers_invalid_paths():
    with pytest.raises(ValueError, match=r"[Ee]xactly one of"):
        DataFile.model_validate({"name": "missing-path", "proc_spec": {"kind": "tabular", "steps": []}})
    with pytest.raises(ValueError, match="Unsupported file extension"):
        DataFile.model_validate(
            {
                "name": "unknown-extension",
                "relative_fpath": "data.xyz",
                "proc_spec": {"kind": "tabular", "steps": []},
            }
        )


def test_datafile_rejects_unknown_processing_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DataFile.model_validate(
            {
                "name": "unknown-option",
                "relative_fpath": "data.json",
                "proc_spec": {"kind": "json", "steps": [], "set_index": "id"},
            }
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


def test_nested_opening_brace_placeholder_is_consistent(tmp_path):
    from r2x_core import DataFile
    from r2x_core.processors import substitute_placeholders

    fpath = tmp_path / "{a{b}.csv"
    data_file = DataFile(name="nested-placeholder", fpath=fpath)
    result = substitute_placeholders(str(data_file.fpath), placeholders={"b": "2025"})

    assert result.unwrap() == str(tmp_path / "{a2025.csv")
