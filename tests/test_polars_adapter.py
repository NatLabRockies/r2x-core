"""Public behavior tests for the Polars expression adapter."""

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import polars as pl
import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError
from rust_ok import Err, Ok

from r2x_core import DataFile, TabularProcessing
from r2x_core.models import (
    AggregateStep,
    ExpressionOperation,
    FilterColumnsStep,
    JoinStep,
    LiteralExpression,
    LowercaseStep,
    MappingStep,
    PivotStep,
    RenameColumnsStep,
    SelectStep,
)
from r2x_core.polars_adapter import PolarsTabularBackend, compile_polars_expression
from r2x_core.tabular_backend import apply_mapping_steps
from r2x_core.types import AggregationFunction, MappingExpressionOperator


@pytest.mark.parametrize("json_input", [False, True])
def test_expression_operators_are_enums_with_string_json_values(json_input: bool) -> None:
    payload = {
        "op": "divide",
        "args": [{"op": "sum", "args": [{"column": "load"}]}, {"literal": 2}],
    }
    expression = (
        ExpressionOperation.model_validate_json(json.dumps(payload))
        if json_input
        else ExpressionOperation.model_validate(payload)
    )

    assert isinstance(expression.op, StrEnum)
    assert expression.op is MappingExpressionOperator.DIVIDE
    assert isinstance(expression.args[0], ExpressionOperation)
    assert expression.args[0].op is AggregationFunction.SUM
    assert expression.model_dump(mode="json") == payload
    assert json.loads(expression.model_dump_json()) == payload
    assert ExpressionOperation.model_validate_json(expression.model_dump_json()) == expression


def test_enum_expression_operators_compile_to_polars() -> None:
    expression = ExpressionOperation(
        op=MappingExpressionOperator.DIVIDE,
        args=[LiteralExpression(literal=12), LiteralExpression(literal=3)],
    )

    result = pl.select(compile_polars_expression(expression, column_names=[]))

    assert result.item() == 4.0


@pytest.mark.parametrize("operator", ["unknown", "DIVIDE", ""])
def test_expression_schema_rejects_unknown_operators(operator: str) -> None:
    with pytest.raises(ValidationError):
        ExpressionOperation.model_validate({"op": operator, "args": [{"literal": 12}, {"literal": 3}]})


@pytest.mark.parametrize(
    "operator",
    [
        MappingExpressionOperator.DIVIDE,
        MappingExpressionOperator.CAST,
        MappingExpressionOperator.LIST_GET,
        MappingExpressionOperator.SPLIT,
    ],
)
def test_binary_expression_operators_require_two_arguments(operator: MappingExpressionOperator) -> None:
    with pytest.raises(ValidationError, match=f"{operator.value} expects exactly two arguments"):
        ExpressionOperation(op=operator, args=[LiteralExpression(literal=1)])


@pytest.mark.parametrize(
    ("operator", "arguments", "message"),
    [
        (
            AggregationFunction.SUM,
            [LiteralExpression(literal=1), LiteralExpression(literal=2)],
            "sum expects exactly one argument",
        ),
        (
            MappingExpressionOperator.DATETIME,
            [LiteralExpression(literal=2024), LiteralExpression(literal=1)],
            "datetime expects year, month, day",
        ),
    ],
)
def test_unary_and_datetime_expressions_reject_invalid_argument_counts(
    operator: AggregationFunction | MappingExpressionOperator,
    arguments: list[LiteralExpression],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ExpressionOperation(op=operator, args=arguments)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            {
                "op": "and",
                "args": [
                    {"op": "le", "args": [{"column": "left"}, {"column": "right"}]},
                    {"op": "gt", "args": [{"column": "right"}, {"literal": 4}]},
                ],
            },
            [False, True],
        ),
        (
            {"op": "any", "args": [{"op": "is_null", "args": [{"column": "maybe"}]}]},
            [True, False],
        ),
        (
            {
                "op": "cast",
                "args": [
                    {"op": "strip_chars", "args": [{"column": "raw"}]},
                    {"literal": "Int64"},
                ],
            },
            [4, 6],
        ),
        (
            {"op": "coalesce", "args": [{"column": "maybe"}, {"literal": "fallback"}]},
            ["fallback", "ready"],
        ),
        (
            {"op": "concat_list", "args": [{"column": "left"}, {"column": "right"}]},
            [[2, 3], [5, 7]],
        ),
        (
            {
                "op": "concat_str",
                "args": [{"column": "left"}, {"literal": ":"}, {"column": "right"}],
            },
            ["2:3", "5:7"],
        ),
        (
            {
                "op": "datetime",
                "args": [
                    {"column": "year"},
                    {"column": "month"},
                    {"column": "day"},
                    {"column": "hour"},
                ],
            },
            [datetime(2024, 1, 2), datetime(2025, 2, 3, 1)],
        ),
        (
            {"op": "divide", "args": [{"column": "left"}, {"column": "right"}]},
            pytest.approx([2 / 3, 5 / 7]),
        ),
        (
            {"op": "eq", "args": [{"column": "left"}, {"literal": 2}]},
            [True, False],
        ),
        (
            {"op": "gt", "args": [{"column": "left"}, {"literal": 3}]},
            [False, True],
        ),
        (
            {"op": "is_null", "args": [{"column": "maybe"}]},
            [True, False],
        ),
        (
            {"op": "le", "args": [{"column": "left"}, {"column": "right"}]},
            [True, True],
        ),
        (
            {
                "op": "list_get",
                "args": [
                    {"op": "concat_list", "args": [{"column": "left"}, {"column": "right"}]},
                    {"literal": 1},
                ],
            },
            [3, 7],
        ),
        (
            {"op": "list_get", "args": [{"column": "short_list"}, {"literal": 1}]},
            [None, None],
        ),
        (
            {
                "op": "list_sort",
                "args": [{"op": "concat_list", "args": [{"column": "right"}, {"column": "left"}]}],
            },
            [[2, 3], [5, 7]],
        ),
        (
            {"op": "lowercase", "args": [{"column": "text"}]},
            [" a-b ", "x-y"],
        ),
        ({"op": "max", "args": [{"column": "left"}]}, [5]),
        ({"op": "mean", "args": [{"column": "left"}]}, [3.5]),
        (
            {"op": "multiply", "args": [{"column": "left"}, {"column": "right"}]},
            [6, 35],
        ),
        (
            {"op": "split", "args": [{"column": "text"}, {"literal": "-"}]},
            [[" A", "B "], ["X", "y"]],
        ),
        (
            {"op": "strip_chars", "args": [{"column": "raw"}]},
            ["4", "6"],
        ),
        (
            {"op": "struct", "args": [{"column": "left"}, {"column": "right"}]},
            [{"left": 2, "right": 3}, {"left": 5, "right": 7}],
        ),
        (
            {"op": "subtract", "args": [{"column": "right"}, {"column": "left"}]},
            [1, 2],
        ),
        ({"op": "sum", "args": [{"column": "left"}]}, [7]),
        (
            {
                "op": "when",
                "args": [
                    {"op": "eq", "args": [{"column": "left"}, {"literal": 2}]},
                    {"literal": "yes"},
                    {"literal": "no"},
                ],
            },
            ["yes", "no"],
        ),
        (
            {
                "op": "year",
                "args": [
                    {
                        "op": "datetime",
                        "args": [
                            {"column": "year"},
                            {"column": "month"},
                            {"column": "day"},
                            {"column": "hour"},
                        ],
                    }
                ],
            },
            [2024, 2025],
        ),
    ],
)
def test_mapping_expressions_compile_to_polars_results(
    expression: dict[str, object], expected: object
) -> None:
    """The backend adapter preserves the declared mapping-expression semantics."""
    frame = pl.DataFrame(
        {
            "left": [2, 5],
            "right": [3, 7],
            "text": [" A-B ", "X-y"],
            "maybe": [None, "ready"],
            "raw": [" 4 ", " 6 "],
            "year": [2024, 2025],
            "month": [1, 2],
            "day": [2, 3],
            "hour": [0, 1],
            "short_list": [[1], [2]],
        }
    ).lazy()
    select = SelectStep.model_validate({"op": "select", "columns": {"result": expression}})
    compiled = compile_polars_expression(
        select.columns["result"], column_names=frame.collect_schema().names()
    )
    actual = frame.select(compiled.alias("result")).collect().get_column("result").to_list()

    assert actual == expected


def test_mapping_steps_preserve_regex_shaped_column_names() -> None:
    frame = pl.LazyFrame({"load": [10.0], "^load$": [99.0], "*": [7]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [
            {
                "op": "select",
                "columns": {
                    "regex_name": {"column": "^load$"},
                    "wildcard_name": {"column": "*"},
                    "doubled": {"op": "multiply", "args": [{"column": "^load$"}, {"literal": 2}]},
                },
            }
        ]
    )

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend())

    assert result.unwrap().collect().to_dicts() == [
        {"regex_name": 99.0, "wildcard_name": 7, "doubled": 198.0}
    ]


@pytest.mark.parametrize("column_name", ["missing", "^load$", "*"])
def test_mapping_steps_fail_for_missing_exact_column_name(column_name: str) -> None:
    frame = pl.LazyFrame({"load": [10.0]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "select", "columns": {"result": {"column": column_name}}}]
    )

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend())

    assert isinstance(result, Err)
    assert f"Column {column_name!r} not found" in str(result.err())


def test_mapping_steps_reject_unsupported_expression_types() -> None:
    """Return explicit errors when a configured expression cannot be compiled."""
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [
            {
                "op": "select",
                "columns": {
                    "converted": {
                        "op": "cast",
                        "args": [{"column": "value"}, {"literal": "unknown-type"}],
                    }
                },
            }
        ]
    )
    result = apply_mapping_steps(pl.LazyFrame({"value": [1]}), steps, backend=PolarsTabularBackend())
    assert isinstance(result, Err)
    assert "Unsupported data type: unknown-type" in str(result.err())


def test_mapping_steps_preserve_exact_column_names() -> None:
    frame = pl.LazyFrame({"value": [1], " value ": [2]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [
            {
                "op": "select",
                "columns": {
                    "result": {"column": "value"},
                    " result ": {"column": " value "},
                },
            }
        ]
    )

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend())

    assert result.unwrap().collect().to_dicts() == [{"result": 1, " result ": 2}]


def test_polars_backend_executes_mapping_steps_and_joins() -> None:
    """The generic step runner delegates table operations to its selected backend."""
    frame = pl.LazyFrame({"id": [1, 2], "left": [2, 5], "right": [3, 7]})
    lookup = pl.LazyFrame({"id": [1, 2], "label": ["small", "large"]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [
            {"op": "join", "source": "labels", "how": "left", "on": ["id"], "validate": "1:1"},
            {
                "op": "with_columns",
                "columns": {
                    "product": {
                        "op": "multiply",
                        "args": [{"column": "left"}, {"column": "right"}],
                    }
                },
            },
            {
                "op": "filter",
                "predicate": {"op": "gt", "args": [{"column": "product"}, {"literal": 10}]},
            },
            {"op": "select", "columns": {"label": {"column": "label"}, "product": {"column": "product"}}},
        ]
    )

    result = apply_mapping_steps(
        frame,
        steps,
        backend=PolarsTabularBackend(),
        source_frames={"labels": lookup},
    )

    assert isinstance(result, Ok)
    assert result.value.collect().to_dicts() == [{"label": "large", "product": 35}]


def test_polars_backend_executes_assert_group_sort_unique_and_unpivot_steps() -> None:
    """Each table step transforms rows according to its mapping semantics."""
    frame = pl.LazyFrame({"category": ["b", "a", "b"], "value": [2, 3, 4]})
    grouped_steps = TypeAdapter(list[MappingStep]).validate_python(
        [
            {
                "op": "assert",
                "predicate": {"op": "gt", "args": [{"column": "value"}, {"literal": 0}]},
            },
            {
                "op": "group_by",
                "by": ["category"],
                "agg": {"total": {"op": "sum", "args": [{"column": "value"}]}},
            },
            {"op": "sort", "by": {"category": "asc"}},
            {"op": "unique", "subset": ["category"]},
        ]
    )
    grouped = apply_mapping_steps(frame, grouped_steps, backend=PolarsTabularBackend())

    assert isinstance(grouped, Ok)
    assert grouped.value.collect().to_dicts() == [
        {"category": "a", "total": 3},
        {"category": "b", "total": 6},
    ]

    unpivot_steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "unpivot", "index": ["category"], "variable_name": "measure", "value_name": "amount"}]
    )
    unpivoted = apply_mapping_steps(
        pl.LazyFrame({"category": ["a"], "first": [1], "second": [2]}),
        unpivot_steps,
        backend=PolarsTabularBackend(),
    )

    assert isinstance(unpivoted, Ok)
    assert unpivoted.value.collect().to_dicts() == [
        {"category": "a", "measure": "first", "amount": 1},
        {"category": "a", "measure": "second", "amount": 2},
    ]


@pytest.mark.parametrize(
    ("sort_first", "expected"),
    [
        (False, [("b", 3, "b-first"), ("a", 4, "a-first")]),
        (True, [("b", 1, "b-priority"), ("a", 2, "a-priority")]),
    ],
)
def test_unique_steps_keep_the_first_row_for_each_key(
    sort_first: bool, expected: list[tuple[str, int, str]]
) -> None:
    frame = pl.LazyFrame(
        {
            "key": ["b", "a", "b", "a"],
            "priority": [3, 4, 1, 2],
            "payload": ["b-first", "a-first", "b-priority", "a-priority"],
        }
    )
    steps = TypeAdapter(list[MappingStep]).validate_python(
        ([{"op": "sort", "by": {"priority": "asc"}}] if sort_first else [])
        + [{"op": "unique", "subset": ["key"]}]
    )

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend())

    assert result.unwrap().collect().rows() == expected


def test_polars_backend_delegates_custom_steps_to_app_handlers() -> None:
    """Applications can add table behavior without extending core schemas."""

    class AddValueOptions(BaseModel):
        increment: int

    class AddValueHandler:
        options_model: type[AddValueOptions] = AddValueOptions
        input_type: type[pl.LazyFrame] = pl.LazyFrame
        output_type: type[pl.LazyFrame] = pl.LazyFrame

        def apply(self, value: pl.LazyFrame, *, options: AddValueOptions) -> pl.LazyFrame:
            return value.with_columns((pl.col("value") + options.increment).alias("value"))

    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "custom", "handler": "add_value", "kwargs": {"increment": 4}}]
    )
    result = apply_mapping_steps(
        pl.LazyFrame({"value": [1, 2]}),
        steps,
        backend=PolarsTabularBackend(step_handlers={"add_value": AddValueHandler()}),
    )

    assert isinstance(result, Ok)
    assert result.value.collect().to_dicts() == [{"value": 5}, {"value": 6}]


@pytest.mark.parametrize(
    ("input_type", "output_type", "output", "message"),
    [
        (pl.DataFrame, pl.LazyFrame, pl.LazyFrame({"value": [1]}), "expects DataFrame"),
        (
            pl.LazyFrame,
            pl.DataFrame,
            pl.LazyFrame({"value": [1]}),
            "declared DataFrame but returned LazyFrame",
        ),
        (pl.LazyFrame, object, {"value": [1]}, "must return a Polars LazyFrame"),
    ],
)
def test_custom_handlers_must_respect_their_polars_type_contract(
    input_type: type[object], output_type: type[object], output: object, message: str
) -> None:
    class EmptyOptions(BaseModel):
        pass

    class InvalidHandler:
        options_model = EmptyOptions

        def __init__(self) -> None:
            self.input_type = input_type
            self.output_type = output_type

        def apply(self, value: object, *, options: EmptyOptions) -> object:
            return output

    steps = TypeAdapter(list[MappingStep]).validate_python([{"op": "custom", "handler": "invalid"}])
    result = apply_mapping_steps(
        pl.LazyFrame({"value": [1]}),
        steps,
        backend=PolarsTabularBackend(step_handlers={"invalid": InvalidHandler()}),
    )

    assert isinstance(result, Err)
    assert message in str(result.err())


def test_lowercase_and_empty_column_filters_have_defined_behavior() -> None:
    unchanged = pl.LazyFrame({"Name": ["ALICE"]})
    lowercase_disabled = apply_mapping_steps(
        unchanged,
        [LowercaseStep(op="lowercase", lowercase=False)],
        backend=PolarsTabularBackend(),
    )
    empty_filter = apply_mapping_steps(
        unchanged,
        [FilterColumnsStep(op="filter_columns", filter_by={})],
        backend=PolarsTabularBackend(),
    )
    duplicate_columns = apply_mapping_steps(
        pl.LazyFrame({"Name": ["ALICE"], "name": ["alice"]}),
        [LowercaseStep(op="lowercase")],
        backend=PolarsTabularBackend(),
    )

    assert lowercase_disabled.unwrap().collect().to_dicts() == [{"Name": "ALICE"}]
    assert empty_filter.unwrap().collect().to_dicts() == [{"Name": "ALICE"}]
    assert isinstance(duplicate_columns, Err)
    assert "lowercase creates duplicate column names" in str(duplicate_columns.err())


def test_polars_processing_rejects_unresolved_aggregation_placeholders() -> None:
    frame = pl.LazyFrame({"amount": [2, 3], "year": [2024, 2025], "region": ["north", "south"]})
    backend = PolarsTabularBackend()
    aggregate = apply_mapping_steps(
        frame,
        [AggregateStep(op="aggregate", aggregate_on={"amount": "{function}"})],
        backend=backend,
    )
    pivot = apply_mapping_steps(
        frame,
        [
            PivotStep(
                op="pivot",
                pivot_on="year",
                group_by=["region"],
                aggregate_on={"amount": "{function}"},
            )
        ],
        backend=backend,
    )

    assert isinstance(aggregate, Err)
    assert "Unresolved aggregation placeholder" in str(aggregate.err())
    assert isinstance(pivot, Err)
    assert "Unresolved pivot aggregation placeholder" in str(pivot.err())


@pytest.mark.parametrize(
    ("step", "message"),
    [
        (
            {"op": "assert", "predicate": {"op": "gt", "args": [{"column": "value"}, {"literal": 0}]}},
            "assert step failed",
        ),
        (
            {"op": "assert", "predicate": {"literal": None}},
            "assert step failed",
        ),
        (
            {"op": "assert", "predicate": {"literal": False}},
            "assert step failed",
        ),
        (
            {"op": "unpivot", "index": ["missing"], "variable_name": "field", "value_name": "amount"},
            "unpivot index references missing column(s)",
        ),
        (
            {"op": "unpivot", "index": ["id", "value"], "variable_name": "field", "value_name": "amount"},
            "unpivot requires at least one value column",
        ),
        (
            {"op": "unpivot", "index": ["id"], "variable_name": "field", "value_name": "field"},
            "unpivot output names must be distinct",
        ),
        (
            {"op": "unpivot", "index": ["id"], "variable_name": "id", "value_name": "amount"},
            "unpivot output names must be distinct",
        ),
        (
            {"op": "join", "source": "missing", "how": "left", "on": ["id"]},
            "join source 'missing' was not provided",
        ),
        (
            {"op": "custom", "handler": "missing"},
            "No custom mapping handler registered for 'missing'",
        ),
    ],
)
def test_mapping_steps_stop_at_the_first_error(step: dict[str, object], message: str) -> None:
    frame = pl.LazyFrame({"id": [1, 2], "value": [1, -1]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [step, {"op": "custom", "handler": "must_not_run"}]
    )

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend())

    assert isinstance(result, Err)
    assert isinstance(result.err(), ValueError)
    assert message in str(result.err())


def test_mapping_steps_support_cross_joins_without_join_keys() -> None:
    frame = pl.LazyFrame({"id": [1, 2]})
    labels = pl.LazyFrame({"label": ["a", "b"]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "join", "source": "labels", "how": "cross"}]
    )

    result = apply_mapping_steps(
        frame, steps, backend=PolarsTabularBackend(), source_frames={"labels": labels}
    )

    assert result.unwrap().sort("id", "label").collect().rows() == [(1, "a"), (1, "b"), (2, "a"), (2, "b")]


def test_polars_backend_rejects_a_join_without_its_named_source() -> None:
    """Return an explicit operation error for a missing compatible source."""
    backend = PolarsTabularBackend()
    result = backend.apply_mapping_operation(
        JoinStep(op="join", source="missing", on=["id"], how="left"),
        pl.LazyFrame({"id": [1]}),
        source_frames={},
    )
    assert isinstance(result, Err)
    assert "join source 'missing' was not provided" in str(result.err())


def test_polars_backend_processes_existing_tabular_configuration(tmp_path: Path) -> None:
    """Existing TabularProcessing uses the same injected backend contract."""
    frame = pl.LazyFrame({"old_name": ["a", "b"]})
    input_path = tmp_path / "input.csv"
    input_path.touch()
    data_file = DataFile(name="backend-processing", fpath=input_path)
    backend = PolarsTabularBackend()

    result = backend.process(
        frame,
        data_file=data_file,
        processing=TabularProcessing(
            steps=[RenameColumnsStep(op="rename_columns", column_mapping={"old_name": "name"})]
        ),
        sources={},
    )

    assert isinstance(result, Ok)
    assert result.value.collect().to_dicts() == [{"name": "a"}, {"name": "b"}]


@pytest.mark.parametrize(
    "expression",
    [
        {"op": "cast", "args": [{"column": "value"}, {"column": "dtype"}]},
        {"op": "split", "args": [{"column": "value"}, {"literal": 1}]},
        {"op": "list_get", "args": [{"column": "value"}, {"literal": 1.5}]},
        {"op": "when", "args": [{"literal": True}, {"literal": 1}]},
    ],
)
def test_expression_schema_rejects_invalid_operation_arguments(
    expression: dict[str, object],
) -> None:
    """Expression validation catches invalid mapping arguments before execution."""
    with pytest.raises(ValidationError):
        SelectStep.model_validate({"op": "select", "columns": {"result": expression}})
