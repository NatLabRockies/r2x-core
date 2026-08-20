"""Tests for H5 readers module."""

import tempfile
from pathlib import Path

import h5py
import numpy as np
import pytest

from r2x_core.h5_readers import configurable_h5_reader


def test_configurable_h5_reader_default_1d():
    """Test configurable H5 reader with no config (default) and 1D data."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Create a simple H5 file with 1D data
        with h5py.File(str(tmp_path), "w") as f:
            f.create_dataset("test_data", data=np.array([1.0, 2.0, 3.0, 4.0, 5.0]))

        # Read it with no config (uses default)
        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(f)

        assert "test_data" in result
        assert len(result["test_data"]) == 5
        assert result["test_data"][0] == 1.0
    finally:
        tmp_path.unlink()


def test_configurable_h5_reader_default_2d():
    """Test configurable H5 reader with no config (default) and 2D data."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Create a simple H5 file with 2D data
        with h5py.File(str(tmp_path), "w") as f:
            data = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
            f.create_dataset("test_data", data=data)

        # Read it with no config (uses default)
        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(f)

        assert "test_data_col_0" in result
        assert "test_data_col_1" in result
        assert len(result["test_data_col_0"]) == 3
        assert result["test_data_col_0"][0] == 1.0
        assert result["test_data_col_1"][1] == 4.0
    finally:
        tmp_path.unlink()


def test_configurable_h5_reader_with_columns_and_datetime():
    """Test configurable H5 reader with columns and datetime parsing."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Create an H5 file with columns, data, and datetime
        with h5py.File(str(tmp_path), "w") as f:
            columns = np.array(["region1", "region2"], dtype="S")
            data = np.array([[100.0, 150.0], [120.0, 160.0], [110.0, 155.0]])
            dt_strings = np.array(
                [
                    "2007-01-01T00:00:00-06:00",
                    "2007-01-01T01:00:00-06:00",
                    "2007-01-01T02:00:00-06:00",
                ],
                dtype="S",
            )
            solve_years = np.array([2030, 2030, 2030])

            f.create_dataset("columns", data=columns)
            f.create_dataset("data", data=data)
            f.create_dataset("index_datetime", data=dt_strings)
            f.create_dataset("index_year", data=solve_years)

        # Read it with configuration (ReEDS-style via config)
        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="data",
                columns_key="columns",
                datetime_key="index_datetime",
                additional_keys=["index_year"],
            )

        assert "region1" in result
        assert "region2" in result
        assert "datetime" in result
        assert "solve_year" in result
        assert len(result["region1"]) == 3
        assert result["region1"][0] == 100.0
        assert result["solve_year"][0] == 2030
    finally:
        tmp_path.unlink()


def test_configurable_h5_reader_without_solve_year():
    """Test configurable H5 reader without solve_year."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Create an H5 file without solve_year
        with h5py.File(str(tmp_path), "w") as f:
            columns = np.array(["cf1", "cf2"], dtype="S")
            data = np.array([[0.5, 0.6], [0.7, 0.8]])
            dt_strings = np.array(["2007-01-01T00:00:00-06:00", "2007-01-01T01:00:00-06:00"], dtype="S")

            f.create_dataset("columns", data=columns)
            f.create_dataset("data", data=data)
            f.create_dataset("index_datetime", data=dt_strings)

        # Read it with configuration
        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="data",
                columns_key="columns",
                datetime_key="index_datetime",
            )

        assert "cf1" in result
        assert "cf2" in result
        assert "datetime" in result
        assert "solve_year" not in result
    finally:
        tmp_path.unlink()


def test_configurable_h5_reader_custom_keys():
    """Test configurable H5 reader with custom dataset keys."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Create a custom H5 file structure
        with h5py.File(str(tmp_path), "w") as f:
            col_names = np.array(["col_a", "col_b"], dtype="S")
            values = np.array([[1.0, 2.0], [3.0, 4.0]])
            timestamps = np.array([0, 1])
            metadata = np.array([100])

            f.create_dataset("column_names", data=col_names)
            f.create_dataset("values", data=values)
            f.create_dataset("timestamps", data=timestamps)
            f.create_dataset("extra_info", data=metadata)

        # Read it with custom configuration
        with h5py.File(str(tmp_path), "r") as f:
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
    finally:
        tmp_path.unlink()


def test_configurable_h5_reader_no_config_defaults():
    """Test that omitting all config parameters uses default behavior."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Create a simple H5 file
        with h5py.File(str(tmp_path), "w") as f:
            f.create_dataset("data", data=np.array([1, 2, 3]))

        # Read it without any config
        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(f)

        assert "data" in result
        assert len(result["data"]) == 3
    finally:
        tmp_path.unlink()


def test_1d_data_with_columns():
    """Test 1D data when columns_key is provided (line 47)."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            columns = np.array(["single_col"], dtype="S")
            data = np.array([1.0, 2.0, 3.0])
            f.create_dataset("columns", data=columns)
            f.create_dataset("data", data=data)

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="data",
                columns_key="columns",
            )

        assert "single_col" in result
        assert len(result["single_col"]) == 3
    finally:
        tmp_path.unlink()


def test_1d_data_without_columns_key():
    """Test 1D data without columns_key (lines 50-51)."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            data = np.array([10.0, 20.0, 30.0])
            f.create_dataset("my_data", data=data)

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="my_data",
            )

        assert "my_data" in result
        assert len(result["my_data"]) == 3
    finally:
        tmp_path.unlink()


def test_2d_data_without_columns_key():
    """Test 2D data without columns_key (line 52)."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            data = np.array([[1.0, 2.0], [3.0, 4.0]])
            f.create_dataset("values", data=data)

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="values",
            )

        assert "values_col_0" in result
        assert "values_col_1" in result
        assert result["values_col_0"][0] == 1.0
    finally:
        tmp_path.unlink()


def test_non_string_datetime():
    """Test datetime data that's not strings (line 64)."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            data = np.array([1.0, 2.0])
            dt_numeric = np.array([1609459200, 1609545600])
            f.create_dataset("data", data=data)
            f.create_dataset("time", data=dt_numeric)

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="data",
                datetime_key="time",
            )

        assert "datetime" in result
        assert len(result["datetime"]) == 2
    finally:
        tmp_path.unlink()


def test_datetime_with_timezone_kept():
    """Test datetime parsing with timezone kept (lines 118-119)."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            data = np.array([1.0, 2.0])
            dt_strings = np.array(
                ["2007-01-01T00:00:00-06:00", "2007-01-01T01:00:00-06:00"],
                dtype="S",
            )
            f.create_dataset("data", data=data)
            f.create_dataset("time", data=dt_strings)

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="data",
                datetime_key="time",
                strip_timezone=False,
            )

        assert "datetime" in result
    finally:
        tmp_path.unlink()


def test_datetime_parsing_error():
    """Test datetime parsing error handling (lines 121-123)."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            data = np.array([1.0, 2.0])
            dt_strings = np.array(["invalid-datetime", "also-invalid"], dtype="S")
            f.create_dataset("data", data=data)
            f.create_dataset("time", data=dt_strings)

        with (
            h5py.File(str(tmp_path), "r") as f,
            pytest.raises(ValueError, match="Failed to parse datetime string"),
        ):
            configurable_h5_reader(
                f,
                data_key="data",
                datetime_key="time",
            )
    finally:
        tmp_path.unlink()


def test_format_column_name_year():
    """Test format_column_name for year variations."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            data = np.array([1.0, 2.0])
            f.create_dataset("data", data=data)
            f.create_dataset("model_year", data=np.array([2030, 2035]))

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="data",
                additional_keys=["model_year"],
            )

        assert "year" in result
    finally:
        tmp_path.unlink()


def test_h5_reader_index_names_resolves_numeric_indices():
    """Test that index_names dataset resolves index_0, index_1 to meaningful column names.

    This test verifies the fix for the issue where newer ReEDS runs use generic
    index keys (index_0, index_1) instead of named keys (index_datetime, index_year).
    The index_names dataset provides the mapping, and the reader should automatically
    apply it to produce columns named "solve_year" instead of "1".

    Issue: formatting a generic index name returned "1" instead of "solve_year".
    Fix: Reader now checks for index_names dataset and maps index_N to actual names.
    """
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Create H5 file mimicking newer ReEDS format
        with h5py.File(str(tmp_path), "w") as f:
            columns = np.array([b"region1", b"region2"], dtype="S")
            data = np.array([[100.0, 200.0], [150.0, 250.0], [175.0, 275.0]])
            dt_strings = np.array(
                [
                    "2007-01-01T00:00:00-06:00",
                    "2007-01-01T01:00:00-06:00",
                    "2007-01-01T02:00:00-06:00",
                ],
                dtype="S",
            )
            solve_years = np.array([2030, 2030, 2030])

            # Store actual index names in metadata (newer ReEDS format)
            # index_0 contains datetime strings → maps to "index_datetime"
            # index_1 contains years → maps to "index_year" → becomes "solve_year"
            index_names = np.array([b"index_datetime", b"index_year"], dtype="S")

            f.create_dataset("columns", data=columns)
            f.create_dataset("data", data=data)
            f.create_dataset("index_0", data=dt_strings)
            f.create_dataset("index_1", data=solve_years)
            f.create_dataset("index_names", data=index_names)

        # Read with automatic index_names resolution
        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="data",
                columns_key="columns",
                datetime_key="index_0",
                additional_keys=["index_1"],
            )

        # ASSERTION: The issue is fixed - column should be "solve_year", not "1"
        assert "solve_year" in result, f"Expected 'solve_year' column, got: {list(result.keys())}"
        assert "1" not in result, f"Column should not be named '1', got: {list(result.keys())}"

        # Verify the data is correct
        assert len(result["solve_year"]) == 3
        assert result["solve_year"][0] == 2030
        assert result["solve_year"][1] == 2030
        assert result["solve_year"][2] == 2030

        # Verify other expected columns
        assert "region1" in result
        assert "region2" in result
        assert "datetime" in result
        assert len(result["datetime"]) == 3

    finally:
        tmp_path.unlink()


def test_h5_reader_respects_user_overrides_for_index_names():
    """Ensure explicit column_name_mapping can override index dataset names."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            columns = np.array([b"col1", b"col2"], dtype="S")
            data = np.array([[10.0, 20.0], [30.0, 40.0]])
            dt_strings = np.array(["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z"], dtype="S")
            years = np.array([2030, 2035])

            f.create_dataset("columns", data=columns)
            f.create_dataset("data", data=data)
            f.create_dataset("index_datetime", data=dt_strings)
            f.create_dataset("index_year", data=years)

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                data_key="data",
                columns_key="columns",
                datetime_key="index_datetime",
                datetime_column_name="custom_datetime",
                additional_keys=["index_year"],
                column_name_mapping={
                    "index_datetime": "custom_datetime",
                    "index_year": "planning_year",
                },
            )

        assert "custom_datetime" in result
        assert "planning_year" in result
        assert "solve_year" not in result
        assert list(result["planning_year"]) == [2030, 2035]

    finally:
        tmp_path.unlink()


def test_h5_reader_missing_index_dataset_raises_key_error():
    """Ensure missing referenced index datasets raise KeyError (line 53)."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            columns = np.array([b"col1"], dtype="S")
            data = np.array([[10.0], [20.0]])
            f.create_dataset("columns", data=columns)
            f.create_dataset("data", data=data)
            # reference index_0 but do not create the dataset to trigger the error
            f.create_dataset("index_names", data=np.array([b"0"], dtype="S"))

        with h5py.File(str(tmp_path), "r") as f, pytest.raises(KeyError, match="index_0"):
            configurable_h5_reader(
                f,
                data_key="data",
                columns_key="columns",
                datetime_key="index_0",
            )
    finally:
        tmp_path.unlink()


def test_h5_reader_reads_columnar_group_datasets():
    """Read ReEDS-style groups whose columns are individual datasets."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            group = f.create_group("fuel_price")
            group.create_dataset("columns", data=np.array([b"i", b"r", b"Value"]))
            group.create_dataset("i", data=np.array([b"gas", b"coal"]))
            group.create_dataset("r", data=np.array([b"r1", b"r2"]))
            group.create_dataset("Value", data=np.array([3.0, 4.0]))

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                group_key="fuel_price",
                columns_key="columns",
                columns_as_datasets=True,
            )

        assert result["i"] == ["gas", "coal"]
        assert result["r"] == ["r1", "r2"]
        np.testing.assert_array_equal(result["Value"], np.array([3.0, 4.0]))
    finally:
        tmp_path.unlink()


def test_h5_reader_group_validation_errors():
    """Reject missing groups, column metadata, and column datasets."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            f.create_dataset("not_a_group", data=np.array([1.0]))
            group = f.create_group("group")
            group.create_dataset("columns", data=np.array([b"missing"]))

        with h5py.File(str(tmp_path), "r") as f:
            with pytest.raises(KeyError, match="missing_group"):
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
    finally:
        tmp_path.unlink()


def test_h5_reader_columnar_group_reads_scalar_dataset():
    """Normalize scalar column datasets to one-row arrays."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            group = f.create_group("group")
            group.create_dataset("columns", data=np.array([b"Value"]))
            group.create_dataset("Value", data=np.array(3.0))

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                group_key="group",
                columns_key="columns",
                columns_as_datasets=True,
            )

        np.testing.assert_array_equal(result["Value"], np.array([3.0]))
    finally:
        tmp_path.unlink()


def test_h5_reader_columnar_group_reads_scalar_string_dataset():
    """Normalize decoded scalar string column datasets to one-row lists."""
    with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with h5py.File(str(tmp_path), "w") as f:
            group = f.create_group("group")
            group.create_dataset("columns", data=np.array([b"i"]))
            group.create_dataset("i", data=np.bytes_("gas"))

        with h5py.File(str(tmp_path), "r") as f:
            result = configurable_h5_reader(
                f,
                group_key="group",
                columns_key="columns",
                columns_as_datasets=True,
            )

        assert result["i"] == ["gas"]
    finally:
        tmp_path.unlink()


def test_h5_reader_rejects_invalid_reader_keys(tmp_path):
    """Reject invalid key types before opening configured datasets."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([1.0]))

    with h5py.File(h5_path, "r") as h5_file:
        with pytest.raises(ValueError, match="index_names_key must be a string"):
            configurable_h5_reader(h5_file, data_key="data", index_names_key=1)
        with pytest.raises(ValueError, match="data_key is required"):
            configurable_h5_reader(h5_file, data_key=1, columns_key="columns")


def test_h5_reader_missing_data_key_raises_key_error(tmp_path):
    """Raise KeyError when the configured main dataset does not exist."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("other", data=np.array([1.0]))

    with h5py.File(h5_path, "r") as h5_file, pytest.raises(KeyError, match="missing"):
        configurable_h5_reader(h5_file, data_key="missing")


def test_h5_reader_validates_reader_configuration(tmp_path):
    """Reject invalid configuration values before reading datasets."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([1.0]))
        h5_file.create_dataset("columns", data=np.array([b"value"]))

    invalid_options = [
        ({"group_key": 1}, "group_key must be a string"),
        ({"columns_as_datasets": "yes"}, "columns_as_datasets must be a boolean"),
        ({"data_key": ""}, "data_key is required"),
        ({"columns_key": 1}, "columns_key must be a string"),
        ({"decode_bytes": "yes"}, "decode_bytes must be a boolean"),
        ({"datetime_key": 1}, "datetime_key must be a string"),
        ({"datetime_column_name": 1}, "datetime_column_name must be a string"),
        ({"strip_timezone": "yes"}, "strip_timezone must be a boolean"),
        ({"index_key": 1}, "index_key must be a string"),
        ({"additional_keys": "data"}, "additional_keys must be a list"),
        ({"additional_keys": [1]}, "additional_keys must be a list"),
        ({"column_name_mapping": []}, "column_name_mapping must be a dictionary"),
        ({"column_name_mapping": {1: "value"}}, "column_name_mapping must map strings"),
    ]

    with h5py.File(h5_path, "r") as h5_file:
        for options, message in invalid_options:
            reader_options = {"data_key": "data", **options}
            with pytest.raises(ValueError, match=message):
                configurable_h5_reader(h5_file, **reader_options)


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


def test_h5_reader_decodes_or_preserves_column_labels(tmp_path):
    """Honor decode_bytes for row-oriented column labels."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([[1.0, 2.0]]))
        h5_file.create_dataset("columns", data=np.array([b"one", b"two"]))

    with h5py.File(h5_path, "r") as h5_file:
        decoded = configurable_h5_reader(h5_file, data_key="data", columns_key="columns")
        preserved = configurable_h5_reader(
            h5_file,
            data_key="data",
            columns_key="columns",
            decode_bytes=False,
        )

    assert set(decoded) == {"one", "two"}
    assert set(preserved) == {"one", "two"}


def test_h5_reader_honors_decode_bytes_for_index_names(tmp_path):
    """Use byte index labels to resolve datasets when decoding is disabled."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([[1.0]]))
        h5_file.create_dataset("columns", data=np.array([b"value"]))
        h5_file.create_dataset("index_names", data=np.array([b"index_year"]))
        h5_file.create_dataset("index_0", data=np.array([2030]))

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            data_key="data",
            columns_key="columns",
            additional_keys=["index_0"],
            decode_bytes=False,
        )

    np.testing.assert_array_equal(result["solve_year"], np.array([2030]))


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


def test_h5_reader_handles_scalar_datetime_dataset(tmp_path):
    """Normalize a scalar datetime dataset before parsing it."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([1.0]))
        h5_file.create_dataset("time", data=np.bytes_("2024-01-01T00:00:00Z"))

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(h5_file, data_key="data", datetime_key="time")

    np.testing.assert_array_equal(
        result["datetime"], np.array(["2024-01-01T00:00:00"], dtype="datetime64[us]")
    )


@pytest.mark.parametrize("scope_key", [None, "empty"])
def test_h5_reader_rejects_empty_default_scope(tmp_path, scope_key):
    """Raise a clear error when default reading has no HDF5 entries."""
    h5_path = tmp_path / "empty.h5"
    with h5py.File(h5_path, "w") as h5_file:
        if scope_key is not None:
            h5_file.create_group(scope_key)

    with h5py.File(h5_path, "r") as h5_file, pytest.raises(ValueError, match="contains no datasets"):
        configurable_h5_reader(h5_file, group_key=scope_key)


def test_h5_reader_reads_non_string_column_metadata(tmp_path):
    """Read numeric column metadata without calling HDF5 string decoding."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([[1.0, 2.0]]))
        h5_file.create_dataset("columns", data=np.array([10, 20]))

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(h5_file, data_key="data", columns_key="columns")

    np.testing.assert_array_equal(result["10"], np.array([1.0]))
    np.testing.assert_array_equal(result["20"], np.array([2.0]))


def test_h5_reader_reads_custom_index_names_key(tmp_path):
    """Use a configured dataset name for generic index metadata."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        h5_file.create_dataset("data", data=np.array([[1.0]]))
        h5_file.create_dataset("columns", data=np.array([b"value"]))
        h5_file.create_dataset("names", data=np.array([b"index_year"]))
        h5_file.create_dataset("index_0", data=np.array([2030]))

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            data_key="data",
            columns_key="columns",
            index_names_key="names",
            additional_keys=["index_0"],
        )

    assert result["solve_year"].tolist() == [2030]


def test_h5_reader_preserves_columnar_bytes_when_decoding_disabled(tmp_path):
    """Honor decode_bytes for columnar string datasets and labels."""
    h5_path = tmp_path / "data.h5"
    with h5py.File(h5_path, "w") as h5_file:
        group = h5_file.create_group("group")
        group.create_dataset("columns", data=np.array([b"label"]))
        group.create_dataset("label", data=np.array([b"gas"]))

    with h5py.File(h5_path, "r") as h5_file:
        result = configurable_h5_reader(
            h5_file,
            group_key="group",
            columns_key="columns",
            columns_as_datasets=True,
            decode_bytes=False,
        )

    assert result["label"] == [b"gas"]


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
