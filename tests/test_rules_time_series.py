"""Public Rule execution for configured time-series targets."""

import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fixtures.target_system import NodeComponent, build_target_system
from infrasys import SingleTimeSeries
from rust_ok import Ok

from r2x_core import (
    DataFile,
    DataStore,
    PluginConfig,
    PluginContext,
    PreparedTable,
    RulePlan,
    TabularProcessing,
    apply_rules_to_context,
)


class TimeSeriesConfig(PluginConfig):
    """Resolve target component types for Rule execution."""

    models: tuple[str, ...] = ("fixtures.target_system",)


def _profile_context(tmp_path: Path, *, hour_indexes: tuple[int, ...] = (1, 0)) -> PluginContext:
    profile_path = tmp_path / "profiles.csv"
    with profile_path.open("w", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=["owner_name", "hour_index", "value", "timestamp", "solve_year"],
        )
        writer.writeheader()
        for solve_year, samples in ((2032, (10.0, 20.0, 25.0)), (2040, (30.0, 40.0, 45.0))):
            for hour in hour_indexes:
                writer.writerow(
                    {
                        "owner_name": "node_a",
                        "hour_index": hour,
                        "value": samples[hour],
                        "timestamp": f"2012-01-01T{hour:02}:00:00",
                        "solve_year": solve_year,
                    }
                )

    store = DataStore(path=tmp_path)
    store.add_data(
        [
            DataFile(
                name="profiles_csv",
                fpath=profile_path,
                proc_spec=TabularProcessing(
                    column_schema={
                        "hour_index": "int",
                        "value": "float",
                        "timestamp": "datetime",
                        "solve_year": "int",
                    }
                ),
            )
        ]
    )
    store.add_tables(
        [
            PreparedTable(
                name="profile_rows",
                source="profiles_csv",
                required_columns=["owner_name", "hour_index", "value", "timestamp", "solve_year"],
            )
        ]
    )
    system = build_target_system()
    return PluginContext(config=TimeSeriesConfig(), store=store, target_system=system)


def _profile_plan(context: PluginContext, *, expected_samples: int | None = 2) -> RulePlan:
    result = RulePlan.from_mapping(
        {
            "rules": [
                {
                    "name": "profile",
                    "source": {"kind": "dataset", "dataset": "profile_rows"},
                    "target": {
                        "kind": "time_series",
                        "name": "demand_profile",
                        "owner_type": "NodeComponent",
                        "owner_field": "owner_name",
                        "hour_column": "hour_index",
                        "value_column": "value",
                        "initial_timestamp_column": "timestamp",
                        "resolution_seconds": 3600,
                        "metadata_columns": {"solve_year": "solve_year"},
                        "expected_samples": expected_samples,
                    },
                }
            ],
            "execution": [{"name": "profiles", "rules": ["profile"]}],
            "required_rules": ["profile"],
            "required_stages": ["profiles"],
            "required_datasets": ["profile_rows"],
        },
        context=context,
    )
    assert isinstance(result, Ok), result.err()
    return result.ok()


def test_time_series_rule_sorts_groups_and_preserves_typed_metadata(tmp_path: Path) -> None:
    context = _profile_context(tmp_path)
    plan = _profile_plan(context)

    result = apply_rules_to_context(context, on_error="stop", plan=plan, stage="profiles")

    assert result.success
    assert result.total_converted == 2
    system = context.target_system
    assert system is not None
    node = system.get_component(NodeComponent, "node_a")
    first = system.get_time_series(node, name="demand_profile", solve_year=2032)
    second = system.get_time_series(node, name="demand_profile", solve_year=2040)
    assert first.data_array.tolist() == [10.0, 20.0]
    assert second.data_array.tolist() == [30.0, 40.0]
    assert first.initial_timestamp == datetime(2012, 1, 1)


def test_time_series_rule_rejects_gapped_hours_before_attachment(tmp_path: Path) -> None:
    context = _profile_context(tmp_path, hour_indexes=(0, 2))
    plan = _profile_plan(context)

    result = apply_rules_to_context(context, on_error="stop", plan=plan, stage="profiles")

    assert not result.success
    assert "unique and contiguous from zero" in str(result.rule_results[0].error)
    system = context.target_system
    assert system is not None
    node = system.get_component(NodeComponent, "node_a")
    assert not system.has_time_series(node)


def test_time_series_rule_reports_single_sample_construction_failure(tmp_path: Path) -> None:
    context = _profile_context(tmp_path, hour_indexes=(0,))
    plan = _profile_plan(context, expected_samples=None)

    result = apply_rules_to_context(context, on_error="stop", plan=plan, stage="profiles")

    assert not result.success
    assert "Could not construct time series" in str(result.rule_results[0].error)
    system = context.target_system
    assert system is not None
    node = system.get_component(NodeComponent, "node_a")
    assert not system.has_time_series(node)


def test_time_series_rule_prevalidates_existing_feature_conflicts(tmp_path: Path) -> None:
    context = _profile_context(tmp_path)
    system = context.target_system
    assert system is not None
    node = system.get_component(NodeComponent, "node_a")
    system.add_time_series(
        SingleTimeSeries.from_array(
            np.asarray([30.0, 40.0]),
            name="demand_profile",
            initial_timestamp=datetime(2012, 1, 1),
            resolution=timedelta(hours=1),
        ),
        node,
        solve_year=2040,
    )
    plan = _profile_plan(context)

    result = apply_rules_to_context(context, on_error="stop", plan=plan, stage="profiles")

    assert not result.success
    assert result.rule_results[0].converted == 0
    assert "already has time series" in str(result.rule_results[0].error)
    assert not system.has_time_series(node, name="demand_profile", solve_year=2032)
    existing = system.get_time_series(node, name="demand_profile", solve_year=2040)
    assert existing.data_array.tolist() == [30.0, 40.0]


@pytest.mark.parametrize("reserved", ["name", "time_series_type", "context"])
def test_time_series_target_rejects_reserved_metadata_keys(reserved: str) -> None:
    from r2x_core import TimeSeriesTarget

    with pytest.raises(ValueError, match="reserved key"):
        TimeSeriesTarget.model_validate(
            {
                "name": "demand_profile",
                "owner_type": "NodeComponent",
                "owner_field": "owner_name",
                "hour_column": "hour_index",
                "value_column": "value",
                "initial_timestamp": "2012-01-01T00:00:00",
                "resolution_seconds": 3600,
                "metadata_columns": {reserved: "solve_year"},
            }
        )


def test_time_series_target_rejects_non_dataset_rules() -> None:
    result = RulePlan.from_mapping(
        {
            "rules": [
                {
                    "name": "profile",
                    "source": {"kind": "component", "component_type": "NodeComponent"},
                    "target": {
                        "kind": "time_series",
                        "name": "profile",
                        "owner_type": "NodeComponent",
                        "owner_field": "owner_name",
                        "hour_column": "hour_index",
                        "value_column": "value",
                        "initial_timestamp": "2012-01-01T00:00:00",
                        "resolution_seconds": 3600,
                    },
                }
            ]
        },
        context=PluginContext(config=TimeSeriesConfig(), target_system=build_target_system()),
    )

    assert result.is_err()
    assert "requires a DatasetSource" in str(result.err())
