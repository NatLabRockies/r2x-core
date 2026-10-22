"""Integration tests for the canonical named-source reader route."""

import os
import subprocess
import sys
from pathlib import Path

import h5py
import numpy as np
import polars as pl
import pytest

from r2x_core import DataFile, DataReader
from r2x_core.datafile import FileInfo, ReaderConfig
from r2x_core.exceptions import ConfiguredGroupNotFoundError
from r2x_core.file_reader import TabularSource
from r2x_core.types import FileRequirement


def read_one(
    reader: DataReader,
    item: DataFile,
    folder: Path,
    *,
    placeholders: dict[str, object] | None = None,
) -> object | None:
    """Load one configured name through source orchestration."""
    return reader.read_data_files([item], folder_path=folder, placeholders=placeholders).get(item.name)


def table_data(source: object) -> pl.LazyFrame:
    """Require a Polars-backed source in tests of the built-in tabular reader."""
    assert isinstance(source, TabularSource)
    assert isinstance(source.data, pl.LazyFrame)
    return source.data


def test_parquet_input_uses_configured_format(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    pl.DataFrame({"value": [1, 2]}).write_parquet(path)

    source = read_one(DataReader(), DataFile(name="parquet", fpath=path), tmp_path)

    assert table_data(source).collect().to_dicts() == [{"value": 1}, {"value": 2}]


def test_optional_and_required_missing_inputs(tmp_path: Path) -> None:
    optional = DataFile(
        name="optional",
        fpath=tmp_path / "absent.csv",
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
    )
    assert read_one(DataReader(), optional, tmp_path) is None
    required = DataFile(name="required", fpath=tmp_path / "absent.csv")
    with pytest.raises(FileNotFoundError, match="Missing required file"):
        read_one(DataReader(), required, tmp_path)


def test_builtin_readers_are_cached_per_datareader_instance() -> None:
    first = DataReader()
    second = DataReader()
    selected = first.select_file_reader("csv")

    assert first.select_file_reader("csv") is selected
    assert second.select_file_reader("csv") is not selected


def test_json_processing_does_not_import_polars(tmp_path: Path) -> None:
    code = """
import sys
from pathlib import Path
from r2x_core import DataFile, JSONProcessing
from r2x_core.reader import DataReader
path = Path(sys.argv[1])
path.write_text('{\"old\":\"value\"}', encoding='utf-8')
item = DataFile(name='lazy-json', fpath=path,
    proc_spec=JSONProcessing(steps=[{'op':'rename_keys','mapping':{'old':'new'}}]))
assert DataReader().read_data_files([item], folder_path=path.parent)['lazy-json'].data == {'new':'value'}
assert 'polars' not in sys.modules
"""
    env = os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "lazy.json")],
        check=True,
        timeout=30,
        env=env,
    )


def test_placeholders_resolve_each_supported_path_mode_before_reading(tmp_path: Path) -> None:
    path = tmp_path / "scenario_2030_profile.csv"
    path.write_text("value\n42\n", encoding="utf-8")
    files = [
        DataFile(name="absolute", fpath=tmp_path / "scenario_{year}_profile.csv"),
        DataFile(name="relative", relative_fpath="scenario_{year}_profile.csv"),
        DataFile(name="glob", glob="scenario_{year}_*.csv"),
    ]

    result = DataReader().read_data_files(files, folder_path=tmp_path, placeholders={"year": 2030})

    assert all(table_data(result[name]).collect().to_dicts() == [{"value": 42}] for name in result)


def test_hdf5_missing_group_obeys_requiredness(tmp_path: Path) -> None:
    path = tmp_path / "outputs.h5"
    with h5py.File(path, "w"):
        pass
    reader = DataReader()
    options = {"group_key": "fuel_price"}
    optional = DataFile(
        name="optional",
        fpath=path,
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
        reader=ReaderConfig(format="hdf5", options=options),
    )
    assert read_one(reader, optional, tmp_path) is None
    required = DataFile(name="required", fpath=path, reader=ReaderConfig(format="hdf5", options=options))
    with pytest.raises(ConfiguredGroupNotFoundError, match="fuel_price"):
        read_one(reader, required, tmp_path)


def test_hdf5_columnar_group_is_read_as_table(tmp_path: Path) -> None:
    path = tmp_path / "outputs.h5"
    with h5py.File(path, "w") as output:
        group = output.create_group("fuel_price")
        group.create_dataset("columns", data=np.array([b"i", b"Value"]))
        group.create_dataset("i", data=np.array([b"gas"]))
        group.create_dataset("Value", data=np.array([3.0]))
    item = DataFile(
        name="fuel_price",
        fpath=path,
        reader=ReaderConfig(
            format="hdf5",
            options={
                "group_key": "fuel_price",
                "columns_key": "columns",
                "columns_as_datasets": True,
            },
        ),
    )

    frame = table_data(read_one(DataReader(), item, tmp_path)).collect()

    assert frame.to_dict(as_series=False) == {"i": ["gas"], "Value": [3.0]}


def test_processing_errors_are_explicit_reader_errors(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    item = DataFile(
        name="invalid",
        fpath=path,
        proc_spec={"kind": "tabular", "steps": [{"op": "cast_columns", "column_schema": {"a": "invalid"}}]},
    )
    from r2x_core.exceptions import ReaderError

    with pytest.raises(ReaderError):
        read_one(DataReader(), item, tmp_path)
