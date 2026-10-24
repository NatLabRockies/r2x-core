"""Exercise symbolic HDF5 reader configuration with real files."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from r2x_core import DataFile, DataReader
from r2x_core.datafile import ReaderConfig
from r2x_core.h5_adapter.readers import configurable_h5_reader, read_h5_file


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
        with pytest.raises(ValueError, match="columns_key"):
            configurable_h5_reader(output, data_key="values", columns_key=1)
        with pytest.raises(ValueError, match="columns_key is required"):
            configurable_h5_reader(output, columns_as_datasets=True)


@pytest.mark.parametrize(
    ("invalid_options", "field"),
    [
        ({"group_key": 1}, "group_key"),
        ({"columns_as_datasets": "yes"}, "columns_as_datasets"),
        ({"data_key": ""}, "data_key"),
        ({"data_key": 1}, "data_key"),
        ({"index_names_key": 1}, "index_names_key"),
        ({"columns_key": 1}, "columns_key"),
        ({"decode_bytes": "yes"}, "decode_bytes"),
        ({"datetime_key": 1}, "datetime_key"),
        ({"datetime_column_name": 1}, "datetime_column_name"),
        ({"strip_timezone": "yes"}, "strip_timezone"),
        ({"index_key": 1}, "index_key"),
        ({"additional_keys": "data"}, "additional_keys"),
        ({"additional_keys": [1]}, "additional_keys"),
        ({"column_name_mapping": {"data": 1}}, "column_name_mapping"),
        ({"column_name_mapping": []}, "column_name_mapping"),
        ({"unknown_option": True}, "unknown_option"),
    ],
)
def test_hdf5_options_are_strict_for_direct_and_data_reader_paths(
    tmp_path: Path, invalid_options: dict[str, object], field: str
) -> None:
    path = tmp_path / "strict-options.h5"
    with h5py.File(path, "w") as output:
        output.create_dataset("data", data=np.array([1, 2]))

    reader_options = {"data_key": "data", **invalid_options}
    with h5py.File(path, "r") as input_file, pytest.raises(ValueError, match=field):
        configurable_h5_reader(input_file, **reader_options)
    with pytest.raises(ValueError, match=field):
        read_h5_file(file_path=path, **reader_options)

    item = DataFile(
        name="data",
        fpath=path,
        reader=ReaderConfig(
            format="hdf5_array",
            options=reader_options,
        ),
    )
    with pytest.raises(ValueError, match=field):
        DataReader().read_data_files([item], folder_path=tmp_path)


@pytest.mark.polars
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
