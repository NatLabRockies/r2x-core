"""Opt-in benchmarks for representative r2x-core workflows.

Run with ``mise run bench`` to save results for local comparisons.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import numpy as np
import polars as pl
import pytest
from fixtures.ingestion_models import PSSEBus, PSSEGenerator
from fixtures.source_system import BusComponent
from fixtures.target_system import NodeComponent
from infrasys import Component, SingleTimeSeries
from pytest_benchmark.fixture import BenchmarkFixture

from r2x_core import (
    ArraySource,
    ComponentInstruction,
    ComponentOwner,
    ComponentReference,
    DataFile,
    DataReader,
    DecodedSources,
    PluginConfig,
    PluginContext,
    ReaderConfig,
    RegularTimeAxis,
    Rule,
    System,
    TabularProcessing,
    TimeSeriesInstruction,
    apply_rules_to_context,
    assemble_tables,
    build_system,
    build_system_from_sources,
    export_components_to_csv,
)
from r2x_core.file_reader import TabularSource
from r2x_core.models import AggregateStep, FilterStep
from r2x_core.polars_adapter import PolarsTabularBackend
from r2x_core.result import TranslationResult
from r2x_core.types import AggregationFunction
from r2x_core.units import HasPerUnit, Unit

CSV_ROW_COUNT = 25_000
COMPONENT_COUNT = 1_000
TIME_SERIES_OWNER_COUNT = 10
SAMPLES_PER_PROFILE = 8_760


class BenchUnitComponent(HasPerUnit, Component):
    """Exercise per-unit conversion through component validation."""

    base_power: Annotated[float, Unit("MVA")]
    power: Annotated[float, Unit("pu", base="base_power")]


@pytest.fixture
def dispatch_csv(tmp_path: Path) -> Path:
    """Write deterministic dispatch data for a read, filter, and aggregate pipeline."""
    path = tmp_path / "dispatch.csv"
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(("zone", "output_mw", "in_service"))
        writer.writerows((f"zone-{row % 16}", row, int(row % 5 != 0)) for row in range(CSV_ROW_COUNT))
    return path


@pytest.mark.readers
@pytest.mark.processing
@pytest.mark.polars
@pytest.mark.bench
def test_bench_csv_read_filter_and_aggregate(benchmark: BenchmarkFixture, dispatch_csv: Path) -> None:
    """Measure full CSV decoding and Polars filtering/grouped aggregation."""
    data_file = DataFile(
        name="dispatch",
        relative_fpath=dispatch_csv.name,
        reader=ReaderConfig(format="csv"),
        proc_spec=TabularProcessing(
            steps=[
                FilterStep(op="filter", predicate={"eq": ["in_service", 1]}),
                AggregateStep(
                    op="aggregate",
                    group_by=["zone"],
                    aggregate_on={"output_mw": AggregationFunction.SUM},
                ),
            ]
        ),
    )
    reader = DataReader()

    def read_and_aggregate() -> list[Mapping[str, object]]:
        sources = reader.read_data_files((data_file,), folder_path=dispatch_csv.parent)
        return list(sources["dispatch"].iter_rows())

    rows = benchmark(read_and_aggregate)

    expected = {
        f"zone-{zone}": sum(row for row in range(CSV_ROW_COUNT) if row % 16 == zone and row % 5 != 0)
        for zone in range(16)
    }
    actual = {str(row["zone"]): int(row["output_mw"]) for row in rows}
    assert actual == expected


@pytest.mark.readers
@pytest.mark.ingestion
@pytest.mark.bench
def test_bench_csv_to_system_build(benchmark: BenchmarkFixture, tmp_path: Path) -> None:
    """Measure the configured CSV-to-System path for buses and generators."""
    config_path = tmp_path / "config"
    input_path = tmp_path / "inputs"
    config_path.mkdir()
    input_path.mkdir()

    with (input_path / "buses.csv").open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(("name", "number", "base_kv"))
        writer.writerows((f"bus-{index}", index, 230.0) for index in range(COMPONENT_COUNT))
    with (input_path / "generators.csv").open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(("name", "bus_name", "active_power_mw", "available"))
        writer.writerows(
            (f"generator-{index}", f"bus-{index}", float(index % 500), index % 2 == 0)
            for index in range(COMPONENT_COUNT)
        )
    (config_path / "file_mapping.json").write_text(
        json.dumps(
            [
                {"name": "buses", "relative_fpath": "buses.csv", "reader": {"format": "csv"}},
                {
                    "name": "generators",
                    "relative_fpath": "generators.csv",
                    "reader": {"format": "csv"},
                },
            ]
        ),
        encoding="utf-8",
    )
    (config_path / "parser_rules.json").write_text(
        json.dumps(
            [
                {
                    "kind": "component",
                    "source": "buses",
                    "component_type": "PSSEBus",
                    "fields": {"name": "name", "number": "number", "base_kv": "base_kv"},
                },
                {
                    "kind": "component",
                    "source": "generators",
                    "component_type": "PSSEGenerator",
                    "fields": {
                        "name": "name",
                        "active_power_mw": "active_power_mw",
                        "available": "available",
                    },
                    "references": {"bus": {"component_type": "PSSEBus", "name_field": "bus_name"}},
                },
            ]
        ),
        encoding="utf-8",
    )
    config = PluginConfig(
        models=("fixtures.ingestion_models",),
        config_path_override=config_path,
    )
    system = benchmark(
        build_system,
        config,
        name="bench-full-ingestion",
        input_folder=input_path,
    )

    buses = list(system.get_components(PSSEBus))
    generators = list(system.get_components(PSSEGenerator))
    assert len(buses) == COMPONENT_COUNT
    assert len(generators) == COMPONENT_COUNT
    assert generators[0].bus.name == "bus-0"


@pytest.mark.units
@pytest.mark.bench
def test_bench_unit_aware_component_validation(benchmark: BenchmarkFixture) -> None:
    """Measure natural-unit conversion while validating 1,000 components."""

    def build_components() -> list[BenchUnitComponent]:
        return [
            BenchUnitComponent(
                name=f"generator-{index}",
                base_power=100.0,
                power={"value": float(index), "unit": "MW"},
            )
            for index in range(COMPONENT_COUNT)
        ]

    components = benchmark(build_components)

    assert len(components) == COMPONENT_COUNT
    assert components[1].power == pytest.approx(0.01)
    assert components[-1].power == pytest.approx((COMPONENT_COUNT - 1) / 100)


@pytest.fixture
def component_sources() -> dict[str, TabularSource[pl.LazyFrame]]:
    """Prepare deterministic tabular sources for component construction."""
    backend = PolarsTabularBackend()
    names = [f"bus-{index}" for index in range(COMPONENT_COUNT)]
    buses = pl.DataFrame(
        {
            "name": names,
            "number": list(range(COMPONENT_COUNT)),
            "base_kv": [230.0] * COMPONENT_COUNT,
        }
    )
    generators = pl.DataFrame(
        {
            "name": [f"generator-{index}" for index in range(COMPONENT_COUNT)],
            "bus_name": names,
            "active_power_mw": [float(index % 500) for index in range(COMPONENT_COUNT)],
            "available": [index % 2 == 0 for index in range(COMPONENT_COUNT)],
        }
    )
    return {
        "buses": TabularSource(buses.lazy(), backend),
        "generators": TabularSource(generators.lazy(), backend),
    }


@pytest.fixture
def table_mapping_sources(
    component_sources: dict[str, TabularSource[pl.LazyFrame]],
) -> DecodedSources:
    """Prepare reserve factors to join with the generator table."""
    names = [f"bus-{index}" for index in range(COMPONENT_COUNT)]
    factors = pl.DataFrame(
        {
            "bus_name": names,
            "fraction": [0.1 + (index % 5) * 0.01 for index in range(COMPONENT_COUNT)],
        }
    )
    return {
        "generators": component_sources["generators"],
        "reserve_factors": TabularSource(factors.lazy(), PolarsTabularBackend()),
    }


@pytest.fixture
def table_mapping_file(tmp_path: Path) -> Path:
    """Write one join, multiply, and projection mapping."""
    path = tmp_path / "table-mapping.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "reserve_requirements",
                    "source": "generators",
                    "operations": [
                        {
                            "operation": "join",
                            "source": "reserve_factors",
                            "how": "inner",
                            "on": ["bus_name"],
                            "columns": ["fraction"],
                        },
                        {
                            "operation": "multiply",
                            "columns": ["active_power_mw", "fraction"],
                            "output": "reserve_mw",
                        },
                    ],
                    "columns": {
                        "name": "name",
                        "bus_name": "bus_name",
                        "reserve_mw": "reserve_mw",
                        "available": "available",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.processing
@pytest.mark.table_mapping
@pytest.mark.polars
@pytest.mark.bench
def test_bench_table_mapping_join_and_projection(
    benchmark: BenchmarkFixture,
    table_mapping_sources: DecodedSources,
    table_mapping_file: Path,
) -> None:
    """Measure mapping validation, a 1,000-row join, multiplication, and projection."""
    backend = PolarsTabularBackend()

    def assemble_reserve_table() -> list[Mapping[str, object]]:
        tables = assemble_tables(table_mapping_sources, mapping_path=table_mapping_file, backend=backend)
        return list(tables["reserve_requirements"].iter_rows())

    rows = benchmark(assemble_reserve_table)
    by_name = {str(row["name"]): row for row in rows}

    assert len(rows) == COMPONENT_COUNT
    assert set(by_name["generator-1"]) == {"name", "bus_name", "reserve_mw", "available"}
    assert by_name["generator-1"]["reserve_mw"] == pytest.approx(0.11)


@pytest.fixture
def component_instructions() -> tuple[ComponentInstruction, ...]:
    """Map buses and generators, resolving each generator's bus reference."""
    return (
        ComponentInstruction(
            kind="component",
            source="buses",
            component_type="PSSEBus",
            fields={"number": "number", "base_kv": "base_kv"},
        ),
        ComponentInstruction(
            kind="component",
            source="generators",
            component_type="PSSEGenerator",
            fields={"active_power_mw": "active_power_mw", "available": "available"},
            references={"bus": ComponentReference(component_type="PSSEBus", name_field="bus_name")},
        ),
    )


@pytest.mark.ingestion
@pytest.mark.bench
def test_bench_build_system_from_tabular_sources(
    benchmark: BenchmarkFixture,
    component_sources: dict[str, TabularSource[pl.LazyFrame]],
    component_instructions: tuple[ComponentInstruction, ...],
) -> None:
    """Measure typed construction and reference resolution for 2,000 components."""
    config = PluginConfig(models=("fixtures.ingestion_models",))
    system = benchmark(
        build_system_from_sources,
        component_sources,
        config=config,
        instructions=component_instructions,
        name="bench-ingestion",
    )

    buses = list(system.get_components(PSSEBus))
    generators = list(system.get_components(PSSEGenerator))
    assert len(buses) == COMPONENT_COUNT
    assert len(generators) == COMPONENT_COUNT
    assert generators[0].bus.name == "bus-0"


@pytest.mark.ingestion
@pytest.mark.time_series
@pytest.mark.bench
def test_bench_annual_time_series_attachment(benchmark: BenchmarkFixture) -> None:
    """Measure attaching one annual profile to ten typed bus owners."""
    bus_names = [f"BUS-{index}" for index in range(TIME_SERIES_OWNER_COUNT)]
    bus_frame = pl.DataFrame(
        {
            "name": bus_names,
            "number": list(range(TIME_SERIES_OWNER_COUNT)),
            "base_kv": [230.0] * TIME_SERIES_OWNER_COUNT,
        }
    )
    sources: DecodedSources = {
        "buses": TabularSource(bus_frame.lazy(), PolarsTabularBackend()),
        "loads": ArraySource({"load": np.arange(SAMPLES_PER_PROFILE, dtype=np.float64)}, None),
    }
    instructions = (
        ComponentInstruction(
            kind="component",
            source="buses",
            component_type="PSSEBus",
            fields={"name": "name", "number": "number", "base_kv": "base_kv"},
        ),
        TimeSeriesInstruction(
            kind="time_series",
            source="loads",
            name="load",
            values="load",
            time_axis=RegularTimeAxis(
                kind="regular",
                initial_timestamp=datetime(2024, 1, 1),
                resolution_seconds=3600,
            ),
            owners=[ComponentOwner(component_type="PSSEBus", names=bus_names)],
        ),
    )
    system = benchmark(
        build_system_from_sources,
        sources,
        config=PluginConfig(models=("fixtures.ingestion_models",)),
        instructions=instructions,
        name="bench-time-series",
    )

    owners = list(system.get_components(PSSEBus))
    assert len(owners) == TIME_SERIES_OWNER_COUNT
    assert all(
        system.get_time_series(owner, name="load").data_array.size == SAMPLES_PER_PROFILE for owner in owners
    )


@pytest.fixture
def source_bus_system() -> System:
    """Prepare a source system with many components for rule translation."""
    system = System(name="bench-source")
    system.add_components(
        *(
            BusComponent(
                name=f"bus-{index}",
                uuid=uuid4(),
                voltage_kv=230.0,
                load_mw=float(index),
                zone=f"zone-{index % 16}",
            )
            for index in range(COMPONENT_COUNT)
        )
    )
    return system


@pytest.mark.rules
@pytest.mark.bench
def test_bench_rule_translation(benchmark: BenchmarkFixture, source_bus_system: System) -> None:
    """Measure translating 1,000 source buses into target nodes."""
    config = PluginConfig(models=("fixtures.source_system", "fixtures.target_system"))
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={
            "name": "name",
            "uuid": "uuid",
            "kv_rating": "voltage_kv",
            "demand_mw": "load_mw",
            "area": "zone",
        },
    )
    latest_result: TranslationResult | None = None
    latest_target: System | None = None

    def prepare_context() -> tuple[tuple[PluginContext], dict[str, object]]:
        context = PluginContext(
            config=config,
            source_system=source_bus_system,
            target_system=System(name="bench-target"),
            rules=(rule,),
            store=None,
        )
        return (context,), {}

    def translate(context: PluginContext) -> None:
        nonlocal latest_result, latest_target
        latest_result = apply_rules_to_context(context)
        latest_target = context.target_system

    benchmark.pedantic(translate, setup=prepare_context, rounds=10, iterations=1)

    assert latest_result is not None
    assert latest_result.success
    assert latest_result.total_converted == COMPONENT_COUNT
    assert latest_target is not None
    assert len(list(latest_target.get_components(NodeComponent))) == COMPONENT_COUNT
    assert len(list(source_bus_system.get_components(BusComponent))) == COMPONENT_COUNT


@pytest.mark.system
@pytest.mark.bench
def test_bench_component_csv_export(
    benchmark: BenchmarkFixture, source_bus_system: System, tmp_path: Path
) -> None:
    """Measure writing a 1,000-component target CSV."""
    output_path = tmp_path / "components.csv"
    benchmark(export_components_to_csv, source_bus_system, file_path=output_path)

    with output_path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert len(rows) == COMPONENT_COUNT
    assert {row["name"] for row in rows} == {f"bus-{index}" for index in range(COMPONENT_COUNT)}


@pytest.mark.system
@pytest.mark.time_series
@pytest.mark.bench
def test_bench_system_serialization(
    benchmark: BenchmarkFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Measure JSON and time-series database serialization without touching user cache."""
    monkeypatch.setenv("HOME", str(tmp_path))
    latest_json: bytes | None = None

    def prepare_system() -> tuple[tuple[System], dict[str, object]]:
        system = System(name="bench-serialization")
        components = [Component(name=f"component-{index}") for index in range(COMPONENT_COUNT)]
        system.add_components(*components)
        series = SingleTimeSeries.from_array(
            data=np.arange(SAMPLES_PER_PROFILE, dtype=np.float64),
            name="load",
            initial_timestamp=datetime(2024, 1, 1),
            resolution=timedelta(hours=1),
        )
        system.add_time_series(series, components[0])
        return (system,), {}

    def serialize_system(system: System) -> None:
        nonlocal latest_json
        latest_json = system.to_json_bytes()

    benchmark.pedantic(serialize_system, setup=prepare_system, rounds=5, iterations=1)

    assert latest_json is not None
    restored = System.from_json(latest_json)
    components = list(restored.get_components(Component))
    assert len(components) == COMPONENT_COUNT
    assert restored.has_time_series(components[0])
    assert restored.get_time_series(components[0], name="load").data_array.size == SAMPLES_PER_PROFILE
