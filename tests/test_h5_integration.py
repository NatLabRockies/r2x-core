"""Integration test for H5 reader with DataStore.from_json()."""

import json
import tempfile
from pathlib import Path

import h5py
import numpy as np

from r2x_core.datafile import ReaderConfig


def test_datastore_from_json_with_reader_kwargs():
    """Test complete DataStore.from_json() workflow with reader_kwargs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create a test H5 file in ReEDS format
        h5_file = tmpdir_path / "load_data.h5"
        with h5py.File(str(h5_file), "w") as f:
            columns = np.array(["region_ca", "region_tx"], dtype="S")
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

        # Create JSON configuration file (must be an array, not object)
        config = [
            {
                "name": "load",
                "fpath": str(h5_file),
                "info": {"description": "Hourly load data", "file_type": "time_series"},
                "reader": {
                    "kwargs": {
                        "data_key": "data",
                        "columns_key": "columns",
                        "datetime_key": "index_datetime",
                        "additional_keys": ["index_year"],
                    }
                },
            }
        ]

        config_file = tmpdir_path / "config.json"
        with open(config_file, "w") as f:
            json.dump(config, f)

        # Load DataStore from JSON
        from r2x_core.store import DataStore

        store = DataStore.from_json(config_file, path=tmpdir_path)

        # Verify the store loaded correctly
        files = store.list_data()
        assert len(files) == 1
        assert "load" in files

        data_file = store["load"]
        assert data_file.reader is not None
        assert data_file.reader.kwargs["data_key"] == "data"
        assert data_file.reader.kwargs["columns_key"] == "columns"

        # Read the file using the store's reader
        from r2x_core.reader import DataReader

        reader = DataReader()
        df = reader.read_data_file(data_file, folder_path=tmpdir_path).collect()

        # Verify the data
        assert "region_ca" in df.columns
        assert "region_tx" in df.columns
        assert "datetime" in df.columns
        assert "solve_year" in df.columns
        assert len(df) == 3
        assert df["region_ca"][0] == 100.0
        assert df["solve_year"][0] == 2030


def test_datastore_from_json_with_multiple_h5_files():
    """Test DataStore with multiple H5 files using different schemas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create ReEDS load file
        load_file = tmpdir_path / "load.h5"
        with h5py.File(str(load_file), "w") as f:
            columns = np.array(["region1"], dtype="S")
            data = np.array([[100.0], [120.0]])
            dt_strings = np.array(["2007-01-01T00:00:00-06:00", "2007-01-01T01:00:00-06:00"], dtype="S")
            f.create_dataset("columns", data=columns)
            f.create_dataset("data", data=data)
            f.create_dataset("index_datetime", data=dt_strings)

        # Create custom tabular file
        custom_file = tmpdir_path / "custom.h5"
        with h5py.File(str(custom_file), "w") as f:
            col_names = np.array(["tech_a", "tech_b"], dtype="S")
            values = np.array([[0.5, 0.6], [0.7, 0.8]])
            years = np.array([2030, 2040])

            f.create_dataset("technologies", data=col_names)
            f.create_dataset("cf_values", data=values)
            f.create_dataset("year", data=years)

        # Create simple default file
        simple_file = tmpdir_path / "simple.h5"
        with h5py.File(str(simple_file), "w") as f:
            f.create_dataset("simple_data", data=np.array([1, 2, 3]))

        # Create JSON configuration with all three (must be an array)
        config = [
            {
                "name": "load",
                "fpath": str(load_file),
                "reader": {
                    "kwargs": {
                        "data_key": "data",
                        "columns_key": "columns",
                        "datetime_key": "index_datetime",
                    }
                },
            },
            {
                "name": "cf",
                "fpath": str(custom_file),
                "reader": {
                    "kwargs": {
                        "data_key": "cf_values",
                        "columns_key": "technologies",
                        "index_key": "year",
                    }
                },
            },
            {
                "name": "simple",
                "fpath": str(simple_file),
            },
        ]

        config_file = tmpdir_path / "config.json"
        with open(config_file, "w") as f:
            json.dump(config, f)

        # Load DataStore from JSON
        from r2x_core.store import DataStore

        store = DataStore.from_json(config_file, path=tmpdir_path)

        # Verify all files loaded
        files = store.list_data()
        assert len(files) == 3

        # Read each file
        from r2x_core.reader import DataReader

        reader = DataReader()

        # Load file (ReEDS schema)
        load_file_obj = store["load"]
        load_df = reader.read_data_file(load_file_obj, folder_path=tmpdir_path).collect()
        assert "region1" in load_df.columns
        assert "datetime" in load_df.columns

        cf_file_obj = store["cf"]
        cf_df = reader.read_data_file(cf_file_obj, folder_path=tmpdir_path).collect()
        assert "tech_a" in cf_df.columns
        assert "tech_b" in cf_df.columns
        assert "year" in cf_df.columns

        # Simple file (default schema)
        simple_file_obj = store["simple"]
        simple_df = reader.read_data_file(simple_file_obj, folder_path=tmpdir_path).collect()
        assert "simple_data" in simple_df.columns


def test_datastore_roundtrip_with_reader_kwargs():
    """Test that DataStore with reader_kwargs can roundtrip through JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create a dummy H5 file
        h5_file = tmpdir_path / "data.h5"
        with h5py.File(str(h5_file), "w") as f:
            f.create_dataset("data", data=np.array([1, 2, 3]))

        # Create DataStore programmatically
        from r2x_core.datafile import DataFile
        from r2x_core.store import DataStore

        data_file = DataFile(
            name="test",
            fpath=h5_file,
            reader=ReaderConfig(
                kwargs={
                    "data_key": "data",
                    "columns_key": "columns",
                    "datetime_key": "index_datetime",
                }
            ),
        )
        store = DataStore(tmpdir_path)
        store.add_data([data_file])

        # Export to JSON
        json_file = tmpdir_path / "export.json"
        store.to_json(fpath=json_file)

        # Read back
        store_loaded = DataStore.from_json(json_file, path=tmpdir_path)

        # Verify reader_kwargs preserved
        files = store_loaded.list_data()
        assert len(files) == 1
        assert "test" in files

        loaded_file = store_loaded["test"]
        assert loaded_file.reader is not None
        assert loaded_file.reader.kwargs is not None
        assert loaded_file.reader.kwargs["data_key"] == "data"
