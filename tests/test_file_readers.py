"""Exercise built-in and application-registered input readers with real files."""

import json
from pathlib import Path
from xml.etree import ElementTree

import h5py
import numpy as np
import polars as pl
import pytest

from r2x_core.datafile import DataFile, ReaderConfig
from r2x_core.file_reader import ArraySource, DecodedSources, DocumentSource
from r2x_core.h5_adapter import H5PyFileReader, H5Reader
from r2x_core.json_adapter import JSONFileReader
from r2x_core.polars_adapter import PolarsTabularFileReader
from r2x_core.polars_adapter.readers import read_polars_h5_file
from r2x_core.reader import DataReader
from r2x_core.xml_adapter import XMLFileReader

pytestmark = [pytest.mark.readers, pytest.mark.polars]


def read_polars_file(
    format_name: str,
    *,
    file_path: Path,
    options: dict[str, object] | None = None,
) -> pl.LazyFrame:
    """Read a tabular fixture through the configured source representation."""
    source = PolarsTabularFileReader().read_file(
        format_name,
        file_path=file_path,
        reader_config=ReaderConfig(format=format_name, options=options or {}),
    )["data"]
    assert hasattr(source, "data")
    return source.data


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.csv"
    path.write_text("col1,col2,col3\n1,2,3\n4,5,6\n", encoding="utf-8")
    return path


@pytest.fixture
def tsv_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.tsv"
    path.write_text("col1\tcol2\tcol3\n1\t2\t3\n4\t5\t6\n", encoding="utf-8")
    return path


@pytest.fixture
def json_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.json"
    path.write_text(json.dumps({"key1": "value1", "key2": [1, 2, 3], "nested": {"a": 1}}))
    return path


@pytest.fixture
def xml_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.xml"
    path.write_text('<root><child name="test">value</child><child name="test2">value2</child></root>')
    return path


def test_read_csv_and_tsv(csv_file: Path, tsv_file: Path) -> None:
    for format_name, path in (("csv", csv_file), ("tsv", tsv_file)):
        frame = read_polars_file(format_name, file_path=path).collect()
        assert frame.shape == (2, 3)
        assert frame.columns == ["col1", "col2", "col3"]


def test_read_csv_options_and_validation(csv_file: Path, tmp_path: Path) -> None:
    frame = read_polars_file("csv", file_path=csv_file, options={"skip_rows": 1}).collect()
    assert frame.shape == (1, 3)
    with pytest.raises(ValueError, match="header_rows"):
        read_polars_file("csv", file_path=tmp_path / "missing.csv", options={"header_rows": 0})


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"has_header": True}, "has_header=True"),
        ({"new_columns": ["first", "second"]}, "new_columns"),
        ({"skip_rows_after_header": 1}, "skip_rows_after_header"),
    ],
)
def test_multrow_csv_headers_reject_conflicting_options(
    tmp_path: Path, options: dict[str, object], message: str
) -> None:
    path = tmp_path / "headers.csv"
    path.write_text("first,second\nname,value\na,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        read_polars_file("csv", file_path=path, options={"header_rows": 2, **options})


@pytest.mark.parametrize(
    ("separator", "expected"),
    [(" ", ["Model Year", "Capacity MW"]), (" | ", ["Model | Year", "Capacity | MW"])],
)
def test_multrow_csv_header_separator_is_preserved(
    tmp_path: Path, separator: str, expected: list[str]
) -> None:
    path = tmp_path / "headers.csv"
    path.write_text("Model,Capacity\nYear,MW\n2025,10\n", encoding="utf-8")
    frame = read_polars_file(
        "csv", file_path=path, options={"header_rows": 2, "header_separator": separator}
    ).collect()
    assert frame.columns == expected
    assert frame.rows() == [(2025, 10)]


def test_multrow_csv_headers_reject_insufficient_and_duplicate_headers(tmp_path: Path) -> None:
    insufficient = tmp_path / "insufficient.csv"
    insufficient.write_text("name,value\na,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected 3 header rows"):
        read_polars_file("csv", file_path=insufficient, options={"header_rows": 3})
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text("group,group\nvalue,value\na,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate column names"):
        read_polars_file("csv", file_path=duplicate, options={"header_rows": 2})


def test_json_and_xml_decoders_preserve_native_documents(json_file: Path, xml_file: Path) -> None:
    json_source = JSONFileReader().read_file(
        "json", file_path=json_file, reader_config=ReaderConfig(format="json")
    )["data"]
    xml_source = XMLFileReader().read_file(
        "xml", file_path=xml_file, reader_config=ReaderConfig(format="xml")
    )["data"]
    assert json_source.data == {"key1": "value1", "key2": [1, 2, 3], "nested": {"a": 1}}
    assert isinstance(xml_source.data, ElementTree.Element)
    assert xml_source.data.tag == "root"
    with pytest.raises(TypeError, match="explicit reader conversion"):
        xml_source.fields()


@pytest.mark.parametrize(
    ("reader", "format_name"),
    [(JSONFileReader(), "json"), (XMLFileReader(), "xml")],
)
def test_document_readers_reject_unsupported_options(
    json_file: Path, reader: JSONFileReader | XMLFileReader, format_name: str
) -> None:
    config = ReaderConfig(format=format_name, options={"unsupported": True})

    with pytest.raises(ValueError, match="has no options"):
        reader.read_file(format_name, file_path=json_file, reader_config=config)


def test_document_readers_reject_wrong_formats_and_invalid_json(tmp_path: Path, json_file: Path) -> None:
    with pytest.raises(ValueError, match="cannot read format"):
        JSONFileReader().read_file("xml", file_path=json_file, reader_config=ReaderConfig())
    with pytest.raises(ValueError, match="cannot read format"):
        XMLFileReader().read_file("json", file_path=json_file, reader_config=ReaderConfig())
    path = tmp_path / "broken.json"
    path.write_text('{"invalid":', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        DataReader().read_data_files([DataFile(name="broken", fpath=path)], folder_path=tmp_path)


def test_data_reader_registers_and_overrides_symbolic_formats(json_file: Path) -> None:
    builtin = DataReader().select_file_reader("json")
    assert isinstance(builtin, JSONFileReader)
    custom = JSONFileReader()
    reader = DataReader(file_readers={"json": custom})
    assert reader.select_file_reader("json") is custom
    with pytest.raises(ValueError, match="No reader registered"):
        reader.select_file_reader("unregistered")


def test_data_reader_reads_builtin_xml_into_named_source(xml_file: Path, tmp_path: Path) -> None:
    source = DataReader().read_data_files([DataFile(name="xml", fpath=xml_file)], folder_path=tmp_path)["xml"]
    assert isinstance(source.data, ElementTree.Element)
    assert source.data.tag == "root"


def test_polars_reader_preserves_hdf5_array_and_table_layouts(tmp_path: Path) -> None:
    one_dimensional = tmp_path / "one.h5"
    with h5py.File(one_dimensional, "w") as output:
        output.create_dataset("data", data=np.array([1, 2, 3, 4, 5]))
    one_frame = read_polars_file("hdf5", file_path=one_dimensional).collect()
    assert one_frame.shape == (5, 1)
    assert one_frame.columns == ["data"]

    matrix = tmp_path / "matrix.h5"
    with h5py.File(matrix, "w") as output:
        output.create_dataset("matrix", data=np.array([[1, 2, 3], [4, 5, 6]]))
    matrix_frame = read_polars_file("hdf5", file_path=matrix).collect()
    assert matrix_frame.shape == (2, 3)
    assert matrix_frame.columns == ["matrix_col_0", "matrix_col_1", "matrix_col_2"]


def test_hdf5_table_applies_declared_columns_after_array_decoding(tmp_path: Path) -> None:
    """A table schema must not be rejected by the nested native array reader."""
    path = tmp_path / "input.h5"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("values", data=[1, 2])
    data_file = DataFile.model_validate(
        {
            "name": "input",
            "fpath": str(path),
            "reader": {"format": "hdf5", "options": {"data_key": "values"}},
            "columns": [{"name": "values", "dtype": "int64", "rename": "id"}],
        }
    )

    result = DataReader().read_data_files([data_file], folder_path=tmp_path)["input"]

    assert list(result.iter_rows()) == [{"id": 1}, {"id": 2}]


def test_polars_reader_accepts_custom_hdf5_array_decoder(tmp_path: Path) -> None:
    path = tmp_path / "custom.h5"
    with h5py.File(path, "w") as output:
        output.create_dataset("data", data=np.array([1, 2]))

    class ScaledH5Reader(H5Reader):
        def read_file(
            self,
            format_name: str,
            /,
            *,
            file_path: Path,
            reader_config: ReaderConfig,
        ) -> DecodedSources:
            with h5py.File(file_path, "r") as source:
                values = np.asarray(source[str(reader_config.options["data_key"])]) * 2
            return {"data": ArraySource({"data": values}, None)}

    source = PolarsTabularFileReader(h5_reader=ScaledH5Reader()).read_file(
        "hdf5", file_path=path, reader_config=ReaderConfig(options={"data_key": "data"})
    )["data"]
    assert source.data.collect().to_dicts() == [{"data": 2}, {"data": 4}]


def test_hdf5_reader_options_select_columns_and_datetime(tmp_path: Path) -> None:
    path = tmp_path / "timeseries.h5"
    with h5py.File(path, "w") as output:
        output.create_dataset("columns", data=np.array(["north", "south"], dtype="S"))
        output.create_dataset("data", data=np.array([[1.0, 2.0], [3.0, 4.0]]))
        output.create_dataset(
            "dates", data=np.array(["2024-01-01T00:00:00", "2024-01-01T01:00:00"], dtype="S")
        )
    frame = read_polars_file(
        "hdf5",
        file_path=path,
        options={"data_key": "data", "columns_key": "columns", "datetime_key": "dates"},
    ).collect()
    assert frame.columns == ["north", "south", "datetime"]
    assert frame.height == 2


def test_custom_hdf5_reader_returns_arrays_without_polars_conversion(tmp_path: Path) -> None:
    path = tmp_path / "samples.h5"
    with h5py.File(path, "w") as output:
        output.create_dataset("samples", data=np.array([1.0, 2.0]))
    data_file = DataFile(
        name="samples",
        fpath=path,
        reader=ReaderConfig(format="hdf5_array", options={"data_key": "samples"}),
    )
    source = DataReader().read_data_files([data_file], folder_path=tmp_path)["samples"]
    assert isinstance(source, ArraySource)
    assert source.values("samples") == [1.0, 2.0]


def test_data_reader_requires_explicit_format_for_custom_extension(tmp_path: Path) -> None:
    path = tmp_path / "new.ext"
    path.write_text("{}", encoding="utf-8")
    item = DataFile(name="new", fpath=path, reader=ReaderConfig(format="json"))
    assert DataReader().read_data_files([item], folder_path=tmp_path)["new"].data == {}


def test_csv_reader_options_are_strict(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    item = DataFile(
        name="table",
        fpath=path,
        reader=ReaderConfig(format="csv", options={"not_a_scan_option": True}),
    )
    with pytest.raises(ValueError, match="Unsupported CSV reader option"):
        DataReader().read_data_files([item], folder_path=tmp_path)


def test_hdf5_reader_validates_format_and_options_before_opening(tmp_path: Path) -> None:
    """Reject unsupported HDF5 formats and reader-specific option names."""
    reader = H5PyFileReader()
    path = tmp_path / "not-opened.h5"
    with pytest.raises(ValueError, match="cannot read format"):
        reader.read_file("csv", file_path=path, reader_config=ReaderConfig())
    with pytest.raises(ValueError, match="Invalid HDF5 reader options"):
        reader.read_file(
            "hdf5_array",
            file_path=path,
            reader_config=ReaderConfig(format="hdf5_array", options={"unrecognized": True}),
        )


def test_polars_reader_rejects_unsupported_formats_and_array_only_hdf5(
    tmp_path: Path,
) -> None:
    """Require explicit conversion when an HDF5 reader does not provide columns."""
    reader = PolarsTabularFileReader()
    path = tmp_path / "unread.ext"
    with pytest.raises(ValueError, match="Polars cannot read format"):
        reader.read_file("unreadable", file_path=path, reader_config=ReaderConfig())

    class ArrayOnlyReader(H5Reader):
        def read_file(
            self,
            format_name: str,
            /,
            *,
            file_path: Path,
            reader_config: ReaderConfig,
        ) -> DecodedSources:
            return {"data": ArraySource(np.array([1.0, 2.0]), None)}

    with pytest.raises(ValueError, match="one named array mapping"):
        read_polars_h5_file(
            file_path=path,
            reader_config=ReaderConfig(format="hdf5"),
            h5_reader=ArrayOnlyReader(),
        )


def test_reader_rejects_empty_and_invalid_named_outputs() -> None:
    """Require every registered reader output to be a named decoded source."""
    with pytest.raises(ValueError, match="returned no named sources"):
        DataReader.name_decoded_sources("empty", {})
    with pytest.raises(TypeError, match="invalid named source"):
        DataReader.name_decoded_sources("invalid", {"document": object()})
    with pytest.raises(TypeError, match="invalid named source"):
        DataReader.name_decoded_sources("invalid", {1: DocumentSource({"value": 1}, None)})


def test_derived_sources_must_follow_their_dependencies(tmp_path: Path) -> None:
    """Keep declared source composition ordered and fail before reading inputs."""
    item = DataFile(name="derived", source="not-yet-loaded")
    with pytest.raises(ValueError, match="before it is declared"):
        DataReader().read_data_files([item], folder_path=tmp_path)


def test_reader_placeholders_reject_missing_and_non_string_paths(tmp_path: Path) -> None:
    """Validate path and reader options before any file access."""
    missing_path = DataFile(name="missing", fpath=Path("{input}"))
    with pytest.raises(ValueError, match="Placeholder \\{input\\} has no configured value"):
        DataReader.resolve_placeholders(missing_path, placeholders=None)
    wrong_type = DataFile(name="wrong", fpath=Path("{input}"))
    with pytest.raises(ValueError, match="must resolve to strings"):
        DataReader.resolve_placeholders(wrong_type, placeholders={"input": ["not", "a path"]})
    options = DataFile(
        name="options",
        fpath=tmp_path / "unused.json",
        reader=ReaderConfig(format="json", options={"encoding": "{encoding}"}),
    )
    with pytest.raises(ValueError, match="Placeholder \\{encoding\\} has no configured value"):
        DataReader.resolve_placeholders(options, placeholders=None)
