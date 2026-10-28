"""Validate translation of time series metadata between fixture systems."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fixtures.source_system import BusComponent
from fixtures.target_system import NodeComponent
from infrasys import Component, SingleTimeSeries, component_associations
from infrasys.time_series_manager import TimeSeriesManager
from infrasys.time_series_models import TimeSeriesStorageType
from infrasys.utils.sqlite import create_in_memory_db

from r2x_core import PluginConfig, PluginContext, Rule, System, apply_rules_to_context
from r2x_core.time_series import (
    main_database_path,
    replace_single_time_series,
    transfer_time_series_metadata,
)


class ConnectedBusComponent(Component):
    bus: BusComponent


pytestmark = pytest.mark.time_series


@pytest.mark.parametrize("component_count", [0, 1, 33_000])
@pytest.mark.parametrize("with_time_series", [False, True])
def test_rules_translate_components_beyond_sql_variable_limit(
    component_count: int, with_time_series: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def create_variable_limited_db(database: str = ":memory:") -> sqlite3.Connection:
        connection = create_in_memory_db(database)
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 32_766)
        return connection

    monkeypatch.setattr(component_associations, "create_in_memory_db", create_variable_limited_db)
    source = System(name="source")
    source.add_components(*(BusComponent(name=f"bus_{index}") for index in range(component_count)))
    if with_time_series and component_count:
        profile = SingleTimeSeries.from_array(
            data=np.array([100.0, 110.0]),
            name="load_profile",
            initial_timestamp=datetime(2024, 1, 1),
            resolution=timedelta(hours=1),
        )
        source.add_time_series(profile, source.get_component(BusComponent, "bus_0"))
    target = System(name="target")
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    result = apply_rules_to_context(context)

    assert len(list(target.get_components(NodeComponent))) == component_count
    assert {component.uuid for component in target.iter_all_components()} == {
        component.uuid for component in source.iter_all_components()
    }
    assert result.total_converted == component_count
    assert result.failed_rules == 0
    assert result.time_series_transferred == int(with_time_series and component_count > 0)
    if with_time_series and component_count:
        node = target.get_component(NodeComponent, "bus_0")
        metadata = target.list_time_series_metadata(node, name="load_profile")
        assert len(metadata) == 1
        assert metadata[0].time_series_uuid == profile.uuid


def test_time_series_transfer_maps_only_associations_of_target_components(
    context_example: PluginContext,
) -> None:
    source = context_example.source_system
    target = context_example.target_system
    assert source is not None
    assert target is not None
    bus = source.get_component(BusComponent, "bus_a")
    unrelated_bus = BusComponent(name="untranslated")
    connected = ConnectedBusComponent(name="connected", bus=bus)
    unrelated = ConnectedBusComponent(name="unrelated", bus=unrelated_bus)
    source.add_components(unrelated_bus, connected, unrelated)
    target.add_component(NodeComponent(name=bus.name, uuid=bus.uuid))

    result = transfer_time_series_metadata(context_example)

    assert result.children_remapped == 1
    assert result.transferred == 1
    assert source.list_parent_components(bus) == [connected]
    assert source.list_parent_components(unrelated_bus) == [unrelated]
    assert target.has_time_series(target.get_component(NodeComponent, bus.name))
    assert transfer_time_series_metadata(context_example).transferred == 0


def test_time_series_transfer_via_fixture_context(context_example: PluginContext):
    """Translation applies fixture rules and transfers time series metadata."""
    result = apply_rules_to_context(context_example)

    assert result.time_series_transferred > 0

    target_system = context_example.target_system
    assert target_system is not None
    node_components = list(target_system.get_components(NodeComponent))
    assert node_components, "Expected translated NodeComponent instances"

    nodes_with_ts = [node for node in node_components if target_system.has_time_series(node)]
    assert nodes_with_ts, "No NodeComponent received time series metadata"

    for node in nodes_with_ts:
        keys = target_system.list_time_series_keys(node)
        assert keys


def test_replace_single_time_series_preserves_shared_source_data(context_example: PluginContext):
    """Replacing a target association preserves shared source data."""
    source_system = context_example.source_system
    assert source_system is not None
    source_bus = source_system.get_component(BusComponent, "bus_a")
    original = source_system.get_time_series(source_bus, name="load_profile")
    manager = TimeSeriesManager(
        create_in_memory_db(),
        time_series_directory=source_system.get_time_series_directory(),
        time_series_storage_type=TimeSeriesStorageType.ARROW,
        permanent=True,
    )
    target_system = System(name="TargetFixture", time_series_manager=manager)
    target_bus = source_bus.model_copy(deep=True)
    target_system.add_component(target_bus)
    context = context_example.evolve(target_system=target_system)
    transfer_time_series_metadata(context)
    replacement = SingleTimeSeries.from_array(
        data=original.data_array / 100.0,
        name=original.name,
        initial_timestamp=original.initial_timestamp,
        resolution=original.resolution,
    )

    replace_single_time_series(target_system, target_bus, replacement)

    replaced = target_system.get_time_series(target_bus, name="load_profile")
    preserved = source_system.get_time_series(source_bus, name="load_profile")
    np.testing.assert_allclose(replaced.data_array, replacement.data_array)
    np.testing.assert_allclose(preserved.data_array, original.data_array)
    assert replaced.uuid == replacement.uuid
    assert preserved.uuid == original.uuid


def test_replace_single_time_series_requires_one_match(context_example: PluginContext):
    """Replacement requires one matching association."""
    source_system = context_example.source_system
    assert source_system is not None
    source_bus = source_system.get_component(BusComponent, "bus_a")
    original = source_system.get_time_series(source_bus, name="load_profile")
    replacement = SingleTimeSeries.from_array(
        data=original.data_array,
        name="missing_profile",
        initial_timestamp=original.initial_timestamp,
        resolution=original.resolution,
    )

    with pytest.raises(ValueError, match="found 0"):
        replace_single_time_series(source_system, source_bus, replacement)


def test_replace_single_time_series_restores_association_on_storage_failure(
    context_example: PluginContext, tmp_path
):
    """A storage failure restores the existing association."""
    source_system = context_example.source_system
    assert source_system is not None
    source_bus = source_system.get_component(BusComponent, "bus_a")
    original = source_system.get_time_series(source_bus, name="load_profile")
    replacement = SingleTimeSeries.from_array(
        data=original.data_array / 100.0,
        name=original.name,
        initial_timestamp=original.initial_timestamp,
        resolution=original.resolution,
    )
    storage_directory = source_system.get_time_series_directory()
    assert storage_directory is not None
    unavailable_directory = tmp_path / "unavailable"
    storage_directory.rename(unavailable_directory)

    try:
        with pytest.raises(OSError):
            replace_single_time_series(source_system, source_bus, replacement)
    finally:
        unavailable_directory.rename(storage_directory)

    restored = source_system.get_time_series(source_bus, name="load_profile")
    np.testing.assert_allclose(restored.data_array, original.data_array)
    assert restored.uuid == original.uuid


def test_time_series_transfer_is_idempotent(context_example: PluginContext):
    """Re-running metadata transfer does not duplicate associations."""
    first_result = apply_rules_to_context(context_example)
    target_system = context_example.target_system
    assert target_system is not None

    with target_system.open_time_series_store(mode="r") as store:
        initial_count = store.metadata_conn.execute(
            "SELECT COUNT(*) FROM time_series_associations"
        ).fetchone()[0]

    second_result = transfer_time_series_metadata(context_example)

    with target_system.open_time_series_store(mode="r") as store:
        final_count = store.metadata_conn.execute("SELECT COUNT(*) FROM time_series_associations").fetchone()[
            0
        ]

    assert first_result.time_series_transferred == initial_count
    assert second_result.transferred == 0
    assert final_count == initial_count


def test_time_series_transfer_deduplicates_rows(context_example: PluginContext, caplog):
    """Duplicate associations are removed and do not change totals."""
    apply_rules_to_context(context_example)
    target_system = context_example.target_system
    assert target_system is not None

    with target_system.open_time_series_store(mode="a") as store:
        conn = store.metadata_conn
        base_count = conn.execute("SELECT COUNT(*) FROM time_series_associations").fetchone()[0]
        conn.execute("DROP INDEX IF EXISTS idx_ts_owner_series_unique")
        conn.execute(
            """
            INSERT INTO time_series_associations (
                time_series_uuid, time_series_type, initial_timestamp, resolution, horizon,
                interval, window_count, length, name, owner_uuid, owner_type, owner_category,
                features, scaling_factor_multiplier, metadata_uuid, units
            )
            SELECT
                time_series_uuid, time_series_type, initial_timestamp, resolution || '_dup', horizon,
                interval, window_count, length, name, owner_uuid, owner_type, owner_category,
                features, scaling_factor_multiplier, metadata_uuid, units
            FROM time_series_associations
            LIMIT 1
            """
        )

    caplog.set_level("WARNING")
    stats = transfer_time_series_metadata(context_example)

    with target_system.open_time_series_store(mode="r") as store:
        final_count = store.metadata_conn.execute("SELECT COUNT(*) FROM time_series_associations").fetchone()[
            0
        ]

    assert stats.transferred == 0
    assert final_count == base_count
    assert any("duplicate time series association rows" in record.message for record in caplog.records)


def test_time_series_transfer_falls_back_without_db_path(monkeypatch, context_example: PluginContext):
    """When no DB path is available, transfer still succeeds via SELECT/INSERT path."""
    apply_rules_to_context(context_example)
    target_system = context_example.target_system
    assert target_system is not None

    with target_system.open_time_series_store(mode="r") as store:
        initial_count = store.metadata_conn.execute(
            "SELECT COUNT(*) FROM time_series_associations"
        ).fetchone()[0]

    monkeypatch.setattr("r2x_core.time_series.main_database_path", lambda conn: None)
    stats = transfer_time_series_metadata(context_example)

    with target_system.open_time_series_store(mode="r") as store:
        final_count = store.metadata_conn.execute("SELECT COUNT(*) FROM time_series_associations").fetchone()[
            0
        ]

    assert stats.transferred == 0
    assert stats.updated >= 0
    assert final_count == initial_count


def test_time_series_transfer_uses_attach_path(tmp_path, monkeypatch, context_example: PluginContext):
    """ATTACH-based bulk copy path is exercised when a DB path is available."""
    apply_rules_to_context(context_example)

    def copy_source_to_temp(conn):
        dst = tmp_path / "src_ts.db"
        with sqlite3.connect(dst) as dst_con:
            conn.backup(dst_con)
        return str(dst)

    monkeypatch.setattr("r2x_core.time_series.main_database_path", copy_source_to_temp)
    stats = transfer_time_series_metadata(context_example)

    assert stats.transferred >= 0


def test_time_series_transfer_logs_post_remap_cleanup(monkeypatch, context_example: PluginContext, caplog):
    """Post-remap dedupe path logs when rows are removed."""
    apply_rules_to_context(context_example)
    source_system = context_example.source_system
    target_system = context_example.target_system
    assert source_system is not None
    assert target_system is not None

    source_bus = source_system.get_component(BusComponent, "bus_a")
    source_system.add_component(ConnectedBusComponent(name="connected", bus=source_bus))

    call_counts = {"count": 0}

    def fake_dedup(conn, cols):
        call_counts["count"] += 1
        # First call (pre-insert) does nothing, second call (post-update) reports removals.
        return 0 if call_counts["count"] == 1 else 1

    monkeypatch.setattr("r2x_core.time_series.deduplicate_time_series_associations", fake_dedup)

    caplog.set_level("WARNING")
    stats = transfer_time_series_metadata(context_example)

    assert stats.updated >= 0
    assert call_counts["count"] >= 2
    assert any("after remapping" in record.message for record in caplog.records)


def test_main_database_path_propagates_closed_connection_error() -> None:
    conn = sqlite3.connect(":memory:")
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        main_database_path(conn)


def test_main_database_path_returns_none_for_memory_database() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        assert main_database_path(conn) is None
    finally:
        conn.close()


def test_main_database_path_returns_path(tmp_path: Path) -> None:
    path = tmp_path / "metadata.db"
    conn = sqlite3.connect(path)
    try:
        assert main_database_path(conn) == str(path)
    finally:
        conn.close()


def test_transfer_time_series_requires_systems(context_example: PluginContext):
    """transfer_time_series_metadata raises ValueError if systems are None."""
    # Create a context with no systems
    context = context_example.evolve(source_system=None, target_system=None)

    with pytest.raises(ValueError, match="source_system and target_system must be set"):
        transfer_time_series_metadata(context)
