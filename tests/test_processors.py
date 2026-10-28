"""Functional tests for processors module.

These tests focus on realistic processor behavior using TabularProcessing and JSONProcessing
models. Each test exercises a specific processor function with real data to ensure filtering,
renaming, dropping, casting, and pivoting work as expected.
"""

import warnings
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import polars as pl
import pytest
from rust_ok import Err, Ok, Result

from r2x_core.datafile import DataFile
from r2x_core.json_adapter.processing import (
    JSONProcessingBackend,
    drop_keys,
    filter_records,
    rename_keys,
    select_keys,
)
from r2x_core.models import (
    AggregateStep,
    CastColumnsStep,
    DropColumnsStep,
    DropJSONKeysStep,
    FillNullStep,
    FilterColumnsStep,
    JSONProcessing,
    LowercaseStep,
    PivotStep,
    RenameColumnsStep,
    RenameJSONKeysStep,
    ReplaceValuesStep,
    ScaleColumnsStep,
    SelectColumnsStep,
    SortStep,
    SplitColumnsStep,
    StripCharactersStep,
    TabularProcessing,
    UniqueStep,
    UnpivotColumnsStep,
)
from r2x_core.polars_adapter import PolarsTabularBackend
from r2x_core.polars_adapter.processing import apply_polars_step
from r2x_core.processors import substitute_placeholders
from r2x_core.reader import DataReader
from r2x_core.types import FileProcessing, JSONValue

pytestmark = [pytest.mark.processing, pytest.mark.polars]


def apply_polars_processing(
    frame: pl.LazyFrame,
    *,
    proc_spec: FileProcessing | None,
    placeholders: dict[str, object] | None = None,
) -> Result[pl.LazyFrame, ValueError]:
    """Exercise typed processing and placeholder resolution for an in-memory source."""
    if proc_spec is None:
        return Ok(frame)
    configured = DataFile(name="in-memory", source="frame", proc_spec=proc_spec)
    try:
        resolved = DataReader.resolve_placeholders(configured, placeholders=placeholders)
    except ValueError as error:
        return Err(error)
    if not isinstance(resolved.proc_spec, TabularProcessing):
        return Err(ValueError("PolarsTabularBackend requires TabularProcessing"))
    return PolarsTabularBackend().process(
        frame,
        processing=resolved.proc_spec,
        sources={},
        data_file=resolved,
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


@pytest.mark.parametrize(
    ("filter_by", "expected_names"),
    [
        pytest.param({"name": "Alice"}, ["Alice"], id="scalar"),
        pytest.param({"name": ["Alice", "Bob"]}, ["Alice", "Bob"], id="list"),
        pytest.param({"retire_year": 2036, "age": 30}, ["Alice"], id="and"),
    ],
)
def test_apply_polars_step_filters_values(
    sample_csv: Path,
    filter_by: dict[str, str | int | list[str]],
    expected_names: list[str],
):
    """Filter using scalar, list, and combined predicates."""
    result = apply_polars_step(
        pl.scan_csv(sample_csv), step=FilterColumnsStep(op="filter_columns", filter_by=filter_by)
    ).collect()

    assert len(result) == len(expected_names)
    assert result["name"].to_list() == expected_names


def test_apply_polars_step_rejects_unsupported_step():
    with pytest.raises(ValueError, match="Unsupported table processing operation: object"):
        apply_polars_step(pl.LazyFrame({"value": [1]}), step=object())


def test_apply_polars_step_drop_columns_removes_existing(sample_csv: Path):
    """Test that drop_columns removes specified columns."""
    lf = pl.scan_csv(sample_csv)

    result = apply_polars_step(lf, step=DropColumnsStep(op="drop_columns", drop_columns=["city", "score"]))
    result = result.collect()

    assert "city" not in result.columns
    assert "score" not in result.columns
    assert "name" in result.columns
    assert "age" in result.columns


def test_apply_polars_step_rename_columns_renames_existing(sample_csv: Path):
    """Test that column_mapping renames columns correctly."""
    lf = pl.scan_csv(sample_csv)

    result = apply_polars_step(
        lf,
        step=RenameColumnsStep(
            op="rename_columns", column_mapping={"name": "person_name", "age": "person_age"}
        ),
    )
    result = result.collect()

    assert "person_name" in result.columns
    assert "person_age" in result.columns
    assert "name" not in result.columns
    assert "age" not in result.columns


def test_apply_polars_step_cast_schema_casts_columns(sample_csv: Path):
    """Test that column_schema casts columns to correct types."""
    lf = pl.scan_csv(sample_csv)

    result = apply_polars_step(
        lf, step=CastColumnsStep(op="cast_columns", column_schema={"age": "int32", "retire_year": "int32"})
    )
    result = result.collect()

    assert result.schema["age"] == pl.Int32
    assert result.schema["retire_year"] == pl.Int32


def test_apply_polars_step_cast_schema_unsupported_type_raises(sample_csv: Path):
    """Test that unsupported type strings raise ValueError."""
    lf = pl.scan_csv(sample_csv)

    with pytest.raises(ValueError, match="Unsupported data type"):
        apply_polars_step(lf, step=CastColumnsStep(op="cast_columns", column_schema={"age": "invalid_type"}))


def test_unpivot_on_stacks_selected_columns():
    """Wide-to-long processing uses its explicit unpivot operation."""
    lf = pl.LazyFrame({"2020": [100], "2025": [200], "2030": [300]})
    proc_spec = TabularProcessing(
        steps=[UnpivotColumnsStep(op="unpivot_columns", columns=["2020", "2025", "2030"])]
    )

    result = apply_polars_processing(lf, proc_spec=proc_spec).unwrap_or_raise().collect()

    assert result.columns == ["variable", "value"]
    assert result.height == 3
    assert result.to_dicts() == [
        {"variable": "2020", "value": 100},
        {"variable": "2025", "value": 200},
        {"variable": "2030", "value": 300},
    ]


@pytest.mark.parametrize(
    ("data", "mapping", "expected"),
    [
        pytest.param(
            {"name": "Alice", "age": 30, "city": "NYC"},
            {"name": "person_name", "age": "person_age"},
            {"person_name": "Alice", "person_age": 30, "city": "NYC"},
            id="object",
        ),
        pytest.param(
            [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}],
            {"name": "person_name", "age": "years"},
            [{"person_name": "Alice", "years": 30}, {"person_name": "Bob", "years": 25}],
            id="list-of-objects",
        ),
    ],
)
def test_json_rename_keys(data: JSONValue, mapping: dict[str, str], expected: JSONValue) -> None:
    assert rename_keys(data, mapping=mapping) == expected


@pytest.mark.parametrize(
    ("data", "where", "expected"),
    [
        pytest.param(
            {"name": "Alice", "age": 30, "city": "NYC", "score": 85.5},
            {"age": 30},
            {"name": "Alice", "age": 30, "city": "NYC", "score": 85.5},
            id="scalar-match",
        ),
        pytest.param(
            {"name": "Alice", "age": 30, "city": "NYC"},
            {"name": ["Alice", "Bob"]},
            {"name": "Alice", "age": 30, "city": "NYC"},
            id="list-match",
        ),
        pytest.param({"name": "Bob", "age": 25, "city": "LA"}, {"age": 30}, {}, id="no-match"),
        pytest.param(
            [
                {"name": "Alice", "age": 30, "city": "NYC"},
                {"name": "Bob", "age": 30, "city": "LA"},
                {"name": "Charlie", "age": 25, "city": "CHI"},
            ],
            {"age": 30},
            [
                {"name": "Alice", "age": 30, "city": "NYC"},
                {"name": "Bob", "age": 30, "city": "LA"},
            ],
            id="list-records",
        ),
    ],
)
def test_json_filters_records(data: JSONValue, where: dict[str, JSONValue], expected: JSONValue) -> None:
    """Filter object records by exact scalar/list values, including no matches."""
    assert filter_records(data, where=where) == expected


@pytest.mark.parametrize(
    ("data", "keys", "expected"),
    [
        pytest.param(
            {"name": "Alice", "age": 30, "city": "NYC", "score": 85.5},
            frozenset({"name", "score"}),
            {"name": "Alice", "score": 85.5},
            id="object",
        ),
        pytest.param(
            [{"name": "Alice", "age": 30, "city": "NYC"}, {"name": "Bob", "age": 25, "city": "LA"}],
            frozenset({"name", "city"}),
            [{"name": "Alice", "city": "NYC"}, {"name": "Bob", "city": "LA"}],
            id="list-select-columns",
        ),
        pytest.param(
            [{"name": "Alice", "age": 30, "city": "NYC"}, {"name": "Bob", "age": 25, "city": "LA"}],
            frozenset({"name", "age"}),
            [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}],
            id="list-of-objects",
        ),
    ],
)
def test_json_select_keys(data: JSONValue, keys: frozenset[str], expected: JSONValue) -> None:
    assert select_keys(data, keys=keys) == expected


@pytest.mark.parametrize("value", ["plain string", 42], ids=["string", "integer"])
def test_json_filter_and_selection_passthrough_non_records(value: JSONValue):
    assert filter_records(value, where={"key": "value"}) == value
    assert select_keys(value, keys=frozenset({"name"})) == value


@pytest.mark.parametrize(
    ("step", "error_pattern"),
    [
        (DropColumnsStep(op="drop_columns", drop_columns=["nonexistent"]), r"drop_columns.*nonexistent"),
        (
            RenameColumnsStep(op="rename_columns", column_mapping={"nonexistent": "new_name"}),
            r"column_mapping.*nonexistent",
        ),
        (
            SelectColumnsStep(op="select_columns", select_columns=["nonexistent"]),
            r"select_columns.*nonexistent",
        ),
        (
            CastColumnsStep(op="cast_columns", column_schema={"nonexistent": "int32"}),
            r"column_schema.*nonexistent",
        ),
        (
            FilterColumnsStep(op="filter_columns", filter_by={"nonexistent_column": "value"}),
            r"filter_columns.*nonexistent_column",
        ),
    ],
)
def test_apply_polars_step_rejects_missing_columns(
    sample_csv: Path,
    step: DropColumnsStep | RenameColumnsStep | SelectColumnsStep | CastColumnsStep | FilterColumnsStep,
    error_pattern: str,
):
    """Report the missing field with context for each direct operation."""
    with pytest.raises(ValueError, match=error_pattern):
        apply_polars_step(pl.scan_csv(sample_csv), step=step)


@pytest.mark.parametrize(
    ("column", "years", "values", "filter_value", "expected_rows"),
    [
        ("date", [2020, 2021], [100, 200], 2020, [{"date": 2020, "value": 100}]),
        (
            "year",
            [2020, 2021, 2022],
            [100, 200, 150],
            [2020, 2021],
            [{"year": 2020, "value": 100}, {"year": 2021, "value": 200}],
        ),
    ],
)
def test_apply_polars_step_filters_datetime_years(
    column: str,
    years: list[int],
    values: list[int],
    filter_value: int | list[int],
    expected_rows: list[dict[str, int]],
):
    """Filter one or more numeric years and check the exact rows."""
    frame = pl.LazyFrame({column: years, "value": values})
    result = apply_polars_step(
        frame, step=FilterColumnsStep(op="filter_columns", filter_by={column: filter_value})
    ).collect()

    assert result.to_dicts() == expected_rows


def test_apply_polars_step_select_columns(sample_csv: Path):
    """Test select_columns."""
    lf = pl.scan_csv(sample_csv)

    result = apply_polars_step(
        lf, step=SelectColumnsStep(op="select_columns", select_columns=["name", "age"])
    )
    result = result.collect()

    assert set(result.columns) == {"name", "age"}


def test_apply_polars_step_empty_filter(sample_csv: Path):
    """Test apply_filters with no filters specified."""
    lf = pl.scan_csv(sample_csv)
    step = FilterColumnsStep(op="filter_columns", filter_by={})
    result = apply_polars_step(lf, step=step)

    # Should return unchanged - verify by collecting and checking
    assert result.collect().equals(lf.collect())


def test_apply_polars_step_drop_columns_all_removed(sample_csv: Path):
    """Test drop_columns when all columns are removed."""
    lf = pl.scan_csv(sample_csv)
    schema_names = lf.collect_schema().names()

    result = apply_polars_step(lf, step=DropColumnsStep(op="drop_columns", drop_columns=schema_names))
    column_names = result.collect_schema().names()
    collected = result.collect()

    assert collected.columns == []
    assert column_names == []


def test_apply_processing_with_placeholder_substitution(sample_csv: Path):
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(
        steps=[FilterColumnsStep(op="filter_columns", filter_by={"name": "{year}"})]
    )

    result = apply_polars_processing(lf, proc_spec=proc_spec, placeholders={"year": "Alice"})
    assert result.is_ok()


def test_apply_processing_placeholder_error(sample_csv: Path):
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(
        steps=[FilterColumnsStep(op="filter_columns", filter_by={"name": "{missing}"})]
    )

    result = apply_polars_processing(lf, proc_spec=proc_spec, placeholders={"year": 2030})
    assert result.is_err()
    assert "missing" in str(result.err())


def test_apply_processing_substitutes_transformation_values():
    """Substitute placeholders in non-filter tabular operations."""
    lf = pl.LazyFrame({"name": ["a", "b"], "amount": [1, 2]})
    proc_spec = TabularProcessing(steps=[SortStep(op="sort", by={"amount": "{direction}"})])

    result = apply_polars_processing(
        lf,
        proc_spec=proc_spec,
        placeholders={"direction": "desc"},
    )
    assert result.is_ok()
    assert result.unwrap().collect()["amount"].to_list() == [2, 1]


def test_apply_processing_rejects_invalid_substituted_transformation():
    """Revalidate substituted operation values before running the processor."""
    proc_spec = TabularProcessing(steps=[SortStep(op="sort", by={"amount": "{direction}"})])
    result = apply_polars_processing(
        pl.LazyFrame({"amount": [1]}),
        proc_spec=proc_spec,
        placeholders={"direction": "sideways"},
    )
    assert result.is_err()
    assert "validation error" in str(result.err()).lower()


def test_apply_processing_substitutes_typed_transformation_values():
    proc_spec = TabularProcessing(
        steps=[
            LowercaseStep(op="lowercase", lowercase="{enabled}"),
            ScaleColumnsStep(op="scale_columns", scale={"amount": "{factor}"}),
        ]
    )
    result = apply_polars_processing(
        pl.LazyFrame({"AMOUNT": [2.0]}),
        proc_spec=proc_spec,
        placeholders={"enabled": True, "factor": 0.5},
    )

    assert result.is_ok()
    assert result.unwrap().collect().to_dicts() == [{"amount": 1.0}]


@pytest.mark.parametrize(
    ("step", "placeholders"),
    [
        (LowercaseStep(op="lowercase", lowercase="{enabled}"), {"enabled": "not-a-bool"}),
        (ScaleColumnsStep(op="scale_columns", scale={"amount": "{factor}"}), {"factor": float("inf")}),
    ],
)
def test_apply_processing_revalidates_typed_placeholders(
    step: LowercaseStep | ScaleColumnsStep,
    placeholders: dict[str, bool | float | str],
):
    proc_spec = TabularProcessing(steps=[step])
    result = apply_polars_processing(
        pl.LazyFrame({"amount": [2.0]}),
        proc_spec=proc_spec,
        placeholders=placeholders,
    )
    assert result.is_err()
    assert "validation error" in str(result.err()).lower()


def test_json_drop_columns_with_list():
    data = [
        {"name": "Alice", "age": 30, "city": "NYC"},
        {"name": "Bob", "age": 25, "city": "LA"},
    ]
    result = drop_keys(data, keys=frozenset({"city"}))

    assert len(result) == 2
    assert all("city" not in item for item in result)
    assert all("name" in item for item in result)


def test_tabular_processing_full_pipeline(sample_csv: Path):
    lf = pl.scan_csv(sample_csv)
    proc_spec = TabularProcessing(
        steps=[
            RenameColumnsStep(op="rename_columns", column_mapping={"name": "person_name"}),
            FilterColumnsStep(op="filter_columns", filter_by={"age": 30}),
        ]
    )

    result = apply_polars_processing(lf, proc_spec=proc_spec).unwrap_or_raise().collect()

    assert result.to_dicts() == [
        {"person_name": "Alice", "age": 30, "city": "NYC", "score": 85.5, "retire_year": 2036}
    ]


def test_json_backend_rejects_incompatible_processing_and_data():
    backend = JSONProcessingBackend()
    data_file = DataFile(name="json-backend", source="frame")

    unsupported = backend.process(
        {"value": 1},
        processing=TabularProcessing(),
        sources={},
        data_file=data_file,
    )
    invalid_data = backend.process(
        cast(JSONValue, object()),
        processing=JSONProcessing(),
        sources={},
        data_file=data_file,
    )

    assert unsupported.is_err()
    assert "requires JSONProcessing" in str(unsupported.err())
    assert invalid_data.is_err()
    assert "requires JSON-compatible data" in str(invalid_data.err())


def test_process_json_data_full_pipeline():
    from r2x_core.json_adapter.processing import process_json_data

    data = {
        "users": [
            {"name": "Alice", "age": 30, "status": "active"},
            {"name": "Bob", "age": 25, "status": "inactive"},
        ]
    }
    proc_spec = JSONProcessing(
        steps=[
            RenameJSONKeysStep(op="rename_keys", mapping={"name": "person_name"}),
            DropJSONKeysStep(op="drop_keys", keys=["status"]),
        ]
    )
    result = process_json_data(data, steps=proc_spec.steps)

    assert result == {
        "users": [
            {"person_name": "Alice", "age": 30},
            {"person_name": "Bob", "age": 25},
        ]
    }


@pytest.mark.parametrize(
    ("csv_data", "column", "years", "expected_rows"),
    [
        pytest.param(
            "date,value\n2020,100\n2021,200\n",
            "date",
            2020,
            [{"date": 2020, "value": 100}],
            id="single-year",
        ),
        pytest.param(
            "year,value\n2020,100\n2021,200\n2022,150\n",
            "year",
            [2020, 2021],
            [{"year": 2020, "value": 100}, {"year": 2021, "value": 200}],
            id="multiple-years",
        ),
    ],
)
def test_apply_polars_step_filters_years(
    tmp_path: Path,
    csv_data: str,
    column: str,
    years: int | list[int],
    expected_rows: list[dict[str, int]],
):
    csv_file = tmp_path / "year-filter.csv"
    csv_file.write_text(csv_data)
    result = apply_polars_step(
        pl.scan_csv(csv_file), step=FilterColumnsStep(op="filter_columns", filter_by={column: years})
    ).collect()

    assert result.to_dicts() == expected_rows


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


@pytest.mark.parametrize("value", ["{unclosed", "}{"], ids=["unclosed", "unmatched-braces"])
def test_substitute_placeholders_unmatched_braces_are_unchanged(value: str) -> None:
    """Strings with braces but no placeholder expression pass through unchanged."""
    result = substitute_placeholders(value, placeholders={})

    assert result.unwrap() is value


def test_substitute_placeholders_preserves_nested_values_without_changes():
    """Nested values without placeholders retain their data through substitution."""
    value = {"items": ["plain text", 3]}

    result = substitute_placeholders(value, placeholders={"x": 1})

    assert result.unwrap() == value


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


def test_tabular_value_transformations():
    """Apply replacement, null filling, sorting, and deduplication."""
    frame = pl.LazyFrame({"region": ["West", "West", "East"], "value": [None, 2, 1]})
    proc_spec = TabularProcessing(
        steps=[
            LowercaseStep(op="lowercase", lowercase=True),
            ReplaceValuesStep(op="replace_values", replace_values={"west": "north"}),
            FillNullStep(op="fill_null", fill_null={"value": 0}),
            UniqueStep(op="unique", subset=["region", "value"]),
            SortStep(op="sort", by={"value": "desc"}),
            SelectColumnsStep(op="select_columns", select_columns=["region", "value"]),
        ]
    )
    result = apply_polars_processing(frame, proc_spec=proc_spec).unwrap_or_raise().collect()
    assert result.to_dicts() == [
        {"region": "north", "value": 2},
        {"region": "east", "value": 1},
        {"region": "north", "value": 0},
    ]


def test_tabular_long_to_wide_pivot_count():
    frame = pl.LazyFrame(
        {
            "region": ["West", "West", "East"],
            "year": [2020, 2020, 2020],
            "amount": [1, None, 3],
        }
    )
    proc_spec = TabularProcessing(
        steps=[PivotStep(op="pivot", pivot_on="year", group_by=["region"], aggregate_on={"amount": "count"})]
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        result = apply_polars_processing(frame, proc_spec=proc_spec).unwrap_or_raise().collect()

    assert {row["region"]: row["2020"] for row in result.to_dicts()} == {"West": 1, "East": 1}


def test_pivot_key_matching_source_column_does_not_aggregate_twice():
    frame = pl.LazyFrame({"id": ["a", "a"], "year": ["year", "2020"], "value": [1, 2]})
    proc_spec = TabularProcessing(
        steps=[PivotStep(op="pivot", pivot_on="year", group_by=["id"], aggregate_on={"value": "sum"})]
    )
    result = apply_polars_processing(frame, proc_spec=proc_spec).unwrap_or_raise().collect()

    assert result.to_dicts() == [{"id": "a", "year": 1, "2020": 2}]


def test_tabular_long_to_wide_pivot():
    """Pivot long-form rows using grouped value aggregation."""
    frame = pl.LazyFrame(
        {
            "region": ["West", "West", "West"],
            "year": [2020, 2020, 2021],
            "amount": [1, 2, 3],
        }
    )
    proc_spec = TabularProcessing(
        steps=[PivotStep(op="pivot", pivot_on="year", group_by=["region"], aggregate_on={"amount": "sum"})]
    )
    result = apply_polars_processing(frame, proc_spec=proc_spec).unwrap_or_raise().collect()
    assert result.to_dicts() == [{"region": "West", "2021": 3, "2020": 3}]


def test_unpivot_pipeline_renames_casts_and_filters():
    frame = pl.LazyFrame(
        {
            "region": ["NYISO", "PJM"],
            "2025": [10, 20],
            "2030": [30, 40],
        }
    )
    proc_spec = TabularProcessing(
        steps=[
            UnpivotColumnsStep(op="unpivot_columns", columns=["2025", "2030"]),
            RenameColumnsStep(
                op="rename_columns", column_mapping={"variable": "year", "value": "capacity_mw"}
            ),
            CastColumnsStep(op="cast_columns", column_schema={"year": "int"}),
            FilterColumnsStep(op="filter_columns", filter_by={"year": "{solve_year}"}),
            SelectColumnsStep(op="select_columns", select_columns=["region", "year", "capacity_mw"]),
        ]
    )
    result = apply_polars_processing(
        frame,
        proc_spec=proc_spec,
        placeholders={"solve_year": 2030},
    )

    assert result.is_ok()
    assert result.unwrap().collect().to_dicts() == [
        {"region": "NYISO", "year": 2030, "capacity_mw": 30},
        {"region": "PJM", "year": 2030, "capacity_mw": 40},
    ]


def test_tabular_processing_preserves_case_by_default():
    frame = pl.LazyFrame({"Technology": ["Gas & FO"]})

    preserved = (
        apply_polars_processing(frame, proc_spec=TabularProcessing(steps=[])).unwrap_or_raise().collect()
    )
    lowered = (
        apply_polars_processing(
            frame,
            proc_spec=TabularProcessing(steps=[LowercaseStep(op="lowercase", lowercase=True)]),
        )
        .unwrap_or_raise()
        .collect()
    )

    assert preserved.columns == ["Technology"]
    assert preserved["Technology"].to_list() == ["Gas & FO"]
    assert lowered.columns == ["technology"]
    assert lowered["technology"].to_list() == ["gas & fo"]


def test_tabular_numeric_string_cleanup():
    frame = pl.LazyFrame(
        {
            "limit": ["2,450"],
            "price": ["$4.99 "],
            "share": ["171.20%"],
            "count": ["-"],
        }
    )
    proc_spec = TabularProcessing(
        steps=[
            ReplaceValuesStep(op="replace_values", replace_values={"-": "0"}),
            StripCharactersStep(
                op="strip_characters", strip_chars={"limit": [","], "price": ["$"], "share": ["%"]}
            ),
            CastColumnsStep(
                op="cast_columns",
                column_schema={"limit": "float", "price": "float", "share": "float", "count": "float"},
            ),
            ScaleColumnsStep(op="scale_columns", scale={"share": 0.01}),
        ]
    )
    result = apply_polars_processing(frame, proc_spec=proc_spec).unwrap_or_raise().collect()

    assert result.to_dicts() == [{"limit": 2450.0, "price": 4.99, "share": 1.712, "count": 0.0}]


def test_apply_processing_returns_err_for_invalid_transformation():
    result = apply_polars_processing(
        pl.LazyFrame({"a": [1]}),
        proc_spec=TabularProcessing(
            steps=[FilterColumnsStep(op="filter_columns", filter_by={"missing": "x"})]
        ),
    )

    assert result.is_err()
    assert "filter_columns" in str(result.err())


def test_null_pivot_keys_are_rejected():
    result = apply_polars_processing(
        pl.LazyFrame({"id": ["a", "a"], "year": [None, 2020], "value": [1, 2]}),
        proc_spec=TabularProcessing(
            steps=[PivotStep(op="pivot", pivot_on="year", group_by=["id"], aggregate_on={"value": "sum"})]
        ),
    )

    assert result.is_err()
    assert "null" in str(result.err()).lower()


def test_tabular_unpivot_group_aggregate_pipeline():
    """Compose unpivot, grouping, aggregation, sorting, and selection."""
    frame = pl.LazyFrame(
        {
            "region": ["West", "West", "East"],
            "jan": [1, 3, 2],
            "feb": [2, 1, 4],
        }
    )
    proc_spec = TabularProcessing(
        steps=[
            LowercaseStep(op="lowercase", lowercase=True),
            UnpivotColumnsStep(op="unpivot_columns", columns=["jan", "feb"]),
            AggregateStep(op="aggregate", aggregate_on={"value": "sum"}, group_by=["region", "variable"]),
            SortStep(op="sort", by={"value": "desc"}),
            SelectColumnsStep(op="select_columns", select_columns=["region", "variable", "value"]),
        ]
    )
    result = apply_polars_processing(frame, proc_spec=proc_spec).unwrap_or_raise().collect()
    assert result["value"].to_list() == [4, 4, 3, 2]
    assert {tuple(row.values()) for row in result.to_dicts()} == {
        ("east", "feb", 4),
        ("west", "jan", 4),
        ("west", "feb", 3),
        ("east", "jan", 2),
    }


def test_tabular_processing_rejects_invalid_aggregation():
    """Reject unsupported aggregation functions during configuration validation."""
    with pytest.raises(ValueError, match="Input should be"):
        TabularProcessing(
            steps=[AggregateStep(op="aggregate", aggregate_on={"value": "average"}, group_by=[])]
        )


@pytest.mark.parametrize("function", ["n_unique", "std", "var"])
def test_tabular_processing_rejects_pivot_aggregations_unsupported_by_polars(function: str):
    with pytest.raises(ValueError, match="pivot does not support"):
        TabularProcessing(
            steps=[
                PivotStep(op="pivot", pivot_on="year", group_by=["region"], aggregate_on={"amount": function})
            ]
        )


def test_tabular_processing_rejects_unsupported_index_configuration():
    """Reject pandas index settings that Polars cannot represent."""
    with pytest.raises(ValueError, match="extra_forbidden"):
        TabularProcessing.model_validate({"steps": [], "set_index": "id"})


def test_tabular_processing_rejects_invalid_combinations():
    """Validate each reshape and aggregation operation independently."""
    with pytest.raises(ValueError, match="at least 1 item"):
        TabularProcessing(steps=[PivotStep(op="pivot", pivot_on="year", group_by=[], aggregate_on={})])
    with pytest.raises(ValueError, match="at least 1 item"):
        TabularProcessing(steps=[AggregateStep(op="aggregate", aggregate_on={}, group_by=["region"])])
    with pytest.raises(ValueError, match="group_by column"):
        TabularProcessing(
            steps=[AggregateStep(op="aggregate", aggregate_on={"region": "count"}, group_by=["region"])]
        )
    with pytest.raises(ValueError, match="Input should be 'asc' or 'desc'"):
        TabularProcessing(steps=[SortStep(op="sort", by={"value": "sideways"})])
    combined = TabularProcessing(
        steps=[
            UnpivotColumnsStep(op="unpivot_columns", columns=["amount"]),
            PivotStep(op="pivot", pivot_on="year", group_by=["id"], aggregate_on={"amount": "sum"}),
        ]
    )
    assert [step.op for step in combined.steps] == ["unpivot_columns", "pivot"]


def test_replace_values_does_not_coerce_booleans_to_numeric_columns():
    frame = pl.LazyFrame(
        {
            "flag": [True, False],
            "count": [1, 0],
            "amount": [1.0, 0.0],
        }
    )
    result = apply_polars_step(
        frame, step=ReplaceValuesStep(op="replace_values", replace_values={True: False})
    )

    assert result.collect().to_dicts() == [
        {"flag": False, "count": 1, "amount": 1.0},
        {"flag": False, "count": 0, "amount": 0.0},
    ]


def test_replace_values_can_be_limited_to_named_columns():
    frame = pl.LazyFrame(
        {
            "emission_type": ["co2", "unknown", None],
            "emission_source": ["combustion", "unknown", None],
            "other_label": ["co2", "combustion", None],
            "count": [1, None, 3],
        }
    )
    normalized_type = apply_polars_step(
        frame,
        step=ReplaceValuesStep(op="replace_values", replace_values={"co2": "CO2"}, columns=["emission_type"]),
    )
    normalized_source = apply_polars_step(
        normalized_type,
        step=ReplaceValuesStep(
            op="replace_values",
            replace_values={"combustion": "COMBUSTION", None: "COMBUSTION"},
            columns=["emission_source"],
        ),
    )

    assert normalized_source.collect().to_dicts() == [
        {"emission_type": "CO2", "emission_source": "COMBUSTION", "other_label": "co2", "count": 1},
        {
            "emission_type": "unknown",
            "emission_source": "unknown",
            "other_label": "combustion",
            "count": None,
        },
        {"emission_type": None, "emission_source": "COMBUSTION", "other_label": None, "count": 3},
    ]


def test_replace_values_rejects_missing_scoped_columns():
    with pytest.raises(ValueError, match="replace_values references missing column"):
        apply_polars_step(
            pl.LazyFrame({"value": ["old"]}),
            step=ReplaceValuesStep(op="replace_values", replace_values={"old": "new"}, columns=["missing"]),
        )


def test_replace_values_rejects_duplicate_scoped_columns():
    with pytest.raises(ValueError, match="columns cannot contain duplicates"):
        ReplaceValuesStep(op="replace_values", replace_values={"old": "new"}, columns=["value", "value"])


@pytest.mark.parametrize(
    ("stored", "dtype", "old", "new"),
    [
        pytest.param(Decimal("1.23"), pl.Decimal(5, 2), Decimal("1.234"), Decimal("2.34"), id="decimal-key"),
        pytest.param(
            Decimal("1.23"), pl.Decimal(5, 2), Decimal("1.23"), Decimal("2.345"), id="decimal-value"
        ),
        pytest.param(
            datetime(2020, 1, 1, microsecond=1_000),
            pl.Datetime("ms"),
            datetime(2020, 1, 1, microsecond=1_001),
            datetime(2021, 1, 1),
            id="datetime",
        ),
        pytest.param(1.0, pl.Float32, 1.00000001, 2.0, id="float32"),
    ],
)
def test_replace_values_rejects_values_that_lose_precision(
    stored: object, dtype: pl.DataType, old: object, new: object
):
    frame = pl.DataFrame({"value": pl.Series("value", [stored], dtype=dtype)}).lazy()
    result = apply_polars_step(frame, step=ReplaceValuesStep(op="replace_values", replace_values={old: new}))

    assert result.collect()["value"].to_list() == [stored]


def test_replace_values_still_matches_float_nan():
    from math import nan

    result = apply_polars_step(
        pl.LazyFrame({"amount": [nan]}),
        step=ReplaceValuesStep(op="replace_values", replace_values={nan: 0.0}),
    )

    assert result.collect()["amount"].to_list() == [0.0]


def test_replace_values_does_not_coerce_rationals_to_float_columns():
    from fractions import Fraction

    large_rational = Fraction(2**53 + 1, 1)
    frame = pl.LazyFrame({"amount": [float(2**53)]})
    result = apply_polars_step(
        frame, step=ReplaceValuesStep(op="replace_values", replace_values={large_rational: Fraction(0, 1)})
    )

    assert result.collect()["amount"].to_list() == [float(2**53)]


def test_replace_values_allows_only_lossless_integer_to_float_widening():
    large_integer = 2**53 + 1
    frame = pl.LazyFrame(
        {
            "count": [1, large_integer],
            "amount": [1.0, float(large_integer - 1)],
            "small": pl.Series("small", [44, 45], dtype=pl.Int8),
        }
    )
    result = apply_polars_step(
        frame, step=ReplaceValuesStep(op="replace_values", replace_values={1: 2, large_integer: 0, 300: -1})
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
def test_replace_values_preserves_logical_families(old: object, new: object, dtype: pl.DataType):
    frame = pl.DataFrame(
        {
            "value": pl.Series("value", [old], dtype=dtype),
            "whole": [1],
        }
    ).lazy()
    result = apply_polars_step(frame, step=ReplaceValuesStep(op="replace_values", replace_values={old: new}))

    assert result.collect().to_dicts() == [{"value": new, "whole": 1}]


def test_tabular_additional_operation_edges():
    """Cover direct operation calls and explicit operation errors."""
    from datetime import date

    with pytest.raises(ValueError, match="at least 1 item"):
        TabularProcessing(steps=[PivotStep(op="pivot", pivot_on="year", group_by=[], aggregate_on={})])
    with pytest.raises(ValueError, match=r"pivot.*missing column"):
        apply_polars_step(
            pl.LazyFrame({"amount": [1]}),
            step=PivotStep(op="pivot", pivot_on="label", group_by=[], aggregate_on={"amount": "sum"}),
        )
    with pytest.raises(ValueError, match="one aggregation function"):
        TabularProcessing(
            steps=[
                PivotStep(
                    op="pivot", pivot_on="year", group_by=["region"], aggregate_on={"a": "sum", "b": "mean"}
                )
            ]
        )
    with pytest.raises(ValueError, match="cannot also be a group_by or aggregate_on"):
        TabularProcessing(
            steps=[PivotStep(op="pivot", pivot_on="year", group_by=["year"], aggregate_on={"amount": "sum"})]
        )
    with pytest.raises(ValueError, match="cannot also be a group_by or aggregate_on"):
        TabularProcessing(
            steps=[PivotStep(op="pivot", pivot_on="year", group_by=[], aggregate_on={"year": "sum"})]
        )
    valid_unpivot = apply_polars_step(
        pl.LazyFrame({"amount": [1], "january": [2]}),
        step=UnpivotColumnsStep(op="unpivot_columns", columns=["amount", "january"]),
    )
    assert valid_unpivot.collect().columns == ["variable", "value"]
    with pytest.raises(ValueError, match="output names"):
        apply_polars_step(
            pl.LazyFrame({"value": [1], "amount": [2]}),
            step=UnpivotColumnsStep(op="unpivot_columns", columns=["amount"]),
        )

    today = date.today()
    mixed = pl.LazyFrame({"flag": [True, None], "when": [today, None]})
    replaced = apply_polars_step(
        mixed, step=ReplaceValuesStep(op="replace_values", replace_values={True: False})
    )
    assert replaced.collect()["flag"].to_list() == [False, None]
    temporal = apply_polars_step(
        pl.LazyFrame({"when": [today, None]}),
        step=ReplaceValuesStep(op="replace_values", replace_values={today: date(2000, 1, 1)}),
    )
    assert temporal.collect()["when"].to_list() == [date(2000, 1, 1), None]
    mixed_target = apply_polars_step(
        pl.LazyFrame({"number": [1, None], "label": ["a", None]}),
        step=ReplaceValuesStep(op="replace_values", replace_values={None: "missing"}),
    )
    mixed_target_result = mixed_target.collect()
    assert mixed_target_result["number"].to_list() == [1, None]
    assert mixed_target_result["label"].to_list() == ["a", "missing"]
    incompatible = apply_polars_step(
        pl.LazyFrame({"number": [1]}),
        step=ReplaceValuesStep(op="replace_values", replace_values={object(): "ignored"}),
    )
    assert incompatible.collect().to_dicts() == [{"number": 1}]
    opaque_value = object()
    opaque = apply_polars_step(
        pl.LazyFrame({"opaque": pl.Series("opaque", [opaque_value], dtype=pl.Object)}),
        step=ReplaceValuesStep(op="replace_values", replace_values={"old": "new"}),
    )
    assert opaque.collect()["opaque"][0] is opaque_value
    filled = apply_polars_step(mixed, step=FillNullStep(op="fill_null", fill_null={"flag": False}))
    assert filled.collect()["flag"].to_list() == [True, False]

    aggregated = apply_polars_step(
        pl.LazyFrame({"amount": [1, 2]}),
        step=AggregateStep(op="aggregate", aggregate_on={"amount": "sum"}, group_by=[]),
    )
    assert aggregated.collect().to_dicts() == [{"amount": 3}]
    sorted_frame = apply_polars_step(
        pl.LazyFrame({"amount": [1, 2]}), step=SortStep(op="sort", by={"amount": "asc"})
    )
    assert sorted_frame.collect()["amount"].to_list() == [1, 2]
    with pytest.raises(ValueError, match="duplicate column"):
        apply_polars_step(
            pl.LazyFrame({"old": [1], "new": [2]}),
            step=RenameColumnsStep(op="rename_columns", column_mapping={"old": "new"}),
        )


def test_empty_tabular_processing_preserves_frame_and_schema():
    frame = pl.LazyFrame({"label": ["value"]})
    result = apply_polars_processing(frame, proc_spec=TabularProcessing())

    assert result.is_ok()
    transformed = result.unwrap()
    assert transformed is frame
    assert transformed.collect_schema().names() == ["label"]
    assert transformed.collect().to_dicts() == [{"label": "value"}]


@pytest.mark.parametrize(
    ("years", "expected"),
    [
        pytest.param([2020, 2021], [datetime(2020, 1, 1), datetime(2021, 6, 15)], id="year-list"),
        pytest.param(2020, [datetime(2020, 1, 1)], id="single-year"),
    ],
)
def test_pl_build_filter_expr_datetime_years(years: int | list[int], expected: list[datetime]):
    """Filter datetime values by a single year or several years."""
    from r2x_core.polars_adapter.processing import pl_build_filter_expr

    frame = pl.DataFrame({"datetime": [datetime(2020, 1, 1), datetime(2021, 6, 15), datetime(2022, 12, 31)]})

    assert (
        frame.filter(pl_build_filter_expr("datetime", value=years, column_names=frame.columns))[
            "datetime"
        ].to_list()
        == expected
    )


def test_tabular_processing_reports_non_numeric_scale():
    result = apply_polars_processing(
        pl.LazyFrame({"value": ["not numeric"]}),
        proc_spec=TabularProcessing(steps=[ScaleColumnsStep(op="scale_columns", scale={"value": 0.01})]),
    )

    assert result.is_err()
    assert "scale requires numeric columns" in str(result.err())


def test_split_columns_creates_named_fields():
    frame = pl.LazyFrame({"label": ["2030|NYISO", "2035|PJM"], "capacity": [10, 20]})
    step = SplitColumnsStep(
        op="split_columns",
        split_column={"label": {"separator": "|", "into": ["year", "zone"]}},
    )

    result = apply_polars_step(frame, step=step).collect()

    assert result.columns == ["year", "zone", "capacity"]
    assert result.to_dicts() == [
        {"year": "2030", "zone": "NYISO", "capacity": 10},
        {"year": "2035", "zone": "PJM", "capacity": 20},
    ]


def test_split_column_rejects_overwriting_existing_columns():
    result = apply_polars_processing(
        pl.LazyFrame({"label": ["2030|NYISO"], "year": [2030]}),
        proc_spec=TabularProcessing(
            steps=[
                SplitColumnsStep(
                    op="split_columns", split_column={"label": {"separator": "|", "into": ["year", "zone"]}}
                )
            ]
        ),
    )

    assert result.is_err()
    assert "overwrite existing column" in str(result.err())


def test_pivot_result_reports_output_schema() -> None:
    frame = pl.LazyFrame({"region": ["a", "a"], "year": [2020, 2021], "amount": [1, 2]})
    step = PivotStep(op="pivot", pivot_on="year", group_by=["region"], aggregate_on={"amount": "sum"})
    result = apply_polars_step(frame, step=step)

    assert result.collect_schema().names() == ["region", "2020", "2021"]
    assert result.collect().to_dicts() == [{"region": "a", "2020": 1, "2021": 2}]
