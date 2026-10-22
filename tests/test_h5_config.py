"""Exercise symbolic HDF5 reader configuration with real files."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from r2x_core import DataFile, DataReader
from r2x_core.datafile import ReaderConfig
from r2x_core.h5_adapter.readers import configurable_h5_reader


def test_hdf5_reader_configuration_roundtrip(tmp_path: Path) -> None:
    """Serialize the selected reader and validated HDF5 layout options."""
    item = DataFile(
        name="load",
        relative_fpath="data/load.h5",
        reader=ReaderConfig(
            format="hdf5",
            options={
                "data_key": "data",
                "columns_key": "columns",
                "datetime_key": "index_datetime",
                "additional_keys": ["index_year"],
            },
        ),
    )

    restored = DataFile.model_validate_json(item.model_dump_json())

    assert restored.reader.format == "hdf5"
    assert restored.reader.options == item.reader.options


def test_hdf5_layout_errors_are_explicit(tmp_path: Path) -> None:
    """Reject malformed HDF5 selectors rather than guessing a layout."""
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as output:
        output.create_dataset("values", data=np.array([1, 2]))
        with pytest.raises(ValueError, match="columns_key must be a string"):
            configurable_h5_reader(output, data_key="values", columns_key=1)
        with pytest.raises(ValueError, match="columns_key is required"):
            configurable_h5_reader(output, columns_as_datasets=True)


def test_hdf5_mapping_reads_columns_datetime_and_additional_keys(tmp_path: Path) -> None:
    """Resolve configured HDF5 datasets into a named Polars table source."""
    path = tmp_path / "load.h5"
    with h5py.File(path, "w") as output:
        output.create_dataset("columns", data=np.array(["north", "south"], dtype="S"))
        output.create_dataset("data", data=np.array([[100.0, 150.0], [120.0, 160.0]]))
        output.create_dataset(
            "index_datetime",
            data=np.array(["2024-01-01T00:00:00", "2024-01-01T01:00:00"], dtype="S"),
        )
        output.create_dataset("index_year", data=np.array([2024, 2025]))
    item = DataFile(
        name="load",
        fpath=path,
        reader=ReaderConfig(
            format="hdf5",
            options={
                "data_key": "data",
                "columns_key": "columns",
                "datetime_key": "index_datetime",
                "additional_keys": ["index_year"],
            },
        ),
    )

    source = DataReader().read_data_files([item], folder_path=tmp_path)["load"]
    frame = source.data.collect()

    assert frame.columns == ["north", "south", "datetime", "solve_year"]
    assert frame.rows() == [
        (100.0, 150.0, np.datetime64("2024-01-01T00:00:00.000000"), 2024),
        (120.0, 160.0, np.datetime64("2024-01-01T01:00:00.000000"), 2025),
    ]
