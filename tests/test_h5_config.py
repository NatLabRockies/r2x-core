"""Test configuration-based H5 reader usage (integration test)."""

import json
import tempfile
from pathlib import Path

import h5py
import numpy as np

from r2x_core.datafile import ReaderConfig
from r2x_core.polars_adapter import PolarsTabularFileReader
from r2x_core.types import H5Format


def test_h5format_serialization_default():
    """Test that default H5Format serializes correctly."""
    from pydantic import BaseModel

    class TestModel(BaseModel):
        file_format: H5Format

    # Create without reader
    h5_format = H5Format()
    model = TestModel(file_format=h5_format)

    # Should serialize as just the type name
    json_data = model.model_dump()
    assert json_data["file_format"] == "H5Format"


def test_json_config_workflow_with_reader_kwargs():
    """Test complete workflow: JSON config with reader_kwargs -> read file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create a test H5 file in ReEDS format
        h5_file = tmpdir_path / "test_load.h5"
        with h5py.File(str(h5_file), "w") as f:
            columns = np.array(["region1", "region2"], dtype="S")
            data = np.array([[100.0, 150.0], [120.0, 160.0]])
            dt_strings = np.array(["2007-01-01T00:00:00-06:00", "2007-01-01T01:00:00-06:00"], dtype="S")
            f.create_dataset("columns", data=columns)
            f.create_dataset("data", data=data)
            f.create_dataset("index_datetime", data=dt_strings)

        # Create JSON configuration with reader_kwargs (no schema, just describe structure)
        config = {
            "name": "test_file",
            "fpath": str(h5_file),
            "file_type": "H5Format",
            "reader_kwargs": {
                "data_key": "data",
                "columns_key": "columns",
                "datetime_key": "index_datetime",
            },
        }

        # Simulate reading with reader_kwargs
        h5_format = H5Format()
        reader_kwargs = config.get("reader_kwargs", {})
        assert isinstance(reader_kwargs, dict)

        df = (
            PolarsTabularFileReader()
            .read_file(
                h5_format,
                file_path=Path(h5_file),
                reader_config=ReaderConfig(kwargs=reader_kwargs),
            )
            .collect()
        )

        # Check data was read correctly
        assert "region1" in df.columns
        assert "region2" in df.columns
        assert "datetime" in df.columns
        assert len(df) == 2


def test_json_config_workflow_with_tabular_schema():
    """Test JSON config workflow with custom configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create a custom H5 file structure
        h5_file = tmpdir_path / "test_data.h5"
        with h5py.File(str(h5_file), "w") as f:
            col_names = np.array(["col_a", "col_b"], dtype="S")
            values = np.array([[1.0, 2.0], [3.0, 4.0]])
            timestamps = np.array([0, 1])

            f.create_dataset("column_names", data=col_names)
            f.create_dataset("values", data=values)
            f.create_dataset("timestamps", data=timestamps)

        # Create JSON configuration with reader_kwargs
        config = {
            "name": "test_file",
            "fpath": str(h5_file),
            "file_type": "H5Format",
            "reader_kwargs": {
                "data_key": "values",
                "columns_key": "column_names",
                "index_key": "timestamps",
            },
        }

        # Read with reader_kwargs
        h5_format = H5Format()
        reader_kwargs = config.get("reader_kwargs", {})
        assert isinstance(reader_kwargs, dict)

        df = (
            PolarsTabularFileReader()
            .read_file(
                h5_format,
                file_path=Path(h5_file),
                reader_config=ReaderConfig(kwargs=reader_kwargs),
            )
            .collect()
        )

        # Check data was read correctly
        assert "col_a" in df.columns
        assert "col_b" in df.columns
        assert "timestamps" in df.columns
        assert len(df) == 2


def test_config_json_roundtrip_with_reader_kwargs():
    """Test that config with reader_kwargs can be written to JSON and read back."""
    # Create a mock configuration (describe file structure, not model-specific schema)
    config = {
        "files": [
            {
                "name": "load",
                "fpath": "data/load.h5",
                "file_type": "H5Format",
                "reader_kwargs": {
                    "data_key": "data",
                    "columns_key": "columns",
                    "datetime_key": "index_datetime",
                    "additional_keys": ["index_year"],
                },
            },
            {
                "name": "cf",
                "fpath": "data/cf.h5",
                "file_type": "H5Format",
                "reader_kwargs": {
                    "data_key": "cf_values",
                    "columns_key": "technologies",
                },
            },
            {
                "name": "simple",
                "fpath": "data/simple.h5",
                "file_type": "H5Format",
            },
        ]
    }

    # Write to JSON
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        config_file = Path(f.name)

    try:
        # Read back
        with open(config_file) as f:
            loaded_config = json.load(f)

        # Verify structure preserved
        assert loaded_config["files"][0]["reader_kwargs"]["data_key"] == "data"
        assert loaded_config["files"][0]["reader_kwargs"]["columns_key"] == "columns"
        assert loaded_config["files"][0]["reader_kwargs"]["datetime_key"] == "index_datetime"
        assert loaded_config["files"][1]["reader_kwargs"]["data_key"] == "cf_values"
        assert "reader_kwargs" not in loaded_config["files"][2]  # Simple file has no reader_kwargs

        # Verify reader_kwargs can be extracted
        reader_kwargs = loaded_config["files"][0].get("reader_kwargs", {})
        assert reader_kwargs["data_key"] == "data"
    finally:
        config_file.unlink()
