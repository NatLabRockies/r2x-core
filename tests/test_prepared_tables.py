"""Tests for explicitly configured prepared tables."""

import json
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

from r2x_core import DataFile, DataStore, PreparedTable, ReaderConfig, TableJoin, prepare_table_frames
from r2x_core.prepared_tables import PreparedTableError


def write_mapping(folder: Path, *, files: list[dict[str, object]], tables: list[dict[str, object]]) -> Path:
    """Write a file-mapping envelope for a test data directory."""
    mapping_path = folder / "file_mapping.json"
    mapping_path.write_text(json.dumps({"files": files, "tables": tables}))
    return mapping_path


def test_prepared_table_explicit_cross_join_repeats_left_rows_in_order() -> None:
    table = PreparedTable(
        name="hydro_solve_year_rows",
        source="hydro_hours",
        frame_sources=["solve_years"],
        required_columns=["owner_name", "hour_index", "solve_year"],
        joins=[
            TableJoin(
                source="solve_years",
                columns={"year": "solve_year"},
                how="cross",
                cardinality="m:m",
            )
        ],
    )

    result = prepare_table_frames(
        table,
        {
            "hydro_hours": pl.DataFrame({"owner_name": ["hydro_a", "hydro_b"], "hour_index": [0, 1]}),
            "solve_years": pl.DataFrame({"year": [2032, 2040]}),
        },
    )

    assert result is not None
    assert result.collect().to_dicts() == [
        {"owner_name": "hydro_a", "hour_index": 0, "solve_year": 2032},
        {"owner_name": "hydro_a", "hour_index": 0, "solve_year": 2040},
        {"owner_name": "hydro_b", "hour_index": 1, "solve_year": 2032},
        {"owner_name": "hydro_b", "hour_index": 1, "solve_year": 2040},
    ]


def test_prepared_table_rejects_duplicate_declared_keys() -> None:
    table = PreparedTable(
        name="monthly_profiles",
        source="profiles",
        required_columns=["technology", "region", "solve_year", "month"],
        unique_keys=[["technology", "region", "solve_year", "month"]],
    )

    with pytest.raises(PreparedTableError, match="duplicate key rows"):
        prepare_table_frames(
            table,
            {
                "profiles": pl.DataFrame(
                    {
                        "technology": ["hyd-a", "hyd-a"],
                        "region": ["p1", "p1"],
                        "solve_year": [2032, 2032],
                        "month": [1, 1],
                    }
                )
            },
        )


def test_prepared_table_semijoin_filters_without_adding_payload_columns() -> None:
    table = PreparedTable(
        name="complete_adjustments",
        source="adjustments",
        frame_sources=["complete_groups"],
        required_columns=["technology", "month", "capacity_adjustment"],
        joins=[
            TableJoin(
                source="complete_groups",
                on={"technology": "technology"},
                columns={},
                how="semi",
                cardinality="m:1",
            )
        ],
    )

    result = prepare_table_frames(
        table,
        {
            "adjustments": pl.DataFrame(
                {
                    "technology": ["hyd-a", "hyd-b", "hyd-a"],
                    "month": [1, 1, 2],
                    "capacity_adjustment": [0.9, 0.8, 0.7],
                }
            ),
            "complete_groups": pl.DataFrame({"technology": ["hyd-a"]}),
        },
    )

    assert result is not None
    frame = result.collect()
    assert frame.columns == ["technology", "month", "capacity_adjustment"]
    assert frame.to_dicts() == [
        {"technology": "hyd-a", "month": 1, "capacity_adjustment": 0.9},
        {"technology": "hyd-a", "month": 2, "capacity_adjustment": 0.7},
    ]


def test_prepared_table_dependencies_compose_and_snapshot_shared_sources(tmp_path: Path) -> None:
    base_path = tmp_path / "base.csv"
    rates_path = tmp_path / "rates.csv"
    base_path.touch()
    rates_path.touch()
    reads = {"base": 0, "rates": 0}

    def read_base(path: Path, **kwargs: object) -> pl.LazyFrame:
        reads["base"] += 1
        return pl.DataFrame({"id": [1, 2], "value": [10.0, 20.0]}).lazy()

    def read_rates(path: Path, **kwargs: object) -> pl.LazyFrame:
        reads["rates"] += 1
        return pl.DataFrame({"id": [1, 2], "rate": [0.1, 0.2]}).lazy()

    store = DataStore(path=tmp_path)
    store.add_data(
        [
            DataFile(name="base", fpath=base_path, reader=ReaderConfig(function=read_base)),
            DataFile(name="rates", fpath=rates_path, reader=ReaderConfig(function=read_rates)),
        ]
    )
    store.add_tables(
        [
            PreparedTable(name="base_rows", source="base", required_columns=["id", "value"]),
            PreparedTable(name="rate_rows", source="rates", required_columns=["id", "rate"]),
            PreparedTable(
                name="left_branch",
                source="base_rows",
                required_columns=["id", "value", "rate"],
                joins=[TableJoin(source="rate_rows", on={"id": "id"}, columns={"rate": "rate"})],
            ),
            PreparedTable(
                name="right_branch",
                source="base_rows",
                required_columns=["id", "value", "right_rate"],
                joins=[TableJoin(source="rate_rows", on={"id": "id"}, columns={"rate": "right_rate"})],
            ),
            PreparedTable(
                name="joined_generator_rows",
                source="left_branch",
                required_columns=["id", "value", "rate", "right_rate"],
                joins=[
                    TableJoin(source="right_branch", on={"id": "id"}, columns={"right_rate": "right_rate"})
                ],
            ),
        ]
    )

    first_result = store.read_table("joined_generator_rows")

    assert first_result is not None
    assert first_result.collect().to_dicts() == [
        {"id": 1, "value": 10.0, "rate": 0.1, "right_rate": 0.1},
        {"id": 2, "value": 20.0, "rate": 0.2, "right_rate": 0.2},
    ]
    assert reads == {"base": 1, "rates": 1}

    second_result = store.read_table("joined_generator_rows")

    assert second_result is not None
    assert second_result.collect().height == 2
    assert reads == {"base": 2, "rates": 2}


def test_prepare_tables_shares_sources_across_output_roots(tmp_path: Path) -> None:
    base_path = tmp_path / "base.csv"
    rates_path = tmp_path / "rates.csv"
    base_path.touch()
    rates_path.touch()
    reads = {"base": 0, "rates": 0}

    def read_base(path: Path, **kwargs: object) -> pl.LazyFrame:
        reads["base"] += 1
        return pl.DataFrame({"id": [1]}).lazy()

    def read_rates(path: Path, **kwargs: object) -> pl.LazyFrame:
        reads["rates"] += 1
        return pl.DataFrame({"id": [1], "rate": [0.5]}).lazy()

    store = DataStore(path=tmp_path)
    store.add_data(
        [
            DataFile(name="base", fpath=base_path, reader=ReaderConfig(function=read_base)),
            DataFile(name="rates", fpath=rates_path, reader=ReaderConfig(function=read_rates)),
        ]
    )
    store.add_tables(
        [
            PreparedTable(name="base_rows", source="base", required_columns=["id"]),
            PreparedTable(name="rate_rows", source="rates", required_columns=["id", "rate"]),
            PreparedTable(
                name="left_result",
                source="base_rows",
                required_columns=["id", "left_rate"],
                joins=[TableJoin(source="rate_rows", on={"id": "id"}, columns={"rate": "left_rate"})],
            ),
            PreparedTable(
                name="right_result",
                source="base_rows",
                required_columns=["id", "right_rate"],
                joins=[TableJoin(source="rate_rows", on={"id": "id"}, columns={"rate": "right_rate"})],
            ),
        ]
    )

    results = store.prepare_tables(("left_result", "right_result"))

    assert results["left_result"] is not None
    assert results["right_result"] is not None
    assert results["left_result"].collect().get_column("left_rate").to_list() == [0.5]
    assert results["right_result"].collect().get_column("right_rate").to_list() == [0.5]
    assert reads == {"base": 1, "rates": 1}


def test_prepared_table_dependencies_use_fresh_parameterized_sources_per_call(tmp_path: Path) -> None:
    (tmp_path / "base.csv").write_text("id\n1\n")
    (tmp_path / "rates_2030.csv").write_text("id,rate\n1,0.2\n")
    (tmp_path / "rates_2031.csv").write_text("id,rate\n1,0.3\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {"name": "base", "fpath": "base.csv"},
            {"name": "rates", "fpath": "rates_{year}.csv"},
        ],
        tables=[
            {
                "name": "base_rows",
                "source": "base",
                "required_columns": ["id"],
            },
            {
                "name": "rate_rows",
                "source": "rates",
                "required_columns": ["id", "rate"],
            },
            {
                "name": "policy",
                "source": "base_rows",
                "required_columns": ["id", "rate"],
                "joins": [{"source": "rate_rows", "on": {"id": "id"}, "columns": {"rate": "rate"}}],
            },
        ],
    )
    store = DataStore.from_json(mapping_path)

    for year, expected in ((2030, 0.2), (2031, 0.3)):
        result = store.read_table("policy", placeholders={"year": year})
        assert result is not None
        assert result.collect().to_dicts() == [{"id": 1, "rate": expected}]


def test_prepared_table_dependencies_reject_unknown_names_and_cycles_before_read(tmp_path: Path) -> None:
    file_path = tmp_path / "source.csv"
    file_path.touch()
    reads = 0

    def read_source(path: Path, **kwargs: object) -> pl.LazyFrame:
        nonlocal reads
        reads += 1
        return pl.DataFrame({"id": [1]}).lazy()

    store = DataStore(path=tmp_path)
    store.add_data([DataFile(name="source", fpath=file_path, reader=ReaderConfig(function=read_source))])

    with pytest.raises(ValidationError, match="references unknown file, table, runtime, or frame source"):
        store.add_tables(
            [PreparedTable(name="unknown_root", source="not_registered", required_columns=["id"])]
        )
    with pytest.raises(ValueError, match=r"dependency cycle.*cycle_a.*cycle_b.*cycle_a"):
        store.add_tables(
            [
                PreparedTable(name="cycle_a", source="cycle_b", required_columns=["id"]),
                PreparedTable(name="cycle_b", source="cycle_a", required_columns=["id"]),
            ]
        )
    assert reads == 0


def test_removing_a_table_dependency_is_rejected_atomically() -> None:
    store = DataStore()
    store.add_tables(
        [
            PreparedTable(
                name="base_rows",
                source="base_input",
                frame_sources=["base_input"],
                required_columns=["id"],
            ),
            PreparedTable(
                name="rate_rows",
                source="rate_input",
                frame_sources=["rate_input"],
                required_columns=["id", "rate"],
            ),
            PreparedTable(
                name="final_rows",
                source="base_rows",
                required_columns=["id", "rate"],
                joins=[TableJoin(source="rate_rows", on={"id": "id"}, columns={"rate": "rate"})],
            ),
        ]
    )

    with pytest.raises(KeyError, match="referenced by remaining prepared table"):
        store.remove_table("base_rows")
    with pytest.raises(KeyError, match="referenced by remaining prepared table"):
        store.remove_table("rate_rows")

    assert store.list_tables() == ["base_rows", "final_rows", "rate_rows"]
    store.remove_table("base_rows", "final_rows", "rate_rows")
    assert store.list_tables() == []


def test_prepare_table_accepts_transitive_declared_frame_inputs() -> None:
    store = DataStore()
    store.add_tables(
        [
            PreparedTable(
                name="generator_rows",
                source="generator_input",
                frame_sources=["generator_input"],
                required_columns=["id", "technology"],
            ),
            PreparedTable(
                name="rates",
                source="rate_input",
                frame_sources=["rate_input"],
                required_columns=["technology", "rate"],
            ),
            PreparedTable(
                name="generator_policy",
                source="generator_rows",
                required_columns=["id", "technology", "rate"],
                joins=[TableJoin(source="rates", on={"technology": "technology"}, columns={"rate": "rate"})],
            ),
        ]
    )

    result = store.prepare_table(
        "generator_policy",
        inputs={
            "generator_input": pl.DataFrame({"id": [1], "technology": ["wind"]}),
            "rate_input": pl.DataFrame({"technology": ["wind"], "rate": [0.25]}),
        },
    )

    assert result is not None
    assert result.collect().to_dicts() == [{"id": 1, "technology": "wind", "rate": 0.25}]
    with pytest.raises(PreparedTableError, match="undeclared frame source"):
        store.prepare_table("generator_policy", inputs={"other": pl.DataFrame({"id": [1]})})

    ambiguous_store = DataStore()
    with pytest.raises(ValidationError, match=r"frame source name.*collide"):
        ambiguous_store.add_tables(
            [
                PreparedTable(
                    name="generator_rows",
                    source="raw_input",
                    frame_sources=["raw_input"],
                    required_columns=["id"],
                ),
                PreparedTable(name="raw_input", source="generator_rows", required_columns=["id"]),
            ]
        )


@pytest.mark.parametrize(
    ("broadcast", "singleton_rows"),
    [("right", 0), ("right", 2), ("left", 0), ("left", 2)],
)
def test_broadcast_requires_exact_singleton_even_when_other_side_is_empty(
    broadcast: str, singleton_rows: int
) -> None:
    store = DataStore()
    if broadcast == "right":
        table = PreparedTable(
            name="prepared",
            source="rows",
            frame_sources=["rows", "control"],
            required_columns=["id", "setting"],
            joins=[
                TableJoin(
                    source="control",
                    on={},
                    columns={"setting": "setting"},
                    broadcast="right",
                    cardinality="m:1",
                )
            ],
        )
        inputs = {
            "rows": pl.DataFrame({"id": pl.Series([], dtype=pl.Int64)}),
            "control": pl.DataFrame({"setting": pl.Series(range(singleton_rows), dtype=pl.Int64)}),
        }
    else:
        table = PreparedTable(
            name="prepared",
            source="control",
            frame_sources=["control", "rows"],
            required_columns=["setting", "rate"],
            joins=[
                TableJoin(
                    source="rows",
                    on={},
                    columns={"rate": "rate"},
                    how="left",
                    cardinality="1:m",
                    broadcast="left",
                )
            ],
        )
        inputs = {
            "control": pl.DataFrame({"setting": pl.Series(range(singleton_rows), dtype=pl.Int64)}),
            "rows": pl.DataFrame({"rate": pl.Series([], dtype=pl.Float64)}),
        }
    store.add_tables([table])

    with pytest.raises(PreparedTableError, match="exactly one row"):
        store.prepare_table("prepared", inputs=inputs)


def test_missing_optional_right_broadcast_adds_null_payload_but_empty_is_invalid(tmp_path: Path) -> None:
    """A missing optional control is distinct from a present empty singleton source."""
    (tmp_path / "rows.csv").write_text("id\n1\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {"name": "rows", "relative_fpath": "rows.csv"},
            {
                "name": "control",
                "relative_fpath": "control.csv",
                "info": {"is_optional": True},
            },
        ],
        tables=[
            {
                "name": "prepared",
                "source": "rows",
                "required_columns": ["id", "setting"],
                "joins": [
                    {
                        "source": "control",
                        "columns": {"setting": "setting"},
                        "broadcast": "right",
                        "cardinality": "m:1",
                        "missing_source": "null",
                    }
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)

    absent = store.read_data("prepared")

    assert absent is not None
    assert absent.collect().to_dicts() == [{"id": 1, "setting": None}]

    (tmp_path / "control.csv").write_text("setting\n")
    with pytest.raises(PreparedTableError, match="exactly one row"):
        store.read_data("prepared")


def test_join_can_explicitly_complete_optional_right_payload_columns() -> None:
    table = PreparedTable(
        name="prepared",
        source="base",
        frame_sources=["base", "attributes"],
        required_columns=["id", "optional_rate"],
        joins=[
            TableJoin(
                source="attributes",
                on={"id": "id"},
                columns={"rate": "optional_rate"},
                ensure_null_columns=["rate"],
            )
        ],
    )

    result = prepare_table_frames(
        table,
        {
            "base": pl.DataFrame({"id": [1, 2]}),
            "attributes": pl.DataFrame({"id": [1, 2]}),
        },
    )

    assert result is not None
    assert result.collect().to_dicts() == [
        {"id": 1, "optional_rate": None},
        {"id": 2, "optional_rate": None},
    ]


def test_right_singleton_broadcasts_controls_to_all_left_rows() -> None:
    store = DataStore()
    store.add_tables(
        [
            PreparedTable(
                name="prepared",
                source="rows",
                frame_sources=["rows", "control"],
                required_columns=["id", "enabled"],
                joins=[
                    TableJoin(
                        source="control",
                        on={},
                        columns={"enabled": "enabled"},
                        broadcast="right",
                        cardinality="m:1",
                    )
                ],
            )
        ]
    )

    result = store.prepare_table(
        "prepared",
        inputs={
            "rows": pl.DataFrame({"id": [1, 2]}),
            "control": pl.DataFrame({"enabled": [True]}),
        },
    )

    assert result is not None
    assert result.collect().to_dicts() == [{"id": 1, "enabled": True}, {"id": 2, "enabled": True}]


@pytest.mark.parametrize(
    ("values", "expected_error"),
    [([0, 1, 2, 3, 4], False), ([0, 2, 3], True), ([1, 1, 2], True)],
    ids=["filter-to-singleton", "filter-to-empty", "filter-to-multiple"],
)
def test_right_singleton_is_validated_after_source_filter(values: list[int], expected_error: bool) -> None:
    store = DataStore()
    store.add_tables(
        [
            PreparedTable(
                name="prepared",
                source="rows",
                frame_sources=["rows", "controls"],
                required_columns=["id", "setting"],
                joins=[
                    TableJoin(
                        source="controls",
                        on={},
                        columns={"setting": "setting"},
                        broadcast="right",
                        cardinality="m:1",
                        right_filter=[{"column": "setting", "operator": "eq", "value": 1}],
                    )
                ],
            )
        ]
    )

    inputs = {
        "rows": pl.DataFrame({"id": [1]}),
        "controls": pl.DataFrame({"setting": values}),
    }
    if expected_error:
        with pytest.raises(PreparedTableError, match="exactly one row"):
            store.prepare_table("prepared", inputs=inputs)
        return

    result = store.prepare_table("prepared", inputs=inputs)
    assert result is not None
    assert result.collect().to_dicts() == [{"id": 1, "setting": 1}]


def test_left_singleton_broadcast_left_join_preserves_row_for_empty_right() -> None:
    store = DataStore()
    store.add_tables(
        [
            PreparedTable(
                name="prepared",
                source="control",
                frame_sources=["control", "rows"],
                required_columns=["enabled", "rate"],
                joins=[
                    TableJoin(
                        source="rows",
                        on={},
                        columns={"rate": "rate"},
                        how="left",
                        cardinality="1:m",
                        broadcast="left",
                    )
                ],
            )
        ]
    )

    result = store.prepare_table(
        "prepared",
        inputs={
            "control": pl.DataFrame({"enabled": [True]}),
            "rows": pl.DataFrame({"rate": pl.Series([], dtype=pl.Float64)}),
        },
    )

    assert result is not None
    assert result.collect().to_dicts() == [{"enabled": True, "rate": None}]


@pytest.mark.parametrize(
    ("enabled", "rates_present", "expected_error"),
    [(True, False, True), (False, False, False), (True, True, False)],
    ids=["enabled-absent", "disabled-absent", "enabled-existing-empty"],
)
def test_required_when_distinguishes_absent_from_existing_empty_source(
    tmp_path: Path, enabled: bool, rates_present: bool, expected_error: bool
) -> None:
    rates_path = tmp_path / "rates.csv"
    if rates_present:
        rates_path.write_text("id,rate\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {
                "name": "rates",
                "fpath": "rates.csv",
                "info": {"is_optional": True},
                "reader": {"kwargs": {"infer_schema": False}},
                "proc_spec": {"column_schema": {"id": "int", "rate": "float"}},
            }
        ],
        tables=[
            {
                "name": "policy",
                "source": "generator_rows",
                "frame_sources": ["generator_rows", "flags"],
                "required_columns": ["id", "enabled", "rate"],
                "joins": [
                    {"source": "flags", "on": {"id": "id"}, "columns": {"enabled": "enabled"}},
                    {
                        "source": "rates",
                        "on": {"id": "id"},
                        "columns": {"rate": "rate"},
                        "missing_source": "null",
                        "required_when": [{"column": "enabled", "operator": "eq", "value": True}],
                    },
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)
    inputs = {
        "generator_rows": pl.DataFrame({"id": [1]}),
        "flags": pl.DataFrame({"id": [1], "enabled": [enabled]}),
    }

    if expected_error:
        with pytest.raises(PreparedTableError, match="required_when matched"):
            store.prepare_table("policy", inputs=inputs)
        return

    result = store.prepare_table("policy", inputs=inputs)
    assert result is not None
    assert result.collect().to_dicts() == [{"id": 1, "enabled": enabled, "rate": None}]


def test_required_when_is_checked_before_loading_join_source(tmp_path: Path) -> None:
    rates_path = tmp_path / "rates.csv"
    rates_path.touch()
    reads = 0

    def read_rates(path: Path, **kwargs: object) -> pl.LazyFrame:
        nonlocal reads
        reads += 1
        return pl.DataFrame({"id": [1], "rate": [0.5]}).lazy()

    store = DataStore(path=tmp_path)
    store.add_data(
        [
            DataFile(
                name="rates",
                fpath=rates_path,
                reader=ReaderConfig(function=read_rates),
            )
        ]
    )
    store.add_tables(
        [
            PreparedTable(
                name="policy",
                source="generator_rows",
                frame_sources=["generator_rows"],
                required_columns=["id", "rate"],
                joins=[
                    TableJoin(
                        source="rates",
                        on={"id": "id"},
                        columns={"rate": "rate"},
                        required_when=[{"column": "missing_flag", "operator": "eq", "value": True}],
                    )
                ],
            )
        ]
    )

    with pytest.raises(PreparedTableError, match=r"required_when.*missing_flag"):
        store.prepare_table("policy", inputs={"generator_rows": pl.DataFrame({"id": [1]})})
    assert reads == 0


def test_prepared_table_join_is_stable_and_round_trips(tmp_path: Path) -> None:
    """Prepared table selection is stable, and store operations retain its config."""
    (tmp_path / "base.csv").write_text("from_region,to_region,capacity\nA,B,100\n")
    (tmp_path / "costs.csv").write_text("from_region,to_region,cost_bin,cost\nA,B,0,11\nA,B,0,12\nA,B,1,20\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {"name": "capacity", "fpath": "base.csv"},
            {"name": "costs", "fpath": "costs.csv"},
        ],
        tables=[
            {
                "name": "transmission",
                "source": "capacity",
                "required_columns": ["from_region", "to_region", "capacity", "cost"],
                "joins": [
                    {
                        "source": "costs",
                        "on": {"from_region": "from_region", "to_region": "to_region"},
                        "columns": {"cost": "cost"},
                        "select_first": {"order_by": {"cost_bin": "asc"}},
                    }
                ],
            }
        ],
    )

    store = DataStore.from_json(mapping_path)
    assert store.list_data() == ["capacity", "costs", "transmission"]
    assert store.list_files() == ["capacity", "costs"]
    assert store.list_tables() == ["transmission"]
    assert "transmission" in store
    assert store.get_table("transmission").name == "transmission"
    result = store.read_data("transmission")
    assert result is not None
    assert result.collect().to_dict(as_series=False) == {
        "from_region": ["A"],
        "to_region": ["B"],
        "capacity": [100],
        "cost": [11],
    }

    exported = tmp_path / "exported.json"
    store.to_json(exported)
    restored = DataStore.from_json(exported)
    assert restored.list_tables() == ["transmission"]
    assert restored.read_data("transmission").collect().equals(result.collect())

    store.add_tables(
        [
            PreparedTable(
                name="capacity_copy",
                source="capacity",
                required_columns=["from_region", "to_region", "capacity"],
            )
        ]
    )
    assert store.list_tables() == ["capacity_copy", "transmission"]
    with pytest.raises(KeyError, match="referenced"):
        store.remove_data("capacity")
    store.remove_table("capacity_copy", "transmission")
    assert store.list_tables() == []
    store.remove_data("capacity", "costs")
    assert store.list_data() == []


def test_prepare_table_uses_named_in_memory_base_with_configured_joins(tmp_path: Path) -> None:
    """Frame-backed recipes share the prepared-table join and row-order contract."""
    (tmp_path / "costs.csv").write_text("technology,cost\ngas,0\nwind,12\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "costs", "fpath": "costs.csv"}],
        tables=[
            {
                "name": "generator_policy",
                "source": "generator_rows",
                "frame_sources": ["generator_rows"],
                "required_columns": ["technology", "capacity", "fom_cost"],
                "joins": [
                    {
                        "source": "costs",
                        "on": {"technology": "technology"},
                        "columns": {"cost": "fom_cost"},
                        "allow_null_left_keys": True,
                    }
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)
    generators = pl.DataFrame({"technology": ["gas", None, "wind"], "capacity": [10.0, 20.0, 30.0]})

    result = store.prepare_table("generator_policy", inputs={"generator_rows": generators})

    assert result is not None
    assert result.collect().to_dicts() == [
        {"technology": "gas", "capacity": 10.0, "fom_cost": 0},
        {"technology": None, "capacity": 20.0, "fom_cost": None},
        {"technology": "wind", "capacity": 30.0, "fom_cost": 12},
    ]


def test_asof_join_uses_strict_prior_nonzero_rates_and_preserves_left_order(tmp_path: Path) -> None:
    mapping_path = write_mapping(
        tmp_path,
        files=[],
        tables=[
            {
                "name": "generator_fom",
                "source": "generator_rows",
                "frame_sources": ["generator_rows", "history"],
                "required_columns": ["generator_id", "year", "previous_rate"],
                "joins": [
                    {
                        "source": "history",
                        "on": {"technology": "technology", "region": "region"},
                        "columns": {"rate": "previous_rate"},
                        "allow_null_left_keys": True,
                        "asof": {
                            "left_on": "year",
                            "right_on": "history_year",
                            "allow_exact_matches": False,
                        },
                        "right_filter": [{"column": "rate", "operator": "ne", "value": 0}],
                    }
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)
    generators = pl.DataFrame(
        {
            "generator_id": [2, 0, 1, 3],
            "technology": ["gas", "gas", "gas", None],
            "region": ["R1", "R1", "R1", None],
            "year": [2031, 2029, 2030, 2031],
            "history_year": [2001, 2002, 2003, 2004],
        }
    )
    history = pl.DataFrame(
        {
            "technology": ["gas", "gas", "gas"],
            "region": ["R1", "R1", "R1"],
            "history_year": [2029, 2028, 2030],
            "rate": [6.0, 5.0, 0.0],
        }
    )

    result = store.prepare_table("generator_fom", inputs={"generator_rows": generators, "history": history})

    assert result is not None
    assert result.collect().select("generator_id", "history_year", "previous_rate").to_dicts() == [
        {"generator_id": 2, "history_year": 2001, "previous_rate": 6.0},
        {"generator_id": 0, "history_year": 2002, "previous_rate": 5.0},
        {"generator_id": 1, "history_year": 2003, "previous_rate": 6.0},
        {"generator_id": 3, "history_year": 2004, "previous_rate": None},
    ]


def test_asof_join_preserves_payload_named_like_its_internal_order_column(tmp_path: Path) -> None:
    mapping_path = write_mapping(
        tmp_path,
        files=[],
        tables=[
            {
                "name": "generator_fom",
                "source": "generator_rows",
                "frame_sources": ["generator_rows", "history"],
                "required_columns": ["generator_id", "__prepared_table_order"],
                "joins": [
                    {
                        "source": "history",
                        "on": {"technology": "technology"},
                        "columns": {"rate": "__prepared_table_order"},
                        "asof": {"left_on": "year", "right_on": "history_year"},
                    }
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)

    result = store.prepare_table(
        "generator_fom",
        inputs={
            "generator_rows": pl.DataFrame(
                {"generator_id": [2, 1], "technology": ["gas", "gas"], "year": [2031, 2029]}
            ),
            "history": pl.DataFrame(
                {"technology": ["gas", "gas"], "history_year": [2028, 2030], "rate": [5.0, 8.0]}
            ),
        },
    )

    assert result is not None
    assert result.collect().select("generator_id", "__prepared_table_order").to_dicts() == [
        {"generator_id": 2, "__prepared_table_order": 8.0},
        {"generator_id": 1, "__prepared_table_order": 5.0},
    ]


def test_asof_join_rejects_duplicate_temporal_keys(tmp_path: Path) -> None:
    mapping_path = write_mapping(
        tmp_path,
        files=[],
        tables=[
            {
                "name": "generator_fom",
                "source": "generator_rows",
                "frame_sources": ["generator_rows", "history"],
                "required_columns": ["generator_id", "prior_rate"],
                "joins": [
                    {
                        "source": "history",
                        "on": {"technology": "technology"},
                        "columns": {"rate": "prior_rate"},
                        "asof": {"left_on": "year", "right_on": "history_year"},
                    }
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)

    with pytest.raises(PreparedTableError, match="duplicate temporal keys"):
        store.prepare_table(
            "generator_fom",
            inputs={
                "generator_rows": pl.DataFrame({"generator_id": [1], "technology": ["gas"], "year": [2032]}),
                "history": pl.DataFrame(
                    {
                        "technology": ["gas", "gas"],
                        "history_year": [2028, 2028],
                        "rate": [5.0, 6.0],
                    }
                ),
            },
        )


def test_inner_many_to_many_join_expands_in_left_and_right_input_order(tmp_path: Path) -> None:
    (tmp_path / "biofuel.csv").write_text(
        "fuel_type,region,year,fuel_price\nbiomass,R1,2030,3\nbiomass,R2,2030,5\n"
    )
    (tmp_path / "fuel_map.csv").write_text("fuel_type,technology\nbiomass,biomass-cc\nbiomass,biomass-st\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {"name": "biofuel", "fpath": "biofuel.csv"},
            {"name": "fuel_map", "fpath": "fuel_map.csv"},
        ],
        tables=[
            {
                "name": "biofuel_by_technology",
                "source": "biofuel",
                "required_columns": ["region", "year", "fuel_price", "technology"],
                "joins": [
                    {
                        "source": "fuel_map",
                        "on": {"fuel_type": "fuel_type"},
                        "columns": {"technology": "technology"},
                        "how": "inner",
                        "cardinality": "m:m",
                    }
                ],
            }
        ],
    )

    result = DataStore.from_json(mapping_path).read_data("biofuel_by_technology")

    assert result is not None
    assert result.collect().to_dicts() == [
        {"fuel_type": "biomass", "region": "R1", "year": 2030, "fuel_price": 3, "technology": "biomass-cc"},
        {"fuel_type": "biomass", "region": "R1", "year": 2030, "fuel_price": 3, "technology": "biomass-st"},
        {"fuel_type": "biomass", "region": "R2", "year": 2030, "fuel_price": 5, "technology": "biomass-cc"},
        {"fuel_type": "biomass", "region": "R2", "year": 2030, "fuel_price": 5, "technology": "biomass-st"},
    ]


def test_inner_expanding_join_rejects_null_keys_at_collection(tmp_path: Path) -> None:
    (tmp_path / "left.csv").write_text("fuel_type,price\n,3\n")
    (tmp_path / "right.csv").write_text("fuel_type,technology\nbiomass,biomass-cc\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "left", "fpath": "left.csv"}, {"name": "right", "fpath": "right.csv"}],
        tables=[
            {
                "name": "expanded",
                "source": "left",
                "required_columns": ["fuel_type", "price", "technology"],
                "joins": [
                    {
                        "source": "right",
                        "on": {"fuel_type": "fuel_type"},
                        "columns": {"technology": "technology"},
                        "how": "inner",
                        "cardinality": "m:m",
                    }
                ],
            }
        ],
    )

    with pytest.raises(PreparedTableError, match="null join key"):
        DataStore.from_json(mapping_path).read_data("expanded")


def test_expanding_join_requires_inner_semantics() -> None:
    with pytest.raises(ValidationError, match="expanding joins require how='inner'"):
        TableJoin(
            source="mapping",
            on={"fuel_type": "fuel_type"},
            columns={"technology": "technology"},
            cardinality="m:m",
        )


def test_select_first_without_order_preserves_first_input_row(tmp_path: Path) -> None:
    """An explicit unsorted representative selection keeps the first source row."""
    (tmp_path / "base.csv").write_text("region\nA\n")
    (tmp_path / "right.csv").write_text("region,cost\nA,17\nA,19\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "base", "fpath": "base.csv"}, {"name": "right", "fpath": "right.csv"}],
        tables=[
            {
                "name": "result",
                "source": "base",
                "required_columns": ["region", "cost"],
                "joins": [
                    {
                        "source": "right",
                        "on": {"region": "region"},
                        "columns": {"cost": "cost"},
                        "select_first": {},
                    }
                ],
            }
        ],
    )

    result = DataStore.from_json(mapping_path).read_data("result")
    assert result is not None
    assert result.collect().to_dicts() == [{"region": "A", "cost": 17}]


def test_file_mapping_requires_files_tables_envelope(tmp_path: Path) -> None:
    """The old list-root mapping is rejected rather than silently accepted."""
    mapping_path = tmp_path / "file_mapping.json"
    mapping_path.write_text(json.dumps([{"name": "base", "fpath": "base.csv"}]))

    with pytest.raises(ValidationError):
        DataStore.from_json(mapping_path)


def test_prepared_table_rejects_bad_join_keys_and_payloads() -> None:
    """Join keys and payload columns are explicit, unique, and non-empty."""
    with pytest.raises(ValidationError, match="right join-key references must be unique"):
        TableJoin(source="source", on={"first": "region", "second": "region"}, columns={"value": "value"})
    with pytest.raises(ValidationError, match="cannot repeat right join keys"):
        TableJoin(source="source", on={"region": "region"}, columns={"region": "region"})
    with pytest.raises(ValidationError, match="payload output columns must be unique"):
        TableJoin(
            source="source",
            on={"first": "first", "second": "second"},
            columns={"first_value": "value", "second_value": "value"},
        )
    with pytest.raises(ValidationError, match="keyed joins require at least one join key"):
        TableJoin(source="source", on={}, columns={"value": "value"})


@pytest.mark.parametrize(
    ("base_csv", "right_csv", "join", "error"),
    [
        (
            "from_region,to_region\nA,B\n",
            "from_region,to_region,cost\nA,B,1\nA,B,2\n",
            {
                "source": "costs",
                "on": {"from_region": "from_region", "to_region": "to_region"},
                "columns": {"cost": "cost"},
            },
            "duplicate keys",
        ),
        (
            "from_region,to_region\nA,B\n",
            "from_region,to_region\nA,B\n",
            {
                "source": "costs",
                "on": {"from_region": "from_region", "to_region": "to_region"},
                "columns": {"cost": "cost"},
            },
            "missing column.*cost",
        ),
        (
            "from_region,to_region\nA,\n",
            "from_region,to_region,cost\nA,B,1\n",
            {
                "source": "costs",
                "on": {"from_region": "from_region", "to_region": "to_region"},
                "columns": {"cost": "cost"},
            },
            "null join key",
        ),
    ],
)
def test_prepared_table_reports_invalid_join_data(
    tmp_path: Path,
    base_csv: str,
    right_csv: str,
    join: dict[str, object],
    error: str,
) -> None:
    """Collection of lazy physical inputs reports table and source context."""
    (tmp_path / "base.csv").write_text(base_csv)
    (tmp_path / "costs.csv").write_text(right_csv)
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "capacity", "fpath": "base.csv"}, {"name": "costs", "fpath": "costs.csv"}],
        tables=[
            {
                "name": "transmission",
                "source": "capacity",
                "required_columns": ["from_region", "to_region"],
                "joins": [join],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)

    with pytest.raises(PreparedTableError, match=error) as result:
        store.read_table("transmission")

    assert "transmission" in str(result.value)
    assert "costs" in str(result.value)


def test_prepared_table_accepts_empty_physical_inputs(tmp_path: Path) -> None:
    """An empty but well-formed base and enrichment produce an empty table."""
    (tmp_path / "base.csv").write_text("from_region,to_region,capacity\n")
    (tmp_path / "costs.csv").write_text("from_region,to_region,cost\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "capacity", "fpath": "base.csv"}, {"name": "costs", "fpath": "costs.csv"}],
        tables=[
            {
                "name": "transmission",
                "source": "capacity",
                "required_columns": ["from_region", "to_region", "capacity", "cost"],
                "joins": [
                    {
                        "source": "costs",
                        "on": {"from_region": "from_region", "to_region": "to_region"},
                        "columns": {"cost": "cost"},
                    }
                ],
            }
        ],
    )

    result = DataStore.from_json(mapping_path).read_table("transmission")
    assert result is not None
    assert result.collect().is_empty()
    assert result.collect().columns == ["from_region", "to_region", "capacity", "cost"]


def test_optional_missing_base_propagates_none_before_reading_enrichments(tmp_path: Path) -> None:
    """An absent optional base short-circuits even when a required enrichment disappears later."""
    base_path = tmp_path / "base.csv"
    enrichment_path = tmp_path / "enrichment.csv"
    base_path.write_text("region,capacity\nA,100\n")
    enrichment_path.write_text("region,loss\nA,0.1\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {"name": "capacity", "fpath": "base.csv", "info": {"is_optional": True}},
            {"name": "losses", "fpath": "enrichment.csv"},
        ],
        tables=[
            {
                "name": "transmission",
                "source": "capacity",
                "required_columns": ["region", "capacity", "loss"],
                "joins": [
                    {
                        "source": "losses",
                        "on": {"region": "region"},
                        "columns": {"loss": "loss"},
                    }
                ],
            }
        ],
    )

    store = DataStore.from_json(mapping_path)
    base_path.unlink()
    enrichment_path.unlink()

    assert store.read_table("transmission") is None
    assert store.is_optional("transmission")
    assert store.is_optional("capacity")


def test_optional_prepared_root_short_circuits_outer_joins(tmp_path: Path) -> None:
    base_path = tmp_path / "base.csv"
    rates_path = tmp_path / "rates.csv"
    base_path.write_text("id\n1\n")
    rates_path.write_text("id,rate\n1,0.2\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {"name": "base", "fpath": "base.csv", "info": {"is_optional": True}},
            {"name": "rates", "fpath": "rates.csv"},
        ],
        tables=[
            {"name": "optional_rows", "source": "base", "required_columns": ["id"]},
            {
                "name": "final_rows",
                "source": "optional_rows",
                "required_columns": ["id", "rate"],
                "joins": [{"source": "rates", "on": {"id": "id"}, "columns": {"rate": "rate"}}],
            },
        ],
    )
    store = DataStore.from_json(mapping_path)
    base_path.unlink()
    rates_path.unlink()

    assert store.read_table("final_rows") is None
    assert store.is_optional("final_rows")


def test_nested_required_source_error_keeps_dependency_context(tmp_path: Path) -> None:
    base_path = tmp_path / "base.csv"
    base_path.write_text("id\n1\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "base", "fpath": "base.csv"}],
        tables=[
            {"name": "source_rows", "source": "base", "required_columns": ["id"]},
            {"name": "final_rows", "source": "source_rows", "required_columns": ["id"]},
        ],
    )
    store = DataStore.from_json(mapping_path)
    base_path.unlink()

    with pytest.raises(
        PreparedTableError,
        match=r"final_rows.*source_rows.*source_rows.*base",
    ):
        store.read_table("final_rows")


def test_optional_physical_root_short_circuits_missing_required_frame_join(tmp_path: Path) -> None:
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "base", "fpath": "missing.csv", "info": {"is_optional": True}}],
        tables=[
            {
                "name": "prepared",
                "source": "base",
                "frame_sources": ["enrichment"],
                "required_columns": ["id", "rate"],
                "joins": [
                    {
                        "source": "enrichment",
                        "on": {"id": "id"},
                        "columns": {"rate": "rate"},
                    }
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)

    assert store.prepare_table("prepared") is None


def test_null_missing_mode_adds_payload_for_an_absent_frame(tmp_path: Path) -> None:
    mapping_path = write_mapping(
        tmp_path,
        files=[],
        tables=[
            {
                "name": "generator_policy",
                "source": "generator_rows",
                "frame_sources": ["generator_rows", "optional_rates"],
                "required_columns": ["technology", "capacity"],
                "joins": [
                    {
                        "source": "optional_rates",
                        "on": {"technology": "technology"},
                        "columns": {"rate": "rate"},
                        "missing_source": "null",
                    }
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)

    result = store.prepare_table(
        "generator_policy",
        inputs={
            "generator_rows": pl.DataFrame({"technology": ["gas"], "capacity": [10.0]}),
            "optional_rates": None,
        },
    )

    assert result is not None
    assert result.collect().to_dicts() == [{"technology": "gas", "capacity": 10.0, "rate": None}]


def test_optional_file_metadata_does_not_weaken_a_required_join(tmp_path: Path) -> None:
    (tmp_path / "base.csv").write_text("technology\nwind\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {"name": "base", "fpath": "base.csv"},
            {"name": "rates", "fpath": "missing.csv", "info": {"is_optional": True}},
        ],
        tables=[
            {
                "name": "generator_policy",
                "source": "base",
                "required_columns": ["technology", "rate"],
                "joins": [
                    {
                        "source": "rates",
                        "on": {"technology": "technology"},
                        "columns": {"rate": "rate"},
                    }
                ],
            }
        ],
    )

    with pytest.raises(PreparedTableError, match="required source 'rates'"):
        DataStore.from_json(mapping_path).read_table("generator_policy")


def test_reused_frame_source_applies_missing_mode_per_join(tmp_path: Path) -> None:
    mapping_path = write_mapping(
        tmp_path,
        files=[],
        tables=[
            {
                "name": "generator_policy",
                "source": "generator_rows",
                "frame_sources": ["generator_rows", "rates"],
                "required_columns": ["technology", "optional_rate"],
                "joins": [
                    {
                        "source": "rates",
                        "on": {"technology": "technology"},
                        "columns": {"rate": "optional_rate"},
                        "missing_source": "null",
                    },
                    {
                        "source": "rates",
                        "on": {"technology": "technology"},
                        "columns": {"rate": "required_rate"},
                    },
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)

    with pytest.raises(PreparedTableError, match="required source 'rates'"):
        store.prepare_table(
            "generator_policy",
            inputs={"generator_rows": pl.DataFrame({"technology": ["wind"]}), "rates": None},
        )


def test_reused_lazy_source_is_materialized_once_per_execution(tmp_path: Path) -> None:
    mapping_path = write_mapping(
        tmp_path,
        files=[],
        tables=[
            {
                "name": "generator_policy",
                "source": "generator_rows",
                "frame_sources": ["generator_rows", "rates"],
                "required_columns": ["technology", "first_rate", "second_rate"],
                "joins": [
                    {
                        "source": "rates",
                        "on": {"technology": "technology"},
                        "columns": {"rate": "first_rate"},
                    },
                    {
                        "source": "rates",
                        "on": {"technology": "technology"},
                        "columns": {"rate": "second_rate"},
                    },
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)
    materializations: list[int] = []

    def record_materialization(frame: pl.DataFrame) -> pl.DataFrame:
        materializations.append(1)
        return frame

    rates = (
        pl.DataFrame({"technology": ["wind"], "rate": [0.25]})
        .lazy()
        .map_batches(
            record_materialization,
            predicate_pushdown=False,
            projection_pushdown=False,
            slice_pushdown=False,
        )
    )
    result = store.prepare_table(
        "generator_policy",
        inputs={"generator_rows": pl.DataFrame({"technology": ["wind"]}), "rates": rates},
    )

    assert result is not None
    assert result.collect().to_dicts() == [{"technology": "wind", "first_rate": 0.25, "second_rate": 0.25}]
    assert len(materializations) == 1


def test_nullable_join_does_not_make_a_reused_required_root_optional(tmp_path: Path) -> None:
    mapping_path = write_mapping(
        tmp_path,
        files=[],
        tables=[
            {
                "name": "generator_policy",
                "source": "generator_rows",
                "frame_sources": ["generator_rows"],
                "required_columns": ["technology"],
                "joins": [
                    {
                        "source": "generator_rows",
                        "on": {"technology": "technology"},
                        "columns": {"capacity": "joined_capacity"},
                        "missing_source": "null",
                    }
                ],
            }
        ],
    )
    store = DataStore.from_json(mapping_path)

    with pytest.raises(PreparedTableError, match=r"requires named frame input.*generator_rows"):
        store.prepare_table("generator_policy")


def test_prepared_table_rejects_unused_frame_sources() -> None:
    with pytest.raises(ValidationError, match=r"frame_sources.*unused"):
        PreparedTable(
            name="generator_policy",
            source="generator_rows",
            frame_sources=["generator_rows", "unused"],
            required_columns=["technology"],
        )


def test_skip_missing_mode_leaves_the_prepared_base_unchanged(tmp_path: Path) -> None:
    """A skipped missing enrichment does not discard the prepared base."""
    (tmp_path / "base.csv").write_text("from_region,to_region,capacity\nA,B,100\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {"name": "capacity", "fpath": "base.csv"},
            {"name": "losses", "fpath": "missing.csv", "info": {"is_optional": True}},
        ],
        tables=[
            {
                "name": "transmission",
                "source": "capacity",
                "required_columns": ["from_region", "to_region", "capacity"],
                "joins": [
                    {
                        "source": "losses",
                        "on": {"from_region": "from_region", "to_region": "to_region"},
                        "columns": {"losses": "losses"},
                        "missing_source": "skip",
                    }
                ],
            }
        ],
    )

    result = DataStore.from_json(mapping_path).read_table("transmission")
    assert result is not None
    assert result.collect().to_dict(as_series=False) == {
        "from_region": ["A"],
        "to_region": ["B"],
        "capacity": [100],
    }


def test_prepared_table_rejects_dangling_and_colliding_names(tmp_path: Path) -> None:
    """Mapping validation rejects unknown sources and cross-kind name collisions."""
    (tmp_path / "base.csv").write_text("region,value\nA,1\n")
    dangling = write_mapping(
        tmp_path,
        files=[{"name": "base", "fpath": "base.csv"}],
        tables=[{"name": "result", "source": "missing", "required_columns": ["region"]}],
    )
    with pytest.raises(ValidationError, match="references unknown file, table, runtime, or frame source"):
        DataStore.from_json(dangling)

    collision = write_mapping(
        tmp_path,
        files=[{"name": "base", "fpath": "base.csv"}],
        tables=[{"name": "base", "source": "base", "required_columns": ["region"]}],
    )
    with pytest.raises(ValidationError, match="must be unique"):
        DataStore.from_json(collision)


def test_prepared_table_rejects_overlapping_join_payload(tmp_path: Path) -> None:
    """Join payload columns cannot silently overwrite the base."""
    (tmp_path / "base.csv").write_text("region,value\nA,1\n")
    (tmp_path / "right.csv").write_text("region,value\nA,2\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "base", "fpath": "base.csv"}, {"name": "right", "fpath": "right.csv"}],
        tables=[
            {
                "name": "result",
                "source": "base",
                "required_columns": ["region", "value"],
                "joins": [{"source": "right", "on": {"region": "region"}, "columns": {"value": "value"}}],
            }
        ],
    )

    with pytest.raises(PreparedTableError, match=r"overlapping payload.*value"):
        DataStore.from_json(mapping_path).read_table("result")


def test_prepared_table_rejects_missing_sort_column(tmp_path: Path) -> None:
    """Sorting for select-first validates the configured sort columns."""
    (tmp_path / "base.csv").write_text("region\nA\n")
    (tmp_path / "right.csv").write_text("region,cost\nA,1\n")
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "base", "fpath": "base.csv"}, {"name": "right", "fpath": "right.csv"}],
        tables=[
            {
                "name": "result",
                "source": "base",
                "required_columns": ["region", "cost"],
                "joins": [
                    {
                        "source": "right",
                        "on": {"region": "region"},
                        "columns": {"cost": "cost"},
                        "select_first": {"order_by": {"cost_bin": "asc"}},
                    }
                ],
            }
        ],
    )

    with pytest.raises(PreparedTableError, match=r"missing column.*cost_bin"):
        DataStore.from_json(mapping_path).read_table("result")


def test_prepared_table_joins_crossed_keys_and_applies_column_operations(tmp_path: Path) -> None:
    """Transmission-shaped tables support reversed keys and declarative column calculations."""
    (tmp_path / "lines.csv").write_text(
        "from_region,to_region,trtype,capacity,cost,distance\n"
        "A,B,AC,100,120,10\n"
        "B,A,AC,50,50,4\n"
        "C,D,AC,300,90,0\n"
        "E,F,AC,500,,5\n"
        "G,H,AC,700,80,\n"
    )
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "lines", "fpath": "lines.csv"}],
        tables=[
            {
                "name": "prepared_lines",
                "source": "lines",
                "required_columns": [
                    "from_region",
                    "to_region",
                    "capacity",
                    "reverse_capacity",
                    "line_cost_per_mw_mile",
                ],
                "joins": [
                    {
                        "source": "lines",
                        "on": {
                            "from_region": "to_region",
                            "to_region": "from_region",
                            "trtype": "trtype",
                        },
                        "columns": {"capacity": "reverse_capacity"},
                    }
                ],
                "proc_spec": {
                    "safe_divide": {
                        "line_cost_per_mw_mile": {"numerator": "cost", "denominator": "distance"}
                    },
                    "fill_null_from": {"reverse_capacity": "capacity"},
                },
            }
        ],
    )

    result = DataStore.from_json(mapping_path).read_data("prepared_lines")
    assert result is not None
    assert result.collect().select(
        "from_region", "to_region", "reverse_capacity", "line_cost_per_mw_mile"
    ).to_dicts() == [
        {"from_region": "A", "to_region": "B", "reverse_capacity": 50, "line_cost_per_mw_mile": 12.0},
        {"from_region": "B", "to_region": "A", "reverse_capacity": 100, "line_cost_per_mw_mile": 12.5},
        {"from_region": "C", "to_region": "D", "reverse_capacity": 300, "line_cost_per_mw_mile": None},
        {"from_region": "E", "to_region": "F", "reverse_capacity": 500, "line_cost_per_mw_mile": None},
        {"from_region": "G", "to_region": "H", "reverse_capacity": 700, "line_cost_per_mw_mile": None},
    ]


def test_prepared_table_rejects_duplicate_reverse_keys_when_collected(tmp_path: Path) -> None:
    """Crossed key mappings retain strict many-to-one cardinality at execution."""
    (tmp_path / "lines.csv").write_text(
        "from_region,to_region,trtype,capacity\nA,B,AC,100\nB,A,AC,50\nB,A,AC,60\n"
    )
    mapping_path = write_mapping(
        tmp_path,
        files=[{"name": "lines", "fpath": "lines.csv"}],
        tables=[
            {
                "name": "prepared_lines",
                "source": "lines",
                "required_columns": ["from_region", "to_region", "capacity", "reverse_capacity"],
                "joins": [
                    {
                        "source": "lines",
                        "on": {
                            "from_region": "to_region",
                            "to_region": "from_region",
                            "trtype": "trtype",
                        },
                        "columns": {"capacity": "reverse_capacity"},
                    }
                ],
            }
        ],
    )

    with pytest.raises(PreparedTableError, match="duplicate keys"):
        DataStore.from_json(mapping_path).read_data("prepared_lines")


@pytest.mark.parametrize(
    ("p2_values", "expected", "error"),
    [
        (
            ["30.0", "NA"],
            [
                {"region": "p1", "max_active_power": 10.0},
                {"region": "p2", "max_active_power": 30.0},
            ],
            None,
        ),
        (["NA", "NA"], None, r"load_peaks.*load_profiles.*max_active_power"),
    ],
    ids=["mixed-numeric-columns", "all-null-region-fails"],
)
def test_prepared_table_unpivots_wide_profiles_into_regional_peaks(
    tmp_path: Path,
    p2_values: list[str],
    expected: list[dict[str, str | float]] | None,
    error: str | None,
) -> None:
    """Wide mixed-type profiles become numeric peaks, and all-null peaks fail."""
    (tmp_path / "load.csv").write_text(
        f"datetime,p1,p2\n2012-01-01T00:00:00,9.0,{p2_values[0]}\n2012-01-01T01:00:00,10.0,{p2_values[1]}\n"
    )
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {
                "name": "load_profiles",
                "fpath": "load.csv",
                "reader": {"kwargs": {"infer_schema": False}},
                "proc_spec": {"column_schema": {"p1": "float"}},
            }
        ],
        tables=[
            {
                "name": "load_peaks",
                "source": "load_profiles",
                "required_columns": ["region", "max_active_power"],
                "non_null_columns": ["region", "max_active_power"],
                "proc_spec": {
                    "unpivot_on": {"all_except": ["datetime"]},
                    "replace_values": {"NA": None},
                    "column_mapping": {"variable": "region", "value": "max_active_power"},
                    "column_schema": {"max_active_power": "float"},
                    "group_by": ["region"],
                    "aggregate_on": {"max_active_power": "max"},
                },
            }
        ],
    )
    store = DataStore.from_json(mapping_path)

    if error is not None:
        with pytest.raises(PreparedTableError, match=error):
            store.read_data("load_peaks")
        return

    exported_mapping = tmp_path / "round_trip.json"
    store.to_json(exported_mapping)
    restored_store = DataStore.from_json(exported_mapping)
    assert restored_store.get_table("load_peaks").non_null_columns == ["region", "max_active_power"]

    assert expected is not None
    result = restored_store.read_data("load_peaks")

    assert result is not None
    assert result.collect().to_dicts() == expected


def test_prepared_table_validates_non_null_columns() -> None:
    """Non-null output constraints must be unique and declared as required."""
    with pytest.raises(ValidationError, match="non_null_columns must be unique"):
        PreparedTable(
            name="load_peaks",
            source="load_profiles",
            required_columns=["region", "max_active_power"],
            non_null_columns=["max_active_power", "max_active_power"],
        )
    with pytest.raises(ValidationError, match="non_null_columns must be required_columns"):
        PreparedTable(
            name="load_peaks",
            source="load_profiles",
            required_columns=["region"],
            non_null_columns=["max_active_power"],
        )
