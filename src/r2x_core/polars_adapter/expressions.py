"""Compile backend-neutral mapping expressions into Polars expressions."""

from __future__ import annotations

import polars as pl
from polars.datatypes.classes import DataTypeClass

from ..models import ColumnExpression, Expression, ExpressionOperation, LiteralExpression

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
        raise ValueError(f"Unsupported data type: {type_name}")
    return polars_type


def compile_polars_expression(expression: Expression) -> pl.Expr:
    """Compile a mapping expression without exposing Polars in its schema."""
    if isinstance(expression, ColumnExpression):
        return pl.col(expression.column)
    if isinstance(expression, LiteralExpression):
        return pl.lit(expression.literal)
    if not isinstance(expression, ExpressionOperation):
        raise TypeError(f"Unsupported expression model: {type(expression).__name__}")

    arguments = [compile_polars_expression(argument) for argument in expression.args]
    match expression.op:
        case "and":
            return pl.all_horizontal(arguments)
        case "any":
            return pl.any_horizontal(arguments)
        case "cast":
            type_argument = expression.args[1]
            if not isinstance(type_argument, LiteralExpression) or not isinstance(type_argument.literal, str):
                raise ValueError("cast requires a literal string type name as its second argument")
            return arguments[0].cast(resolve_polars_dtype(type_argument.literal))
        case "coalesce":
            return pl.coalesce(arguments)
        case "concat_list":
            return pl.concat_list(arguments)
        case "concat_str":
            return pl.concat_str(arguments, separator="")
        case "datetime":
            return pl.datetime(
                arguments[0],
                arguments[1],
                arguments[2],
                hour=arguments[3] if len(arguments) > 3 else None,
                minute=arguments[4] if len(arguments) > 4 else None,
                second=arguments[5] if len(arguments) > 5 else None,
                microsecond=arguments[6] if len(arguments) > 6 else None,
            )
        case "divide":
            return arguments[0] / arguments[1]
        case "eq":
            return arguments[0] == arguments[1]
        case "gt":
            return arguments[0] > arguments[1]
        case "is_null":
            return arguments[0].is_null()
        case "le":
            return arguments[0] <= arguments[1]
        case "list_get":
            index_argument = expression.args[1]
            if (
                not isinstance(index_argument, LiteralExpression)
                or not isinstance(index_argument.literal, int)
                or isinstance(index_argument.literal, bool)
            ):
                raise ValueError("list_get requires a literal integer index as its second argument")
            return arguments[0].list.get(index_argument.literal, null_on_oob=True)
        case "list_sort":
            return arguments[0].list.sort()
        case "lowercase":
            return arguments[0].str.to_lowercase()
        case "max":
            return arguments[0].max()
        case "mean":
            return arguments[0].mean()
        case "multiply":
            return arguments[0] * arguments[1]
        case "split":
            separator_argument = expression.args[1]
            if not isinstance(separator_argument, LiteralExpression) or not isinstance(
                separator_argument.literal, str
            ):
                raise ValueError("split requires a literal string separator as its second argument")
            return arguments[0].str.split(separator_argument.literal)
        case "strip_chars":
            return arguments[0].str.strip_chars()
        case "struct":
            return pl.struct(arguments)
        case "subtract":
            return arguments[0] - arguments[1]
        case "sum":
            return arguments[0].sum()
        case "when":
            return pl.when(arguments[0]).then(arguments[1]).otherwise(arguments[2])
        case "year":
            return arguments[0].dt.year()
        case _:
            raise ValueError(f"Unsupported mapping expression operation: {expression.op}")
