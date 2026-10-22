"""Compile backend-neutral mapping expressions into Polars expressions."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import polars as pl
from polars.datatypes.classes import DataTypeClass
from polars.selectors import Selector, by_index

from ..models import ColumnExpression, Expression, ExpressionOperation, LiteralExpression
from ..types import AggregationFunction, MappingExpressionOperator

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


def compile_polars_expression(expression: Expression, *, column_names: Sequence[str]) -> pl.Expr:
    """Compile against a frame whose ordered schema matches ``column_names``."""
    if isinstance(expression, ColumnExpression):
        return exact_column_expression(expression.column, column_names=column_names)
    if isinstance(expression, LiteralExpression):
        return pl.lit(expression.literal)
    if not isinstance(expression, ExpressionOperation):
        msg = f"Unsupported expression model: {type(expression).__name__}"
        raise TypeError(msg)

    arguments = [
        compile_polars_expression(argument, column_names=column_names) for argument in expression.args
    ]
    if isinstance(expression.op, AggregationFunction):
        return apply_aggregation(arguments[0], function=expression.op)
    match expression.op:
        case MappingExpressionOperator.AND:
            return pl.all_horizontal(arguments)
        case MappingExpressionOperator.ANY:
            return pl.any_horizontal(arguments)
        case MappingExpressionOperator.CAST:
            type_argument = expression.args[1]
            if not isinstance(type_argument, LiteralExpression) or not isinstance(type_argument.literal, str):
                msg = "cast requires a literal string type name as its second argument"
                raise ValueError(msg)
            return arguments[0].cast(resolve_polars_dtype(type_argument.literal))
        case MappingExpressionOperator.COALESCE:
            return pl.coalesce(arguments)
        case MappingExpressionOperator.CONCAT_LIST:
            return pl.concat_list(arguments)
        case MappingExpressionOperator.CONCAT_STR:
            return pl.concat_str(arguments, separator="")
        case MappingExpressionOperator.DATETIME:
            return pl.datetime(*arguments)
        case MappingExpressionOperator.DIVIDE:
            return arguments[0] / arguments[1]
        case MappingExpressionOperator.EQ:
            return arguments[0] == arguments[1]
        case MappingExpressionOperator.GT:
            return arguments[0] > arguments[1]
        case MappingExpressionOperator.IS_NULL:
            return arguments[0].is_null()
        case MappingExpressionOperator.LE:
            return arguments[0] <= arguments[1]
        case MappingExpressionOperator.LIST_GET:
            index_argument = expression.args[1]
            if (
                not isinstance(index_argument, LiteralExpression)
                or not isinstance(index_argument.literal, int)
                or isinstance(index_argument.literal, bool)
            ):
                msg = "list_get requires a literal integer index as its second argument"
                raise ValueError(msg)
            return arguments[0].list.get(index_argument.literal, null_on_oob=True)
        case MappingExpressionOperator.LIST_SORT:
            return arguments[0].list.sort()
        case MappingExpressionOperator.LOWERCASE:
            return arguments[0].str.to_lowercase()
        case MappingExpressionOperator.MULTIPLY:
            return arguments[0] * arguments[1]
        case MappingExpressionOperator.SPLIT:
            separator_argument = expression.args[1]
            if not isinstance(separator_argument, LiteralExpression) or not isinstance(
                separator_argument.literal, str
            ):
                msg = "split requires a literal string separator as its second argument"
                raise ValueError(msg)
            return arguments[0].str.split(separator_argument.literal)
        case MappingExpressionOperator.STRIP_CHARS:
            return arguments[0].str.strip_chars()
        case MappingExpressionOperator.STRUCT:
            return pl.struct(arguments)
        case MappingExpressionOperator.SUBTRACT:
            return arguments[0] - arguments[1]
        case MappingExpressionOperator.WHEN:
            return pl.when(arguments[0]).then(arguments[1]).otherwise(arguments[2])
        case MappingExpressionOperator.YEAR:
            return arguments[0].dt.year()
        case _:
            msg = f"Unsupported mapping expression operation: {expression.op}"
            raise ValueError(msg)
