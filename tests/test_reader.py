import pytest


@pytest.fixture
def sample_csv(tmp_path):
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("a,b,c\n1,2,3\n4,5,6\n")
    return csv_file


@pytest.fixture
def sample_json(tmp_path):
    json_file = tmp_path / "data.json"
    json_file.write_text('{"key": "value", "num": 42}')
    return json_file


@pytest.fixture
def reader_example():
    from r2x_core.reader import DataReader

    return DataReader()


def test_read_data_file_basic(reader_example, sample_csv, tmp_path):
    from r2x_core.datafile import DataFile

    data_file = DataFile(name="test", fpath=sample_csv)

    result = reader_example.read_data_file(data_file, folder_path=tmp_path)

    assert result is not None
    collected = result.collect()
    assert collected.shape == (2, 3)


def test_read_optional_missing_file(reader_example, tmp_path):
    from r2x_core.datafile import DataFile, FileInfo

    dummy_file = tmp_path / "dummy.csv"
    dummy_file.write_text("col1,col2\n1,2\n")

    data_file = DataFile(name="test", fpath=dummy_file, info=FileInfo(is_optional=True))
    dummy_file.unlink()

    result = reader_example.read_data_file(data_file, folder_path=tmp_path)

    assert result is None


def test_read_required_missing_file(reader_example, tmp_path):
    from r2x_core.datafile import DataFile, FileInfo

    dummy_file = tmp_path / "dummy.csv"
    dummy_file.write_text("col1,col2\n1,2\n")

    data_file = DataFile(name="test", fpath=dummy_file, info=FileInfo(is_optional=False))

    dummy_file.unlink()

    with pytest.raises(FileNotFoundError, match="Missing required file"):
        reader_example.read_data_file(data_file, folder_path=tmp_path)


def test_custom_reader_function(reader_example, tmp_path):
    from r2x_core import DataFile
    from r2x_core.datafile import ReaderConfig

    test_file = tmp_path / "custom.csv"
    test_file.write_text("custom content")

    def custom_reader(path):
        return path.read_text().upper()

    data_file = DataFile(
        name="custom", fpath=test_file, reader=ReaderConfig(function=custom_reader, kwargs={})
    )
    result = reader_example.read_data_file(data_file, folder_path=tmp_path)

    assert result == "CUSTOM CONTENT"


def test_get_supported_file_types(reader_example):
    file_types = reader_example.get_supported_file_types()

    assert ".csv" in file_types
    assert ".json" in file_types
    assert ".xml" in file_types
    assert ".h5" in file_types


def test_register_custom_transformation(reader_example):
    def custom_transform(data_file, data):
        return data

    reader_example.register_custom_transformation(str, transform_func=custom_transform)


def test_read_with_reader_kwargs(reader_example, sample_csv, tmp_path):
    from r2x_core import DataFile
    from r2x_core.datafile import ReaderConfig

    data_file = DataFile(name="test", fpath=sample_csv, reader=ReaderConfig(kwargs={"skip_rows": 1}))

    result = reader_example.read_data_file(data_file, folder_path=tmp_path)
    collected = result.collect()

    assert collected.shape == (1, 3)


def test_read_json_file(reader_example, sample_json, tmp_path):
    from r2x_core import DataFile

    data_file = DataFile(name="json_test", fpath=sample_json)

    result = reader_example.read_data_file(data_file, folder_path=tmp_path)

    assert isinstance(result, dict)
    assert result["key"] == "value"
    assert result["num"] == 42


def test_read_data_file_with_custom_reader(reader_example, sample_csv, tmp_path):
    import polars as pl

    from r2x_core.datafile import DataFile, ReaderConfig

    def custom_reader(path, **kwargs):
        return pl.read_csv(path, **kwargs)

    data_file = DataFile(
        name="test",
        fpath=sample_csv,
        reader=ReaderConfig(function=custom_reader, kwargs={}),
    )

    result = reader_example.read_data_file(data_file, folder_path=tmp_path)
    assert result is not None


def test_read_data_file_with_processing_error(reader_example, sample_csv, tmp_path):
    from r2x_core.datafile import DataFile, TabularProcessing

    data_file = DataFile(
        name="test",
        fpath=sample_csv,
        proc_spec=TabularProcessing(column_schema={"a": "invalid_type_name"}),
    )

    with pytest.raises(ValueError):
        reader_example.read_data_file(data_file, folder_path=tmp_path)


def test_read_data_file_glob_pattern(reader_example, tmp_path):
    from r2x_core.datafile import DataFile

    (tmp_path / "data1.csv").write_text("a,b\n1,2\n")

    data_file = DataFile(name="test", glob="*.csv")
    result = reader_example.read_data_file(data_file, folder_path=tmp_path)
    assert result is not None


def test_read_data_file_relative_path(reader_example, tmp_path):
    from r2x_core.datafile import DataFile

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("col1,col2\n1,2\n")

    data_file = DataFile(name="test", relative_fpath="data.csv")
    result = reader_example.read_data_file(data_file, folder_path=tmp_path)
    assert result is not None


def test_read_optional_data_file_missing_h5_group(reader_example, tmp_path):
    """Optional HDF5 files return None when their configured group is absent."""
    import h5py

    from r2x_core import DataFile
    from r2x_core.datafile import FileInfo, ReaderConfig

    h5_path = tmp_path / "outputs.h5"
    with h5py.File(h5_path, "w"):
        pass

    data_file = DataFile(
        name="fuel_price",
        fpath=h5_path,
        info=FileInfo(is_optional=True),
        reader=ReaderConfig(kwargs={"group_key": "fuel_price"}),
    )

    assert reader_example.read_data_file(data_file, folder_path=tmp_path) is None


def test_read_data_file_h5_group(reader_example, tmp_path):
    """DataFile reader kwargs can select a columnar HDF5 group."""
    import h5py
    import numpy as np

    from r2x_core import DataFile
    from r2x_core.datafile import ReaderConfig

    h5_path = tmp_path / "outputs.h5"
    with h5py.File(h5_path, "w") as h5_file:
        group = h5_file.create_group("fuel_price")
        group.create_dataset("columns", data=np.array([b"i", b"Value"]))
        group.create_dataset("i", data=np.array([b"gas"]))
        group.create_dataset("Value", data=np.array([3.0]))

    data_file = DataFile(
        name="fuel_price",
        fpath=h5_path,
        reader=ReaderConfig(
            kwargs={
                "group_key": "fuel_price",
                "columns_key": "columns",
                "columns_as_datasets": True,
            }
        ),
    )
    result = reader_example.read_data_file(data_file, folder_path=tmp_path).collect()

    assert result.to_dict(as_series=False) == {"i": ["gas"], "Value": [3.0]}
