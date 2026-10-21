"""Test DataFile filter_by functionality with PluginConfig variables."""

import json
from pathlib import Path

import pytest

from r2x_core import DataStore, PluginConfig
from r2x_core.exceptions import ReaderError


class SampleConfig(PluginConfig):
    """Sample configuration for testing."""

    solve_year: int
    weather_year: int
    scenario: str = "base"


def test_filter_by_with_solve_year_substitution(tmp_path: Path):
    """Test that filter_by substitutes '{solve_year}' placeholder with config value."""
    csv_file = tmp_path / "generators.csv"
    csv_file.write_text("name,capacity,year\ngen1,100,2025\ngen2,200,2030\ngen3,150,2035\n")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    mapping_file = config_dir / "file_mapping.json"
    mapping = [
        {
            "name": "generators",
            "fpath": "generators.csv",
            "proc_spec": {
                "kind": "tabular",
                "steps": [{"op": "filter_columns", "filter_by": {"year": "{solve_year}"}}],
            },
        }
    ]
    mapping_file.write_text(json.dumps(mapping))

    config = SampleConfig(solve_year=2030, weather_year=2012, config_path_override=config_dir)

    store = DataStore.from_plugin_config(config, path=tmp_path)
    data = store.read_data(name="generators", placeholders=config.model_dump())
    df = data.collect()

    assert len(df) == 1
    assert df["year"][0] == 2030
    assert df["name"][0] == "gen2"


def test_filter_by_with_multiple_config_variables(tmp_path: Path):
    """Test filter_by with multiple config variable substitutions."""
    csv_file = tmp_path / "data.csv"
    csv_file.write_text(
        "name,year,weather_year,scenario\n"
        "item1,2030,2012,base\n"
        "item2,2030,2012,high\n"
        "item3,2030,2007,base\n"
        "item4,2035,2012,base\n"
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    mapping_file = config_dir / "file_mapping.json"
    mapping = [
        {
            "name": "filtered_data",
            "fpath": "data.csv",
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
        }
    ]
    mapping_file.write_text(json.dumps(mapping))

    config = SampleConfig(
        solve_year=2030, weather_year=2012, scenario="base", config_path_override=config_dir
    )

    store = DataStore.from_plugin_config(config, path=tmp_path)
    data = store.read_data(name="filtered_data", placeholders=config.model_dump())
    df = data.collect()

    assert len(df) == 1
    assert df["name"][0] == "item1"
    assert df["year"][0] == 2030
    assert df["weather_year"][0] == 2012
    assert df["scenario"][0] == "base"


def test_filter_by_with_config_variable_in_list(tmp_path: Path):
    """Test config variable substitution within list filters."""
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,year\nitem1,2025\nitem2,2030\nitem3,2035\n")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    mapping_file = config_dir / "file_mapping.json"
    mapping = [
        {
            "name": "multi_year",
            "fpath": "data.csv",
            "proc_spec": {
                "kind": "tabular",
                "steps": [{"op": "filter_columns", "filter_by": {"year": [2025, "{solve_year}"]}}],
            },
        }
    ]
    mapping_file.write_text(json.dumps(mapping))

    config = SampleConfig(solve_year=2030, weather_year=2012, config_path_override=config_dir)

    store = DataStore.from_plugin_config(config, path=tmp_path)
    data = store.read_data(name="multi_year", placeholders=config.model_dump())
    df = data.collect()

    assert len(df) == 2
    assert set(df["year"]) == {2025, 2030}


def test_filter_by_with_custom_config_fields(tmp_path: Path):
    """Test that config variable substitution works with any PluginConfig field names."""

    class CustomConfig(PluginConfig):
        model_year: int
        horizon_year: int

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,model_year,horizon_year\nitem1,2030,2050\nitem2,2030,2040\nitem3,2025,2050\n")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    mapping_file = config_dir / "file_mapping.json"
    mapping = [
        {
            "name": "custom_filter",
            "fpath": "data.csv",
            "proc_spec": {
                "kind": "tabular",
                "steps": [
                    {
                        "op": "filter_columns",
                        "filter_by": {"model_year": "{model_year}", "horizon_year": "{horizon_year}"},
                    }
                ],
            },
        }
    ]
    mapping_file.write_text(json.dumps(mapping))

    config = CustomConfig(model_year=2030, horizon_year=2050, config_path_override=config_dir)

    store = DataStore.from_plugin_config(config, path=tmp_path)
    data = store.read_data(name="custom_filter", placeholders=config.model_dump())
    df = data.collect()

    assert len(df) == 1
    assert df["name"][0] == "item1"
    assert df["model_year"][0] == 2030
    assert df["horizon_year"][0] == 2050


def test_filter_by_placeholder_without_substitutions_fails_gracefully(tmp_path: Path):
    """Test that placeholders without placeholders dict give helpful error message."""

    from r2x_core import DataStore

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,year\nitem1,2025\nitem2,2030\n")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    mapping_file = config_dir / "file_mapping.json"
    mapping = [
        {
            "name": "test_data",
            "fpath": "data.csv",
            "proc_spec": {
                "kind": "tabular",
                "steps": [{"op": "filter_columns", "filter_by": {"year": "{solve_year}"}}],
            },
        }
    ]
    mapping_file.write_text(json.dumps(mapping))

    config = SampleConfig(solve_year=2030, weather_year=2012, config_path_override=config_dir)

    store: DataStore = DataStore.from_plugin_config(config, path=tmp_path)
    with pytest.raises(ReaderError) as exc_info:
        store.read_data(name="test_data")

    error_msg = str(exc_info.value)
    assert (
        "Found placeholder '{solve_year}'" in error_msg or "Placeholder '{solve_year}' not found" in error_msg
    )


def test_filter_by_unknown_placeholder_fails_gracefully(tmp_path: Path):
    """Test that unknown placeholder names give helpful error message."""

    from r2x_core import DataStore

    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,year\nitem1,2025\nitem2,2030\n")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    mapping_file = config_dir / "file_mapping.json"
    mapping = [
        {
            "name": "test_data",
            "fpath": "data.csv",
            "proc_spec": {
                "kind": "tabular",
                "steps": [{"op": "filter_columns", "filter_by": {"year": "{unknown_var}"}}],
            },
        }
    ]
    mapping_file.write_text(json.dumps(mapping))

    config = SampleConfig(solve_year=2030, weather_year=2012, config_path_override=config_dir)

    store = DataStore.from_plugin_config(config, path=tmp_path)
    with pytest.raises(ReaderError) as exc_info:
        store.read_data(name="test_data", placeholders=config.model_dump())

    error_msg = str(exc_info.value)
    assert "Placeholder '{unknown_var}' not found" in error_msg
    assert "Available placeholders:" in error_msg
