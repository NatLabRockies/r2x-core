"""Exercise typed placeholders in configured reader processing."""

import json
from pathlib import Path

import polars as pl
import pytest

from r2x_core.datafile import DataFile
from r2x_core.exceptions import ReaderError
from r2x_core.file_reader import TabularSource
from r2x_core.reader import DataReader
from r2x_core.types import JSONValue

pytestmark = [pytest.mark.readers, pytest.mark.polars]


def read_table(
    folder: Path,
    record: dict[str, JSONValue],
    *,
    placeholders: dict[str, JSONValue] | None = None,
) -> pl.DataFrame:
    """Read and process one configured CSV input through DataReader."""
    data_file = DataFile.model_validate(record)
    sources = DataReader().read_data_files([data_file], folder_path=folder, placeholders=placeholders)
    source = sources[data_file.name]
    if not isinstance(source, TabularSource):
        msg = f"Expected a tabular source, found {type(source).__name__}"
        raise TypeError(msg)
    return source.data.collect()


def test_filter_by_with_config_variables(tmp_path: Path) -> None:
    """Substitute several typed configuration values before filtering."""
    (tmp_path / "data.csv").write_text(
        "name,year,weather_year,scenario\n"
        "item1,2030,2012,base\nitem2,2030,2012,high\nitem3,2030,2007,base\nitem4,2035,2012,base\n",
        encoding="utf-8",
    )
    result = read_table(
        tmp_path,
        {
            "name": "filtered",
            "relative_fpath": "data.csv",
            "proc_spec": {
                "kind": "tabular",
                "steps": [
                    {
                        "op": "filter_columns",
                        "filter_by": {
                            "year": "{solve_year}",
                            "weather_year": "{weather_year}",
                            "scenario": "{scenario}",
                        },
                    }
                ],
            },
        },
        placeholders={"solve_year": 2030, "weather_year": 2012, "scenario": "base"},
    )

    assert result.to_dicts() == [{"name": "item1", "year": 2030, "weather_year": 2012, "scenario": "base"}]


def test_filter_by_substitutes_values_inside_lists(tmp_path: Path) -> None:
    """Preserve list filters while substituting typed values."""
    (tmp_path / "data.csv").write_text("name,year\nitem1,2025\nitem2,2030\nitem3,2035\n", encoding="utf-8")
    result = read_table(
        tmp_path,
        {
            "name": "years",
            "relative_fpath": "data.csv",
            "proc_spec": {
                "kind": "tabular",
                "steps": [
                    {
                        "op": "filter_columns",
                        "filter_by": {"year": [2025, "{solve_year}"]},
                    }
                ],
            },
        },
        placeholders={"solve_year": 2030},
    )

    assert result["year"].to_list() == [2025, 2030]


@pytest.mark.parametrize("placeholders", [None, {"different": 2030}])
def test_filter_by_requires_each_placeholder(
    tmp_path: Path, placeholders: dict[str, JSONValue] | None
) -> None:
    """Fail clearly when a processing placeholder is not supplied."""
    (tmp_path / "data.csv").write_text("name,year\nitem1,2030\n", encoding="utf-8")
    record: dict[str, JSONValue] = {
        "name": "missing",
        "relative_fpath": "data.csv",
        "proc_spec": {
            "kind": "tabular",
            "steps": [{"op": "filter_columns", "filter_by": {"year": "{solve_year}"}}],
        },
    }

    with pytest.raises((ReaderError, ValueError), match="solve_year"):
        read_table(tmp_path, record, placeholders=placeholders)


def test_reader_processes_configured_file_mapping_json(tmp_path: Path) -> None:
    """Validate file mapping configuration without constructing a DataStore reader loop."""
    (tmp_path / "data.csv").write_text("year,value\n2025,1\n2030,2\n", encoding="utf-8")
    mapping = tmp_path / "file_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "future",
                    "relative_fpath": "data.csv",
                    "proc_spec": {
                        "kind": "tabular",
                        "steps": [{"op": "filter_columns", "filter_by": {"year": "{year}"}}],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    from pydantic import TypeAdapter

    files = TypeAdapter(list[DataFile]).validate_json(mapping.read_bytes())
    source = DataReader().read_data_files(files, folder_path=tmp_path, placeholders={"year": 2030})["future"]

    assert isinstance(source, TabularSource)
    assert source.values("value") == [2]
