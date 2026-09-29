import json
from xml.etree import ElementTree

import h5py
import numpy as np
import polars as pl
import pytest

from r2x_core.file_readers import read_file_by_type
from r2x_core.file_types import H5Format, JSONFormat, TableFormat, XMLFormat


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
    result = read_file_by_type(TableFormat(), file_path=csv_file)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (2, 3)
    assert df.columns == ["col1", "col2", "col3"]


def test_read_tsv_file(tsv_file):
    result = read_file_by_type(TableFormat(), file_path=tsv_file)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (2, 3)
    assert df.columns == ["col1", "col2", "col3"]


def test_read_csv_with_kwargs(csv_file):
    result = read_file_by_type(TableFormat(), file_path=csv_file, skip_rows=1)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (1, 3)


def test_read_json_file(json_file):
    result = read_file_by_type(JSONFormat(), file_path=json_file)

    assert isinstance(result, dict)
    assert result["key1"] == "value1"
    assert result["key2"] == [1, 2, 3]
    assert result["nested"]["a"] == 1


def test_read_xml_file(xml_file):
    result = read_file_by_type(XMLFormat(), file_path=xml_file)

    assert isinstance(result, ElementTree.Element)
    assert result.tag == "root"
    children = list(result)
    assert len(children) == 2
    assert children[0].attrib["name"] == "test"


def test_read_h5_file_1d(h5_file_1d):
    result = read_file_by_type(H5Format(), file_path=h5_file_1d)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (5, 1)
    assert "data" in df.columns


def test_read_h5_file_2d(h5_file_2d):
    result = read_file_by_type(H5Format(), file_path=h5_file_2d)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape == (2, 3)
    assert "matrix_col_0" in df.columns
    assert "matrix_col_1" in df.columns
    assert "matrix_col_2" in df.columns


def test_read_h5_file_group_fallback(h5_file_group):
    result = read_file_by_type(H5Format(), file_path=h5_file_group)

    assert isinstance(result, pl.LazyFrame)
    df = result.collect()
    assert df.shape[0] == 1


def test_unsupported_file_type(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

    class UnsupportedType:
        pass

    with pytest.raises(NotImplementedError, match="No reader implemented"):
        read_file_by_type(UnsupportedType(), file_path=test_file)


@pytest.mark.parametrize(
    ("header_rows", "kwargs", "message"),
    [
        (0, {}, "header_rows must be at least 1"),
        (2, {"has_header": True}, "has_header=True"),
        (2, {"new_columns": ["first", "second"]}, "new_columns"),
        (2, {"skip_rows_after_header": 1}, "skip_rows_after_header"),
    ],
)
def test_read_csv_rejects_unsupported_multirow_header_options(tmp_path, header_rows, kwargs, message):
    csv_path = tmp_path / "headers.csv"
    csv_path.write_text("first,second\nname,value\na,1\n")

    with pytest.raises(ValueError, match=message):
        read_file_by_type(TableFormat(), file_path=csv_path, header_rows=header_rows, **kwargs)


def test_read_csv_rejects_insufficient_header_rows(tmp_path):
    csv_path = tmp_path / "one_header.csv"
    csv_path.write_text("name,value\na,1\n")

    with pytest.raises(ValueError, match="Expected 3 header rows"):
        read_file_by_type(TableFormat(), file_path=csv_path, header_rows=3)


def test_read_csv_rejects_duplicate_combined_headers(tmp_path):
    csv_path = tmp_path / "duplicate_headers.csv"
    csv_path.write_text("group,group\nvalue,value\na,1\n")

    with pytest.raises(ValueError, match="duplicate column names"):
        read_file_by_type(TableFormat(), file_path=csv_path, header_rows=2)
