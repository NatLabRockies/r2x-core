from pathlib import Path

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


def test_read_parquet_data_file(reader_example, tmp_path):
    import polars as pl

    from r2x_core.datafile import DataFile

    parquet_path = tmp_path / "data.parquet"
    pl.DataFrame({"value": [1, 2]}).write_parquet(parquet_path)

    result = reader_example.read_data_file(DataFile(name="parquet", fpath=parquet_path), folder_path=tmp_path)

    assert result.collect().to_dicts() == [{"value": 1}, {"value": 2}]


def test_reader_uses_injected_file_reader_and_non_polars_backend(tmp_path):
    import csv
    from dataclasses import dataclass
    from pathlib import Path
    from typing import TypeGuard

    from rust_ok import Ok, Result

    from r2x_core.datafile import DataFile, ReaderConfig, TabularProcessing
    from r2x_core.file_reader import FileReader
    from r2x_core.reader import DataReader
    from r2x_core.tabular_backend import TabularBackend
    from r2x_core.types import FileFormat, TableFormat

    @dataclass
    class CsvRows:
        rows: list[dict[str, str]]

    class CsvFileReader(FileReader[CsvRows]):
        def supports_file_type(self, file_type: FileFormat, /) -> bool:
            return isinstance(file_type, TableFormat)

        def read_file(
            self,
            file_type: FileFormat,
            /,
            *,
            file_path: Path,
            reader_config: ReaderConfig,
        ) -> CsvRows:
            if reader_config.kwargs.get("header_rows", 1) != 1:
                raise ValueError("This reader supports one header row")
            separator = str(reader_config.kwargs.get("separator", ","))
            with file_path.open(encoding="utf-8", newline="") as file:
                return CsvRows(list(csv.DictReader(file, delimiter=separator)))

    class CsvBackend(TabularBackend[CsvRows]):
        def supports_data(self, value: object, /) -> TypeGuard[CsvRows]:
            return isinstance(value, CsvRows)

        def process(
            self,
            frame: CsvRows,
            *,
            data_file: DataFile,
            proc_spec: TabularProcessing,
        ) -> Result[CsvRows, ValueError]:
            column_mapping = proc_spec.column_mapping or {}
            return Ok(
                CsvRows(
                    [
                        {column_mapping.get(name, name): value for name, value in row.items()}
                        for row in frame.rows
                    ]
                )
            )

    csv_path = tmp_path / "backend.csv"
    csv_path.write_text("old_name,value\na,1\n", encoding="utf-8")
    backend: TabularBackend[CsvRows] = CsvBackend()
    file_reader: FileReader[CsvRows] = CsvFileReader()
    reader = DataReader(tabular_backend=backend, file_readers=[file_reader])
    data_file = DataFile(
        name="alternate-backend",
        fpath=csv_path,
        proc_spec=TabularProcessing(column_mapping={"old_name": "name"}),
    )

    result = reader.read_data_file(data_file, folder_path=tmp_path)

    assert isinstance(result, CsvRows)
    assert result.rows == [{"name": "a", "value": "1"}]


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


def test_default_file_reader_is_cached_per_reader_instance():
    pytest.importorskip("polars")

    from r2x_core.reader import DataReader
    from r2x_core.types import TableFormat

    first_reader = DataReader()
    second_reader = DataReader()
    first_default = first_reader.select_file_reader(TableFormat())

    assert first_reader.select_file_reader(TableFormat()) is first_default
    assert second_reader.select_file_reader(TableFormat()) is not first_default


def test_default_json_processor_is_cached_per_reader_instance():
    from r2x_core.reader import DataReader

    first_reader = DataReader()
    second_reader = DataReader()
    first_default = first_reader.json_processor

    assert first_reader.json_processor is first_default
    assert second_reader.json_processor is not first_default


def test_json_processing_does_not_import_polars(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    pytest.importorskip("polars")
    code = """
import sys
from pathlib import Path
from r2x_core.datafile import DataFile, JSONProcessing
from r2x_core.reader import DataReader

path = Path(sys.argv[1])
path.write_text('{"old":"value"}', encoding="utf-8")
data_file = DataFile(
    name="lazy-json",
    fpath=path,
    proc_spec=JSONProcessing(key_mapping={"old": "new"}),
)
assert DataReader().read_data_file(data_file, folder_path=path.parent) == {"new": "value"}
assert "polars" not in sys.modules
"""
    env = os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}

    subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "lazy.json")],
        check=True,
        timeout=30,
        env=env,
    )


def test_reader_uses_an_injected_json_processor(tmp_path):
    from rust_ok import Err, Ok, Result

    from r2x_core.datafile import DataFile, JSONProcessing
    from r2x_core.json_adapter import JSONProcessor
    from r2x_core.reader import DataReader
    from r2x_core.types import JSONValue

    class UppercaseKeys:
        def process(
            self,
            data: JSONValue,
            *,
            data_file: DataFile,
            proc_spec: JSONProcessing,
        ) -> Result[JSONValue, ValueError]:
            if not isinstance(data, dict):
                return Err(ValueError("Expected a JSON object"))
            return Ok({key.upper(): value for key, value in data.items()})

    processor: JSONProcessor = UppercaseKeys()
    path = tmp_path / "payload.json"
    path.write_text('{"name":"grid","capacity":4}', encoding="utf-8")
    reader = DataReader(json_processor=processor)
    data_file = DataFile(name="custom-transform", fpath=path, proc_spec=JSONProcessing())

    result = reader.read_data_file(data_file, folder_path=tmp_path)

    assert result == {"NAME": "grid", "CAPACITY": 4}


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
    from r2x_core.exceptions import ReaderError

    data_file = DataFile(
        name="test",
        fpath=sample_csv,
        proc_spec=TabularProcessing(column_schema={"a": "invalid_type_name"}),
    )

    with pytest.raises(ReaderError):
        reader_example.read_data_file(data_file, folder_path=tmp_path)


def test_read_data_file_substitutes_placeholders_in_path_sources(reader_example, tmp_path):
    from r2x_core.datafile import DataFile

    csv_path = tmp_path / "scenario_2030_profile.csv"
    csv_path.write_text("value\n42\n")
    path_sources = [
        ("fpath", tmp_path / "scenario_{year}_profile.csv"),
        ("relative_fpath", "scenario_{year}_profile.csv"),
        ("glob", "scenario_{year}_*.csv"),
    ]

    for path_field, path_value in path_sources:
        data_file = DataFile(name=path_field, **{path_field: path_value})
        result = reader_example.read_data_file(
            data_file,
            folder_path=tmp_path,
            placeholders={"year": 2030},
        )
        assert result.collect().to_dicts() == [{"value": 42}]


def test_read_data_file_substitutes_boolean_and_numeric_processing_placeholders(reader_example, tmp_path):
    from r2x_core.datafile import DataFile, TabularProcessing

    csv_path = tmp_path / "typed.csv"
    csv_path.write_text("Value\n2\n")
    data_file = DataFile(
        name="typed-placeholders",
        fpath=csv_path,
        proc_spec=TabularProcessing(lowercase="{enabled}", scale={"value": "{factor}"}),
    )

    result = reader_example.read_data_file(
        data_file,
        folder_path=tmp_path,
        placeholders={"enabled": True, "factor": 0.5},
    )

    assert result.collect().to_dicts() == [{"value": 1.0}]


def test_read_data_file_rejects_unknown_path_placeholder(reader_example, tmp_path):
    from r2x_core.datafile import DataFile

    data_file = DataFile(name="unknown", relative_fpath="scenario_{year}.csv")

    with pytest.raises(ValueError, match=r"\{year\}"):
        reader_example.read_data_file(data_file, folder_path=tmp_path)


def test_read_data_file_combines_multiple_header_rows_and_processes_them(reader_example, tmp_path):
    from r2x_core.datafile import DataFile, ReaderConfig, TabularProcessing

    csv_path = tmp_path / "profiles.csv"
    csv_path.write_text("Model Year,2025,2025,2030\nZone,NYISO_A,NYISO_B,NYISO_A\nNYISO,10,20,30\n")
    data_file = DataFile(
        name="profiles",
        fpath=csv_path,
        reader=ReaderConfig(kwargs={"header_rows": 2}),
        proc_spec=TabularProcessing(
            unpivot_on=["2025|NYISO_A", "2025|NYISO_B", "2030|NYISO_A"],
            split_column={"variable": {"separator": "|", "into": ["year", "zone"]}},
            column_schema={"year": "int"},
            filter_by={"year": "{solve_year}"},
            select_columns=["Model Year|Zone", "year", "zone", "value"],
        ),
    )

    result = reader_example.read_data_file(
        data_file,
        folder_path=tmp_path,
        placeholders={"solve_year": 2030},
    )

    assert result.collect().to_dicts() == [
        {"Model Year|Zone": "NYISO", "year": 2030, "zone": "NYISO_A", "value": 30}
    ]


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


def test_read_required_data_file_missing_h5_group_raises(reader_example, tmp_path):
    """Required HDF5 files report absent configured groups."""
    import h5py

    from r2x_core import DataFile
    from r2x_core.datafile import FileInfo, ReaderConfig
    from r2x_core.exceptions import ConfiguredGroupNotFoundError

    h5_path = tmp_path / "outputs.h5"
    with h5py.File(h5_path, "w"):
        pass

    data_file = DataFile(
        name="fuel_price",
        fpath=h5_path,
        info=FileInfo(is_optional=False),
        reader=ReaderConfig(kwargs={"group_key": "fuel_price"}),
    )

    with pytest.raises(ConfiguredGroupNotFoundError, match="fuel_price"):
        reader_example.read_data_file(data_file, folder_path=tmp_path)


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


def test_custom_reader_applies_processing(reader_example, sample_csv, tmp_path):
    import polars as pl

    from r2x_core.datafile import DataFile, ReaderConfig, TabularProcessing

    data_file = DataFile(
        name="custom-processed",
        fpath=sample_csv,
        reader=ReaderConfig(function=lambda path: pl.LazyFrame({"old": [1]})),
        proc_spec=TabularProcessing(column_mapping={"old": "new"}),
    )

    result = reader_example.read_data_file(data_file, folder_path=tmp_path)

    assert result.collect().to_dicts() == [{"new": 1}]


def test_custom_reader_processing_errors_are_reader_errors(reader_example, sample_csv, tmp_path):
    import polars as pl

    from r2x_core.datafile import DataFile, ReaderConfig, TabularProcessing
    from r2x_core.exceptions import ReaderError

    data_file = DataFile(
        name="custom-invalid",
        fpath=sample_csv,
        reader=ReaderConfig(function=lambda path: pl.LazyFrame({"a": [1]})),
        proc_spec=TabularProcessing(filter_by={"missing": "x"}),
    )

    with pytest.raises(ReaderError, match="filter_by"):
        reader_example.read_data_file(data_file, folder_path=tmp_path)


def test_custom_reader_receives_configured_keyword_values(
    reader_example, sample_csv: Path, tmp_path: Path
) -> None:
    from r2x_core import DataFile, ReaderConfig

    def custom_reader(path: Path, *, limit: int, uppercase: bool, prefix: str) -> str:
        text = path.read_text()[:limit]
        return prefix + (text.upper() if uppercase else text)

    data_file = DataFile(
        name="custom",
        fpath=sample_csv,
        reader=ReaderConfig(
            function=custom_reader, kwargs={"limit": 3, "uppercase": True, "prefix": "data:"}
        ),
    )

    assert reader_example.read_data_file(data_file, folder_path=tmp_path) == "data:A,B"
