"""Tests for configured calendar and System projection sources."""

from datetime import datetime, timedelta

import numpy as np
import polars as pl
import pytest
from fixtures.target_system import NodeComponent
from infrasys import SingleTimeSeries

from r2x_core import (
    CalendarSource,
    DataStore,
    PluginConfig,
    PluginContext,
    PreparedTableError,
    SystemFrameSource,
    TimeSeriesProjection,
)


class SourceConfig(PluginConfig):
    """Resolve component classes used by runtime source tests."""

    models: tuple[str, ...] = ("fixtures.target_system",)


def test_calendar_source_generates_weather_year_and_sample_limit() -> None:
    source = CalendarSource.model_validate(
        {
            "kind": "calendar",
            "name": "weather_calendar",
            "year": "{weather_year}",
            "resolution_seconds": 3600,
            "sample_limit": 8760,
        }
    )

    frame = source.to_frame(placeholders={"weather_year": 2012})

    assert frame.height == 8760
    assert frame.row(0, named=True) == {
        "year": 2012,
        "hour_index": 0,
        "timestamp": datetime(2012, 1, 1),
        "month": 1,
    }
    assert frame.filter(pl.col("month") == 2).height == 696
    assert frame[-1, "hour_index"] == 8759


def test_store_reads_typed_configuration_records_as_a_named_source(tmp_path) -> None:
    store = DataStore(path=tmp_path)
    store.load_file_mapping(
        {
            "files": [],
            "sources": [
                {
                    "kind": "config_records",
                    "name": "reserve_products",
                    "asset": "defaults.json",
                    "records_key": "reserve_products",
                    "columns": {"name": "string", "wind_fraction": "float64"},
                }
            ],
            "tables": [],
        },
        mapping_path=tmp_path / "mapping.json",
    )
    config = SourceConfig(
        asset_overrides={"defaults": {"reserve_products": [{"name": "SPINNING", "wind_fraction": 0.1}]}}
    )
    context = PluginContext(config=config, store=store)

    frame = store.read_data("reserve_products", context=context)

    assert isinstance(frame, pl.DataFrame)
    assert frame.schema == {"name": pl.String, "wind_fraction": pl.Float64}
    assert frame.to_dicts() == [{"name": "SPINNING", "wind_fraction": 0.1}]


@pytest.mark.parametrize(
    ("primary_content", "fallback_content", "empty_policy", "expected"),
    [
        (None, "id\n2\n", "select", [{"id": 2}]),
        ("id\n", "id\n2\n", "select", []),
        ("id\n", "id\n2\n", "skip", [{"id": 2}]),
    ],
    ids=["missing-primary-selects-fallback", "empty-primary-selected", "empty-primary-skipped"],
)
def test_first_present_source_uses_configured_empty_policy(
    tmp_path,
    primary_content: str | None,
    fallback_content: str,
    empty_policy: str,
    expected: list[dict[str, int]],
) -> None:
    """Select the first physical file that exists, including an empty one."""
    if primary_content is not None:
        (tmp_path / "primary.csv").write_text(primary_content)
    (tmp_path / "fallback.csv").write_text(fallback_content)
    store = DataStore(path=tmp_path)
    store.load_file_mapping(
        {
            "files": [
                {"name": "primary", "relative_fpath": "primary.csv", "info": {"is_optional": True}},
                {"name": "fallback", "relative_fpath": "fallback.csv", "info": {"is_optional": True}},
            ],
            "sources": [
                {
                    "kind": "first_present",
                    "name": "selected",
                    "candidates": ["primary", "fallback"],
                    "empty": empty_policy,
                    "missing": "error",
                }
            ],
            "tables": [],
        },
        mapping_path=tmp_path / "mapping.json",
    )

    frame = store.read_data("selected")

    assert isinstance(frame, pl.DataFrame)
    assert frame.to_dicts() == expected


def test_remove_data_rejects_first_present_candidate_atomically(tmp_path) -> None:
    (tmp_path / "primary.csv").write_text("id\n7\n")
    store = DataStore(path=tmp_path)
    store.load_file_mapping(
        {
            "files": [{"name": "primary", "relative_fpath": "primary.csv", "info": {"is_optional": True}}],
            "sources": [{"kind": "first_present", "name": "selected", "candidates": ["primary"]}],
            "tables": [],
        },
        mapping_path=tmp_path / "mapping.json",
    )

    with pytest.raises(KeyError, match=r"selected.*primary"):
        store.remove_data("primary")

    assert store.list_files() == ["primary"]
    assert store.read_data("primary").collect().to_dicts() == [{"id": 7}]
    assert store.read_data("selected").to_dicts() == [{"id": 7}]


def test_load_file_mapping_resolves_sources_against_existing_files(tmp_path) -> None:
    from r2x_core import DataFile, FileInfo

    primary = tmp_path / "primary.csv"
    secondary = tmp_path / "secondary.csv"
    primary.write_text("id\n7\n")
    secondary.write_text("id\n99\n")
    store = DataStore(path=tmp_path)
    store.add_data(
        [
            DataFile(name="primary", fpath=primary, info=FileInfo(is_optional=True)),
            DataFile(name="secondary", fpath=secondary, info=FileInfo(is_optional=True)),
        ]
    )

    store.load_file_mapping(
        {
            "files": [],
            "sources": [
                {"kind": "first_present", "name": "selected", "candidates": ["primary", "secondary"]}
            ],
            "tables": [],
        },
        mapping_path=tmp_path / "source-fragment.json",
    )

    assert store.read_data("selected").to_dicts() == [{"id": 7}]


def test_first_present_source_reuses_cached_root_snapshot(tmp_path) -> None:
    primary_path = tmp_path / "primary.csv"
    primary_path.write_text("id,value\n1,7\n")
    (tmp_path / "secondary.csv").write_text("id,value\n1,99\n")

    def read_and_remove(path):
        frame = pl.read_csv(path)
        path.unlink()
        return frame.lazy()

    from r2x_core import DataFile, FileInfo, ReaderConfig

    store = DataStore(path=tmp_path)
    store.add_data(
        [
            DataFile(
                name="primary",
                fpath=primary_path,
                info=FileInfo(is_optional=True),
                reader=ReaderConfig(function=read_and_remove),
            ),
            DataFile(
                name="secondary",
                fpath=tmp_path / "secondary.csv",
                info=FileInfo(is_optional=True),
            ),
        ]
    )
    store.load_file_mapping(
        {
            "files": [],
            "sources": [
                {"kind": "first_present", "name": "selected", "candidates": ["primary", "secondary"]}
            ],
            "tables": [
                {
                    "name": "joined",
                    "source": "primary",
                    "frame_sources": ["selected"],
                    "required_columns": ["id", "value", "rate"],
                    "joins": [
                        {
                            "source": "selected",
                            "on": {"id": "id"},
                            "columns": {"value": "rate"},
                            "cardinality": "m:1",
                        }
                    ],
                }
            ],
        },
        mapping_path=tmp_path / "mapping.json",
    )

    result = store.prepare_table("joined")

    assert result is not None
    assert result.collect().to_dicts() == [{"id": 1, "value": 7, "rate": 7}]


def test_first_present_source_caches_optional_absence_for_one_request(tmp_path) -> None:
    primary_path = tmp_path / "primary.csv"
    (tmp_path / "fallback_one.csv").write_text("id\n1\n")
    (tmp_path / "fallback_two.csv").write_text("id\n2\n")

    def read_and_create_primary(path):
        frame = pl.read_csv(path)
        primary_path.write_text("id\n7\n")
        return frame

    from r2x_core import DataFile, FileInfo, ReaderConfig

    store = DataStore(path=tmp_path)
    store.add_data(
        [
            DataFile(
                name="primary",
                fpath=primary_path,
                info=FileInfo(is_optional=True),
            ),
            DataFile(
                name="fallback_one",
                fpath=tmp_path / "fallback_one.csv",
                info=FileInfo(is_optional=True),
                reader=ReaderConfig(function=read_and_create_primary),
            ),
            DataFile(
                name="fallback_two",
                fpath=tmp_path / "fallback_two.csv",
                info=FileInfo(is_optional=True),
            ),
        ]
    )
    store.load_file_mapping(
        {
            "files": [],
            "sources": [
                {"kind": "first_present", "name": "first_source", "candidates": ["primary", "fallback_one"]},
                {"kind": "first_present", "name": "second_source", "candidates": ["primary", "fallback_two"]},
            ],
            "tables": [
                {
                    "name": "first_table",
                    "source": "first_source",
                    "frame_sources": ["first_source"],
                    "required_columns": ["id"],
                },
                {
                    "name": "second_table",
                    "source": "second_source",
                    "frame_sources": ["second_source"],
                    "required_columns": ["id"],
                },
            ],
        },
        mapping_path=tmp_path / "mapping.json",
    )

    results = store.prepare_tables(("first_table", "second_table"))

    assert primary_path.exists()
    assert results["first_table"].collect().to_dicts() == [{"id": 1}]
    assert results["second_table"].collect().to_dicts() == [{"id": 2}]


def test_first_present_source_does_not_fall_back_after_selected_source_fails(tmp_path) -> None:
    """A present but invalid candidate fails instead of reading its fallback."""
    (tmp_path / "primary.csv").write_bytes(b"id\n\xff")
    (tmp_path / "fallback.csv").write_text("id\n2\n")
    store = DataStore(path=tmp_path)
    store.load_file_mapping(
        {
            "files": [
                {"name": "primary", "relative_fpath": "primary.csv", "info": {"is_optional": True}},
                {"name": "fallback", "relative_fpath": "fallback.csv", "info": {"is_optional": True}},
            ],
            "sources": [{"kind": "first_present", "name": "selected", "candidates": ["primary", "fallback"]}],
            "tables": [],
        },
        mapping_path=tmp_path / "mapping.json",
    )

    with pytest.raises(PreparedTableError, match=r"selected.*primary"):
        store.read_data("selected")


def test_first_present_source_uses_reader_path_placeholder_resolution(tmp_path) -> None:
    (tmp_path / "primary_2032.csv").write_text("id\n7\n")
    (tmp_path / "fallback.csv").write_text("id\n99\n")
    store = DataStore(path=tmp_path)
    store.load_file_mapping(
        {
            "files": [
                {
                    "name": "primary",
                    "relative_fpath": "primary_{solve_year}.csv",
                    "info": {"is_optional": True},
                },
                {"name": "fallback", "relative_fpath": "fallback.csv", "info": {"is_optional": True}},
            ],
            "sources": [{"kind": "first_present", "name": "selected", "candidates": ["primary", "fallback"]}],
            "tables": [],
        },
        mapping_path=tmp_path / "mapping.json",
    )
    placeholders = {"solve_year": 2032}

    primary = store.read_data("primary", placeholders=placeholders)
    selected = store.read_data("selected", placeholders=placeholders)

    assert isinstance(primary, pl.LazyFrame)
    assert isinstance(selected, pl.DataFrame)
    assert primary.collect().to_dicts() == [{"id": 7}]
    assert selected.to_dicts() == [{"id": 7}]


def test_first_present_source_can_declare_no_source_as_none(tmp_path) -> None:
    store = DataStore(path=tmp_path)
    store.load_file_mapping(
        {
            "files": [{"name": "primary", "relative_fpath": "primary.csv", "info": {"is_optional": True}}],
            "sources": [
                {"kind": "first_present", "name": "selected", "candidates": ["primary"], "missing": "none"}
            ],
            "tables": [],
        },
        mapping_path=tmp_path / "mapping.json",
    )

    assert store.read_data("selected") is None
    assert store.is_optional("selected")


@pytest.mark.parametrize("reserved", ["name", "time_series_type"])
def test_time_series_projection_rejects_reserved_feature_names(reserved: str) -> None:
    with pytest.raises(ValueError, match="reserved key"):
        TimeSeriesProjection.model_validate({"name": "demand", "features": {reserved: 2032}})


def test_system_projection_includes_components_without_series() -> None:
    from fixtures.target_system import build_target_system

    system = build_target_system()
    context = PluginContext(config=SourceConfig(), target_system=system)
    source = SystemFrameSource.model_validate(
        {
            "kind": "system",
            "name": "nodes",
            "system": "target",
            "component_type": "NodeComponent",
            "fields": {
                "area": {"path": "area", "dtype": "string"},
                "demand": {"path": "demand_mw", "dtype": "float64"},
            },
        }
    )

    frame = source.to_frame(context=context)

    assert frame.to_dicts() == [{"owner_name": "node_a", "area": "north-zone", "demand": 140.0}]


def test_system_time_series_projection_uses_explicit_missing_policy() -> None:
    from fixtures.target_system import build_target_system

    system = build_target_system()
    node = next(system.get_components(NodeComponent))
    system.add_time_series(
        SingleTimeSeries.from_array(
            np.asarray([1.0, 2.5]),
            name="demand",
            initial_timestamp=datetime(2012, 1, 1),
            resolution=timedelta(hours=1),
        ),
        node,
        solve_year=2032,
    )
    context = PluginContext(config=SourceConfig(), target_system=system)
    source = SystemFrameSource.model_validate(
        {
            "kind": "system",
            "name": "node_profiles",
            "system": "target",
            "component_type": "NodeComponent",
            "fields": {"area": {"path": "area", "dtype": "string"}},
            "time_series": {"name": "demand", "features": {"solve_year": 2032}, "missing": "skip"},
        }
    )

    frame = source.to_frame(context=context)

    assert frame.to_dicts() == [
        {"owner_name": "node_a", "area": "north-zone", "hour_index": 0, "value": 1.0},
        {"owner_name": "node_a", "area": "north-zone", "hour_index": 1, "value": 2.5},
    ]


def test_store_resolves_declared_runtime_sources_in_prepared_tables(tmp_path) -> None:
    from fixtures.target_system import build_target_system

    store = DataStore(path=tmp_path)
    store.load_file_mapping(
        {
            "files": [],
            "sources": [
                {
                    "kind": "system",
                    "name": "nodes",
                    "system": "target",
                    "component_type": "NodeComponent",
                    "fields": {"area": {"path": "area", "dtype": "string"}},
                }
            ],
            "tables": [
                {
                    "name": "node_rows",
                    "source": "nodes",
                    "frame_sources": ["nodes"],
                    "required_columns": ["owner_name", "area"],
                }
            ],
        },
        mapping_path=tmp_path / "mapping.json",
    )
    context = PluginContext(config=SourceConfig(), target_system=build_target_system(), store=store)

    result = store.prepare_table("node_rows", context=context)

    assert result is not None
    assert result.collect().to_dicts() == [{"owner_name": "node_a", "area": "north-zone"}]


def test_system_projection_rejects_invalid_public_field_paths() -> None:
    from fixtures.target_system import build_target_system

    source = SystemFrameSource.model_validate(
        {
            "name": "nodes",
            "system": "target",
            "component_type": "NodeComponent",
            "fields": {"area": {"path": "are_typo", "dtype": "string"}},
        }
    )
    context = PluginContext(config=SourceConfig(), target_system=build_target_system())

    with pytest.raises(ValueError, match="are_typo"):
        source.to_frame(context=context)


def test_store_reads_calendar_sources_through_the_named_data_api(tmp_path) -> None:
    store = DataStore(path=tmp_path)
    store.load_file_mapping(
        {
            "files": [],
            "sources": [
                {
                    "kind": "calendar",
                    "name": "calendar",
                    "year": 2012,
                    "resolution_seconds": 3600,
                    "sample_limit": 2,
                }
            ],
            "tables": [],
        },
        mapping_path=tmp_path / "mapping.json",
    )

    data = store.read_data("calendar")

    assert "calendar" in store
    assert "calendar" in store.list_data()
    assert isinstance(data, pl.DataFrame)
    assert data["hour_index"].to_list() == [0, 1]


def test_system_time_series_projection_matches_typed_features() -> None:
    from fixtures.target_system import build_target_system

    system = build_target_system()
    node = next(system.get_components(NodeComponent))
    for solve_year, values in ((2032, [1.0, 2.0]), (2040, [8.0, 9.0])):
        system.add_time_series(
            SingleTimeSeries.from_array(
                np.asarray(values),
                name="demand",
                initial_timestamp=datetime(2012, 1, 1),
                resolution=timedelta(hours=1),
            ),
            node,
            solve_year=solve_year,
        )
    source = SystemFrameSource.model_validate(
        {
            "name": "node_profiles",
            "system": "target",
            "component_type": "NodeComponent",
            "time_series": {"name": "demand", "features": {"solve_year": 2032}},
        }
    )
    context = PluginContext(config=SourceConfig(), target_system=system)

    frame = source.to_frame(context=context)

    assert frame["value"].to_list() == [1.0, 2.0]


def test_store_resolves_typed_time_series_feature_placeholders(tmp_path) -> None:
    from fixtures.target_system import build_target_system

    system = build_target_system()
    node = next(system.get_components(NodeComponent))
    for solve_year, values in ((2032, [1.0, 2.0]), (2040, [8.0, 9.0])):
        system.add_time_series(
            SingleTimeSeries.from_array(
                np.asarray(values),
                name="demand",
                initial_timestamp=datetime(2012, 1, 1),
                resolution=timedelta(hours=1),
            ),
            node,
            solve_year=solve_year,
        )
    store = DataStore(path=tmp_path)
    store.load_file_mapping(
        {
            "files": [],
            "sources": [
                {
                    "kind": "system",
                    "name": "node_profiles",
                    "system": "target",
                    "component_type": "NodeComponent",
                    "time_series": {
                        "name": "demand",
                        "features": {"solve_year": "{solve_year}"},
                    },
                }
            ],
            "tables": [],
        },
        mapping_path=tmp_path / "mapping.json",
    )
    context = PluginContext(config=SourceConfig(), target_system=system, store=store)

    frame = store.read_data("node_profiles", placeholders={"solve_year": 2032}, context=context)

    assert isinstance(frame, pl.DataFrame)
    assert frame["value"].to_list() == [1.0, 2.0]


def test_system_projection_rejects_missing_requested_series() -> None:
    from fixtures.target_system import build_target_system

    source = SystemFrameSource(
        name="node_profiles",
        system="target",
        component_type="NodeComponent",
        time_series=TimeSeriesProjection(name="missing"),
    )
    context = PluginContext(config=SourceConfig(), target_system=build_target_system())

    with pytest.raises(ValueError, match="has no time series"):
        source.to_frame(context=context)
