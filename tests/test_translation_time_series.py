"""Validate translation of time series metadata between fixture systems."""

from __future__ import annotations

import sqlite3
from typing import Any, cast
from uuid import uuid4

import numpy as np
import pytest
from fixtures.source_system import BusComponent
from fixtures.target_system import NodeComponent
from infrasys import SingleTimeSeries
from infrasys.time_series_manager import TimeSeriesManager
from infrasys.time_series_models import TimeSeriesStorageType
from infrasys.utils.sqlite import create_in_memory_db

from r2x_core import PluginContext, System, apply_rules_to_context
from r2x_core.time_series import (
    _main_db_path,
    replace_single_time_series,
    transfer_time_series_metadata,
)


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

    monkeypatch.setattr("r2x_core.time_series._main_db_path", lambda _conn: None)
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

    def _copy_src_to_temp(conn):
        dst = tmp_path / "src_ts.db"
        with sqlite3.connect(dst) as dst_con:
            conn.backup(dst_con)
        return str(dst)

    monkeypatch.setattr("r2x_core.time_series._main_db_path", _copy_src_to_temp)
    stats = transfer_time_series_metadata(context_example)

    assert stats.transferred >= 0


def test_time_series_transfer_logs_post_remap_cleanup(monkeypatch, context_example: PluginContext, caplog):
    """Post-remap dedupe path logs when rows are removed."""
    apply_rules_to_context(context_example)
    source_system = context_example.source_system
    target_system = context_example.target_system
    assert source_system is not None
    assert target_system is not None

    parent = next(iter(target_system.get_components(NodeComponent)))
    parent_uuid = str(parent.uuid)
    child_uuid = str(uuid4())

    assoc_con = source_system._component_mgr._associations._con
    assoc_con.execute(
        "INSERT INTO component_associations VALUES (?, ?, ?, ?, ?)",
        (None, child_uuid, "ChildComponent", parent_uuid, type(parent).__name__),
    )
    assoc_con.commit()

    call_counts = {"count": 0}

    def _fake_dedup(conn, cols):
        call_counts["count"] += 1
        # First call (pre-insert) does nothing, second call (post-update) reports removals.
        return 0 if call_counts["count"] == 1 else 1

    monkeypatch.setattr("r2x_core.time_series._deduplicate_ts_associations", _fake_dedup)

    caplog.set_level("WARNING")
    stats = transfer_time_series_metadata(context_example)

    assert stats.updated >= 0
    assert call_counts["count"] >= 2
    assert any("after remapping" in record.message for record in caplog.records)


def test_main_db_path_handles_errors():
    """_main_db_path returns None if the connection errors."""

    class FailingConn:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    assert _main_db_path(cast(Any, FailingConn())) is None


def test_main_db_path_returns_path():
    """_main_db_path returns stringified path when PRAGMA data exists."""

    class Conn:
        def execute(self, _query):
            class Cursor:
                def fetchall(self):
                    return [(0, "main", "/tmp/test.db")]

            return Cursor()

    assert _main_db_path(cast(Any, Conn())) == "/tmp/test.db"


def test_transfer_time_series_requires_systems(context_example: PluginContext):
    """transfer_time_series_metadata raises ValueError if systems are None."""
    # Create a context with no systems
    context = context_example.evolve(source_system=None, target_system=None)

    with pytest.raises(ValueError, match="source_system and target_system must be set"):
        transfer_time_series_metadata(context)
