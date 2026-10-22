"""HDF5 reader layouts configured and loaded through the canonical source route."""

import json
from pathlib import Path

import h5py
import numpy as np
import polars as pl

from r2x_core.datafile import DataFile, ReaderConfig
from r2x_core.file_reader import TabularSource
from r2x_core.reader import DataReader
from r2x_core.store import DataStore


def read_mapping(folder: Path, records: list[dict[str, object]]) -> dict[str, object]:
    """Validate JSON mapping data and decode each configured input."""
    mapping = folder / "file_mapping.json"
    mapping.write_text(json.dumps(records), encoding="utf-8")
    store = DataStore(folder)
    store.load_file_mapping(mapping)
    return DataReader().read_data_files(store.data_files.values(), folder_path=store.folder)


def table(source: object) -> pl.DataFrame:
    """Require a Polars table for these HDF5 table-layout integration tests."""
    assert isinstance(source, TabularSource)
    assert isinstance(source.data, pl.LazyFrame)
    return source.data.collect()


def test_hdf5_mapping_loads_configured_columns_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "load_data.h5"
    with h5py.File(path, "w") as output:
        output.create_dataset("columns", data=np.array(["region_ca", "region_tx"], dtype="S"))
        output.create_dataset("data", data=np.array([[100.0, 150.0], [120.0, 160.0], [110.0, 155.0]]))
        output.create_dataset(
            "index_datetime",
            data=np.array(
                [
                    "2007-01-01T00:00:00-06:00",
                    "2007-01-01T01:00:00-06:00",
                    "2007-01-01T02:00:00-06:00",
                ],
                dtype="S",
            ),
        )
        output.create_dataset("index_year", data=np.array([2030, 2030, 2030]))

    sources = read_mapping(
        tmp_path,
        [
            {
                "name": "load",
                "fpath": str(path),
                "info": {"description": "Hourly load data", "file_type": "time_series"},
                "reader": {
                    "format": "hdf5",
                    "options": {
                        "data_key": "data",
                        "columns_key": "columns",
                        "datetime_key": "index_datetime",
                        "additional_keys": ["index_year"],
                    },
                },
            }
        ],
    )

    frame = table(sources["load"])
    assert frame.columns == ["region_ca", "region_tx", "datetime", "solve_year"]
    assert frame.height == 3
    assert frame["region_ca"][0] == 100.0
    assert frame["solve_year"][0] == 2030


def test_multiple_hdf5_layouts_load_from_one_mapping(tmp_path: Path) -> None:
    load_path = tmp_path / "load.h5"
    with h5py.File(load_path, "w") as output:
        output.create_dataset("columns", data=np.array(["region1"], dtype="S"))
        output.create_dataset("data", data=np.array([[100.0], [120.0]]))
        output.create_dataset(
            "index_datetime",
            data=np.array(["2007-01-01T00:00:00-06:00", "2007-01-01T01:00:00-06:00"], dtype="S"),
        )
    custom_path = tmp_path / "custom.h5"
    with h5py.File(custom_path, "w") as output:
        output.create_dataset("technologies", data=np.array(["tech_a", "tech_b"], dtype="S"))
        output.create_dataset("cf_values", data=np.array([[0.5, 0.6], [0.7, 0.8]]))
        output.create_dataset("year", data=np.array([2030, 2040]))
    simple_path = tmp_path / "simple.h5"
    with h5py.File(simple_path, "w") as output:
        output.create_dataset("simple_data", data=np.array([1, 2, 3]))

    sources = read_mapping(
        tmp_path,
        [
            {
                "name": "load",
                "fpath": str(load_path),
                "reader": {
                    "format": "hdf5",
                    "options": {
                        "data_key": "data",
                        "columns_key": "columns",
                        "datetime_key": "index_datetime",
                    },
                },
            },
            {
                "name": "cf",
                "fpath": str(custom_path),
                "reader": {
                    "format": "hdf5",
                    "options": {
                        "data_key": "cf_values",
                        "columns_key": "technologies",
                        "index_key": "year",
                    },
                },
            },
            {"name": "simple", "fpath": str(simple_path)},
        ],
    )

    load_frame = table(sources["load"])
    cf_frame = table(sources["cf"])
    simple_frame = table(sources["simple"])
    assert {"region1", "datetime"} <= set(load_frame.columns)
    assert {"tech_a", "tech_b", "year"} <= set(cf_frame.columns)
    assert simple_frame.columns == ["simple_data"]


def test_store_roundtrip_preserves_symbolic_hdf5_options(tmp_path: Path) -> None:
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as output:
        output.create_dataset("data", data=np.array([1, 2, 3]))
    store = DataStore(tmp_path)
    item = DataFile(
        name="test",
        fpath=path,
        reader=ReaderConfig(
            format="hdf5",
            options={"data_key": "data", "columns_key": "columns", "datetime_key": "index_datetime"},
        ),
    )
    store.add_data([item])
    exported = tmp_path / "export.json"
    store.to_json(exported)
    restored = DataStore(tmp_path)
    restored.load_file_mapping(exported)

    assert restored["test"].reader.format == "hdf5"
    assert restored["test"].reader.options == item.reader.options
