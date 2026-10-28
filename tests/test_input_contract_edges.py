"""Input-boundary validation for native schemas and optional sources."""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import polars as pl
import pytest
from pydantic import TypeAdapter, ValidationError

from r2x_core import (
    DataFile,
    DataReader,
    DecodedSources,
    DocumentSource,
    FileReader,
    ReaderConfig,
    SourceAvailability,
    TabularSource,
)
from r2x_core.exceptions import ReaderError
from r2x_core.polars_adapter import PolarsTabularBackend
from r2x_core.types import JSONValue

pytestmark = pytest.mark.ingestion


@pytest.mark.parametrize(
    ("record", "message"),
    [
        pytest.param(
            {"name": "derived", "source": "raw", "columns": [{"name": "id", "dtype": "int64"}]},
            "input 'columns' declarations apply only to physical inputs",
            id="schema-on-derived-source",
        ),
        pytest.param(
            {
                "name": "raw",
                "relative_fpath": "input.csv",
                "columns": [{"name": "id", "dtype": "int64"}, {"name": "id", "dtype": "string"}],
            },
            "input column names must be unique",
            id="duplicate-native-names",
        ),
        pytest.param(
            {
                "name": "raw",
                "relative_fpath": "input.csv",
                "columns": [
                    {"name": "a", "dtype": "int64", "rename": "id"},
                    {"name": "b", "dtype": "int64", "rename": "id"},
                ],
            },
            "input column renames must produce unique names",
            id="duplicate-output-names",
        ),
    ],
)
def test_native_schema_rejects_ambiguous_declarations(record: dict[str, object], message: str) -> None:
    """Native declarations belong to physical inputs and use unique column names."""
    with pytest.raises(ValidationError, match=message):
        DataFile.model_validate(record)


@pytest.mark.parametrize(
    ("extension", "content", "message"),
    [
        pytest.param("json", "{}", "JSON reader does not support", id="json"),
        pytest.param("xml", "<data/>", "XML reader does not support", id="xml"),
    ],
)
def test_document_readers_reject_native_table_columns(
    tmp_path: Path, extension: str, content: str, message: str
) -> None:
    """Document formats do not silently reinterpret a tabular native schema."""
    path = tmp_path / f"document.{extension}"
    path.write_text(content, encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "document",
            "fpath": str(path),
            "columns": [{"name": "id", "dtype": "int64"}],
        }
    )

    with pytest.raises(ValueError, match=message):
        DataReader().read_data_files([data_file], folder_path=tmp_path)


class ExternalDocumentReader(FileReader):
    """Read a real JSON document without claiming a tabular representation."""

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        if format_name != "external_document":
            msg = f"Unsupported document format {format_name!r}"
            raise ValueError(msg)
        value = TypeAdapter(JSONValue).validate_python(json.loads(file_path.read_text(encoding="utf-8")))
        return {"data": DocumentSource(value, None)}


def test_custom_document_reader_cannot_satisfy_a_native_table_schema(tmp_path: Path) -> None:
    """Application readers cannot silently return document data for a tabular declaration."""
    (tmp_path / "document.json").write_text('{"id": 1}', encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "document",
            "relative_fpath": "document.json",
            "reader": {"format": "external_document"},
            "columns": [{"name": "id", "dtype": "int64"}],
        }
    )

    with pytest.raises(TypeError, match="column declarations require a tabular reader"):
        DataReader(file_readers={"external_document": ExternalDocumentReader()}).read_data_files(
            [data_file], folder_path=tmp_path
        )


@pytest.mark.parametrize(
    ("columns", "expected"),
    [
        pytest.param(None, {"id": 1}, id="no-columns"),
        pytest.param(
            [{"name": "id", "dtype": "string", "rename": "asset_id"}],
            {"asset_id": "001"},
            id="declared-columns",
        ),
    ],
)
def test_custom_reader_receives_optional_columns_in_reader_config(
    tmp_path: Path, columns: list[dict[str, str]] | None, expected: dict[str, object]
) -> None:
    """A custom reader can use declared types without changing its method signature."""

    class SchemaAwareReader(FileReader):
        def read_file(
            self,
            format_name: str,
            /,
            *,
            file_path: Path,
            reader_config: ReaderConfig,
        ) -> DecodedSources:
            schema = {column.name: pl.String for column in reader_config.columns if column.dtype == "string"}
            frame = pl.scan_csv(file_path, schema_overrides=schema)
            return {"data": TabularSource(frame, PolarsTabularBackend())}

    (tmp_path / "input.custom").write_text("id\n001\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "input",
            "relative_fpath": "input.custom",
            "reader": {"format": "custom"},
            "columns": columns,
        }
    )

    result = DataReader(file_readers={"custom": SchemaAwareReader()}).read_data_files(
        [data_file], folder_path=tmp_path
    )["input"]

    assert list(result.iter_rows()) == [expected]
    assert data_file.reader.columns == ()


def test_reader_keeps_distinct_column_declarations_for_the_same_file(tmp_path: Path) -> None:
    """Per-read column metadata does not leak between cached decodes."""
    (tmp_path / "input.csv").write_text("id\n001\n", encoding="utf-8")
    files = [
        DataFile.model_validate(
            {
                "name": name,
                "relative_fpath": "input.csv",
                "columns": [{"name": "id", "dtype": dtype}],
            }
        )
        for name, dtype in (("as_text", "string"), ("as_number", "int64"))
    ]

    sources = DataReader().read_data_files(files, folder_path=tmp_path)

    assert list(sources["as_text"].iter_rows()) == [{"id": "001"}]
    assert list(sources["as_number"].iter_rows()) == [{"id": 1}]


def test_hdf5_array_reader_rejects_native_table_columns(tmp_path: Path) -> None:
    """An array representation cannot accept a tabular native schema."""
    path = tmp_path / "input.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("values", data=[1, 2])
    data_file = DataFile.model_validate(
        {
            "name": "input",
            "fpath": str(path),
            "reader": {"format": "hdf5_array"},
            "columns": [{"name": "id", "dtype": "int64"}],
        }
    )

    with pytest.raises(ValueError, match="HDF5 array reader does not support native table column"):
        DataReader().read_data_files([data_file], folder_path=tmp_path)


def test_inline_datetime_rejects_nontext_values() -> None:
    """An inline datetime must be an ISO text value, not an integer timestamp."""
    with pytest.raises(ValidationError, match="does not match 'datetime'"):
        DataFile.model_validate(
            {"name": "inline", "inline_table": {"schema": {"date": "datetime"}, "rows": [{"date": 1}]}}
        )


@pytest.mark.parametrize(
    ("optional_columns", "message"),
    [
        pytest.param(["id", "id"], "optional_columns must be unique", id="repeated-optional-name"),
        pytest.param(
            ["missing"], "optional_columns must be declared in column_schema", id="undeclared-optional-name"
        ),
    ],
)
def test_cast_optional_columns_must_match_the_declared_schema(
    optional_columns: list[str], message: str
) -> None:
    """Optional cast fields must be unique members of the declared schema."""
    record = {
        "name": "derived",
        "source": "raw",
        "proc_spec": {
            "kind": "tabular",
            "steps": [
                {"op": "cast_columns", "column_schema": {"id": "int64"}, "optional_columns": optional_columns}
            ],
        },
    }

    with pytest.raises(ValidationError, match=message):
        DataFile.model_validate(record)


@pytest.mark.parametrize(
    ("precedence", "range_separator", "prefix_separator", "message"),
    [
        pytest.param(
            ["exact", "range", "range"], "*", "_", "precedence must contain", id="duplicate-precedence"
        ),
        pytest.param(
            ["exact", "range", "prefix"], ".", ".", "separators must differ", id="identical-delimiters"
        ),
    ],
)
def test_source_pattern_configuration_requires_unambiguous_rules(
    precedence: list[str], range_separator: str, prefix_separator: str, message: str
) -> None:
    """Pattern priority must be complete and range and prefix syntax must differ."""
    record = {
        "name": "matched",
        "source": "raw",
        "proc_spec": {
            "kind": "tabular",
            "steps": [
                {
                    "op": "match_source_patterns",
                    "column": "name",
                    "source": "patterns",
                    "pattern_column": "pattern",
                    "range_separator": range_separator,
                    "prefix_separator": prefix_separator,
                    "precedence": precedence,
                    "prefix_policy": "first",
                    "duplicate_policy": "first",
                    "unmatched": "keep",
                }
            ],
        },
    }

    with pytest.raises(ValidationError, match=message):
        DataFile.model_validate(record)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param(["int64"], "schema_overrides must map", id="not-a-mapping"),
        pytest.param({"id": 42}, "schema_overrides must map", id="non-string-dtype"),
        pytest.param({"id": "string"}, "schema_overrides conflict", id="conflicting-dtype"),
    ],
)
def test_native_schema_rejects_invalid_or_conflicting_csv_overrides(
    tmp_path: Path, overrides: object, message: str
) -> None:
    """Reader overrides cannot contradict or bypass the input's declared column types."""
    (tmp_path / "input.csv").write_text("id,name\n7,wind\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "input",
            "relative_fpath": "input.csv",
            "reader": {"format": "csv", "options": {"schema_overrides": overrides}},
            "columns": [{"name": "id", "dtype": "int64"}],
        }
    )

    with pytest.raises(ValueError, match=message):
        DataReader().read_data_files([data_file], folder_path=tmp_path)


def test_csv_reader_rejects_unknown_reader_options(tmp_path: Path) -> None:
    """An unrecognized CSV option cannot be silently ignored by the input reader."""
    (tmp_path / "input.csv").write_text("id\n7\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "input",
            "relative_fpath": "input.csv",
            "reader": {"format": "csv", "options": {"not_a_real_option": True}},
        }
    )

    with pytest.raises(ValueError, match="Unsupported CSV reader option"):
        DataReader().read_data_files([data_file], folder_path=tmp_path)


def test_native_schema_accepts_compatible_csv_overrides_for_extra_columns(tmp_path: Path) -> None:
    """A matching override can supply a dtype for a column outside the declared schema."""
    (tmp_path / "input.csv").write_text("id,code\n7,001\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "input",
            "relative_fpath": "input.csv",
            "reader": {"format": "csv", "options": {"schema_overrides": {"id": "int64", "code": "string"}}},
            "columns": [{"name": "id", "dtype": "int64"}],
        }
    )

    source = DataReader().read_data_files([data_file], folder_path=tmp_path)["input"]

    assert list(source.iter_rows()) == [{"id": 7, "code": "001"}]


def test_optional_missing_hdf_group_keeps_declared_absent_schema(tmp_path: Path) -> None:
    """A missing optional HDF5 group is distinct from a present empty group."""
    path = tmp_path / "inputs.h5"
    with h5py.File(path, "w") as handle:
        present = handle.create_group("present")
        present.create_dataset("columns", data=[b"id"])
        present.create_dataset("id", shape=(0,), dtype="i8")
    data_file = DataFile.model_validate(
        {
            "name": "missing_group",
            "fpath": str(path),
            "info": {"requirement": "optional"},
            "reader": {
                "format": "hdf5",
                "options": {
                    "group_key": "missing",
                    "columns_key": "columns",
                    "columns_as_datasets": True,
                },
            },
            "columns": [{"name": "id", "dtype": "int64"}],
        }
    )

    present_record = data_file.model_dump(mode="json")
    present_record["name"] = "present_group"
    present_record["reader"] = {
        "format": "hdf5",
        "options": {
            "group_key": "present",
            "columns_key": "columns",
            "columns_as_datasets": True,
        },
    }
    files = [data_file, DataFile.model_validate(present_record)]
    sources = DataReader().read_data_files(files, folder_path=tmp_path)
    absent, present = sources["missing_group"], sources["present_group"]

    assert isinstance(absent, TabularSource)
    assert isinstance(present, TabularSource)
    assert absent.availability is SourceAvailability.ABSENT
    assert absent.absent_inputs == frozenset({"missing_group"})
    assert present.availability is SourceAvailability.PRESENT
    assert present.absent_inputs == frozenset()
    assert absent.fields() == present.fields() == ["id"]
    assert list(absent.iter_rows()) == list(present.iter_rows()) == []


def test_native_join_preserves_temporary_shaped_field_names(tmp_path: Path) -> None:
    """A native join cannot overwrite a user column that resembles an internal key."""
    files = [
        DataFile.model_validate(
            {
                "name": "left",
                "inline_table": {
                    "schema": {"id": "int64", "__r2x_join_key_0__": "string"},
                    "rows": [{"id": 1, "__r2x_join_key_0__": "kept"}],
                },
            }
        ),
        DataFile.model_validate(
            {
                "name": "right",
                "inline_table": {
                    "schema": {"id": "int64", "value": "int64"},
                    "rows": [{"id": 1, "value": 5}],
                },
            }
        ),
        DataFile.model_validate(
            {
                "name": "joined",
                "source": "left",
                "proc_spec": {
                    "kind": "tabular",
                    "steps": [{"op": "join", "source": "right", "how": "left", "on": ["id"]}],
                },
            }
        ),
    ]

    result = DataReader().read_data_files(files, folder_path=tmp_path)["joined"]

    assert list(result.iter_rows()) == [{"id": 1, "__r2x_join_key_0__": "kept", "value": 5}]


@pytest.mark.parametrize(
    ("index", "variable_name", "value_name"),
    [
        pytest.param(["id", "id"], "kind", "value", id="repeated-index"),
        pytest.param(["id"], "value", "value", id="repeated-output"),
    ],
)
def test_native_unpivot_rejects_colliding_output_names(
    tmp_path: Path, index: list[str], variable_name: str, value_name: str
) -> None:
    """An input operation cannot overwrite identifiers or reuse its output names."""
    data_file = DataFile.model_validate(
        {
            "name": "inline",
            "inline_table": {"schema": {"id": "int64", "amount": "int64"}, "rows": [{"id": 1, "amount": 2}]},
            "proc_spec": {
                "kind": "tabular",
                "steps": [
                    {
                        "op": "unpivot",
                        "index": index,
                        "variable_name": variable_name,
                        "value_name": value_name,
                    }
                ],
            },
        }
    )

    with pytest.raises(ReaderError, match="unpivot output names must be distinct"):
        DataReader().read_data_files([data_file], folder_path=tmp_path)


def test_absent_input_processing_cannot_fabricate_a_row(tmp_path: Path) -> None:
    """Aggregating a missing source cannot turn absence into a synthetic zero row."""
    data_file = DataFile.model_validate(
        {
            "name": "missing",
            "relative_fpath": "missing.csv",
            "info": {"requirement": "optional"},
            "columns": [{"name": "id", "dtype": "int64"}],
            "proc_spec": {"kind": "tabular", "steps": [{"op": "aggregate", "aggregate_on": {"id": "count"}}]},
        }
    )

    with pytest.raises(ValueError, match="Processing absent DataFile 'missing' created rows"):
        DataReader().read_data_files([data_file], folder_path=tmp_path)


def test_derived_file_processing_cannot_create_rows_from_an_absent_source(tmp_path: Path) -> None:
    """A derived alias cannot turn typed absence into a row-bearing absent source."""
    files = [
        DataFile.model_validate(
            {
                "name": "missing",
                "relative_fpath": "missing.csv",
                "info": {"requirement": "optional"},
                "columns": [{"name": "id", "dtype": "int64"}],
            }
        ),
        DataFile.model_validate(
            {
                "name": "derived",
                "source": "missing",
                "proc_spec": {
                    "kind": "tabular",
                    "steps": [{"op": "aggregate", "aggregate_on": {"id": "count"}}],
                },
            }
        ),
    ]

    with pytest.raises(ValueError, match="Processing absent DataFile 'derived' created rows"):
        DataReader().read_data_files(files, folder_path=tmp_path)


def test_derived_file_cannot_use_a_missing_optional_source_without_a_schema(tmp_path: Path) -> None:
    """A direct source reference cannot fabricate an absent optional input."""
    files = [
        DataFile.model_validate(
            {"name": "optional", "relative_fpath": "missing.csv", "info": {"requirement": "optional"}}
        ),
        DataFile.model_validate({"name": "derived", "source": "optional"}),
    ]

    with pytest.raises(ValueError, match="Named source 'optional'"):
        DataReader().read_data_files(files, folder_path=tmp_path)


def test_conditional_input_reports_malformed_predicate_data(tmp_path: Path) -> None:
    """A lazy conversion failure is not mistaken for an empty condition or missing optional file."""
    file = DataFile.model_validate(
        {
            "name": "input",
            "relative_fpath": "input.csv",
            "info": {"requirement": "optional"},
            "required_when": {"source": "policy", "predicate": {"gt": ["count", 0]}},
        }
    )
    backend = PolarsTabularBackend()
    policy = TabularSource(
        pl.LazyFrame({"count": ["not-a-number"]}).with_columns(pl.col("count").cast(pl.Int64)), backend
    )

    with pytest.raises(ReaderError) as captured:
        DataReader().read_data_files([file], folder_path=tmp_path, initial_sources={"policy": policy})

    assert isinstance(captured.value.__cause__, pl.exceptions.PolarsError)


def test_conditional_input_cannot_use_an_absent_predicate_source(tmp_path: Path) -> None:
    """A missing condition source cannot be mistaken for a present empty predicate."""
    files = [
        DataFile.model_validate(
            {
                "name": "policy",
                "relative_fpath": "policy.csv",
                "info": {"requirement": "optional"},
                "columns": [{"name": "enabled", "dtype": "bool"}],
            }
        ),
        DataFile.model_validate(
            {
                "name": "input",
                "relative_fpath": "input.csv",
                "info": {"requirement": "optional"},
                "required_when": {"source": "policy", "predicate": "enabled"},
            }
        ),
    ]

    with pytest.raises(ValueError, match="required_when source 'policy' is absent"):
        DataReader().read_data_files(files, folder_path=tmp_path)
