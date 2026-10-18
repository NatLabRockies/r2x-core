"""Tests for explicitly configured prepared tables."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from r2x_core import DataStore, PreparedTable, TableJoin
from r2x_core.prepared_tables import PreparedTableError


def write_mapping(folder: Path, *, files: list[dict[str, object]], tables: list[dict[str, object]]) -> Path:
    """Write a file-mapping envelope for a test data directory."""
    mapping_path = folder / "file_mapping.json"
    mapping_path.write_text(json.dumps({"files": files, "tables": tables}))
    return mapping_path


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
    with pytest.raises(ValidationError, match="at least 1 item"):
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


def test_optional_missing_base_propagates_none(tmp_path: Path) -> None:
    """An absent optional physical base makes the prepared table absent."""
    mapping_path = write_mapping(
        tmp_path,
        files=[
            {
                "name": "capacity",
                "fpath": "missing.csv",
                "info": {"is_optional": True},
            }
        ],
        tables=[
            {
                "name": "transmission",
                "source": "capacity",
                "required_columns": ["from_region", "to_region", "capacity"],
            }
        ],
    )

    store = DataStore.from_json(mapping_path)
    assert store.read_table("transmission") is None
    assert store.is_optional("transmission")
    assert store.is_optional("capacity")


def test_optional_missing_enrichment_skips_join(tmp_path: Path) -> None:
    """An absent optional enrichment does not discard the prepared base."""
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
    with pytest.raises(ValidationError, match="unknown physical file"):
        DataStore.from_json(dangling)

    collision = write_mapping(
        tmp_path,
        files=[{"name": "base", "fpath": "base.csv"}],
        tables=[{"name": "base", "source": "base", "required_columns": ["region"]}],
    )
    with pytest.raises(ValidationError, match="unique across"):
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
