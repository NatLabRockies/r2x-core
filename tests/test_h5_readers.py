"""Tests for H5 readers module."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from r2x_core.exceptions import ConfiguredGroupNotFoundError
from r2x_core.h5py_adapter import configurable_h5_reader, read_h5_file

pytestmark = pytest.mark.readers


def test_read_h5_file_opens_file_and_reads_configured_columns(tmp_path: Path) -> None:
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("columns", data=np.array([b"first", b"second"]))
        h5_file.create_dataset("data", data=np.array([[1, 2], [3, 4]]))

    result = read_h5_file(file_path=h5_path, data_key="data", columns_key="columns")

    assert result["first"].tolist() == [1, 3]
    assert result["second"].tolist() == [2, 4]


@pytest.mark.parametrize(
    ("decode_bytes", "expected"),
    [(True, ["north", "south"]), (False, [b"north", b"south"])],
)
def test_read_h5_file_decodes_default_string_dataset(
    tmp_path: Path, decode_bytes: bool, expected: list[str] | list[bytes]
) -> None:
    h5_path = tmp_path / "regions.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("regions", data=np.asarray([b"north", b"south"], dtype="S"))

    result = read_h5_file(file_path=h5_path, decode_bytes=decode_bytes)

    assert result["regions"].tolist() == expected


@pytest.mark.parametrize(
    ("dataset_name", "data", "expected"),
    [
        (
            "test_data",
            np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
            {"test_data": np.array([1.0, 2.0, 3.0, 4.0, 5.0])},
        ),
        (
            "test_data",
            np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]),
            {
                "test_data_col_0": np.array([1.0, 3.0, 5.0]),
                "test_data_col_1": np.array([2.0, 4.0, 6.0]),
            },
        ),
        ("data", np.array([1, 2, 3]), {"data": np.array([1, 2, 3])}),
    ],
    ids=["one-dimensional", "two-dimensional", "default-dataset-name"],
)
def test_configurable_h5_reader_defaults_to_first_dataset(
    tmp_path: Path, dataset_name: str, data: np.ndarray, expected: dict[str, np.ndarray]
) -> None:
    h5_path = tmp_path / "default.h5"
    with h5py.File(h5_path, "w") as output:
        output.create_dataset(dataset_name, data=data)

    with h5py.File(h5_path, "r") as input_file:
        result = configurable_h5_reader(input_file)

    assert list(result) == list(expected)
    for name, values in expected.items():
        np.testing.assert_array_equal(result[name], values)


def test_default_h5_reader_preserves_a_first_group(tmp_path: Path) -> None:
    h5_path = tmp_path / "group.h5"
    with h5py.File(h5_path, "w") as output:
        output.create_group("metadata")

    with h5py.File(h5_path, "r") as input_file:
        result = configurable_h5_reader(input_file)

    assert list(result) == ["metadata"]
    assert result["metadata"][0].startswith("<HDF5 group")


@pytest.mark.parametrize(
    ("columns", "data", "datetimes", "years", "expected"),
    [
        pytest.param(
            np.array([b"region1", b"region2"]),
            np.array([[100.0, 150.0], [120.0, 160.0], [110.0, 155.0]]),
            np.array(
                [
                    b"2007-01-01T00:00:00-06:00",
                    b"2007-01-01T01:00:00-06:00",
                    b"2007-01-01T02:00:00-06:00",
                ]
            ),
            np.array([2030, 2030, 2030]),
            {
                "region1": np.array([100.0, 120.0, 110.0]),
                "region2": np.array([150.0, 160.0, 155.0]),
                "datetime": np.array(
                    ["2007-01-01T00:00:00", "2007-01-01T01:00:00", "2007-01-01T02:00:00"],
                    dtype="datetime64[us]",
                ),
                "index_year": np.array([2030, 2030, 2030]),
            },
            id="with-index-year",
        ),
        pytest.param(
            np.array([b"cf1", b"cf2"]),
            np.array([[0.5, 0.6], [0.7, 0.8]]),
            np.array([b"2007-01-01T00:00:00-06:00", b"2007-01-01T01:00:00-06:00"]),
            None,
            {
                "cf1": np.array([0.5, 0.7]),
                "cf2": np.array([0.6, 0.8]),
                "datetime": np.array(["2007-01-01T00:00:00", "2007-01-01T01:00:00"], dtype="datetime64[us]"),
            },
            id="without-solve-year",
        ),
    ],
)
def test_configurable_h5_reader_with_columns_and_datetime(
    tmp_path: Path,
    columns: np.ndarray,
    data: np.ndarray,
    datetimes: np.ndarray,
    years: np.ndarray | None,
    expected: dict[str, np.ndarray],
) -> None:
    h5_path = tmp_path / "reader.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("columns", data=columns)
        h5_file.create_dataset("data", data=data)
        h5_file.create_dataset("index_datetime", data=datetimes)
        if years is not None:
            h5_file.create_dataset("index_year", data=years)

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            data_key="data",
            columns_key="columns",
            datetime_key="index_datetime",
            additional_keys=["index_year"] if years is not None else [],
        )

    assert result.keys() == expected.keys()
    for name, values in expected.items():
        np.testing.assert_array_equal(result[name], values)


def test_configurable_h5_reader_custom_keys(tmp_path: Path) -> None:
    """Test configurable H5 reader with custom dataset keys."""
    h5_path = tmp_path / "reader.h5"

    # Create a custom H5 file structure
    with h5py.File(str(h5_path), "w") as f:
        col_names = np.array(["col_a", "col_b"], dtype="S")
        values = np.array([[1.0, 2.0], [3.0, 4.0]])
        timestamps = np.array([0, 1])
        metadata = np.array([100])

        f.create_dataset("column_names", data=col_names)
        f.create_dataset("values", data=values)
        f.create_dataset("timestamps", data=timestamps)
        f.create_dataset("extra_info", data=metadata)

    # Read it with custom configuration
    with h5py.File(str(h5_path), "r") as f:
        result = configurable_h5_reader(
            f,
            data_key="values",
            columns_key="column_names",
            index_key="timestamps",
            additional_keys=["extra_info"],
        )

    assert "col_a" in result
    assert "col_b" in result
    assert "timestamps" in result
    assert "extra_info" in result
    assert result["col_a"][0] == 1.0
    assert result["timestamps"][1] == 1


@pytest.mark.parametrize(
    ("data_key", "data", "columns", "expected"),
    [
        pytest.param(
            "my_data",
            np.array([10.0, 20.0, 30.0]),
            None,
            {"my_data": np.array([10.0, 20.0, 30.0])},
            id="1d-without-columns",
        ),
        pytest.param(
            "values",
            np.array([[1.0, 2.0], [3.0, 4.0]]),
            None,
            {"values_col_0": np.array([1.0, 3.0]), "values_col_1": np.array([2.0, 4.0])},
            id="2d-without-columns",
        ),
        pytest.param(
            "data",
            np.array([1.0, 2.0, 3.0]),
            np.array([b"single_col"]),
            {"single_col": np.array([1.0, 2.0, 3.0])},
            id="1d-with-column-label",
        ),
    ],
)
def test_configurable_h5_reader_reads_row_data(
    tmp_path: Path,
    data_key: str,
    data: np.ndarray,
    columns: np.ndarray | None,
    expected: dict[str, np.ndarray],
) -> None:
    h5_path = tmp_path / "reader.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset(data_key, data=data)
        if columns is not None:
            h5_file.create_dataset("columns", data=columns)

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            data_key=data_key,
            columns_key="columns" if columns is not None else None,
        )

    assert list(result) == list(expected)
    for name, values in expected.items():
        np.testing.assert_array_equal(result[name], values)


@pytest.mark.parametrize(
    ("decode_bytes", "expected_fuel", "expected_technology"),
    [
        (True, ["ngas", "coal"], ["gas-cc", "coal"]),
        (False, [b"ngas", b"coal"], [b"gas-cc", b"coal"]),
    ],
)
def test_h5_reader_decodes_declared_string_data_and_additional_keys(
    tmp_path: Path,
    decode_bytes: bool,
    expected_fuel: list[str] | list[bytes],
    expected_technology: list[str] | list[bytes],
) -> None:
    """Decode HDF5 strings consistently for row data and additional columns."""
    h5_path = tmp_path / "fuel-map.h5"
    with h5py.File(h5_path, "w") as h5_file:
        group = h5_file.create_group("fuel2tech")
        group.create_dataset("f", data=np.asarray([b"ngas", b"coal"], dtype="S"))
        group.create_dataset("i", data=np.asarray([b"gas-cc", b"coal"], dtype="S"))
        group.create_dataset("capacity", data=np.asarray([1.0, 2.0]))

    result = read_h5_file(
        file_path=h5_path,
        group_key="fuel2tech",
        data_key="f",
        additional_keys=["i", "capacity"],
        decode_bytes=decode_bytes,
    )

    assert result["f"].tolist() == expected_fuel
    assert result["i"].tolist() == expected_technology
    np.testing.assert_array_equal(result["capacity"], np.asarray([1.0, 2.0]))


def test_h5_reader_preserves_numeric_columnar_array_dtype(tmp_path: Path) -> None:
    h5_path = tmp_path / "capacity.h5"
    with h5py.File(h5_path, "w") as h5_file:
        group = h5_file.create_group("capacity")
        group.create_dataset("columns", data=np.asarray([b"mw"], dtype="S"))
        group.create_dataset("mw", data=np.asarray([1.25, 2.5], dtype=np.float32))

    result = read_h5_file(
        file_path=h5_path,
        group_key="capacity",
        columns_key="columns",
        columns_as_datasets=True,
    )

    assert isinstance(result["mw"], np.ndarray)
    assert result["mw"].dtype == np.dtype(np.float32)
    np.testing.assert_array_equal(result["mw"], np.asarray([1.25, 2.5], dtype=np.float32))


@pytest.mark.parametrize(
    ("data", "timestamps", "strip_timezone", "expected"),
    [
        pytest.param(
            np.array([1.0, 2.0]),
            np.array([1609459200, 1609545600]),
            True,
            np.array([1609459200, 1609545600]),
            id="numeric-values",
        ),
        pytest.param(
            np.array([1.0, 2.0]),
            np.array(["2007-01-01T00:00:00-06:00", "2007-01-01T01:00:00-06:00"], dtype="S"),
            False,
            np.array(["2007-01-01T06:00:00", "2007-01-01T07:00:00"], dtype="datetime64[us]"),
            id="timezone-normalized-to-utc",
        ),
        pytest.param(
            np.array([1.0]),
            np.bytes_("2024-01-01T00:00:00Z"),
            True,
            np.array(["2024-01-01T00:00:00"], dtype="datetime64[us]"),
            id="scalar-bytes",
        ),
    ],
)
def test_h5_reader_parses_datetime_inputs(
    tmp_path: Path, data: np.ndarray, timestamps: np.ndarray, strip_timezone: bool, expected: np.ndarray
) -> None:
    h5_path = tmp_path / "reader.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=data)
        h5_file.create_dataset("time", data=timestamps)

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            data_key="data",
            datetime_key="time",
            strip_timezone=strip_timezone,
        )

    np.testing.assert_array_equal(result["datetime"], expected)


def test_datetime_parsing_error(tmp_path: Path) -> None:
    """Test datetime parsing error handling (lines 121-123)."""
    h5_path = tmp_path / "reader.h5"

    with h5py.File(str(h5_path), "w") as f:
        data = np.array([1.0, 2.0])
        dt_strings = np.array(["invalid-datetime", "also-invalid"], dtype="S")
        f.create_dataset("data", data=data)
        f.create_dataset("time", data=dt_strings)

    with (
        h5py.File(str(h5_path), "r") as f,
        pytest.raises(ValueError, match="Failed to parse datetime string"),
    ):
        configurable_h5_reader(
            f,
            data_key="data",
            datetime_key="time",
        )


def test_h5_reader_preserves_dataset_names_unless_mapped(tmp_path: Path) -> None:
    h5_path = tmp_path / "reader.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([1.0, 2.0]))
        h5_file.create_dataset("model_year", data=np.array([2030, 2035]))

    with h5py.File(h5_path, "r") as h5_file:
        unchanged = configurable_h5_reader(h5_file, data_key="data", additional_keys=["model_year"])
        mapped = configurable_h5_reader(
            h5_file,
            data_key="data",
            additional_keys=["model_year"],
            column_name_mapping={"model_year": "year"},
        )

    assert "model_year" in unchanged
    assert "year" not in unchanged
    assert "year" in mapped


@pytest.mark.parametrize(
    ("datasets", "reader_options", "expected"),
    [
        pytest.param(
            {
                "columns": np.array([b"region1", b"region2"]),
                "data": np.array([[100.0, 200.0], [150.0, 250.0], [175.0, 275.0]]),
                "index_0": np.array(
                    [
                        b"2007-01-01T00:00:00-06:00",
                        b"2007-01-01T01:00:00-06:00",
                        b"2007-01-01T02:00:00-06:00",
                    ]
                ),
                "index_1": np.array([2030, 2030, 2030]),
                "index_names": np.array([b"index_datetime", b"index_year"]),
            },
            {"datetime_key": "index_0", "additional_keys": ["index_1"]},
            {
                "region1": np.array([100.0, 150.0, 175.0]),
                "region2": np.array([200.0, 250.0, 275.0]),
                "datetime": np.array(
                    ["2007-01-01T00:00:00", "2007-01-01T01:00:00", "2007-01-01T02:00:00"],
                    dtype="datetime64[us]",
                ),
                "index_year": np.array([2030, 2030, 2030]),
            },
            id="numeric-index-names",
        ),
        pytest.param(
            {
                "columns": np.array([b"col1", b"col2"]),
                "data": np.array([[10.0, 20.0], [30.0, 40.0]]),
                "index_datetime": np.array([b"2024-01-01T00:00:00Z", b"2024-01-01T01:00:00Z"]),
                "index_year": np.array([2030, 2035]),
            },
            {
                "datetime_key": "index_datetime",
                "datetime_column_name": "custom_datetime",
                "additional_keys": ["index_year"],
                "column_name_mapping": {
                    "index_datetime": "custom_datetime",
                    "index_year": "planning_year",
                },
            },
            {
                "col1": np.array([10.0, 30.0]),
                "col2": np.array([20.0, 40.0]),
                "custom_datetime": np.array(
                    ["2024-01-01T00:00:00", "2024-01-01T01:00:00"], dtype="datetime64[us]"
                ),
                "planning_year": np.array([2030, 2035]),
            },
            id="user-overrides",
        ),
    ],
)
def test_h5_reader_maps_index_names(
    tmp_path: Path,
    datasets: dict[str, np.ndarray],
    reader_options: dict[str, object],
    expected: dict[str, np.ndarray],
) -> None:
    """Resolve automatic index names and explicit column-name overrides."""
    h5_path = tmp_path / "reader.h5"
    with h5py.File(h5_path, "w") as h5_file:
        for name, values in datasets.items():
            h5_file.create_dataset(name, data=values)

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            data_key="data",
            columns_key="columns",
            **reader_options,
        )

    assert result.keys() == expected.keys()
    for name, values in expected.items():
        np.testing.assert_array_equal(result[name], values)


def test_h5_reader_missing_index_dataset_raises_key_error(tmp_path: Path) -> None:
    """Ensure missing referenced index datasets raise KeyError (line 53)."""
    h5_path = tmp_path / "reader.h5"

    with h5py.File(str(h5_path), "w") as f:
        columns = np.array([b"col1"], dtype="S")
        data = np.array([[10.0], [20.0]])
        f.create_dataset("columns", data=columns)
        f.create_dataset("data", data=data)
        # reference index_0 but do not create the dataset to trigger the error
        f.create_dataset("index_names", data=np.array([b"0"], dtype="S"))

    with h5py.File(str(h5_path), "r") as f, pytest.raises(KeyError, match="index_0"):
        configurable_h5_reader(
            f,
            data_key="data",
            columns_key="columns",
            datetime_key="index_0",
        )


@pytest.mark.parametrize(
    ("columns", "values", "decode_bytes", "expected"),
    [
        pytest.param(
            np.array([b"i", b"r", b"Value"]),
            {"i": np.array([b"gas", b"coal"]), "r": np.array([b"r1", b"r2"]), "Value": np.array([3.0, 4.0])},
            True,
            {"i": ["gas", "coal"], "r": ["r1", "r2"], "Value": np.array([3.0, 4.0])},
            id="multiple-columns",
        ),
        pytest.param(
            np.array([b"Value"]), {"Value": 3.0}, True, {"Value": np.array([3.0])}, id="scalar-numeric"
        ),
        pytest.param(np.array([b"i"]), {"i": np.bytes_("gas")}, True, {"i": ["gas"]}, id="scalar-string"),
        pytest.param(
            np.array([b"label"]),
            {"label": np.array([b"gas"])},
            False,
            {"label": [b"gas"]},
            id="preserve-bytes",
        ),
    ],
)
def test_h5_reader_reads_columnar_group_datasets(
    tmp_path: Path,
    columns: np.ndarray,
    values: dict[str, object],
    decode_bytes: bool,
    expected: dict[str, object],
) -> None:
    h5_path = tmp_path / "reader.h5"
    with h5py.File(h5_path, "w") as h5_file:
        group = h5_file.create_group("group")
        group.create_dataset("columns", data=columns)
        for name, value in values.items():
            group.create_dataset(name, data=value)

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            group_key="group",
            columns_key="columns",
            columns_as_datasets=True,
            decode_bytes=decode_bytes,
        )

    assert set(result) == set(expected)
    for name, value in expected.items():
        np.testing.assert_array_equal(np.asarray(result[name]), np.asarray(value))


def test_h5_reader_group_validation_errors(tmp_path: Path) -> None:
    """Reject missing groups, column metadata, and column datasets."""
    h5_path = tmp_path / "reader.h5"

    with h5py.File(str(h5_path), "w") as f:
        f.create_dataset("not_a_group", data=np.array([1.0]))
        group = f.create_group("group")
        group.create_dataset("columns", data=np.array([b"missing"]))

    with h5py.File(str(h5_path), "r") as f:
        with pytest.raises(ConfiguredGroupNotFoundError, match="missing_group"):
            configurable_h5_reader(
                f,
                group_key="missing_group",
                columns_key="columns",
                columns_as_datasets=True,
            )
        with pytest.raises(TypeError, match="not_a_group"):
            configurable_h5_reader(f, group_key="not_a_group")
        with pytest.raises(KeyError, match="missing"):
            configurable_h5_reader(
                f,
                group_key="group",
                columns_key="columns",
                columns_as_datasets=True,
            )
        with pytest.raises(ValueError, match="columns_key is required"):
            configurable_h5_reader(f, group_key="group", columns_as_datasets=True)
        with pytest.raises(ValueError, match="columns path 'missing/columns' not found"):
            configurable_h5_reader(
                f,
                group_key="group",
                columns_key="missing/columns",
                columns_as_datasets=True,
            )


def test_h5_reader_requires_a_list_for_additional_keys(tmp_path: Path) -> None:
    h5_path = tmp_path / "additional-keys.h5"
    with h5py.File(str(h5_path), "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([1.0]))
        h5_file.create_dataset("extra", data=np.array([2.0]))

    with h5py.File(str(h5_path), "r") as h5_file:
        direct_result = configurable_h5_reader(h5_file, data_key="data", additional_keys=["extra"])
        with pytest.raises(ValueError, match="additional_keys"):
            configurable_h5_reader(h5_file, data_key="data", additional_keys=("extra",))

    file_result = read_h5_file(file_path=h5_path, data_key="data", additional_keys=["extra"])
    with pytest.raises(ValueError, match="additional_keys"):
        read_h5_file(file_path=h5_path, data_key="data", additional_keys=("extra",))

    np.testing.assert_array_equal(direct_result["extra"], np.array([2.0]))
    np.testing.assert_array_equal(file_result["extra"], np.array([2.0]))


def test_h5_reader_rejects_non_string_column_mapping_key(tmp_path: Path) -> None:
    """Reject malformed mapping keys at the direct reader boundary."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(str(h5_path), "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([1.0]))

    with h5py.File(str(h5_path), "r") as h5_file, pytest.raises(ValueError, match="column_name_mapping"):
        configurable_h5_reader(h5_file, data_key="data", column_name_mapping={1: "value"})


def test_h5_reader_missing_data_key_raises_key_error(tmp_path):
    """Raise KeyError when the configured main dataset does not exist."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("other", data=np.array([1.0]))

    with h5py.File(h5_path, "r") as h5_file, pytest.raises(KeyError, match="missing"):
        configurable_h5_reader(h5_file, data_key="missing")


def test_h5_reader_validates_column_shape_and_group_columns(tmp_path):
    """Reject invalid column metadata and non-dataset column paths."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.ones((2, 2)))
        h5_file.create_dataset("columns", data=np.array([b"one"]))
        h5_file.create_dataset("data_1d", data=np.array([1.0, 2.0]))
        h5_file.create_dataset("empty_columns", data=np.array([], dtype="S"))
        group = h5_file.create_group("group")
        group.create_group("columns")

    with h5py.File(h5_path, "r") as h5_file:
        with pytest.raises(ValueError, match="contains 1 names"):
            configurable_h5_reader(h5_file, data_key="data", columns_key="columns")
        with pytest.raises(ValueError, match="must contain exactly 1 name"):
            configurable_h5_reader(h5_file, data_key="data_1d", columns_key="empty_columns")
        with pytest.raises(TypeError, match="columns path"):
            configurable_h5_reader(
                h5_file,
                group_key="group",
                columns_key="columns",
                columns_as_datasets=True,
            )


@pytest.mark.parametrize(
    ("columns", "decode_bytes", "expected"),
    [
        pytest.param(
            np.array([b"one", b"two"]),
            True,
            {"one": np.array([1.0]), "two": np.array([2.0])},
            id="decode-bytes",
        ),
        pytest.param(
            np.array([b"one", b"two"]),
            False,
            {"one": np.array([1.0]), "two": np.array([2.0])},
            id="preserve-bytes",
        ),
        pytest.param(
            np.array([10, 20]),
            True,
            {"10": np.array([1.0]), "20": np.array([2.0])},
            id="numeric-labels",
        ),
    ],
)
def test_h5_reader_reads_row_oriented_column_metadata(
    tmp_path: Path, columns: np.ndarray, decode_bytes: bool, expected: dict[str, np.ndarray]
) -> None:
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([[1.0, 2.0]]))
        h5_file.create_dataset("columns", data=columns)

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            data_key="data",
            columns_key="columns",
            decode_bytes=decode_bytes,
        )

    assert set(result) == set(expected)
    for name, values in expected.items():
        np.testing.assert_array_equal(result[name], values)


@pytest.mark.parametrize(
    ("index_names_key", "decode_bytes"),
    [
        pytest.param("index_names", False, id="preserve-byte-labels"),
        pytest.param("names", True, id="custom-metadata-key"),
    ],
)
def test_h5_reader_resolves_index_names(index_names_key: str, decode_bytes: bool, tmp_path: Path) -> None:
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([[1.0]]))
        h5_file.create_dataset("columns", data=np.array([b"value"]))
        h5_file.create_dataset(index_names_key, data=np.array([b"index_year"]))
        h5_file.create_dataset("index_0", data=np.array([2030]))

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            data_key="data",
            columns_key="columns",
            index_names_key=index_names_key,
            additional_keys=["index_0"],
            decode_bytes=decode_bytes,
        )

    np.testing.assert_array_equal(result["index_year"], np.array([2030]))


def test_h5_reader_supports_nested_column_metadata_path(tmp_path):
    """Resolve column metadata through a nested HDF5 path."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        group = h5_file.create_group("group")
        metadata = group.create_group("metadata")
        metadata.create_dataset("columns", data=np.array([b"Value"]))
        group.create_dataset("Value", data=np.array([3.0]))

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            group_key="group",
            columns_key="metadata/columns",
            columns_as_datasets=True,
        )

    np.testing.assert_array_equal(result["Value"], np.array([3.0]))


@pytest.mark.parametrize("scope_key", [None, "empty"])
def test_h5_reader_rejects_empty_default_scope(tmp_path, scope_key):
    """Raise a clear error when default reading has no HDF5 entries."""
    h5_path = tmp_path / "empty.h5"
    with h5py.File(h5_path, "w") as h5_file:
        if scope_key is not None:
            h5_file.create_group(scope_key)

    with h5py.File(h5_path, "r") as h5_file, pytest.raises(ValueError, match="contains no datasets"):
        configurable_h5_reader(h5_file, group_key=scope_key)


def test_h5_reader_skips_missing_additional_dataset(tmp_path):
    """Ignore optional additional dataset names that are not present."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([1.0]))

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(h5_file, data_key="data", additional_keys=["missing"])

    assert result == {"data": np.array([1.0])}


def test_h5_reader_resolves_dataset_path(tmp_path):
    """Resolve a dataset addressed by a nested HDF5 path."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        group = h5_file.create_group("values")
        group.create_dataset("data", data=np.array([1.0]))

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(h5_file, data_key="values/data")

    assert result["values/data"].tolist() == [1.0]
