import json
from pathlib import Path
from xml.etree import ElementTree

import h5py
import numpy as np
import polars as pl
import pytest

from r2x_core.datafile import DataFile, ReaderConfig
from r2x_core.file_readers import XMLFileReader
from r2x_core.json_adapter import JSONFileReader
from r2x_core.polars_adapter import PolarsTabularFileReader
from r2x_core.reader import DataReader
from r2x_core.types import (
    FileFormat,
    H5Format,
    JSONFormat,
    TableDataFormat,
    TableFormat,
    XMLFormat,
)


def read_polars_file(
    file_type: TableDataFormat,
    *,
    file_path: Path,
    reader_config: ReaderConfig | None = None,
) -> pl.LazyFrame:
    """Read a tabular fixture through the Polars file reader."""
    return PolarsTabularFileReader().read_file(
        file_type,
        file_path=file_path,
        reader_config=ReaderConfig() if reader_config is None else reader_config,
    )


@pytest.fixture
def csv_file(tmp_path):
    csv_path = tmp_path / "test.csv"
    csv_path.write_text("col1,col2,col3\n1,2,3\n4,5,6\n")
    return csv_path


@pytest.fixture
def tsv_file(tmp_path):
    tsv_path = tmp_path / "test.tsv"
    tsv_path.write_text("col1\tcol2\tcol3\n1\t2\t3\n4\t5\t6\n")
    return tsv_path


@pytest.fixture
def json_file(tmp_path):
    json_path = tmp_path / "test.json"
    data = {"key1": "value1", "key2": [1, 2, 3], "nested": {"a": 1}}
    json_path.write_text(json.dumps(data))
    return json_path


@pytest.fixture
def xml_file(tmp_path):
    xml_path = tmp_path / "test.xml"
    xml_content = """<?xml version="1.0"?>
    <root>
        <child name="test">value</child>
        <child name="test2">value2</child>
    </root>
    """
    xml_path.write_text(xml_content)
    return xml_path


@pytest.fixture
def h5_file_1d(tmp_path):
    h5_path = tmp_path / "test_1d.h5"
    with h5py.File(h5_path, "w") as f:
        f.create_dataset("data", data=np.array([1, 2, 3, 4, 5]))
    return h5_path


@pytest.fixture
def h5_file_2d(tmp_path):
    h5_path = tmp_path / "test_2d.h5"
    with h5py.File(h5_path, "w") as f:
        f.create_dataset("matrix", data=np.array([[1, 2, 3], [4, 5, 6]]))
    return h5_path


@pytest.fixture
def h5_file_group(tmp_path):
    h5_path = tmp_path / "test_group.h5"
    with h5py.File(h5_path, "w") as f:
        f.create_group("mygroup")
    return h5_path


def test_read_csv_file(csv_file):
    result = read_polars_file(TableFormat(), file_path=csv_file)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (2, 3)
    assert df.columns == ["col1", "col2", "col3"]


def test_read_tsv_file(tsv_file):
    result = read_polars_file(TableFormat(), file_path=tsv_file)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (2, 3)
    assert df.columns == ["col1", "col2", "col3"]


def test_read_csv_with_kwargs(csv_file):
    result = read_polars_file(
        TableFormat(), file_path=csv_file, reader_config=ReaderConfig(kwargs={"skip_rows": 1})
    )

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (1, 3)


def test_read_json_file(json_file):
    result = JSONFileReader().read_file(JSONFormat(), file_path=json_file, reader_config=ReaderConfig())

    assert isinstance(result, dict)
    assert result["key1"] == "value1"
    assert result["key2"] == [1, 2, 3]
    assert result["nested"]["a"] == 1


def test_read_xml_file(xml_file):
    result = XMLFileReader().read_file(XMLFormat(), file_path=xml_file, reader_config=ReaderConfig())

    assert isinstance(result, ElementTree.Element)
    assert result.tag == "root"
    children = list(result)
    assert len(children) == 2
    assert children[0].attrib["name"] == "test"


def test_read_h5_file_1d(h5_file_1d):
    result = read_polars_file(H5Format(), file_path=h5_file_1d)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (5, 1)
    assert "data" in df.columns


def test_read_h5_file_2d(h5_file_2d):
    result = read_polars_file(H5Format(), file_path=h5_file_2d)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (2, 3)
    assert "matrix_col_0" in df.columns
    assert "matrix_col_1" in df.columns
    assert "matrix_col_2" in df.columns


def test_read_h5_file_group_fallback(h5_file_group):
    result = read_polars_file(H5Format(), file_path=h5_file_group)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape[0] == 1


def test_polars_file_reader_uses_an_injected_h5_reader(tmp_path):
    from r2x_core.h5_adapter import H5Reader

    h5_path = tmp_path / "custom.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([1, 2]))

    class ScaledH5Reader(H5Reader):
        def read_file(
            self,
            file_type: FileFormat,
            /,
            *,
            file_path: Path,
            reader_config: ReaderConfig,
        ) -> dict[str, np.ndarray]:
            if not self.supports_file_type(file_type):
                raise ValueError("Expected HDF5 format")
            with h5py.File(file_path, "r") as h5_file:
                return {"data": np.asarray(h5_file[str(reader_config.kwargs["data_key"])]) * 2}

    reader = PolarsTabularFileReader(h5_reader=ScaledH5Reader())
    result = reader.read_file(
        H5Format(),
        file_path=h5_path,
        reader_config=ReaderConfig(kwargs={"data_key": "data"}),
    )

    assert result.collect().to_dicts() == [{"data": 2}, {"data": 4}]


def test_data_reader_uses_the_builtin_xml_file_reader(xml_file, tmp_path):
    data_file = DataFile(name="xml", fpath=xml_file)

    result = DataReader().read_data_file(data_file, folder_path=tmp_path)

    assert isinstance(result, ElementTree.Element)
    assert result.tag == "root"


def test_unsupported_file_type():
    from dataclasses import dataclass

    @dataclass(slots=True)
    class UnsupportedFormat(FileFormat):
        pass

    with pytest.raises(ValueError, match="No file reader configured for UnsupportedFormat"):
        DataReader().select_file_reader(UnsupportedFormat())


def test_polars_reader_rejects_zero_header_rows(tmp_path):
    with pytest.raises(ValueError, match="header_rows"):
        read_polars_file(
            TableFormat(),
            file_path=tmp_path / "headers.csv",
            reader_config=ReaderConfig(kwargs={"header_rows": 0}),
        )


def test_reader_config_rejects_csv_options_outside_kwargs():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="header_rows"):
        ReaderConfig(header_rows=2)


@pytest.mark.parametrize(
    ("header_rows", "kwargs", "message"),
    [
        (2, {"has_header": True}, "has_header=True"),
        (2, {"new_columns": ["first", "second"]}, "new_columns"),
        (2, {"skip_rows_after_header": 1}, "skip_rows_after_header"),
    ],
)
def test_read_csv_rejects_unsupported_multirow_header_options(tmp_path, header_rows, kwargs, message):
    csv_path = tmp_path / "headers.csv"
    csv_path.write_text("first,second\nname,value\na,1\n")

    with pytest.raises(ValueError, match=message):
        read_polars_file(
            TableFormat(),
            file_path=csv_path,
            reader_config=ReaderConfig(kwargs={"header_rows": header_rows, **kwargs}),
        )


def test_read_csv_rejects_insufficient_header_rows(tmp_path):
    csv_path = tmp_path / "one_header.csv"
    csv_path.write_text("name,value\na,1\n")

    with pytest.raises(ValueError, match="Expected 3 header rows"):
        read_polars_file(
            TableFormat(),
            file_path=csv_path,
            reader_config=ReaderConfig(kwargs={"header_rows": 3}),
        )


def test_read_csv_rejects_duplicate_combined_headers(tmp_path):
    csv_path = tmp_path / "duplicate_headers.csv"
    csv_path.write_text("group,group\nvalue,value\na,1\n")

    with pytest.raises(ValueError, match="duplicate column names"):
        read_polars_file(
            TableFormat(),
            file_path=csv_path,
            reader_config=ReaderConfig(kwargs={"header_rows": 2}),
        )
