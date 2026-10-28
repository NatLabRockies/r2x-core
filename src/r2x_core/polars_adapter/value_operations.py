"""Value-family checks and typed value operations for Polars tables."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import isnan
from numbers import Integral, Rational, Real
from typing import Any, Literal, TypeAlias

import polars as pl
from polars.datatypes.classes import DataTypeClass

from ..datafile import DataFile
from ..models import ReplaceValuesStep
from .expressions import exact_column_expression
from .validation import require_columns

ValueFamily: TypeAlias = Literal[
    "boolean",
    "integer",
    "float",
    "decimal",
    "string",
    "date",
    "datetime",
    "time",
    "duration",
    "binary",
    "rational",
]


VALUE_FAMILIES: tuple[tuple[type | tuple[type, ...], ValueFamily], ...] = (
    (bool, "boolean"),
    (Integral, "integer"),
    (Decimal, "decimal"),
    (Rational, "rational"),
    (Real, "float"),
    (str, "string"),
    (datetime, "datetime"),
    (date, "date"),
    (time, "time"),
    (timedelta, "duration"),
    ((bytes, bytearray), "binary"),
)


DTYPE_FAMILIES: dict[DataTypeClass, ValueFamily] = {
    pl.Boolean: "boolean",
    pl.Decimal: "decimal",
    pl.String: "string",
    pl.Categorical: "string",
    pl.Enum: "string",
    pl.Date: "date",
    pl.Datetime: "datetime",
    pl.Time: "time",
    pl.Duration: "duration",
    pl.Binary: "binary",
}


def replace_values(
    data_frame: pl.LazyFrame, *, step: ReplaceValuesStep, data_file: DataFile | None = None
) -> pl.LazyFrame:
    """Replace values only when their logical families match each selected column."""
    schema = data_frame.collect_schema()
    schema_names = schema.names()
    columns = step.columns if step.columns is not None else schema_names
    if step.columns is not None:
        require_columns(schema_names, step.columns, operation="replace_values", data_file=data_file)
    expressions = []
    for column in columns:
        dtype = schema[column]
        target_family = polars_dtype_family(dtype)
        if target_family is None:
            continue
        replacements: dict[Any, Any] = {}
        for old, new in step.replace_values.items():
            cast_values: list[Any] = []
            compatible = True
            for value in (old, new):
                if value is None:
                    cast_values.append(None)
                    continue
                source_family = python_value_family(value)
                can_widen_integer = source_family == "integer" and target_family == "float"
                if source_family != target_family and not can_widen_integer:
                    compatible = False
                    break
                try:
                    series = pl.Series("_replacement", [value]).cast(dtype, strict=False)
                except (TypeError, ValueError, pl.exceptions.PolarsError):
                    compatible = False
                    break
                if series.null_count() != 0:
                    compatible = False
                    break
                cast_value = series.item()
                if cast_value != value and not (
                    source_family == "float"
                    and isinstance(cast_value, float)
                    and isnan(cast_value)
                    and isinstance(value, float)
                    and isnan(value)
                ):
                    compatible = False
                    break
                cast_values.append(cast_value)
            if compatible:
                replacements[cast_values[0]] = cast_values[1]
        if replacements:
            expressions.append(
                exact_column_expression(column, column_names=schema_names).replace(replacements).alias(column)
            )
    return data_frame.with_columns(expressions) if expressions else data_frame


def polars_dtype_family(dtype: pl.DataType) -> ValueFamily | None:
    """Return the logical value family for a Polars dtype."""
    if dtype.is_integer():
        return "integer"
    if dtype.is_float():
        return "float"
    return DTYPE_FAMILIES.get(dtype.base_type())


def python_value_family(value: object) -> ValueFamily | None:
    """Return the logical family for a replacement value."""
    return next((family for value_type, family in VALUE_FAMILIES if isinstance(value, value_type)), None)


def pl_build_filter_expr(
    column: str,
    *,
    value: Any,
    column_names: list[str],
    column_dtype: pl.DataType | None = None,
) -> pl.Expr:
    """Build an exact-column filter, treating integer datetime values as years."""
    column_expression = exact_column_expression(column, column_names=column_names)
    if column_dtype == pl.Boolean and type(value) is bool:
        return column_expression == pl.lit(value)
    if (
        column_dtype == pl.Boolean
        and isinstance(value, list)
        and value
        and all(type(item) is bool for item in value)
    ):
        return column_expression.is_in(value)
    if column == "datetime" and isinstance(value, int | list):
        if isinstance(value, list):
            return column_expression.dt.year().is_in(value)
        return column_expression.dt.year() == value
    if isinstance(value, list):
        return column_expression.cast(pl.String).is_in([str(item) for item in value])
    return column_expression.cast(pl.String) == str(value)
