"""Tests for typed input and processing configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from r2x_core import DataFile, InlineTable, SourcePredicate
from r2x_core.datafile import FileInfo, ReaderConfig, extension_for_path_source
from r2x_core.models import (
    JSONProcessing,
    RenameColumnsStep,
    SelectColumnsStep,
    SplitColumnSpec,
    TabularProcessing,
)
from r2x_core.types import FileRequirement, FileType


def test_inline_table_serialization_uses_configuration_schema_key() -> None:
    table = InlineTable.model_validate({"schema": {"year": "int64"}, "rows": [{"year": 2030}]})

    assert table.model_dump(mode="json") == {"schema": {"year": "int64"}, "rows": [{"year": 2030}]}


def test_nested_datafile_configuration() -> None:
    """Validate symbolic reader options and typed processing together."""
    data_file = DataFile(
        name="demand",
        relative_fpath="demand.csv",
        info=FileInfo(description="Hourly demand", units="MW"),
        reader=ReaderConfig(format="csv", options={"header_rows": 2}),
        proc_spec=TabularProcessing(
            steps=[
                RenameColumnsStep(op="rename_columns", column_mapping={"old": "new"}),
                SelectColumnsStep(op="select_columns", select_columns=["new"]),
            ]
        ),
    )

    assert data_file.format_name == "csv"
    assert data_file.info.description == "Hourly demand"
    assert data_file.reader.options == {"header_rows": 2}
    assert [step.op for step in data_file.proc_spec.steps] == ["rename_columns", "select_columns"]


def test_datafile_nested_json_roundtrip() -> None:
    """Roundtrip strict nested configuration without importing reader code from JSON."""
    record = {
        "name": "metadata",
        "fpath": "metadata.json",
        "info": {"file_type": "static", "requirement": "optional", "units": "MW"},
        "reader": {"format": "json", "options": {"encoding": "utf-8"}},
        "required_when": {"source": "conditions", "predicate": "enabled"},
        "proc_spec": {"kind": "json", "steps": [{"op": "rename_keys", "mapping": {"old": "new"}}]},
    }

    restored = DataFile.model_validate_json(DataFile.model_validate(record).model_dump_json())

    assert restored.info.file_type is FileType.STATIC
    assert restored.info.requirement is FileRequirement.OPTIONAL
    assert restored.reader.options == {"encoding": "utf-8"}
    assert isinstance(restored.required_when, SourcePredicate)
    assert restored.required_when.source == "conditions"
    assert isinstance(restored.proc_spec, JSONProcessing)


def test_explicit_registered_format_supports_new_extensions() -> None:
    """An application can configure a new extension without core whitelist changes."""
    data_file = DataFile(
        name="raw",
        relative_fpath="case.raw",
        reader=ReaderConfig(format="dummy_raw", options={"encoding": "utf-8"}),
        info=FileInfo(file_type=FileType.TIME_SERIES),
        proc_spec=JSONProcessing(),
    )

    assert data_file.format_name == "dummy_raw"
    assert data_file.info.file_type is FileType.TIME_SERIES


def test_format_inference_is_limited_to_common_unambiguous_extensions() -> None:
    """Infer common inputs but require explicit symbolic formats for new extensions."""
    assert DataFile(name="table", relative_fpath="table.csv").format_name == "csv"
    assert extension_for_path_source(None) is None
    unknown = DataFile(name="raw", relative_fpath="case.raw")
    with pytest.raises(ValueError, match=r"configure reader\.format"):
        _ = unknown.format_name
    assert DataFile(name="explicit", relative_fpath="case.raw", reader={"format": "raw"}).format_name == "raw"


def test_datafile_requires_one_input_mode_and_reader_options_only_for_files() -> None:
    """Keep path resolution at execution time and named-source config unambiguous."""
    with pytest.raises(ValidationError, match="exactly one"):
        DataFile.model_validate({"name": "empty"})
    with pytest.raises(ValidationError, match="cannot also define"):
        DataFile.model_validate({"name": "mixed", "source": "origin", "relative_fpath": "x.csv"})
    with pytest.raises(ValidationError, match="apply only to physical"):
        DataFile.model_validate({"name": "derived", "source": "origin", "reader": {"format": "csv"}})
    with pytest.raises(ValidationError, match="exactly one of fpath"):
        DataFile.model_validate({"name": "multiple_paths", "fpath": "a.csv", "glob": "*.csv"})
    with pytest.raises(ValidationError, match="requires exactly one"):
        DataFile.model_validate(
            {
                "name": "multiple_sources",
                "source": "origin",
                "inline_table": {"schema": {"id": "int64"}, "rows": []},
            }
        )
    with pytest.raises(ValidationError, match="apply only to physical"):
        DataFile.model_validate(
            {
                "name": "selected",
                "source_selection": {"mode": "first_present", "sources": ["origin"]},
                "reader": {"format": "csv"},
            }
        )
    with pytest.raises(ValidationError, match="require tabular processing"):
        DataFile.model_validate(
            {
                "name": "invalid_inline_processing",
                "inline_table": {"schema": {"id": "int64"}, "rows": []},
                "proc_spec": {"kind": "json"},
            }
        )

    configured = DataFile(name="deferred", relative_fpath="missing-{year}.csv")
    assert configured.relative_fpath == "missing-{year}.csv"


def test_datafile_reader_options_reject_python_implementation_fields() -> None:
    """JSON config selects a symbolic registration and cannot name arbitrary code."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DataFile.model_validate(
            {"name": "unsafe", "relative_fpath": "input.xyz", "reader": {"function": "module.reader"}}
        )


def test_glob_pattern_is_validated_as_configuration() -> None:
    """Validate the pattern itself without resolving files before execution."""
    data_file = DataFile(name="scenario", glob="data_{year}_*.csv")
    assert data_file.glob == "data_{year}_*.csv"
    with pytest.raises(ValidationError, match="does not contain glob wildcards"):
        DataFile.model_validate({"name": "invalid", "glob": "input.csv"})


def test_processing_schema_is_strict_and_format_independent() -> None:
    """The output processor, not a file extension, determines operation purpose."""
    tabular = DataFile.model_validate(
        {
            "name": "tabular-on-json",
            "relative_fpath": "data.json",
            "proc_spec": {"kind": "tabular", "steps": [{"op": "filter_columns", "filter_by": {"status": 1}}]},
        }
    )
    document = DataFile.model_validate(
        {
            "name": "json-on-csv",
            "relative_fpath": "data.csv",
            "proc_spec": {"kind": "json", "steps": [{"op": "filter", "where": {"status": 1}}]},
        }
    )
    assert isinstance(tabular.proc_spec, TabularProcessing)
    assert isinstance(document.proc_spec, JSONProcessing)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DataFile.model_validate(
            {
                "name": "extra",
                "relative_fpath": "data.json",
                "proc_spec": {"kind": "json", "steps": [], "index": "id"},
            }
        )


def test_split_column_requires_distinct_nonempty_output_names() -> None:
    """Keep invalid operation details rejected at model validation time."""
    with pytest.raises(ValidationError, match="cannot be blank"):
        SplitColumnSpec(separator="|", into=["year", " "])
    with pytest.raises(ValidationError, match="must be unique"):
        SplitColumnSpec(separator="|", into=["year", "year"])


def test_datafile_path_resolution_does_not_require_file_existence(tmp_path: Path) -> None:
    """Input availability is checked by the runtime reader, not configuration parsing."""
    data_file = DataFile(name="missing", fpath=tmp_path / "not-created.csv")

    assert data_file.fpath == tmp_path / "not-created.csv"
