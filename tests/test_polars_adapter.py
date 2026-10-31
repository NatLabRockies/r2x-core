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
from r2x_core.exceptions import ReaderError
from r2x_core.file_reader import TabularSource
from r2x_core.models import (
    AggregateStep,
    Expression,
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
from r2x_core.reader import DataReader
from r2x_core.tabular_backend import apply_mapping_steps
from r2x_core.types import AggregationFunction, MappingExpressionOperator

pytestmark = [pytest.mark.processing, pytest.mark.table_mapping, pytest.mark.polars]


@pytest.mark.parametrize("json_input", [False, True])
def test_compact_expression_schema_round_trips_and_names_exact_columns(json_input: bool) -> None:
    adapter = TypeAdapter(Expression)
    payload = {"multiply": ["^load$", 2]}

    expression = (
        adapter.validate_json(json.dumps(payload)) if json_input else adapter.validate_python(payload)
    )
    frame = pl.DataFrame({"^load$": [5], "load": [100]})
    actual = frame.select(compile_polars_expression(expression, column_names=frame.columns)).item()
    schema = adapter.json_schema()
    operation_schema = schema["$defs"]["ExpressionOperation"]

    assert actual == 10
    assert adapter.dump_python(expression, mode="json") == payload
    assert adapter.validate_json(adapter.dump_json(expression)) == expression
    assert operation_schema["minProperties"] == operation_schema["maxProperties"] == 1
    assert "multiply" in operation_schema["propertyNames"]["enum"]
    for legacy in ({"column": "^load$"}, {"op": "multiply", "args": ["^load$", 2]}):
        with pytest.raises(ValidationError):
            adapter.validate_python(legacy)
        with pytest.raises(ValidationError):
            adapter.validate_json(json.dumps(legacy))


@pytest.mark.parametrize("payload", [{}, {"add": [1, 2], "multiply": [3, 4]}])
@pytest.mark.parametrize("json_input", [False, True])
def test_compact_expression_rejects_zero_or_multiple_operations(
    payload: dict[str, list[int]], json_input: bool
) -> None:
    adapter = TypeAdapter(Expression)

    with pytest.raises(ValidationError):
        if json_input:
            adapter.validate_json(json.dumps(payload))
        else:
            adapter.validate_python(payload)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("op", "column-value"),
        ({"literal": "op"}, "op"),
        (1, 1),
        ({"literal": 1}, 1),
        (1.5, 1.5),
        ({"literal": 1.5}, 1.5),
        (True, True),
        ({"literal": True}, True),
        (None, None),
        ({"literal": None}, None),
    ],
)
def test_compact_expressions_preserve_column_and_scalar_types(payload: object, expected: object) -> None:
    adapter = TypeAdapter(Expression)
    expression = adapter.validate_python(payload)
    frame = pl.DataFrame({"op": ["column-value"]})
    result = frame.select(compile_polars_expression(expression, column_names=frame.columns)).item()

    assert type(result) is type(expected)
    assert result == expected


@pytest.mark.parametrize("json_input", [False, True])
def test_expression_operators_are_enums_with_string_json_values(json_input: bool) -> None:
    payload = {"divide": [{"sum": ["load"]}, 2]}
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
    expression = ExpressionOperation.model_validate({"divide": [12, 3]})

    result = pl.select(compile_polars_expression(expression, column_names=[]))

    assert result.item() == 4.0


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        pytest.param([2024, 1, 2], datetime(2024, 1, 2), id="date"),
        pytest.param([2024, 1, 2, 3], datetime(2024, 1, 2, 3), id="hour"),
        pytest.param([2024, 1, 2, 3, 4], datetime(2024, 1, 2, 3, 4), id="minute"),
        pytest.param([2024, 1, 2, 3, 4, 5], datetime(2024, 1, 2, 3, 4, 5), id="second"),
        pytest.param([2024, 1, 2, 3, 4, 5, 6789], datetime(2024, 1, 2, 3, 4, 5, 6789), id="microsecond"),
    ],
)
def test_datetime_mapping_expression_accepts_each_valid_arity(parts: list[int], expected: datetime) -> None:
    expression = ExpressionOperation.model_validate({"datetime": parts})

    result = pl.select(compile_polars_expression(expression, column_names=[]))

    assert result.item() == expected


@pytest.mark.parametrize(
    ("function", "expected"),
    [
        pytest.param(AggregationFunction.COUNT, 2, id="count-excludes-null"),
        pytest.param(AggregationFunction.FIRST, 2, id="first"),
        pytest.param(AggregationFunction.LAST, 4, id="last"),
        pytest.param(AggregationFunction.MAX, 4, id="max"),
        pytest.param(AggregationFunction.MEAN, 3.0, id="mean"),
        pytest.param(AggregationFunction.MEDIAN, 3.0, id="median"),
        pytest.param(AggregationFunction.MIN, 2, id="min"),
        pytest.param(AggregationFunction.N_UNIQUE, 3, id="n-unique-includes-null"),
        pytest.param(AggregationFunction.STD, pytest.approx(2**0.5), id="std"),
        pytest.param(AggregationFunction.SUM, 6, id="sum"),
        pytest.param(AggregationFunction.VAR, 2, id="var"),
    ],
)
def test_mapping_expression_supports_every_declared_aggregation(
    function: AggregationFunction, expected: object
) -> None:
    frame = pl.DataFrame({"value": [2, None, 4]})
    expression = ExpressionOperation.model_validate({function.value: ["value"]})
    compiled = compile_polars_expression(expression, column_names=frame.columns)

    assert frame.select(compiled.alias("result")).item() == expected


@pytest.mark.parametrize("function", list(AggregationFunction), ids=lambda function: function.value)
@pytest.mark.parametrize("argument_count", [0, 2], ids=["no-operands", "multiple-operands"])
def test_aggregation_expressions_require_one_operand(
    function: AggregationFunction, argument_count: int
) -> None:
    arguments = list(range(argument_count))

    with pytest.raises(ValidationError) as exc_info:
        ExpressionOperation.model_validate({function.value: arguments})

    if argument_count == 2:
        assert f"{function.value} expects exactly one argument" in str(exc_info.value)


@pytest.mark.parametrize("operator", ["unknown", "DIVIDE", ""])
def test_expression_schema_rejects_unknown_operators(operator: str) -> None:
    with pytest.raises(ValidationError):
        ExpressionOperation.model_validate({operator: [12, 3]})


@pytest.mark.parametrize(
    "operator",
    [
        MappingExpressionOperator.DIVIDE,
        MappingExpressionOperator.CAST,
        MappingExpressionOperator.LIST_GET,
        MappingExpressionOperator.SPLIT,
        MappingExpressionOperator.STRFTIME,
    ],
)
def test_binary_expression_operators_require_two_arguments(operator: MappingExpressionOperator) -> None:
    with pytest.raises(ValidationError, match=f"{operator.value} expects exactly two arguments"):
        ExpressionOperation.model_validate({operator.value: [1]})


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
        (
            MappingExpressionOperator.MONTH,
            [LiteralExpression(literal=2024), LiteralExpression(literal=1)],
            "month expects exactly one argument",
        ),
    ],
)
def test_unary_and_datetime_expressions_reject_invalid_argument_counts(
    operator: AggregationFunction | MappingExpressionOperator,
    arguments: list[Expression],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        ExpressionOperation.model_validate({operator.value: arguments})


@pytest.mark.parametrize(
    "format_expression",
    ["%b", {"literal": 12}],
    ids=["column-reference", "non-string-literal"],
)
def test_strftime_requires_a_literal_string_format(format_expression: object) -> None:
    with pytest.raises(ValidationError, match="strftime requires a literal string format string"):
        ExpressionOperation.model_validate({"strftime": ["timestamp", format_expression]})


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            {"and": [{"le": ["left", "right"]}, {"gt": ["right", 4]}]},
            [False, True],
        ),
        (
            {"any": [{"is_null": ["maybe"]}]},
            [True, False],
        ),
        (
            {"cast": [{"strip_chars": ["raw"]}, {"literal": "Int64"}]},
            [4, 6],
        ),
        (
            {"coalesce": ["maybe", {"literal": "fallback"}]},
            ["fallback", "ready"],
        ),
        (
            {"concat_list": ["left", "right"]},
            [[2, 3], [5, 7]],
        ),
        (
            {"concat_str": ["left", {"literal": ":"}, "right"]},
            ["2:3", "5:7"],
        ),
        (
            {"datetime": ["year", "month", "day", "hour"]},
            [datetime(2024, 1, 2), datetime(2025, 2, 3, 1)],
        ),
        (
            {"divide": ["left", "right"]},
            pytest.approx([2 / 3, 5 / 7]),
        ),
        (
            {"eq": ["left", 2]},
            [True, False],
        ),
        (
            {"gt": ["left", 3]},
            [False, True],
        ),
        (
            {"is_null": ["maybe"]},
            [True, False],
        ),
        (
            {"le": ["left", "right"]},
            [True, True],
        ),
        (
            {"list_get": [{"concat_list": ["left", "right"]}, 1]},
            [3, 7],
        ),
        (
            {"list_get": ["short_list", 1]},
            [None, None],
        ),
        (
            {"list_sort": [{"concat_list": ["right", "left"]}]},
            [[2, 3], [5, 7]],
        ),
        (
            {"lowercase": ["text"]},
            [" a-b ", "x-y"],
        ),
        ({"month": ["timestamp"]}, [2, 12]),
        ({"max": ["left"]}, [5]),
        ({"mean": ["left"]}, [3.5]),
        (
            {"multiply": ["left", "right"]},
            [6, 35],
        ),
        (
            {"split": ["text", {"literal": "-"}]},
            [[" A", "B "], ["X", "y"]],
        ),
        ({"strftime": ["timestamp", {"literal": "%b"}]}, ["Feb", "Dec"]),
        (
            {"lowercase": [{"strftime": ["timestamp", {"literal": "%b"}]}]},
            ["feb", "dec"],
        ),
        (
            {"strip_chars": ["raw"]},
            ["4", "6"],
        ),
        (
            {"struct": ["left", "right"]},
            [{"left": 2, "right": 3}, {"left": 5, "right": 7}],
        ),
        (
            {"subtract": ["right", "left"]},
            [1, 2],
        ),
        ({"sum": ["left"]}, [7]),
        (
            {"when": [{"eq": ["left", 2]}, {"literal": "yes"}, {"literal": "no"}]},
            ["yes", "no"],
        ),
        (
            {"year": [{"datetime": ["year", "month", "day", "hour"]}]},
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
            "timestamp": [datetime(2024, 2, 29), datetime(2025, 12, 31)],
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
                    "regex_name": "^load$",
                    "wildcard_name": "*",
                    "doubled": {"multiply": ["^load$", 2]},
                },
            }
        ]
    )

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend())

    assert result.unwrap().collect().to_dicts() == [
        {"regex_name": 99.0, "wildcard_name": 7, "doubled": 198.0}
    ]


def test_named_column_steps_use_exact_names_for_scale_and_select() -> None:
    frame = pl.LazyFrame({"^load$": [5, 6], "load": [100, 200]})
    backend = PolarsTabularBackend()
    scale = TypeAdapter(list[MappingStep]).validate_python([{"op": "scale_columns", "scale": {"^load$": 2}}])
    select = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "select_columns", "select_columns": ["^load$"]}]
    )

    scaled = apply_mapping_steps(frame, scale, backend=backend).unwrap().collect()
    selected = apply_mapping_steps(frame, select, backend=backend).unwrap().collect()

    assert scaled.to_dicts() == [{"^load$": 10, "load": 100}, {"^load$": 12, "load": 200}]
    assert selected.columns == ["^load$"]
    assert selected.to_series().to_list() == [5, 6]


@pytest.mark.parametrize(
    ("data", "step", "columns", "rows"),
    [
        pytest.param(
            {"^key$": ["a", "b"], "key": ["x", "x"], "^value$": [1, 2]},
            {"op": "filter_columns", "filter_by": {"^key$": "a"}},
            ["^key$", "key", "^value$"],
            [{"^key$": "a", "key": "x", "^value$": 1}],
            id="filter",
        ),
        pytest.param(
            {"^key$": ["a"], "key": ["x"], "^value$": [1]},
            {"op": "drop_columns", "drop_columns": ["^value$"]},
            ["^key$", "key"],
            [{"^key$": "a", "key": "x"}],
            id="drop",
        ),
        pytest.param(
            {"^key$": ["a"], "key": ["x"]},
            {"op": "rename_columns", "column_mapping": {"^key$": "renamed"}},
            ["renamed", "key"],
            [{"renamed": "a", "key": "x"}],
            id="rename",
        ),
        pytest.param(
            {"^label$": ["2030|NY"], "label": ["2031|TX"]},
            {
                "op": "split_columns",
                "split_column": {"^label$": {"separator": "|", "into": ["year", "zone"]}},
            },
            ["year", "zone", "label"],
            [{"year": "2030", "zone": "NY", "label": "2031|TX"}],
            id="split",
        ),
        pytest.param(
            {"^label$": [" old "], "label": ["keep"]},
            {"op": "replace_values", "replace_values": {" old ": "new"}},
            ["^label$", "label"],
            [{"^label$": "new", "label": "keep"}],
            id="replace",
        ),
        pytest.param(
            {"^label$": [" old "], "label": [" old "]},
            {"op": "strip_characters", "strip_chars": {"^label$": [" "]}},
            ["^label$", "label"],
            [{"^label$": "old", "label": " old "}],
            id="strip",
        ),
        pytest.param(
            {"^value$": [1, 2], "value": [100, 200]},
            {"op": "cast_columns", "column_schema": {"^value$": "str"}},
            ["^value$", "value"],
            [{"^value$": "1", "value": 100}, {"^value$": "2", "value": 200}],
            id="cast",
        ),
        pytest.param(
            {"^value$": [None, 2], "value": [100, 200]},
            {"op": "fill_null", "fill_null": {"^value$": 0}},
            ["^value$", "value"],
            [{"^value$": 0, "value": 100}, {"^value$": 2, "value": 200}],
            id="fill-null",
        ),
        pytest.param(
            {"^key$": ["a", "a"], "key": ["x", "y"], "^load$": [2, 3], "load": [100, 200]},
            {"op": "aggregate", "aggregate_on": {"^load$": "sum"}, "group_by": ["^key$"]},
            ["^key$", "^load$"],
            [{"^key$": "a", "^load$": 5}],
            id="aggregate",
        ),
        pytest.param(
            {"^priority$": [2, 1], "priority": [1, 2]},
            {"op": "sort", "by": {"^priority$": "asc"}},
            ["^priority$", "priority"],
            [{"^priority$": 1, "priority": 2}, {"^priority$": 2, "priority": 1}],
            id="sort",
        ),
        pytest.param(
            {"^key$": ["a", "b"], "key": ["x", "x"], "^load$": [1, 2]},
            {"op": "unpivot_columns", "columns": ["^load$"]},
            ["^key$", "key", "variable", "value"],
            [
                {"^key$": "a", "key": "x", "variable": "^load$", "value": 1},
                {"^key$": "b", "key": "x", "variable": "^load$", "value": 2},
            ],
            id="unpivot",
        ),
    ],
)
def test_tabular_operations_resolve_literal_column_names(
    data: dict[str, list[object]],
    step: dict[str, object],
    columns: list[str],
    rows: list[dict[str, object]],
) -> None:
    steps = TypeAdapter(list[MappingStep]).validate_python([step])
    result = apply_mapping_steps(pl.LazyFrame(data), steps, backend=PolarsTabularBackend()).unwrap().collect()

    assert result.columns == columns
    assert result.to_dicts() == rows


@pytest.mark.parametrize(
    ("how", "columns", "expected"),
    [
        pytest.param(
            "inner",
            ["left_id", "^key$", "key", "payload", "key_right"],
            [{"left_id": "L1", "^key$": "a", "key": "lx", "payload": "R1", "key_right": "rx"}],
            id="inner-coalesces-key",
        ),
        pytest.param(
            "left",
            ["left_id", "^key$", "key", "payload", "key_right"],
            [
                {"left_id": "L1", "^key$": "a", "key": "lx", "payload": "R1", "key_right": "rx"},
                {"left_id": "L2", "^key$": "b", "key": "ly", "payload": None, "key_right": None},
                {"left_id": "LN", "^key$": None, "key": "ln", "payload": None, "key_right": None},
            ],
            id="left-null-not-matched",
        ),
        pytest.param(
            "right",
            ["left_id", "key", "payload", "key_right", "^key$"],
            [
                {"left_id": "L1", "key": "lx", "payload": "R1", "key_right": "rx", "^key$": "a"},
                {"left_id": None, "key": None, "payload": "R3", "key_right": "ry", "^key$": "c"},
                {"left_id": None, "key": None, "payload": "RN", "key_right": "rn", "^key$": None},
            ],
            id="right-key-position-and-null",
        ),
        pytest.param(
            "full",
            ["left_id", "^key$", "key", "payload", "key_right", "^key$_right"],
            [
                {
                    "left_id": "L1",
                    "^key$": "a",
                    "key": "lx",
                    "payload": "R1",
                    "key_right": "rx",
                    "^key$_right": "a",
                },
                {
                    "left_id": None,
                    "^key$": None,
                    "key": None,
                    "payload": "R3",
                    "key_right": "ry",
                    "^key$_right": "c",
                },
                {
                    "left_id": None,
                    "^key$": None,
                    "key": None,
                    "payload": "RN",
                    "key_right": "rn",
                    "^key$_right": None,
                },
                {
                    "left_id": "L2",
                    "^key$": "b",
                    "key": "ly",
                    "payload": None,
                    "key_right": None,
                    "^key$_right": None,
                },
                {
                    "left_id": "LN",
                    "^key$": None,
                    "key": "ln",
                    "payload": None,
                    "key_right": None,
                    "^key$_right": None,
                },
            ],
            id="full-keeps-both-key-columns",
        ),
        pytest.param(
            "semi",
            ["left_id", "^key$", "key"],
            [{"left_id": "L1", "^key$": "a", "key": "lx"}],
            id="semi-left-schema",
        ),
        pytest.param(
            "anti",
            ["left_id", "^key$", "key"],
            [
                {"left_id": "L2", "^key$": "b", "key": "ly"},
                {"left_id": "LN", "^key$": None, "key": "ln"},
            ],
            id="anti-left-schema",
        ),
    ],
)
def test_join_strategies_resolve_literal_keys_and_keep_native_schemas(
    how: str, columns: list[str], expected: list[dict[str, object]]
) -> None:
    left = pl.LazyFrame({"left_id": ["L1", "L2", "LN"], "^key$": ["a", "b", None], "key": ["lx", "ly", "ln"]})
    right = pl.LazyFrame(
        {"payload": ["R1", "R3", "RN"], "key": ["rx", "ry", "rn"], "^key$": ["a", "c", None]}
    )
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "join", "source": "right", "how": how, "on": ["^key$"]}]
    )

    result = (
        apply_mapping_steps(left, steps, backend=PolarsTabularBackend(), source_frames={"right": right})
        .unwrap()
        .collect()
    )

    assert result.columns == columns
    assert sorted(result.to_dicts(), key=repr) == sorted(expected, key=repr)


@pytest.mark.parametrize(
    ("left_data", "right_data", "expected_columns", "expected_row"),
    [
        pytest.param(
            {"id": [1], "left": ["left value"], "__r2x_join_key_0__": ["reserved"]},
            {"id": [1], "right": ["right value"]},
            ["id", "left", "__r2x_join_key_0__", "right"],
            {"id": 1, "left": "left value", "__r2x_join_key_0__": "reserved", "right": "right value"},
            id="left-temporary-name",
        ),
        pytest.param(
            {"id": [1], "left": ["left value"]},
            {"id": [1], "right": ["right value"], "__r2x_join_key_0___right": ["reserved"]},
            ["id", "left", "right", "__r2x_join_key_0___right"],
            {"id": 1, "left": "left value", "right": "right value", "__r2x_join_key_0___right": "reserved"},
            id="right-suffix-name",
        ),
    ],
)
def test_join_preserves_columns_that_collide_with_temporary_key_names(
    left_data: dict[str, list[object]],
    right_data: dict[str, list[object]],
    expected_columns: list[str],
    expected_row: dict[str, object],
) -> None:
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "join", "source": "right", "how": "inner", "on": ["id"]}]
    )

    result = (
        apply_mapping_steps(
            pl.LazyFrame(left_data),
            steps,
            backend=PolarsTabularBackend(),
            source_frames={"right": pl.LazyFrame(right_data)},
        )
        .unwrap()
        .collect()
    )

    assert result.columns == expected_columns
    assert result.to_dicts() == [expected_row]


def test_multi_key_join_resolves_names_in_different_positions() -> None:
    left = pl.LazyFrame({"^key$": ["a", "a"], "^region$": ["n", "s"], "left": [1, 2]})
    right = pl.LazyFrame({"^region$": ["s", "n"], "payload": [20, 10], "^key$": ["a", "a"]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "join", "source": "right", "how": "inner", "on": ["^key$", "^region$"]}]
    )

    result = (
        apply_mapping_steps(left, steps, backend=PolarsTabularBackend(), source_frames={"right": right})
        .unwrap()
        .collect()
    )

    assert result.columns == ["^key$", "^region$", "left", "payload"]
    assert sorted(result.rows()) == [("a", "n", 1, 10), ("a", "s", 2, 20)]


def test_join_rejects_missing_literal_key_despite_matching_plain_name() -> None:
    left = pl.LazyFrame({"key": ["a"], "left": [1]})
    right = pl.LazyFrame({"key": ["a"], "right": [2]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "join", "source": "right", "how": "inner", "on": ["^key$"]}]
    )

    result = apply_mapping_steps(left, steps, backend=PolarsTabularBackend(), source_frames={"right": right})

    assert isinstance(result, Err)
    assert "references missing column(s): ['^key$']" in str(result.err())


def test_join_validates_exact_keys_and_preserves_polars_validation_errors() -> None:
    left = pl.LazyFrame({"^key$": ["a"]})
    right = pl.LazyFrame({"^key$": ["a", "a"]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "join", "source": "right", "how": "inner", "on": ["^key$"], "validate": "1:1"}]
    )

    result = apply_mapping_steps(left, steps, backend=PolarsTabularBackend(), source_frames={"right": right})

    assert isinstance(result, Ok)
    with pytest.raises(pl.exceptions.PolarsError, match="join keys did not fulfill 1:1 validation"):
        result.value.collect()


def test_join_resolves_wildcard_and_quoted_keys_literally() -> None:
    left = pl.LazyFrame({"*": ["a"], 'quoted"key': [1], "left": [10]})
    right = pl.LazyFrame({"right": [20], 'quoted"key': [1], "*": ["a"]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "join", "source": "right", "how": "inner", "on": ["*", 'quoted"key']}]
    )

    result = (
        apply_mapping_steps(left, steps, backend=PolarsTabularBackend(), source_frames={"right": right})
        .unwrap()
        .collect()
    )

    assert result.columns == ["*", 'quoted"key', "left", "right"]
    assert result.to_dicts() == [{"*": "a", 'quoted"key': 1, "left": 10, "right": 20}]


def test_sort_then_unique_keeps_first_row_for_exact_pattern_key() -> None:
    frame = pl.LazyFrame({"^key$": ["b", "b"], "key": ["x", "x"], "^priority$": [2, 1], "priority": [1, 2]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [
            {"op": "sort", "by": {"^priority$": "asc"}},
            {"op": "unique", "subset": ["^key$"]},
        ]
    )

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend()).unwrap().collect()

    assert result.columns == ["^key$", "key", "^priority$", "priority"]
    assert result.to_dicts() == [{"^key$": "b", "key": "x", "^priority$": 1, "priority": 2}]


def test_pivot_resolves_pattern_shaped_group_key_period_and_value_columns() -> None:
    frame = pl.LazyFrame(
        {
            "^key$": ["a", "a", "b"],
            "key": ["x", "y", "x"],
            "^period$": [2020, 2021, 2020],
            "^load$": [1, 2, 3],
            "load": [100, 200, 300],
        }
    )
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [
            {
                "op": "pivot",
                "pivot_on": "^period$",
                "group_by": ["^key$"],
                "aggregate_on": {"^load$": "sum"},
            }
        ]
    )

    processed = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend()).unwrap()
    assert isinstance(processed, pl.LazyFrame)
    result = processed.collect()

    assert result.columns == ["^key$", "2020", "2021"]
    assert sorted(result.to_dicts(), key=lambda row: row["^key$"]) == [
        {"^key$": "a", "2020": 1, "2021": 2},
        {"^key$": "b", "2020": 3, "2021": 0},
    ]


def test_pivot_restores_multiple_pattern_shaped_value_names() -> None:
    frame = pl.LazyFrame(
        {
            "^key$": ["a", "a"],
            "^period$": [2020, 2021],
            "^load$": [1, 2],
            "^capacity$": [10, 20],
        }
    )
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [
            {
                "op": "pivot",
                "pivot_on": "^period$",
                "group_by": ["^key$"],
                "aggregate_on": {"^load$": "sum", "^capacity$": "sum"},
            }
        ]
    )

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend()).unwrap().collect()

    assert result.columns == ["^key$", "^load$_2020", "^load$_2021", "^capacity$_2020", "^capacity$_2021"]
    assert result.to_dicts() == [
        {"^key$": "a", "^load$_2020": 1, "^load$_2021": 2, "^capacity$_2020": 10, "^capacity$_2021": 20}
    ]


def test_named_operations_reject_missing_literal_name_with_plain_match() -> None:
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "select_columns", "select_columns": ["^load$"]}]
    )
    result = apply_mapping_steps(pl.LazyFrame({"load": [10]}), steps, backend=PolarsTabularBackend())

    assert isinstance(result, Err)
    assert "references missing column(s): ['^load$']" in str(result.err())


def test_group_by_uses_exact_pattern_shaped_key_and_value_names() -> None:
    frame = pl.LazyFrame({"^key$": ["a", "b"], "key": ["x", "x"], "^load$": [5, 6]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [
            {
                "op": "group_by",
                "by": ["^key$"],
                "agg": {"total": {"sum": ["^load$"]}},
            }
        ]
    )

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend()).unwrap().collect()

    assert result.columns == ["^key$", "total"]
    assert result.to_dicts() == [{"^key$": "a", "total": 5}, {"^key$": "b", "total": 6}]


def test_join_uses_exact_pattern_shaped_key_and_preserves_coalescing() -> None:
    frame = pl.LazyFrame({"^key$": ["a", "b"], "key": ["x", "x"], "left": [5, 6]})
    lookup = pl.LazyFrame({"payload": [10, 20], "^key$": ["a", "c"], "key": ["x", "x"]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "join", "source": "lookup", "how": "inner", "on": ["^key$"]}]
    )

    result = (
        apply_mapping_steps(frame, steps, backend=PolarsTabularBackend(), source_frames={"lookup": lookup})
        .unwrap()
        .collect()
    )

    assert result.columns == ["^key$", "key", "left", "payload", "key_right"]
    assert result.to_dicts() == [{"^key$": "a", "key": "x", "left": 5, "payload": 10, "key_right": "x"}]


@pytest.mark.parametrize("column_name", ["missing", "^load$", "*"])
def test_mapping_steps_fail_for_missing_exact_column_name(column_name: str) -> None:
    frame = pl.LazyFrame({"load": [10.0]})
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "select", "columns": {"result": column_name}}]
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
                "columns": {"converted": {"cast": ["value", {"literal": "unknown-type"}]}},
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
                    "result": "value",
                    " result ": " value ",
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
                "columns": {"product": {"multiply": ["left", "right"]}},
            },
            {
                "op": "filter",
                "predicate": {"gt": ["product", 10]},
            },
            {"op": "select", "columns": {"label": "label", "product": "product"}},
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
                "predicate": {"gt": ["value", 0]},
            },
            {
                "op": "group_by",
                "by": ["category"],
                "agg": {"total": {"sum": ["value"]}},
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


@pytest.mark.parametrize("error_type", [ValueError, TypeError, RuntimeError])
def test_custom_handler_errors_keep_causes_at_reader_boundary(error_type: type[Exception]) -> None:
    failure = error_type("custom handler failed")

    class EmptyOptions(BaseModel):
        pass

    class RaisingHandler:
        options_model: type[EmptyOptions] = EmptyOptions
        input_type: type[pl.LazyFrame] = pl.LazyFrame
        output_type: type[pl.LazyFrame] = pl.LazyFrame

        def apply(self, value: pl.LazyFrame, *, options: EmptyOptions) -> pl.LazyFrame:
            _ = value, options
            raise failure

    backend = PolarsTabularBackend(step_handlers={"failure": RaisingHandler()})
    source = TabularSource(pl.LazyFrame({"value": [1]}), backend)
    steps = TypeAdapter(list[MappingStep]).validate_python([{"op": "custom", "handler": "failure"}])
    data_file = DataFile(
        name="items",
        source="items",
        proc_spec=TabularProcessing(steps=steps),
    )

    if error_type is ValueError:
        with pytest.raises(ReaderError) as raised:
            DataReader.process_source(source, data_file=data_file, sources={"items": source})
        operation_error = raised.value.__cause__
        assert isinstance(operation_error, ValueError)
        assert "Mapping operation 'custom' failed" in str(operation_error)
        assert operation_error.__cause__ is failure
    else:
        with pytest.raises(error_type) as raised:
            DataReader.process_source(source, data_file=data_file, sources={"items": source})
        assert raised.value is failure


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
            {"op": "assert", "predicate": {"gt": ["value", 0]}},
            "assert step failed",
        ),
        (
            {"op": "assert", "predicate": None},
            "assert step failed",
        ),
        (
            {"op": "assert", "predicate": False},
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
        {"cast": ["value", "dtype"]},
        {"split": ["value", 1]},
        {"list_get": ["value", 1.5]},
        {"when": [True, 1]},
    ],
)
def test_expression_schema_rejects_invalid_operation_arguments(
    expression: dict[str, object],
) -> None:
    """Expression validation catches invalid mapping arguments before execution."""
    with pytest.raises(ValidationError):
        SelectStep.model_validate({"op": "select", "columns": {"result": expression}})
