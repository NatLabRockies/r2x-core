"""Functional tests for processors module.

These tests focus on realistic processor behavior using TabularProcessing and JSONProcessing
models. Each test exercises a specific processor function with real data to ensure filtering,
renaming, dropping, casting, and pivoting work as expected.
"""

import json
import warnings
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from r2x_core.datafile import (
    ColumnAddSpec,
    ColumnPredicate,
    ConditionalAssignment,
    DataFile,
    GroupedFillSpec,
    JSONProcessing,
    RejectRowsSpec,
    TabularProcessing,
    WeightedMeanSpec,
)
from r2x_core.processors import (
    apply_processing,
    json_apply_filters,
    json_rename_keys,
    json_select_keys,
    pl_apply_filters,
    pl_cast_schema,
    pl_drop_columns,
    pl_rename_columns,
    pl_select_columns,
    process_tabular_data,
    substitute_placeholders,
)


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a small CSV with realistic data for testing."""
    csv = tmp_path / "people.csv"
    csv.write_text(
        "name,age,city,score,retire_year\n"
        "Alice,30,NYC,85.5,2036\n"
        "Bob,25,LA,92.3,2036\n"
        "Charlie,35,CHI,78.9,2040\n"
        "Dana,40,NYC,88.0,2036\n"
    )
    return csv


@pytest.fixture
def sample_json_file(tmp_path: Path) -> Path:
    """Create a small JSON file for testing."""
    jf = tmp_path / "sample.json"
    jf.write_text(json.dumps({"name": "Alice", "age": 30, "city": "NYC", "score": 85.5}))
    return jf


def test_pl_apply_filters_single_value(sample_csv: Path):
    """Test filtering with a single value."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(filter_by={"name": "Alice"})
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result, _ = pl_apply_filters(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert len(result) == 1
    assert result["name"][0] == "Alice"


def test_pl_apply_filters_list_values(sample_csv: Path):
    """Test filtering with a list of values."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(filter_by={"name": ["Alice", "Bob"]})
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result, _ = pl_apply_filters(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert len(result) == 2
    names = set(result["name"].to_list())
    assert names == {"Alice", "Bob"}


def test_pl_apply_filters_multiple_conditions(sample_csv: Path):
    """Test filtering with multiple conditions (AND logic)."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(filter_by={"retire_year": 2036, "age": 30})
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result, _ = pl_apply_filters(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert len(result) == 1
    assert result["name"][0] == "Alice"


def test_pl_drop_columns_removes_existing(sample_csv: Path):
    """Test that drop_columns removes specified columns."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(drop_columns=["city", "score"])
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result, _ = pl_drop_columns(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert "city" not in result.columns
    assert "score" not in result.columns
    assert "name" in result.columns
    assert "age" in result.columns


def test_pl_drop_columns_missing_column_is_explicit_error(sample_csv: Path):
    """Test that missing drop columns fail with an actionable error."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(drop_columns=["nonexistent"])
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    with pytest.raises(ValueError, match=r"drop_columns.*nonexistent"):
        pl_drop_columns(lf, data_file=df_file, proc_spec=proc_spec)


def test_pl_rename_columns_renames_existing(sample_csv: Path):
    """Test that column_mapping renames columns correctly."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(column_mapping={"name": "person_name", "age": "person_age"})
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result, _ = pl_rename_columns(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert "person_name" in result.columns
    assert "person_age" in result.columns
    assert "name" not in result.columns
    assert "age" not in result.columns


def test_pl_rename_columns_missing_column_is_explicit_error(sample_csv: Path):
    """Test that missing rename columns fail with an actionable error."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(column_mapping={"nonexistent": "new_name"})
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    with pytest.raises(ValueError, match=r"column_mapping.*nonexistent"):
        pl_rename_columns(lf, data_file=df_file, proc_spec=proc_spec)


def test_pl_cast_schema_casts_columns(sample_csv: Path):
    """Test that column_schema casts columns to correct types."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(column_schema={"age": "int32", "retire_year": "int32"})
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result, _ = pl_cast_schema(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert result.schema["age"] == pl.Int32
    assert result.schema["retire_year"] == pl.Int32


def test_pl_cast_schema_unsupported_type_raises(sample_csv: Path):
    """Test that unsupported type strings raise ValueError."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(column_schema={"age": "invalid_type"})
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    with pytest.raises(ValueError, match="Unsupported data type"):
        pl_cast_schema(lf, data_file=df_file, proc_spec=proc_spec)


def test_unpivot_on_stacks_selected_columns(sample_csv: Path):
    """Wide-to-long processing uses its explicit unpivot operation."""
    lf = pl.LazyFrame({"2020": [100], "2025": [200], "2030": [300]})
    proc_spec = TabularProcessing(unpivot_on=["2020", "2025", "2030"])
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result = process_tabular_data(lf, data_file=df_file, proc_spec=proc_spec).collect()

    assert result.columns == ["variable", "value"]
    assert result.height == 3
    assert result.to_dicts() == [
        {"variable": "2020", "value": 100},
        {"variable": "2025", "value": 200},
        {"variable": "2030", "value": 300},
    ]


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        (
            "all",
            [
                {"variable": "id", "value": 1},
                {"variable": "north", "value": 10},
                {"variable": "south", "value": 20},
            ],
        ),
        (
            {"all_except": ["id"]},
            [
                {"id": 1, "variable": "north", "value": 10},
                {"id": 1, "variable": "south", "value": 20},
            ],
        ),
    ],
    ids=["all-columns", "all-except-identifiers"],
)
def test_unpivot_on_column_selectors(sample_csv: Path, selector, expected):
    data = pl.LazyFrame({"id": [1], "north": [10], "south": [20]})
    proc_spec = TabularProcessing(unpivot_on=selector)
    data_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result = process_tabular_data(data, data_file=data_file, proc_spec=proc_spec).collect()

    assert result.to_dicts() == expected


def test_unpivot_on_rejects_empty_column_selection():
    with pytest.raises(ValueError, match=r"unpivot_on.*at least one"):
        TabularProcessing(unpivot_on=[])


def test_unpivot_on_rejects_missing_identifier_column(sample_csv: Path):
    data = pl.LazyFrame({"id": [1], "north": [10]})
    proc_spec = TabularProcessing(unpivot_on={"all_except": ["missing"]})
    data_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    with pytest.raises(ValueError, match=r"missing column.*missing"):
        process_tabular_data(data, data_file=data_file, proc_spec=proc_spec)


def test_unpivot_on_rejects_empty_resolved_selection(sample_csv: Path):
    data = pl.LazyFrame({"id": [1]})
    proc_spec = TabularProcessing(unpivot_on={"all_except": ["id"]})
    data_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    with pytest.raises(ValueError, match="no value columns"):
        process_tabular_data(data, data_file=data_file, proc_spec=proc_spec)


def test_unpivot_on_rejects_output_name_collision(sample_csv: Path):
    data = pl.LazyFrame({"id": [1], "variable": ["north"], "amount": [10]})
    proc_spec = TabularProcessing(unpivot_on={"all_except": ["id", "variable"]})
    data_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    with pytest.raises(ValueError, match=r"overwrite existing column.*variable"):
        process_tabular_data(data, data_file=data_file, proc_spec=proc_spec)


def test_copy_columns_preserves_source_before_split(sample_csv: Path) -> None:
    """A copied technology key remains available when the source is split."""
    frame = pl.DataFrame({"technology": ["Gas-CC_H2-CT"]}).lazy()
    specification = TabularProcessing(
        copy_columns={"technology": "technology_full"},
        split_column={"technology": {"separator": "_", "into": ["technology_base", "technology_suffix"]}},
    )
    source = DataFile(name="generator technology", fpath=sample_csv)

    result = process_tabular_data(frame, data_file=source, proc_spec=specification).collect()

    assert result.row(0, named=True) == {
        "technology_full": "Gas-CC_H2-CT",
        "technology_base": "Gas-CC",
        "technology_suffix": "H2-CT",
    }


def test_copy_columns_rejects_missing_sources_and_existing_destinations(sample_csv: Path) -> None:
    """Copies must name existing source columns and avoid overwriting payload."""
    frame = pl.DataFrame({"technology": ["Gas-CC"], "technology_full": ["existing"]}).lazy()
    source = DataFile(name="generator technology", fpath=sample_csv)

    with pytest.raises(ValueError, match=r"copy_columns.*missing"):
        process_tabular_data(
            frame,
            data_file=source,
            proc_spec=TabularProcessing(copy_columns={"missing": "technology_full"}),
        )
    with pytest.raises(ValueError, match=r"copy_columns.*overwrite"):
        process_tabular_data(
            frame,
            data_file=source,
            proc_spec=TabularProcessing(copy_columns={"technology": "technology_full"}),
        )


def test_conditional_assignment_can_exclude_nan_rows(sample_csv: Path):
    frame = pl.DataFrame({"duration": [4.0, float("nan"), None]})
    processing = TabularProcessing(
        literal_columns={"eligible": True},
        conditional_assignments=[
            ConditionalAssignment(
                column="eligible",
                when=[ColumnPredicate(column="duration", operator="is_nan")],
                value_source={"kind": "literal", "value": False},
            )
        ],
        filter_rows=[ColumnPredicate(column="eligible", operator="eq", value=True)],
    )
    data_file = DataFile(name="duration-eligibility", fpath=sample_csv, proc_spec=processing)

    result = process_tabular_data(frame.lazy(), data_file=data_file, proc_spec=processing).collect()

    assert result["duration"].to_list() == [4.0, None]


def test_grouped_fallback_fill_respects_groups_and_where_condition(sample_csv: Path):
    frame = pl.DataFrame(
        {
            "technology": ["a", "a", "b", "b"],
            "vintage": ["v1", "v1", "v1", "v1"],
            "thermal": [True, True, False, True],
            "heat_rate": [20.0, None, None, None],
        }
    )
    processing = TabularProcessing(
        fill_null_by_group=[
            GroupedFillSpec(
                column="heat_rate",
                group_by=["technology", "vintage"],
                fallback=10.0,
                where={"thermal": True},
            )
        ]
    )
    data_file = DataFile(name="heat-rates", fpath=sample_csv, proc_spec=processing)

    result = process_tabular_data(frame.lazy(), data_file=data_file, proc_spec=processing).collect()

    assert result["heat_rate"].to_list() == [20.0, 20.0, None, 10.0]


def test_grouped_fallback_fill_handles_entirely_null_columns(sample_csv: Path):
    frame = pl.DataFrame(
        {"technology": ["a", "a"], "heat_rate": [None, None]},
        schema={"technology": pl.String, "heat_rate": pl.Null},
    )
    processing = TabularProcessing(
        fill_null_by_group=[GroupedFillSpec(column="heat_rate", group_by=["technology"], fallback=10.0)]
    )
    data_file = DataFile(name="heat-rates", fpath=sample_csv, proc_spec=processing)

    result = process_tabular_data(frame.lazy(), data_file=data_file, proc_spec=processing).collect()

    assert result["heat_rate"].to_list() == [10.0, 10.0]
    assert result.schema["heat_rate"] == pl.Float64


def test_grouped_fallback_fill_reports_missing_columns(sample_csv: Path):
    frame = pl.DataFrame({"technology": ["a"], "heat_rate": [None]})
    processing = TabularProcessing(
        fill_null_by_group=[GroupedFillSpec(column="heat_rate", group_by=["vintage"], fallback=10.0)]
    )
    data_file = DataFile(name="heat-rates", fpath=sample_csv, proc_spec=processing)

    with pytest.raises(ValueError, match=r"fill_null_by_group.*vintage"):
        process_tabular_data(frame.lazy(), data_file=data_file, proc_spec=processing)


def test_drop_columns_after_removes_intermediates_after_conditional_processing(sample_csv: Path):
    processing = TabularProcessing(
        drop_columns_after=["source", "flag"],
        conditional_assignments=[
            ConditionalAssignment(
                column="rate",
                when=[ColumnPredicate(column="flag", operator="eq", value=True)],
                value_source={"kind": "column", "column": "source"},
            )
        ],
    )
    data = pl.DataFrame({"source": [12.0], "flag": [True], "rate": [1.0]})
    data_file = DataFile(name="drop-intermediates", fpath=sample_csv, proc_spec=processing)

    result = process_tabular_data(data.lazy(), data_file=data_file, proc_spec=processing).collect()

    assert result.to_dicts() == [{"rate": 12.0}]


def test_conditional_assignment_model_dump_preserves_a_literal_null(sample_csv: Path):
    assignment = ConditionalAssignment.model_validate(
        {
            "column": "rate",
            "when": [{"column": "replace", "operator": "eq", "value": True}],
            "value_source": {"kind": "literal", "value": None},
        }
    )
    restored = ConditionalAssignment.model_validate(assignment.model_dump())
    processing = TabularProcessing(conditional_assignments=[restored])
    data = pl.DataFrame({"rate": [0.0], "replace": [True]})
    data_file = DataFile(name="conditional-null", fpath=sample_csv, proc_spec=processing)

    result = process_tabular_data(data.lazy(), data_file=data_file, proc_spec=processing).collect()

    assert result["rate"].to_list() == [None]


def test_conditional_assignments_are_ordered_and_addition_preserves_nulls(sample_csv: Path):
    frame = pl.DataFrame(
        {
            "technology": ["dpv", "hydro", "psh", "base_zero", "unknown"],
            "fom_cost": [80.0, 20.0, 30.0, 0.0, None],
            "distpv": ["yes", "no", "no", "no", "no"],
            "hintage_fom_cost": [0.0, 10.0, 20.0, 0.0, 0.0],
            "hydro_fom_cost": [0.0, 42.0, 42.0, 0.0, 0.0],
            "psh": ["no", "no", "yes", "no", "no"],
            "initial_target_fom": [None, 0.0, 100.0, 0.0, None],
            "target_hydro_fom": [5.0, None, 0.0, 0.0, 5.0],
        }
    )
    processing = TabularProcessing(
        fill_null={"target_hydro_fom": 0.0},
        column_add=[
            ColumnAddSpec(
                target="initial_target_fom",
                left="initial_target_fom",
                right="target_hydro_fom",
            )
        ],
        conditional_assignments=[
            ConditionalAssignment(
                column="fom_cost",
                when=[ColumnPredicate(column="distpv", operator="eq", value="yes")],
                value_source={"kind": "column", "column": "hintage_fom_cost"},
            ),
            ConditionalAssignment(
                column="fom_cost",
                when=[ColumnPredicate(column="hydro_fom_cost", operator="ne", value=0.0)],
                value_source={"kind": "column", "column": "hydro_fom_cost"},
            ),
            ConditionalAssignment(
                column="fom_cost",
                when=[ColumnPredicate(column="psh", operator="eq", value="yes")],
                value_source={"kind": "literal", "value": 130.0},
            ),
        ],
    )
    data_file = DataFile(name="generator-fom", fpath=sample_csv, proc_spec=processing)

    result = process_tabular_data(frame.lazy(), data_file=data_file, proc_spec=processing).collect()

    assert result["fom_cost"].to_list() == [0.0, 42.0, 130.0, 0.0, None]
    assert result["initial_target_fom"].to_list() == [None, 0.0, 100.0, 0.0, None]


def test_conditional_row_validation_rejects_only_matching_rows(sample_csv: Path):
    frame = pl.DataFrame(
        {"technology": ["unknown", "upgrade"], "upgraded": [False, True], "fom_cost": [None, None]}
    )
    processing = TabularProcessing(
        reject_rows=[
            RejectRowsSpec(
                when=[
                    ColumnPredicate(column="upgraded", operator="eq", value=True),
                    ColumnPredicate(column="fom_cost", operator="is_null"),
                ],
                message="upgrade target has no FOM",
            )
        ]
    )
    data_file = DataFile(name="generator-fom", fpath=sample_csv, proc_spec=processing)

    with pytest.raises(ValueError, match="upgrade target has no FOM"):
        process_tabular_data(frame.lazy(), data_file=data_file, proc_spec=processing)

    unknown = frame.filter(pl.col("technology") == "unknown")
    assert (
        process_tabular_data(unknown.lazy(), data_file=data_file, proc_spec=processing).collect().height == 1
    )


def test_weighted_mean_uses_explicit_unknown_and_nonpositive_policies(sample_csv: Path):
    frame = pl.DataFrame(
        {
            "technology": ["a", "a", "b", "b"],
            "capacity": [1.0, 3.0, 0.0, 0.0],
            "fom_cost": [10.0, 20.0, 5.0, 7.0],
        }
    )
    processing = TabularProcessing(
        group_by=["technology"],
        aggregate_on={"capacity": "sum"},
        weighted_mean={
            "fom_cost": WeightedMeanSpec(
                weight_column="capacity",
                unknown_positive_weight="propagate",
                nonpositive_total="null",
                null_weight="ignore",
            )
        },
    )
    data_file = DataFile(name="generator-costs", fpath=sample_csv, proc_spec=processing)

    result = (
        process_tabular_data(frame.lazy(), data_file=data_file, proc_spec=processing)
        .collect()
        .sort("technology")
    )

    assert result.to_dicts() == [
        {"technology": "a", "capacity": 4.0, "fom_cost": 17.5},
        {"technology": "b", "capacity": 0.0, "fom_cost": None},
    ]


def test_weighted_mean_ignore_excludes_unknown_values_from_both_sums(sample_csv: Path):
    frame = pl.DataFrame({"technology": ["a", "a"], "capacity": [1.0, 1.0], "fom_cost": [10.0, None]})
    processing = TabularProcessing(
        group_by=["technology"],
        weighted_mean={
            "fom_cost": WeightedMeanSpec(
                weight_column="capacity",
                unknown_positive_weight="ignore",
                nonpositive_total="null",
                null_weight="ignore",
            )
        },
    )
    data_file = DataFile(name="generator-costs", fpath=sample_csv, proc_spec=processing)

    result = process_tabular_data(frame.lazy(), data_file=data_file, proc_spec=processing).collect()

    assert result.to_dicts() == [{"technology": "a", "fom_cost": 10.0}]


def test_weighted_mean_cannot_be_combined_with_pivot_on():
    with pytest.raises(ValueError, match="weighted_mean is not supported with pivot_on"):
        TabularProcessing(
            pivot_on="kind",
            group_by=["group"],
            aggregate_on={"weight": "sum"},
            weighted_mean={
                "value": WeightedMeanSpec(
                    weight_column="weight",
                    unknown_positive_weight="propagate",
                    nonpositive_total="null",
                    null_weight="ignore",
                )
            },
        )


def test_weighted_mean_propagates_unknown_positive_weight_and_rejects_bad_weights(sample_csv: Path):
    processing = TabularProcessing(
        group_by=["technology"],
        weighted_mean={
            "fom_cost": WeightedMeanSpec(
                weight_column="capacity",
                unknown_positive_weight="propagate",
                nonpositive_total="error",
                null_weight="error",
            )
        },
    )
    data_file = DataFile(name="generator-costs", fpath=sample_csv, proc_spec=processing)
    unknown = pl.DataFrame({"technology": ["a", "a"], "capacity": [1.0, 1.0], "fom_cost": [10.0, None]})
    unknown_result = process_tabular_data(unknown.lazy(), data_file=data_file, proc_spec=processing).collect()
    assert unknown_result["fom_cost"].to_list() == [None]

    nonpositive = pl.DataFrame({"technology": ["a"], "capacity": [0.0], "fom_cost": [10.0]})
    with pytest.raises(ValueError, match="nonpositive total weight"):
        process_tabular_data(nonpositive.lazy(), data_file=data_file, proc_spec=processing)

    missing_weight = pl.DataFrame(
        {"technology": ["a"], "capacity": [None], "fom_cost": [10.0]},
        schema={"technology": pl.String, "capacity": pl.Null, "fom_cost": pl.Float64},
    )
    with pytest.raises(ValueError, match="null weight"):
        process_tabular_data(missing_weight.lazy(), data_file=data_file, proc_spec=processing)


def test_ensured_null_column_is_cast_and_filled(sample_csv: Path) -> None:
    """Missing optional columns enter the recipe before casts and fills."""
    frame = pl.DataFrame({"technology": ["Gas-CC"]}).lazy()
    specification = TabularProcessing(
        ensure_null_columns=["heat_rate"],
        column_schema={"heat_rate": "float"},
        fill_null={"heat_rate": 10.0},
    )
    source = DataFile(name="generator inputs", fpath=sample_csv)

    result = process_tabular_data(frame, data_file=source, proc_spec=specification).collect()

    assert result.schema["heat_rate"] == pl.Float64
    assert result["heat_rate"].to_list() == [10.0]


def test_ensure_null_columns_adds_only_absent_columns(sample_csv: Path) -> None:
    frame = pl.DataFrame({"id": [1, 2], "present": [3.0, 4.0]})
    processing = TabularProcessing(ensure_null_columns=["missing", "present"])
    data_file = DataFile(name="optional-aggregates", fpath=sample_csv, proc_spec=processing)

    result = process_tabular_data(frame.lazy(), data_file=data_file, proc_spec=processing).collect()

    assert result.to_dicts() == [
        {"id": 1, "present": 3.0, "missing": None},
        {"id": 2, "present": 4.0, "missing": None},
    ]


def test_literal_columns_are_added_after_column_renaming(sample_csv: Path):
    frame = pl.LazyFrame({"f": [2.0]})
    processing = TabularProcessing(
        column_mapping={"f": "fuel_price"},
        literal_columns={"fuel_type": "biomass"},
    )
    data_file = DataFile(name="biofuel-prices", fpath=sample_csv, proc_spec=processing)

    result = process_tabular_data(frame, data_file=data_file, proc_spec=processing).collect()

    assert result.to_dicts() == [{"fuel_price": 2.0, "fuel_type": "biomass"}]


def test_json_rename_keys_renames_keys(sample_json_file: Path):
    """Test that key_mapping renames JSON keys."""
    data = {"name": "Alice", "age": 30, "city": "NYC"}
    proc_spec = JSONProcessing(key_mapping={"name": "person_name", "age": "person_age"})
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_rename_keys(data, data_file=df_file, proc_spec=proc_spec)
    assert isinstance(result, dict)

    assert "person_name" in result
    assert "person_age" in result
    assert "name" not in result
    assert "age" not in result
    assert result["person_name"] == "Alice"


def test_json_apply_filters_filters_by_value(sample_json_file: Path):
    """Test that JSON filtering works correctly."""
    data = {"name": "Alice", "age": 30, "city": "NYC", "score": 85.5}
    proc_spec = JSONProcessing(filter_by={"age": 30})
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_apply_filters(data, data_file=df_file, proc_spec=proc_spec)

    assert "age" in result


def test_json_apply_filters_filters_list_values(sample_json_file: Path):
    """Test that JSON filtering works with lists."""
    data = {"name": "Alice", "age": 30, "city": "NYC"}
    proc_spec = JSONProcessing(filter_by={"name": ["Alice", "Bob"]})
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_apply_filters(data, data_file=df_file, proc_spec=proc_spec)

    assert "name" in result


def test_json_select_keys_keeps_specified_keys(sample_json_file: Path):
    """Test that select_keys keeps only specified keys."""
    data = {"name": "Alice", "age": 30, "city": "NYC", "score": 85.5}
    proc_spec = JSONProcessing(select_keys=["name", "score"])
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_select_keys(data, data_file=df_file, proc_spec=proc_spec)
    assert isinstance(result, dict)

    assert set(result.keys()) == {"name", "score"}
    assert result["name"] == "Alice"
    assert result["score"] == 85.5


def test_json_apply_filters_with_no_match(sample_json_file: Path):
    """Test that JSON filtering returns data when no match."""
    data = {"name": "Bob", "age": 25, "city": "LA"}
    proc_spec = JSONProcessing(filter_by={"age": 30})
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_apply_filters(data, data_file=df_file, proc_spec=proc_spec)

    # Should not match - returns dict as-is or filtered
    assert isinstance(result, dict)


def test_json_apply_filters_with_list_of_dicts(sample_json_file: Path):
    """Test that JSON filtering works with list of dicts."""
    data = [
        {"name": "Alice", "age": 30, "city": "NYC"},
        {"name": "Bob", "age": 30, "city": "LA"},
        {"name": "Charlie", "age": 25, "city": "CHI"},
    ]
    proc_spec = JSONProcessing(filter_by={"age": 30})
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_apply_filters(data, data_file=df_file, proc_spec=proc_spec)
    assert isinstance(result, list)

    assert len(result) == 2
    assert isinstance(result[0], dict)
    assert isinstance(result[1], dict)
    assert result[0]["name"] == "Alice"
    assert result[1]["name"] == "Bob"


def test_pl_select_columns(sample_csv: Path):
    """Test select_columns."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(select_columns=["name", "age"])
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result, _ = pl_select_columns(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert set(result.columns) == {"name", "age"}


def test_pl_select_columns_missing_column_is_explicit_error(sample_csv: Path):
    """Test that missing selected columns fail with an actionable error."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(select_columns=["nonexistent"])
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    with pytest.raises(ValueError, match=r"select_columns.*nonexistent"):
        pl_select_columns(lf, data_file=df_file, proc_spec=proc_spec)


def test_pl_apply_filters_no_filters(sample_csv: Path):
    """Test apply_filters with no filters specified."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(filter_by=None)
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result, _ = pl_apply_filters(lf, data_file=df_file, proc_spec=proc_spec)

    # Should return unchanged - verify by collecting and checking
    assert result.collect().equals(lf.collect())


def test_pl_drop_columns_all_removed(sample_csv: Path):
    """Test drop_columns when all columns are removed."""
    lf = pl.scan_csv(sample_csv)
    schema_names = lf.collect_schema().names()
    proc_spec = TabularProcessing(drop_columns=schema_names)
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result, new_names = pl_drop_columns(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert len(result.columns) == 0
    assert len(new_names) == 0


def test_pl_cast_schema_missing_column_is_explicit_error(sample_csv: Path):
    """Test that missing cast columns fail with an actionable error."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(column_schema={"nonexistent": "int32"})
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    with pytest.raises(ValueError, match=r"column_schema.*nonexistent"):
        pl_cast_schema(lf, data_file=df_file, proc_spec=proc_spec)


def test_apply_processing_with_no_proc_spec(sample_csv: Path):
    lf = pl.scan_csv(sample_csv)
    df_file = DataFile(name="test", fpath=sample_csv)

    result = apply_processing(lf, data_file=df_file, proc_spec=None)
    assert result.is_ok()
    assert result.unwrap().collect().equals(lf.collect())


def test_apply_processing_with_unregistered_type(sample_csv: Path):
    class UnregisteredType:
        pass

    df_file = DataFile(name="test", fpath=sample_csv)
    proc_spec = TabularProcessing()
    unregistered_data = UnregisteredType()

    result = apply_processing(unregistered_data, data_file=df_file, proc_spec=proc_spec)
    assert result.is_ok()
    assert isinstance(result.unwrap(), UnregisteredType)


def test_apply_processing_with_placeholder_substitution(sample_csv: Path):
    lf = pl.scan_csv(sample_csv)
    df_file = DataFile(name="test", fpath=sample_csv)
    proc_spec = TabularProcessing(filter_by={"name": "{year}"})

    result = apply_processing(lf, data_file=df_file, proc_spec=proc_spec, placeholders={"year": "Alice"})
    assert result.is_ok()


def test_apply_processing_placeholder_error(sample_csv: Path):
    lf = pl.scan_csv(sample_csv)
    df_file = DataFile(name="test", fpath=sample_csv)
    proc_spec = TabularProcessing(filter_by={"name": "{missing}"})

    result = apply_processing(lf, data_file=df_file, proc_spec=proc_spec, placeholders={"year": 2030})
    assert result.is_err()


def test_filter_rows_list_placeholder_round_trips_and_resolves(sample_csv: Path):
    predicate = ColumnPredicate.model_validate({"column": "region", "operator": "in", "value": "{regions}"})
    restored = ColumnPredicate.model_validate(predicate.model_dump())
    proc_spec = TabularProcessing(filter_rows=[restored])
    result = apply_processing(
        pl.LazyFrame({"region": ["p1", "p2", "p3"]}),
        data_file=DataFile(name="region-filter", fpath=sample_csv),
        proc_spec=proc_spec,
        placeholders={"regions": ["p1", "p3"]},
    )

    assert result.is_ok()
    assert result.unwrap().collect()["region"].to_list() == ["p1", "p3"]


def test_filter_rows_empty_list_placeholder_matches_no_rows(sample_csv: Path):
    proc_spec = TabularProcessing(filter_rows=[{"column": "region", "operator": "in", "value": "{regions}"}])
    result = apply_processing(
        pl.LazyFrame({"region": ["p1"]}),
        data_file=DataFile(name="empty-region-filter", fpath=sample_csv),
        proc_spec=proc_spec,
        placeholders={"regions": []},
    )

    assert result.is_ok()
    assert result.unwrap().collect().is_empty()


@pytest.mark.parametrize("placeholder", ["p1", 1, None])
def test_filter_rows_list_placeholder_rejects_non_list_values(sample_csv: Path, placeholder: object):
    proc_spec = TabularProcessing(filter_rows=[{"column": "region", "operator": "in", "value": "{regions}"}])
    result = apply_processing(
        pl.LazyFrame({"region": ["p1"]}),
        data_file=DataFile(name="invalid-region-filter", fpath=sample_csv),
        proc_spec=proc_spec,
        placeholders={"regions": placeholder},
    )

    assert result.is_err()
    assert "Invalid processing specification" in str(result.err())


def test_filter_rows_list_placeholder_rejects_unresolved_names(sample_csv: Path):
    proc_spec = TabularProcessing(
        filter_rows=[{"column": "region", "operator": "in", "value": "{missing_regions}"}]
    )
    result = apply_processing(
        pl.LazyFrame({"region": ["p1"]}),
        data_file=DataFile(name="unresolved-region-filter", fpath=sample_csv),
        proc_spec=proc_spec,
        placeholders={"regions": ["p1"]},
    )

    assert result.is_err()
    assert "Placeholder '{missing_regions}' not found" in str(result.err())


def test_explode_columns_preserves_empty_category_rows():
    frame = pl.DataFrame({"owner": ["wind", "unknown"], "categories": [["wind", "renewable"], []]})
    spec = TabularProcessing(explode_columns=["categories"])

    result = process_tabular_data(frame.lazy(), data_file=SimpleNamespace(name="categories"), proc_spec=spec)

    assert result.collect().to_dicts() == [
        {"owner": "wind", "categories": "wind"},
        {"owner": "wind", "categories": "renewable"},
        {"owner": "unknown", "categories": None},
    ]


def test_unique_sorted_aggregation_returns_deterministic_distinct_lists():
    frame = pl.DataFrame({"owner": ["a", "a", "a", "b"], "reserve_name": ["z", "a", "z", "b"]})
    spec = TabularProcessing(
        group_by=["owner"],
        aggregate_on={"reserve_name": "unique_sorted"},
        sort_by={"owner": "asc"},
    )

    result = process_tabular_data(frame.lazy(), data_file=SimpleNamespace(name="memberships"), proc_spec=spec)

    assert result.collect().to_dicts() == [
        {"owner": "a", "reserve_name": ["a", "z"]},
        {"owner": "b", "reserve_name": ["b"]},
    ]


def test_column_concat_uses_explicit_separator_and_propagates_nulls():
    frame = pl.DataFrame({"region": ["controlled", None], "product": ["SPINNING", "FLEXIBILITY"]})
    spec = TabularProcessing(
        column_concat=[{"target": "reserve_name", "columns": ["region", "product"], "separator": "_"}]
    )

    result = process_tabular_data(frame.lazy(), data_file=SimpleNamespace(name="identities"), proc_spec=spec)

    assert result.collect()["reserve_name"].to_list() == ["controlled_SPINNING", None]


def test_column_struct_builds_nested_mapping_values():
    frame = pl.DataFrame({"reserve_names": [["region_SPINNING", "region_REGULATION"]]})
    spec = TabularProcessing(column_struct={"ext": {"reserves": "reserve_names"}})

    result = process_tabular_data(frame.lazy(), data_file=SimpleNamespace(name="extensions"), proc_spec=spec)

    assert result.collect().to_dicts() == [
        {
            "reserve_names": ["region_SPINNING", "region_REGULATION"],
            "ext": {"reserves": ["region_SPINNING", "region_REGULATION"]},
        }
    ]


def test_filter_rows_in_rejects_arbitrary_strings():
    with pytest.raises(ValueError, match="complete placeholder"):
        ColumnPredicate(column="region", operator="in", value="p1")


def test_apply_processing_substitutes_transformation_values(sample_csv: Path):
    """Substitute placeholders in non-filter tabular operations."""
    lf = pl.LazyFrame({"name": ["a", "b"], "amount": [1, 2]})
    df_file = DataFile(name="test", fpath=sample_csv)
    proc_spec = TabularProcessing(sort_by={"amount": "{direction}"})

    result = apply_processing(
        lf,
        data_file=df_file,
        proc_spec=proc_spec,
        placeholders={"direction": "desc"},
    )
    assert result.is_ok()
    assert result.unwrap().collect()["amount"].to_list() == [2, 1]


def test_apply_processing_rejects_invalid_substituted_transformation(sample_csv: Path):
    """Return a Result error when a placeholder resolves to invalid settings."""
    proc_spec = TabularProcessing(sort_by={"amount": "{direction}"})
    result = apply_processing(
        pl.LazyFrame({"amount": [1]}),
        data_file=DataFile(name="test", fpath=sample_csv),
        proc_spec=proc_spec,
        placeholders={"direction": "sideways"},
    )
    assert result.is_err()
    assert "Invalid processing specification" in str(result.err())


def test_apply_processing_substitutes_typed_transformation_values(sample_csv: Path):
    proc_spec = TabularProcessing(lowercase="{enabled}", scale={"amount": "{factor}"})
    result = apply_processing(
        pl.LazyFrame({"AMOUNT": [2.0]}),
        data_file=DataFile(name="typed-placeholders", fpath=sample_csv),
        proc_spec=proc_spec,
        placeholders={"enabled": True, "factor": 0.5},
    )

    assert result.is_ok()
    assert result.unwrap().collect().to_dicts() == [{"amount": 1.0}]


@pytest.mark.parametrize(
    ("config", "placeholders"),
    [
        ({"lowercase": "{enabled}"}, {"enabled": "not-a-bool"}),
        ({"scale": {"amount": "{factor}"}}, {"factor": float("inf")}),
    ],
)
def test_apply_processing_revalidates_typed_placeholders(
    sample_csv: Path,
    config: dict[str, object],
    placeholders: dict[str, bool | float | str],
):
    proc_spec = TabularProcessing(**config)
    result = apply_processing(
        pl.LazyFrame({"amount": [2.0]}),
        data_file=DataFile(name="invalid-typed-placeholder", fpath=sample_csv),
        proc_spec=proc_spec,
        placeholders=placeholders,
    )

    assert result.is_err()
    assert "Invalid processing specification" in str(result.err())


def test_json_select_columns_with_nested_list(sample_json_file: Path):
    from r2x_core.processors import json_select_columns

    data = [
        {"name": "Alice", "age": 30, "city": "NYC"},
        {"name": "Bob", "age": 25, "city": "LA"},
    ]
    proc_spec = JSONProcessing(select_keys=["name", "city"])
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_select_columns(data, data_file=df_file, proc_spec=proc_spec)

    assert len(result) == 2
    assert all(isinstance(item, dict) and set(item.keys()) == {"name", "city"} for item in result)


def test_json_rename_keys_with_list(sample_json_file: Path):
    from r2x_core.processors import json_rename_keys

    data = [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
    ]
    proc_spec = JSONProcessing(key_mapping={"name": "person_name", "age": "years"})
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_rename_keys(data, data_file=df_file, proc_spec=proc_spec)

    assert len(result) == 2
    assert all("person_name" in item for item in result)
    assert all("years" in item for item in result)


def test_json_drop_columns_with_list(sample_json_file: Path):
    from r2x_core.processors import json_drop_columns

    data = [
        {"name": "Alice", "age": 30, "city": "NYC"},
        {"name": "Bob", "age": 25, "city": "LA"},
    ]
    proc_spec = JSONProcessing(drop_keys=["city"])
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_drop_columns(data, data_file=df_file, proc_spec=proc_spec)

    assert len(result) == 2
    assert all("city" not in item for item in result)
    assert all("name" in item for item in result)


def test_process_tabular_data_full_pipeline(sample_csv: Path):
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(
        column_mapping={"name": "person_name"},
        filter_by={"age": 30},
    )
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    result = process_tabular_data(lf, data_file=df_file, proc_spec=proc_spec).collect()

    assert "person_name" in result.columns
    assert len(result) >= 0


def test_process_json_data_full_pipeline(sample_json_file: Path):
    from r2x_core.processors import process_json_data

    data = {
        "users": [
            {"name": "Alice", "age": 30, "status": "active"},
            {"name": "Bob", "age": 25, "status": "inactive"},
        ]
    }
    proc_spec = JSONProcessing(
        key_mapping={"name": "person_name"},
        drop_keys=["status"],
    )
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = process_json_data(data, data_file=df_file, proc_spec=proc_spec)

    assert result is not None


def test_pl_apply_filters_datetime_single_year(sample_csv: Path):
    csv_file = sample_csv.parent / "datetime_data.csv"
    csv_file.write_text("date,value\n2020,100\n2021,200\n")

    lf = pl.scan_csv(csv_file)
    proc_spec = TabularProcessing(filter_by={"date": 2020})
    df_file = DataFile(name="test", fpath=csv_file, proc_spec=proc_spec)

    result, _ = pl_apply_filters(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert result is not None


def test_pl_apply_filters_datetime_multiple_years(sample_csv: Path):
    csv_file = sample_csv.parent / "datetime_data2.csv"
    csv_file.write_text("year,value\n2020,100\n2021,200\n2022,150\n")

    lf = pl.scan_csv(csv_file)
    proc_spec = TabularProcessing(filter_by={"year": [2020, 2021]})
    df_file = DataFile(name="test", fpath=csv_file, proc_spec=proc_spec)

    result, _ = pl_apply_filters(lf, data_file=df_file, proc_spec=proc_spec)
    result = result.collect()

    assert result is not None


def test_substitute_placeholders_non_string_passthrough():
    """Test substitute_placeholders returns non-string/list/dict values unchanged."""
    result = substitute_placeholders(42, placeholders={"x": 1})
    assert result.is_ok()
    assert result.unwrap() == 42

    result = substitute_placeholders(3.14, placeholders={"x": 1})
    assert result.is_ok()
    assert result.unwrap() == 3.14


def test_substitute_placeholders_string_without_placeholder():
    """Test substitute_placeholders returns string without braces unchanged."""
    result = substitute_placeholders("plain text", placeholders={"x": 1})
    assert result.is_ok()
    assert result.unwrap() == "plain text"


def test_substitute_placeholders_supports_embedded_values():
    """Substitute placeholders embedded in surrounding text."""
    result = substitute_placeholders("prefix_{variable}.csv", placeholders={"variable": 2030})
    assert result.is_ok()
    assert result.unwrap() == "prefix_2030.csv"


def test_substitute_placeholders_rejects_unknown_embedded_values():
    result = substitute_placeholders("prefix_{missing}.csv", placeholders={"year": 2030})
    assert result.is_err()
    assert "{missing}" in str(result.err())


def test_substitute_placeholders_list_error_propagation():
    """Test substitute_placeholders propagates errors from list items."""
    result = substitute_placeholders(["{valid}", "{missing}"], placeholders={"valid": 1})
    assert result.is_err()
    assert "missing" in str(result.err())


def test_pl_apply_filters_missing_column_is_explicit_error(sample_csv: Path):
    """Test that missing filter columns fail with an actionable error."""
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(filter_by={"nonexistent_column": "value"})
    df_file = DataFile(name="test", fpath=sample_csv, proc_spec=proc_spec)

    with pytest.raises(ValueError, match=r"filter_by.*nonexistent_column"):
        pl_apply_filters(lf, data_file=df_file, proc_spec=proc_spec)


def test_tabular_value_transformations(sample_csv: Path):
    """Apply replacement, null filling, sorting, and deduplication."""
    frame = pl.LazyFrame({"region": ["West", "West", "East"], "value": [None, 2, 1]})
    proc_spec = TabularProcessing(
        lowercase=True,
        replace_values={"west": "north"},
        fill_null={"value": 0},
        distinct_on=["region", "value"],
        sort_by={"value": "descending"},
        select_columns=["region", "value"],
    )
    data_file = DataFile(name="values", fpath=sample_csv, proc_spec=proc_spec)

    result = process_tabular_data(frame, data_file=data_file, proc_spec=proc_spec).collect()
    assert result.to_dicts() == [
        {"region": "north", "value": 2},
        {"region": "east", "value": 1},
        {"region": "north", "value": 0},
    ]


def test_tabular_long_to_wide_pivot_count(sample_csv: Path):
    frame = pl.LazyFrame(
        {
            "region": ["West", "West", "East"],
            "year": [2020, 2020, 2020],
            "amount": [1, None, 3],
        }
    )
    proc_spec = TabularProcessing(
        pivot_on="year",
        group_by=["region"],
        aggregate_on={"amount": "count"},
    )
    data_file = DataFile(name="counts", fpath=sample_csv, proc_spec=proc_spec)

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        result = process_tabular_data(frame, data_file=data_file, proc_spec=proc_spec).collect()

    assert {row["region"]: row["2020"] for row in result.to_dicts()} == {"West": 1, "East": 1}


def test_pivot_key_matching_source_column_does_not_aggregate_twice(sample_csv: Path):
    frame = pl.LazyFrame({"id": ["a", "a"], "year": ["year", "2020"], "value": [1, 2]})
    proc_spec = TabularProcessing(
        pivot_on="year",
        group_by=["id"],
        aggregate_on={"value": "sum"},
    )
    data_file = DataFile(name="pivot-key-collision", fpath=sample_csv, proc_spec=proc_spec)

    result = process_tabular_data(frame, data_file=data_file, proc_spec=proc_spec).collect()

    assert result.to_dicts() == [{"id": "a", "year": 1, "2020": 2}]


def test_tabular_long_to_wide_pivot(sample_csv: Path):
    """Pivot long-form rows using grouped value aggregation."""
    frame = pl.LazyFrame(
        {
            "region": ["West", "West", "West"],
            "year": [2020, 2020, 2021],
            "amount": [1, 2, 3],
        }
    )
    proc_spec = TabularProcessing(
        pivot_on="year",
        group_by=["region"],
        aggregate_on={"amount": "sum"},
    )
    data_file = DataFile(name="annual", fpath=sample_csv, proc_spec=proc_spec)

    result = process_tabular_data(frame, data_file=data_file, proc_spec=proc_spec).collect()
    assert result.to_dicts() == [{"region": "West", "2021": 3, "2020": 3}]


def test_unpivot_pipeline_renames_casts_and_filters(sample_csv: Path):
    frame = pl.LazyFrame(
        {
            "region": ["NYISO", "PJM"],
            "2025": [10, 20],
            "2030": [30, 40],
        }
    )
    proc_spec = TabularProcessing(
        unpivot_on=["2025", "2030"],
        column_mapping={"variable": "year", "value": "capacity_mw"},
        column_schema={"year": "int"},
        filter_by={"year": "{solve_year}"},
        select_columns=["region", "year", "capacity_mw"],
    )
    data_file = DataFile(name="annual", fpath=sample_csv, proc_spec=proc_spec)

    result = apply_processing(
        frame,
        data_file=data_file,
        proc_spec=proc_spec,
        placeholders={"solve_year": 2030},
    )

    assert result.is_ok()
    assert result.unwrap().collect().to_dicts() == [
        {"region": "NYISO", "year": 2030, "capacity_mw": 30},
        {"region": "PJM", "year": 2030, "capacity_mw": 40},
    ]


def test_tabular_processing_preserves_case_by_default(sample_csv: Path):
    frame = pl.LazyFrame({"Technology": ["Gas & FO"]})
    data_file = DataFile(name="technology", fpath=sample_csv)

    preserved = process_tabular_data(frame, data_file=data_file, proc_spec=TabularProcessing()).collect()
    lowered = process_tabular_data(
        frame, data_file=data_file, proc_spec=TabularProcessing(lowercase=True)
    ).collect()

    assert preserved.columns == ["Technology"]
    assert preserved["Technology"].to_list() == ["Gas & FO"]
    assert lowered.columns == ["technology"]
    assert lowered["technology"].to_list() == ["gas & fo"]


def test_tabular_numeric_string_cleanup(sample_csv: Path):
    frame = pl.LazyFrame(
        {
            "limit": ["2,450"],
            "price": ["$4.99 "],
            "share": ["171.20%"],
            "count": ["-"],
        }
    )
    proc_spec = TabularProcessing(
        replace_values={"-": "0"},
        strip_chars={"limit": [","], "price": ["$"], "share": ["%"]},
        column_schema={"limit": "float", "price": "float", "share": "float", "count": "float"},
        scale={"share": 0.01},
    )
    data_file = DataFile(name="formatted", fpath=sample_csv)

    result = process_tabular_data(frame, data_file=data_file, proc_spec=proc_spec).collect()

    assert result.to_dicts() == [{"limit": 2450.0, "price": 4.99, "share": 1.712, "count": 0.0}]


def test_apply_processing_returns_err_for_invalid_transformation(sample_csv: Path):
    result = apply_processing(
        pl.LazyFrame({"a": [1]}),
        data_file=DataFile(name="missing-column", fpath=sample_csv),
        proc_spec=TabularProcessing(filter_by={"missing": "x"}),
    )

    assert result.is_err()
    assert "filter_by" in str(result.err())


def test_null_pivot_keys_are_rejected(sample_csv: Path):
    result = apply_processing(
        pl.LazyFrame({"id": ["a", "a"], "year": [None, 2020], "value": [1, 2]}),
        data_file=DataFile(name="null-pivot", fpath=sample_csv),
        proc_spec=TabularProcessing(pivot_on="year", group_by=["id"], aggregate_on={"value": "sum"}),
    )

    assert result.is_err()
    assert "null" in str(result.err()).lower()


def test_tabular_unpivot_group_aggregate_pipeline(sample_csv: Path):
    """Compose unpivot, grouping, aggregation, sorting, and selection."""
    frame = pl.LazyFrame(
        {
            "region": ["West", "West", "East"],
            "jan": [1, 3, 2],
            "feb": [2, 1, 4],
        }
    )
    proc_spec = TabularProcessing(
        lowercase=True,
        unpivot_on=["jan", "feb"],
        group_by=["region", "variable"],
        aggregate_on={"value": "sum"},
        sort_by={"value": "descending"},
        select_columns=["region", "variable", "value"],
    )
    data_file = DataFile(name="monthly", fpath=sample_csv, proc_spec=proc_spec)

    result = process_tabular_data(frame, data_file=data_file, proc_spec=proc_spec).collect()
    assert result["value"].to_list() == [4, 4, 3, 2]
    assert {tuple(row.values()) for row in result.to_dicts()} == {
        ("east", "feb", 4),
        ("west", "jan", 4),
        ("west", "feb", 3),
        ("east", "jan", 2),
    }


def test_tabular_processing_rejects_invalid_aggregation():
    """Reject unsupported aggregation functions during configuration validation."""
    with pytest.raises(ValueError, match="Unsupported aggregation function"):
        TabularProcessing(aggregate_on={"value": "average"})


@pytest.mark.parametrize("function", ["n_unique", "std", "var"])
def test_tabular_processing_rejects_pivot_aggregations_unsupported_by_polars(function: str):
    with pytest.raises(ValueError, match="pivot_on does not support"):
        TabularProcessing(
            pivot_on="year",
            group_by=["region"],
            aggregate_on={"amount": function},
        )


def test_tabular_processing_rejects_unsupported_index_configuration():
    """Reject pandas index settings that Polars cannot represent."""
    with pytest.raises(ValueError, match="extra_forbidden"):
        TabularProcessing(set_index="id")


def test_tabular_processing_rejects_invalid_combinations():
    """Reject ambiguous reshape and aggregation configurations."""
    with pytest.raises(ValueError, match="mutually exclusive"):
        TabularProcessing(pivot_on="year", unpivot_on=["amount"])
    with pytest.raises(ValueError, match="requires aggregate_on"):
        TabularProcessing(group_by=["region"])
    with pytest.raises(ValueError, match="group_by column"):
        TabularProcessing(group_by=["region"], aggregate_on={"region": "count"})
    with pytest.raises(ValueError, match="sort direction"):
        TabularProcessing(sort_by={"value": "sideways"})


def test_json_apply_filters_passthrough_non_dict_list(sample_json_file: Path):
    """Test json_apply_filters returns non-dict/list data unchanged."""
    from typing import Any, cast

    proc_spec = JSONProcessing(filter_by={"key": "value"})
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_apply_filters(cast(Any, "plain string"), data_file=df_file, proc_spec=proc_spec)
    assert result == "plain string"

    result = json_apply_filters(cast(Any, 42), data_file=df_file, proc_spec=proc_spec)
    assert result == 42


def test_json_select_keys_with_list_of_dicts(sample_json_file: Path):
    """Test json_select_keys filters keys from list of dicts."""
    data = [
        {"name": "Alice", "age": 30, "city": "NYC"},
        {"name": "Bob", "age": 25, "city": "LA"},
    ]
    proc_spec = JSONProcessing(select_keys=["name", "age"])
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_select_keys(data, data_file=df_file, proc_spec=proc_spec)

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(set(item.keys()) == {"name", "age"} for item in result)


def test_json_select_keys_passthrough_non_dict_list(sample_json_file: Path):
    """Test json_select_keys returns non-dict/list data unchanged."""
    from typing import Any, cast

    proc_spec = JSONProcessing(select_keys=["name"])
    df_file = DataFile(name="test", fpath=sample_json_file, proc_spec=proc_spec)

    result = json_select_keys(cast(Any, "plain string"), data_file=df_file, proc_spec=proc_spec)
    assert result == "plain string"

    result = json_select_keys(cast(Any, 42), data_file=df_file, proc_spec=proc_spec)
    assert result == 42


def test_replace_values_does_not_coerce_booleans_to_numeric_columns(sample_csv: Path):
    from r2x_core.processors import pl_replace_values

    frame = pl.LazyFrame(
        {
            "flag": [True, False],
            "count": [1, 0],
            "amount": [1.0, 0.0],
        }
    )
    result, _ = pl_replace_values(
        frame,
        data_file=DataFile(name="typed-replacements", fpath=sample_csv),
        proc_spec=TabularProcessing(replace_values={True: False}),
    )

    assert result.collect().to_dicts() == [
        {"flag": False, "count": 1, "amount": 1.0},
        {"flag": False, "count": 0, "amount": 0.0},
    ]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        pytest.param(Decimal("1.234"), Decimal("2.34"), id="inexact-key"),
        pytest.param(Decimal("1.23"), Decimal("2.345"), id="inexact-replacement"),
    ],
)
def test_replace_values_rejects_decimal_values_that_round_for_column(
    sample_csv: Path, old: Decimal, new: Decimal
):
    from r2x_core.processors import pl_replace_values

    frame = pl.DataFrame({"value": pl.Series("value", [Decimal("1.23")], dtype=pl.Decimal(5, 2))}).lazy()
    result, _ = pl_replace_values(
        frame,
        data_file=DataFile(name="decimal-replacements", fpath=sample_csv),
        proc_spec=TabularProcessing(replace_values={old: new}),
    )

    assert result.collect()["value"].to_list() == [Decimal("1.23")]


def test_replace_values_rejects_datetime_values_that_lose_precision(sample_csv: Path):
    from r2x_core.processors import pl_replace_values

    stored = datetime(2020, 1, 1, microsecond=1_000)
    inexact_key = datetime(2020, 1, 1, microsecond=1_001)
    frame = pl.DataFrame({"value": pl.Series("value", [stored], dtype=pl.Datetime("ms"))}).lazy()
    result, _ = pl_replace_values(
        frame,
        data_file=DataFile(name="datetime-replacements", fpath=sample_csv),
        proc_spec=TabularProcessing(replace_values={inexact_key: datetime(2021, 1, 1)}),
    )

    assert result.collect()["value"].to_list() == [stored]


def test_replace_values_rejects_float_values_that_lose_precision(sample_csv: Path):
    from r2x_core.processors import pl_replace_values

    frame = pl.DataFrame({"value": pl.Series("value", [1.0], dtype=pl.Float32)}).lazy()
    result, _ = pl_replace_values(
        frame,
        data_file=DataFile(name="float-replacements", fpath=sample_csv),
        proc_spec=TabularProcessing(replace_values={1.00000001: 2.0}),
    )

    assert result.collect()["value"].to_list() == [1.0]


def test_replace_values_still_matches_float_nan(sample_csv: Path):
    from math import nan

    from r2x_core.processors import pl_replace_values

    result, _ = pl_replace_values(
        pl.LazyFrame({"amount": [nan]}),
        data_file=DataFile(name="nan-replacements", fpath=sample_csv),
        proc_spec=TabularProcessing(replace_values={nan: 0.0}),
    )

    assert result.collect()["amount"].to_list() == [0.0]


def test_replace_values_does_not_coerce_rationals_to_float_columns(sample_csv: Path):
    from fractions import Fraction

    from r2x_core.processors import pl_replace_values

    large_rational = Fraction(2**53 + 1, 1)
    frame = pl.LazyFrame({"amount": [float(2**53)]})
    result, _ = pl_replace_values(
        frame,
        data_file=DataFile(name="rational-replacements", fpath=sample_csv),
        proc_spec=TabularProcessing(replace_values={large_rational: Fraction(0, 1)}),
    )

    assert result.collect()["amount"].to_list() == [float(2**53)]


def test_replace_values_allows_only_lossless_integer_to_float_widening(sample_csv: Path):
    from r2x_core.processors import pl_replace_values

    large_integer = 2**53 + 1
    frame = pl.LazyFrame(
        {
            "count": [1, large_integer],
            "amount": [1.0, float(large_integer - 1)],
            "small": pl.Series("small", [44, 45], dtype=pl.Int8),
        }
    )
    result, _ = pl_replace_values(
        frame,
        data_file=DataFile(name="numeric-replacements", fpath=sample_csv),
        proc_spec=TabularProcessing(replace_values={1: 2, large_integer: 0, 300: -1}),
    )

    assert result.collect().to_dicts() == [
        {"count": 2, "amount": 2.0, "small": 44},
        {"count": 0, "amount": float(large_integer - 1), "small": 45},
    ]


@pytest.mark.parametrize(
    ("old", "new", "dtype"),
    [
        pytest.param(Decimal("1.25"), Decimal("2.50"), pl.Decimal(5, 2), id="decimal"),
        pytest.param(1.5, 2.5, pl.Float64, id="float"),
        pytest.param(datetime(2020, 1, 2), datetime(2021, 2, 3), pl.Datetime("us"), id="datetime"),
        pytest.param(time(3, 4), time(4, 5), pl.Time, id="time"),
        pytest.param(timedelta(days=1), timedelta(days=2), pl.Duration("us"), id="duration"),
        pytest.param(b"old", b"new", pl.Binary, id="binary"),
        pytest.param("old", "new", pl.Categorical, id="categorical"),
        pytest.param("old", "new", pl.Enum(["old", "new"]), id="enum"),
    ],
)
def test_replace_values_preserves_logical_families(
    sample_csv: Path, old: object, new: object, dtype: pl.DataType
):
    from r2x_core.processors import pl_replace_values

    frame = pl.DataFrame(
        {
            "value": pl.Series("value", [old], dtype=dtype),
            "whole": [1],
        }
    ).lazy()
    result, _ = pl_replace_values(
        frame,
        data_file=DataFile(name="family-replacements", fpath=sample_csv),
        proc_spec=TabularProcessing(replace_values={old: new}),
    )

    assert result.collect().to_dicts() == [{"value": new, "whole": 1}]


def test_tabular_additional_operation_edges(sample_csv: Path):
    """Cover direct operation calls and explicit operation errors."""
    from datetime import date

    from r2x_core.processors import (
        pl_aggregate,
        pl_fill_null,
        pl_pivot_on,
        pl_rename_columns,
        pl_replace_values,
        pl_sort,
        pl_unpivot_on,
    )

    data_file = DataFile(name="edges", fpath=sample_csv)
    frame = pl.LazyFrame({"year": [2020, 2020]})
    with pytest.raises(ValueError, match="requires at least one value"):
        pl_pivot_on(frame, data_file=data_file, proc_spec=TabularProcessing(pivot_on="year"))
    with pytest.raises(ValueError, match=r"pivot_on.*missing column"):
        pl_pivot_on(
            pl.LazyFrame({"amount": [1]}),
            data_file=data_file,
            proc_spec=TabularProcessing(pivot_on="label", aggregate_on={"amount": "sum"}),
        )
    with pytest.raises(ValueError, match="one aggregation function"):
        TabularProcessing(
            pivot_on="year",
            group_by=["region"],
            aggregate_on={"a": "sum", "b": "mean"},
        )
    with pytest.raises(ValueError, match="cannot also be a group_by"):
        TabularProcessing(pivot_on="year", group_by=["year"], aggregate_on={"amount": "sum"})
    with pytest.raises(ValueError, match="cannot also be an aggregate_on"):
        TabularProcessing(pivot_on="year", aggregate_on={"year": "sum"})
    valid_unpivot, _ = pl_unpivot_on(
        pl.LazyFrame({"amount": [1], "january": [2]}),
        data_file=data_file,
        proc_spec=TabularProcessing(unpivot_on=["amount", "january"]),
    )
    assert valid_unpivot.collect().columns == ["variable", "value"]
    with pytest.raises(ValueError, match="overwrite"):
        pl_unpivot_on(
            pl.LazyFrame({"value": [1], "amount": [2]}),
            data_file=data_file,
            proc_spec=TabularProcessing(unpivot_on=["amount"]),
        )

    today = date.today()
    mixed = pl.LazyFrame({"flag": [True, None], "when": [today, None]})
    replace_spec = TabularProcessing(replace_values={True: False})
    replaced, _ = pl_replace_values(mixed, data_file=data_file, proc_spec=replace_spec)
    assert replaced.collect()["flag"].to_list() == [False, None]
    temporal, _ = pl_replace_values(
        pl.LazyFrame({"when": [today, None]}),
        data_file=data_file,
        proc_spec=TabularProcessing(replace_values={today: date(2000, 1, 1)}),
    )
    assert temporal.collect()["when"].to_list() == [date(2000, 1, 1), None]
    mixed_target, _ = pl_replace_values(
        pl.LazyFrame({"number": [1, None], "label": ["a", None]}),
        data_file=data_file,
        proc_spec=TabularProcessing(replace_values={None: "missing"}),
    )
    mixed_target_result = mixed_target.collect()
    assert mixed_target_result["number"].to_list() == [1, None]
    assert mixed_target_result["label"].to_list() == ["a", "missing"]
    incompatible, _ = pl_replace_values(
        pl.LazyFrame({"number": [1]}),
        data_file=data_file,
        proc_spec=TabularProcessing(replace_values={object(): "ignored"}),
    )
    assert incompatible.collect().to_dicts() == [{"number": 1}]
    opaque_value = object()
    opaque, _ = pl_replace_values(
        pl.LazyFrame({"opaque": pl.Series("opaque", [opaque_value], dtype=pl.Object)}),
        data_file=data_file,
        proc_spec=TabularProcessing(replace_values={"old": "new"}),
    )
    assert opaque.collect()["opaque"][0] is opaque_value
    filled, _ = pl_fill_null(
        mixed, data_file=data_file, proc_spec=TabularProcessing(fill_null={"flag": False})
    )
    assert filled.collect()["flag"].to_list() == [True, False]

    aggregated, _ = pl_aggregate(
        pl.LazyFrame({"amount": [1, 2]}),
        data_file=data_file,
        proc_spec=TabularProcessing(aggregate_on={"amount": "sum"}),
    )
    assert aggregated.collect().to_dicts() == [{"amount": 3}]
    sorted_frame, _ = pl_sort(
        pl.LazyFrame({"amount": [1, 2]}),
        data_file=data_file,
        proc_spec=TabularProcessing(sort_by={"amount": "asc"}),
    )
    assert sorted_frame.collect()["amount"].to_list() == [1, 2]
    with pytest.raises(ValueError, match="duplicate column"):
        pl_rename_columns(
            pl.LazyFrame({"old": [1], "new": [2]}),
            data_file=data_file,
            proc_spec=TabularProcessing(column_mapping={"old": "new"}),
        )


def test_tabular_operations_infer_schema_without_configured_changes(sample_csv: Path):
    from r2x_core.processors import (
        pl_distinct,
        pl_scale,
        pl_split_columns,
        pl_strip_chars,
        pl_unpivot_on,
    )

    data_file = DataFile(name="unchanged", fpath=sample_csv)
    frame = pl.LazyFrame({"label": ["value"]})
    expected = [{"label": "value"}]

    for transform in (pl_unpivot_on, pl_split_columns, pl_strip_chars, pl_scale, pl_distinct):
        result, columns = transform(frame, data_file=data_file, proc_spec=TabularProcessing())
        assert columns == ["label"]
        assert result.collect().to_dicts() == expected


def test_transform_xml_data_placeholder(sample_json_file: Path):
    """Test transform_xml_data returns data unchanged (placeholder implementation)."""
    from r2x_core.processors import transform_xml_data

    df_file = DataFile(name="test", fpath=sample_json_file)
    data = {"root": {"child": "value"}}

    result = transform_xml_data(data, data_file=df_file)

    assert result == data


def test_pl_build_filter_expr_datetime_year_list():
    """Test pl_build_filter_expr with datetime column and list of years."""
    from datetime import datetime

    from r2x_core.processors import pl_build_filter_expr

    expr = pl_build_filter_expr("datetime", value=[2020, 2021])

    df = pl.DataFrame(
        {
            "datetime": [
                datetime(2020, 1, 1),
                datetime(2021, 6, 15),
                datetime(2022, 12, 31),
            ]
        }
    )

    result = df.filter(expr)
    assert len(result) == 2


def test_pl_build_filter_expr_datetime_year_single():
    """Test pl_build_filter_expr with datetime column and single year."""
    from datetime import datetime

    from r2x_core.processors import pl_build_filter_expr

    expr = pl_build_filter_expr("datetime", value=2020)

    df = pl.DataFrame(
        {
            "datetime": [
                datetime(2020, 1, 1),
                datetime(2021, 6, 15),
            ]
        }
    )

    result = df.filter(expr)
    assert len(result) == 1


def test_tabular_processing_reports_non_numeric_scale(sample_csv: Path):
    result = apply_processing(
        pl.LazyFrame({"value": ["not numeric"]}),
        data_file=DataFile(name="invalid-scale", fpath=sample_csv),
        proc_spec=TabularProcessing(scale={"value": 0.01}),
    )

    assert result.is_err()
    assert "scale requires numeric columns" in str(result.err())


def test_split_column_rejects_overwriting_existing_columns(sample_csv: Path):
    result = apply_processing(
        pl.LazyFrame({"label": ["2030|NYISO"], "year": [2030]}),
        data_file=DataFile(name="split-collision", fpath=sample_csv),
        proc_spec=TabularProcessing(split_column={"label": {"separator": "|", "into": ["year", "zone"]}}),
    )

    assert result.is_err()
    assert "overwrite existing column" in str(result.err())


def test_tabular_column_operations_divide_safely_and_fill_from_peer(sample_csv: Path):
    result = apply_processing(
        pl.LazyFrame(
            {
                "cost": [120.0, None, 80.0, 60.0],
                "distance": [10.0, 5.0, 0.0, None],
                "capacity": [100.0, 200.0, 300.0, 400.0],
                "reverse_capacity": [None, 25.0, None, None],
            }
        ),
        data_file=DataFile(name="line-data", fpath=sample_csv),
        proc_spec=TabularProcessing(
            safe_divide={
                "cost_per_mile": {"numerator": "cost", "denominator": "distance"},
                "cost_per_capacity": {"numerator": "cost", "denominator": "capacity"},
            },
            fill_null_from={"reverse_capacity": "capacity"},
        ),
    )

    assert result.is_ok()
    frame = result.ok().collect()
    assert frame["cost_per_mile"].to_list() == [12.0, None, None, None]
    assert frame["cost_per_capacity"].to_list() == [1.2, None, 80 / 300, 0.15]
    assert frame["reverse_capacity"].to_list() == [100.0, 25.0, 300.0, 400.0]


def test_tabular_column_operations_support_all_null_columns(sample_csv: Path):
    """All-null inputs and targets work through the processing API."""
    result = apply_processing(
        pl.LazyFrame(
            {
                "numerator": [None, None],
                "denominator": [None, None],
                "target": [None, None],
                "fallback_ratio": [None, None],
                "source": [1.5, 2.5],
                "partial_numerator": [8.0, None],
                "partial_denominator": [2.0, None],
            }
        ),
        data_file=DataFile(name="null-column-operations", fpath=sample_csv),
        proc_spec=TabularProcessing(
            safe_divide={
                "ratio": {"numerator": "numerator", "denominator": "denominator"},
                "calculated_ratio": {
                    "numerator": "partial_numerator",
                    "denominator": "partial_denominator",
                },
            },
            fill_null_from={"target": "source", "fallback_ratio": "calculated_ratio"},
        ),
    )

    assert result.is_ok()
    assert result.ok().select("ratio", "target", "fallback_ratio").collect().to_dicts() == [
        {"ratio": None, "target": 1.5, "fallback_ratio": 4.0},
        {"ratio": None, "target": 2.5, "fallback_ratio": None},
    ]


def test_tabular_column_operations_validate_inputs_and_collisions(sample_csv: Path):
    data_file = DataFile(name="invalid-line-data", fpath=sample_csv)
    with pytest.raises(ValueError, match="cannot overwrite an input column"):
        TabularProcessing(safe_divide={"cost": {"numerator": "cost", "denominator": "distance"}})

    cases = [
        (
            pl.LazyFrame({"cost": [1.0]}),
            TabularProcessing(safe_divide={"ratio": {"numerator": "cost", "denominator": "missing"}}),
            "references missing column",
        ),
        (
            pl.LazyFrame({"left": [1.0], "right": ["not numeric"]}),
            TabularProcessing(fill_null_from={"left": "right"}),
            "matching column types",
        ),
    ]

    for frame, proc_spec, message in cases:
        result = apply_processing(frame, data_file=data_file, proc_spec=proc_spec)
        assert result.is_err()
        assert message in str(result.err())


def test_tabular_column_operations_reject_same_stage_chaining():
    with pytest.raises(ValueError, match="cannot depend on another safe_divide output"):
        TabularProcessing(
            safe_divide={
                "first": {"numerator": "cost", "denominator": "distance"},
                "second": {"numerator": "first", "denominator": "distance"},
            }
        )
    with pytest.raises(ValueError, match="cannot chain through target columns"):
        TabularProcessing(fill_null_from={"left": "middle", "middle": "right"})


def test_categorize_uses_placeholder_policy_and_preserves_match_order(sample_csv: Path):
    processing = TabularProcessing.model_validate(
        {
            "categorize": [
                {
                    "source_column": "technology",
                    "categories": "{technology_categories}",
                    "output_column": "categories",
                    "primary_category_column": "category",
                    "flags": {"is_variable": ["wind", "solar"]},
                }
            ]
        }
    )
    round_trip = TabularProcessing.model_validate(processing.model_dump())
    result = apply_processing(
        pl.LazyFrame({"technology": ["WIND-ons_1", "upv", "unknown", "STRAẞE"]}),
        data_file=DataFile(name="categorized-generators", fpath=sample_csv),
        proc_spec=round_trip,
        placeholders={
            "technology_categories": {
                "wind": {"prefixes": ["wind-ons"], "exact": []},
                "renewable": {"prefixes": ["wind", "upv"], "exact": []},
                "solar": {"prefixes": ["upv"], "exact": []},
                "street": {"prefixes": [], "exact": ["Straße"]},
            }
        },
    )

    assert result.is_ok()
    assert result.ok().collect().to_dicts() == [
        {
            "technology": "WIND-ons_1",
            "categories": ["wind", "renewable"],
            "category": "wind",
            "is_variable": True,
        },
        {
            "technology": "upv",
            "categories": ["renewable", "solar"],
            "category": "renewable",
            "is_variable": True,
        },
        {"technology": "unknown", "categories": [], "category": None, "is_variable": False},
        {"technology": "STRAẞE", "categories": ["street"], "category": "street", "is_variable": False},
    ]


def test_categorize_rejects_invalid_or_unresolved_placeholder_policy(sample_csv: Path):
    proc_spec = TabularProcessing.model_validate(
        {
            "categorize": [
                {
                    "source_column": "technology",
                    "categories": "{technology_categories}",
                    "output_column": "categories",
                }
            ]
        }
    )
    data = pl.LazyFrame({"technology": ["wind"]})
    data_file = DataFile(name="categorized-generators", fpath=sample_csv)

    unresolved = apply_processing(data, data_file=data_file, proc_spec=proc_spec)
    wrong_type = apply_processing(
        data,
        data_file=data_file,
        proc_spec=proc_spec,
        placeholders={"technology_categories": {"wind": ["wind"]}},
    )

    assert unresolved.is_err()
    assert "Found placeholder '{technology_categories}' but no placeholders provided" in str(unresolved.err())
    assert wrong_type.is_err()
    assert "Invalid processing specification after placeholder substitution" in str(wrong_type.err())


def test_column_multiply_uses_cast_columns_and_preserves_null_arithmetic(sample_csv: Path):
    processing = TabularProcessing.model_validate(
        {
            "column_schema": {"capacity": "float", "capacity_factor": "float"},
            "column_multiply": [{"target": "power", "left": "capacity", "right": "capacity_factor"}],
        }
    )
    result = apply_processing(
        pl.LazyFrame({"capacity": ["100", "200"], "capacity_factor": ["0.25", None]}),
        data_file=DataFile(name="scaled-profile", fpath=sample_csv),
        proc_spec=processing,
    )

    assert result.is_ok()
    frame = result.ok().collect()
    assert frame["power"].to_list() == [25.0, None]
    assert frame.schema["power"] == pl.Float64


def test_not_in_filter_uses_configured_set_and_empty_set_is_identity(sample_csv: Path):
    data = pl.LazyFrame({"technology": ["wind", "coal"]})
    proc_spec = TabularProcessing(
        filter_rows=[{"column": "technology", "operator": "not_in", "value": "{excluded}"}]
    )
    data_file = DataFile(name="generator-exclusions", fpath=sample_csv)

    excluded = apply_processing(
        data,
        data_file=data_file,
        proc_spec=proc_spec,
        placeholders={"excluded": ["coal"]},
    )
    empty_set = apply_processing(
        data,
        data_file=data_file,
        proc_spec=proc_spec,
        placeholders={"excluded": []},
    )

    assert excluded.is_ok()
    assert excluded.ok().collect()["technology"].to_list() == ["wind"]
    assert empty_set.is_ok()
    assert empty_set.ok().collect()["technology"].to_list() == ["wind", "coal"]
