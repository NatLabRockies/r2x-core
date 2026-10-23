"""Compile backend-neutral mapping expressions into Polars expressions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from operator import add, eq, gt, le, mul, ne, sub, truediv

import polars as pl
from polars.datatypes.classes import DataTypeClass
from polars.selectors import Selector, by_index

from ..models import (
    ColumnExpression,
    Expression,
    ExpressionOperation,
    ListLiteralExpression,
    LiteralExpression,
    OptionalColumnExpression,
)
from ..types import AggregationFunction, MappingExpressionOperator

BINARY_MAPPING_COMPILERS: dict[MappingExpressionOperator, Callable[[pl.Expr, pl.Expr], pl.Expr]] = {
    MappingExpressionOperator.ADD: add,
    MappingExpressionOperator.DIVIDE: truediv,
    MappingExpressionOperator.EQ: eq,
    MappingExpressionOperator.GT: gt,
    MappingExpressionOperator.IS_IN: lambda left, right: pl.when(left.is_null())
    .then(pl.lit(None, dtype=pl.Boolean))
    .otherwise(left.is_in(right)),
    MappingExpressionOperator.LE: le,
    MappingExpressionOperator.MULTIPLY: mul,
    MappingExpressionOperator.NEQ: ne,
    MappingExpressionOperator.REPEAT_BY: lambda left, right: left.repeat_by(right),
    MappingExpressionOperator.STARTS_WITH: lambda left, right: left.str.starts_with(right),
    MappingExpressionOperator.SUBTRACT: sub,
}
ExpressionCompiler = Callable[[Sequence[pl.Expr]], pl.Expr]
EXPRESSION_COMPILERS: dict[MappingExpressionOperator, ExpressionCompiler] = {
    MappingExpressionOperator.AND: pl.all_horizontal,
    MappingExpressionOperator.ANY: pl.any_horizontal,
    MappingExpressionOperator.COALESCE: pl.coalesce,
    MappingExpressionOperator.CONCAT_LIST: pl.concat_list,
    MappingExpressionOperator.CONCAT_STR: lambda arguments: pl.concat_str(arguments, separator=""),
    MappingExpressionOperator.DATETIME: lambda arguments: pl.datetime(*arguments),
    MappingExpressionOperator.IS_NULL: lambda arguments: arguments[0].is_null(),
    MappingExpressionOperator.LIST_SORT: lambda arguments: arguments[0].list.sort(),
    MappingExpressionOperator.LOWERCASE: lambda arguments: arguments[0].str.to_lowercase(),
    MappingExpressionOperator.STRIP_CHARS: lambda arguments: arguments[0].str.strip_chars(),
    MappingExpressionOperator.STRUCT: pl.struct,
    MappingExpressionOperator.WHEN: lambda arguments: pl.when(arguments[0])
    .then(arguments[1])
    .otherwise(arguments[2]),
    MappingExpressionOperator.YEAR: lambda arguments: arguments[0].dt.year(),
}

POLARS_DTYPES: dict[str, DataTypeClass] = {
    "bool": pl.Boolean,
    "boolean": pl.Boolean,
    "date": pl.Date,
    "datetime": pl.Datetime,
    "double": pl.Float64,
    "float": pl.Float64,
    "float32": pl.Float32,
    "float64": pl.Float64,
    "int": pl.Int64,
    "int32": pl.Int32,
    "int64": pl.Int64,
    "integer": pl.Int64,
    "str": pl.String,
    "string": pl.String,
}


def resolve_polars_dtype(type_name: str) -> DataTypeClass:
    """Resolve supported mapping type names into Polars data types."""
    polars_type = POLARS_DTYPES.get(type_name.casefold())
    if polars_type is None:
        msg = f"Unsupported data type: {type_name}"
        raise ValueError(msg)
    return polars_type


def apply_aggregation(expression: pl.Expr, *, function: AggregationFunction) -> pl.Expr:
    """Apply one declared aggregation to a Polars expression."""
    operations: dict[AggregationFunction, Callable[[], pl.Expr]] = {
        AggregationFunction.COUNT: expression.count,
        AggregationFunction.FIRST: expression.first,
        AggregationFunction.LAST: expression.last,
        AggregationFunction.MAX: expression.max,
        AggregationFunction.MEAN: expression.mean,
        AggregationFunction.MEDIAN: expression.median,
        AggregationFunction.MIN: expression.min,
        AggregationFunction.N_UNIQUE: expression.n_unique,
        AggregationFunction.STD: expression.std,
        AggregationFunction.SUM: expression.sum,
        AggregationFunction.VAR: expression.var,
    }
    return operations[function]()


def exact_column_index(column: str, *, column_names: Sequence[str]) -> int:
    """Resolve one literal column name in an ordered schema."""
    try:
        return column_names.index(column)
    except ValueError as error:
        msg = f"Column {column!r} not found in current frame"
        raise ValueError(msg) from error


def exact_column_expression(column: str, *, column_names: Sequence[str]) -> pl.Expr:
    """Select one literal column name as a Polars expression."""
    return pl.nth(exact_column_index(column, column_names=column_names))


def exact_column_selector(column: str, *, column_names: Sequence[str]) -> Selector:
    """Select one literal column name as a Polars selector."""
    return by_index(exact_column_index(column, column_names=column_names))


def compile_operation(
    expression: ExpressionOperation,
    *,
    column_names: Sequence[str],
) -> pl.Expr:
    """Compile an already validated operation and its arguments."""
    arguments = [
        compile_polars_expression(argument, column_names=column_names) for argument in expression.args
    ]
    if isinstance(expression.op, AggregationFunction):
        return apply_aggregation(arguments[0], function=expression.op)
    binary_compiler = BINARY_MAPPING_COMPILERS.get(expression.op)
    if binary_compiler is not None:
        return binary_compiler(arguments[0], arguments[1])
    if expression.op is MappingExpressionOperator.CAST:
        type_argument = expression.args[1]
        if not isinstance(type_argument, LiteralExpression) or not isinstance(type_argument.literal, str):
            msg = "cast requires a literal string type name as its second argument"
            raise ValueError(msg)
        return arguments[0].cast(resolve_polars_dtype(type_argument.literal))
    if expression.op is MappingExpressionOperator.LIST_GET:
        index_argument = expression.args[1]
        index = index_argument.literal if isinstance(index_argument, LiteralExpression) else index_argument
        if type(index) is not int:
            msg = "list_get requires a literal integer index as its second argument"
            raise ValueError(msg)
        return arguments[0].list.get(index, null_on_oob=True)
    if expression.op is MappingExpressionOperator.SPLIT:
        separator_argument = expression.args[1]
        if not isinstance(separator_argument, LiteralExpression) or not isinstance(
            separator_argument.literal, str
        ):
            msg = "split requires a literal string separator as its second argument"
            raise ValueError(msg)
        return arguments[0].str.split(separator_argument.literal)
    compiler = EXPRESSION_COMPILERS.get(expression.op)
    if compiler is None:
        msg = f"Unsupported mapping expression operation: {expression.op}"
        raise ValueError(msg)
    return compiler(arguments)


def compile_polars_expression(expression: Expression, *, column_names: Sequence[str]) -> pl.Expr:
    """Compile against a frame whose ordered schema matches ``column_names``."""
    if isinstance(expression, ColumnExpression):
        return exact_column_expression(expression.root, column_names=column_names)
    if isinstance(expression, OptionalColumnExpression):
        if expression.optional_column not in column_names:
            return pl.lit(None)
        return exact_column_expression(expression.optional_column, column_names=column_names)
    if isinstance(expression, LiteralExpression):
        return pl.lit(expression.literal)
    if isinstance(expression, ListLiteralExpression):
        if not isinstance(expression.values, list):
            msg = "Membership list placeholder must be resolved before expression compilation"
            raise ValueError(msg)
        return pl.lit(expression.values)
    if isinstance(expression, ExpressionOperation):
        return compile_operation(expression, column_names=column_names)
    return pl.lit(expression)
