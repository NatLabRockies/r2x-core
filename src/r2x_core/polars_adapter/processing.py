"""Apply ordered table operations with Polars."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import isnan
from numbers import Integral, Rational, Real
from typing import Any, Literal, TypeAlias

import polars as pl
from polars.datatypes.classes import DataTypeClass

from ..datafile import DataFile
from ..models import (
    AggregateStep,
    AssertStep,
    CastColumnsStep,
    DropColumnsStep,
    FillNullStep,
    FilterColumnsStep,
    FilterStep,
    GroupByStep,
    LowercaseStep,
    PivotStep,
    RenameColumnsStep,
    ReplaceValuesStep,
    ScaleColumnsStep,
    SelectColumnsStep,
    SelectStep,
    SortStep,
    SplitColumnsStep,
    StripCharactersStep,
    UniqueStep,
    UnpivotColumnsStep,
    UnpivotStep,
    WithColumnsStep,
)
from ..types import AggregationFunction, ProcessingPlaceholder
from .expressions import compile_polars_expression, resolve_polars_dtype

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


def apply_polars_step(
    data_frame: pl.LazyFrame, *, step: object, data_file: DataFile | None = None
) -> pl.LazyFrame:
    """Apply one non-join, non-custom table operation."""
    schema_names = data_frame.collect_schema().names()
    match step:
        case AssertStep():
            predicate = compile_polars_expression(step.predicate, column_names=schema_names).fill_null(False)
            violations = data_frame.filter(~predicate).limit(1).collect()
            if violations.height:
                msg = "assert step failed for at least one row"
                raise ValueError(msg)
        case FilterStep():
            predicate = compile_polars_expression(step.predicate, column_names=schema_names)
            data_frame = data_frame.filter(predicate)
        case FilterColumnsStep():
            require_columns(
                schema_names, list(step.filter_by), operation="filter_columns", data_file=data_file
            )
            filters = [pl_build_filter_expr(column, value=value) for column, value in step.filter_by.items()]
            data_frame = data_frame.filter(pl.all_horizontal(filters) if filters else pl.lit(True))
        case SelectStep():
            data_frame = data_frame.select(
                [
                    compile_polars_expression(expression, column_names=schema_names).alias(name)
                    for name, expression in step.columns.items()
                ]
            )
        case SelectColumnsStep():
            require_columns(
                schema_names, step.select_columns, operation="select_columns", data_file=data_file
            )
            data_frame = data_frame.select(step.select_columns)
        case WithColumnsStep():
            data_frame = data_frame.with_columns(
                [
                    compile_polars_expression(expression, column_names=schema_names).alias(name)
                    for name, expression in step.columns.items()
                ]
            )
        case UnpivotStep():
            require_columns(schema_names, step.index, operation="unpivot index", data_file=data_file)
            value_columns = [name for name in schema_names if name not in step.index]
            if not value_columns:
                msg = "unpivot requires at least one value column"
                raise ValueError(msg)
            if step.variable_name == step.value_name or {
                step.variable_name,
                step.value_name,
            }.intersection(step.index):
                msg = "unpivot output names must be distinct from each other and the index"
                raise ValueError(msg)
            data_frame = data_frame.unpivot(
                on=value_columns,
                index=step.index,
                variable_name=step.variable_name,
                value_name=step.value_name,
            )
        case UnpivotColumnsStep():
            require_columns(schema_names, step.columns, operation="unpivot", data_file=data_file)
            index_columns = [name for name in schema_names if name not in step.columns]
            if step.variable_name == step.value_name or {
                step.variable_name,
                step.value_name,
            }.intersection(index_columns):
                msg = "unpivot output names must be distinct from each other and the index"
                raise ValueError(msg)
            data_frame = data_frame.unpivot(
                on=step.columns,
                index=index_columns,
                variable_name=step.variable_name,
                value_name=step.value_name,
            )
        case LowercaseStep() if step.lowercase is True:
            lowered_names = [name.lower() for name in schema_names]
            if len(set(lowered_names)) != len(lowered_names):
                msg = f"lowercase creates duplicate column names: {lowered_names}"
                raise ValueError(msg)
            data_frame = data_frame.with_columns(pl.col(pl.String).str.to_lowercase()).rename(
                dict(zip(schema_names, lowered_names, strict=True))
            )
        case LowercaseStep():
            pass
        case DropColumnsStep():
            require_columns(schema_names, step.drop_columns, operation="drop_columns", data_file=data_file)
            data_frame = data_frame.drop(step.drop_columns)
        case RenameColumnsStep():
            require_columns(
                schema_names, list(step.column_mapping), operation="column_mapping", data_file=data_file
            )
            renamed = [step.column_mapping.get(name, name) for name in schema_names]
            if len(set(renamed)) != len(renamed):
                msg = f"column_mapping creates duplicate column names: {renamed}"
                raise ValueError(msg)
            data_frame = data_frame.rename(step.column_mapping)
        case SplitColumnsStep():
            for column, split_spec in step.split_column.items():
                current_names = data_frame.collect_schema().names()
                require_columns(current_names, [column], operation="split_columns", data_file=data_file)
                collisions = sorted(set(split_spec.into) & (set(current_names) - {column}))
                if collisions:
                    msg = f"split_columns would overwrite existing column(s): {collisions}"
                    raise ValueError(msg)
                expression = (
                    pl.col(column)
                    .cast(pl.String)
                    .str.split_exact(split_spec.separator, n=len(split_spec.into) - 1)
                    .struct.rename_fields(split_spec.into)
                    .alias(column)
                )
                data_frame = data_frame.with_columns(expression).unnest(column)
        case ReplaceValuesStep():
            data_frame = replace_values(data_frame, step=step)
        case StripCharactersStep():
            require_columns(
                schema_names, list(step.strip_chars), operation="strip_chars", data_file=data_file
            )
            expressions = []
            for column, characters in step.strip_chars.items():
                pattern = "|".join(re.escape(character) for character in characters)
                cleaned = pl.col(column).cast(pl.String).str.strip_chars().str.replace_all(pattern, "")
                expressions.append(cleaned.alias(column))
            data_frame = data_frame.with_columns(expressions)
        case CastColumnsStep():
            require_columns(
                schema_names, list(step.column_schema), operation="column_schema", data_file=data_file
            )
            data_frame = data_frame.with_columns(
                [
                    pl.col(column).cast(resolve_polars_dtype(dtype))
                    for column, dtype in step.column_schema.items()
                ]
            )
        case ScaleColumnsStep():
            require_columns(schema_names, list(step.scale), operation="scale", data_file=data_file)
            schema = data_frame.collect_schema()
            invalid = {column: schema[column] for column in step.scale if not schema[column].is_numeric()}
            if invalid:
                msg = f"scale requires numeric columns: {invalid}"
                raise ValueError(msg)
            data_frame = data_frame.with_columns(
                [pl.col(column).mul(factor).alias(column) for column, factor in step.scale.items()]
            )
        case FillNullStep():
            require_columns(schema_names, list(step.fill_null), operation="fill_null", data_file=data_file)
            data_frame = data_frame.with_columns(
                [pl.col(column).fill_null(value).alias(column) for column, value in step.fill_null.items()]
            )
        case AggregateStep():
            aggregate_columns = list(step.aggregate_on)
            require_columns(schema_names, aggregate_columns, operation="aggregate_on", data_file=data_file)
            require_columns(schema_names, step.group_by, operation="group_by", data_file=data_file)
            expressions = [
                aggregation_expression(column, function) for column, function in step.aggregate_on.items()
            ]
            data_frame = (
                data_frame.group_by(step.group_by, maintain_order=True).agg(expressions)
                if step.group_by
                else data_frame.select(expressions)
            )
        case PivotStep():
            data_frame = pivot_table(data_frame, step=step, data_file=data_file)
        case GroupByStep():
            require_columns(schema_names, step.by, operation="group_by", data_file=data_file)
            data_frame = data_frame.group_by(step.by, maintain_order=True).agg(
                [
                    compile_polars_expression(expression, column_names=schema_names).alias(name)
                    for name, expression in step.agg.items()
                ]
            )
        case SortStep():
            columns = list(step.by)
            require_columns(schema_names, columns, operation="sort", data_file=data_file)
            data_frame = data_frame.sort(
                columns,
                descending=[direction == "desc" for direction in step.by.values()],
            )
        case UniqueStep():
            require_columns(schema_names, step.subset, operation="unique", data_file=data_file)
            data_frame = data_frame.unique(subset=step.subset, keep="first", maintain_order=True)
        case _:
            msg = f"Unsupported table processing operation: {type(step).__name__}"
            raise ValueError(msg)
    return data_frame


def replace_values(data_frame: pl.LazyFrame, *, step: ReplaceValuesStep) -> pl.LazyFrame:
    """Replace values only when their logical families match each column."""
    schema = data_frame.collect_schema()
    expressions = []
    for column in schema.names():
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
            expressions.append(pl.col(column).replace(replacements).alias(column))
    return data_frame.with_columns(expressions) if expressions else data_frame


def pivot_table(
    data_frame: pl.LazyFrame, *, step: PivotStep, data_file: DataFile | None = None
) -> pl.LazyFrame:
    """Pivot a lazy table after discovering its output key values."""
    schema_names = data_frame.collect_schema().names()
    require_columns(
        schema_names,
        [step.pivot_on, *step.group_by, *step.aggregate_on],
        operation="pivot",
        data_file=data_file,
    )
    pivot_values = (
        data_frame.select(step.pivot_on)
        .unique(maintain_order=True)
        .collect()
        .get_column(step.pivot_on)
        .to_list()
    )
    if any(value is None for value in pivot_values):
        file_context = f" in {data_file.name!r}" if data_file is not None else ""
        msg = f"pivot{file_context} contains null keys in {step.pivot_on!r}"
        raise ValueError(msg)
    function = next(iter(step.aggregate_on.values()))
    if not isinstance(function, AggregationFunction):
        msg = f"Unresolved pivot aggregation placeholder: {function}"
        raise ValueError(msg)
    aggregate_function: str | pl.Expr = (
        pl.element().count() if function is AggregationFunction.COUNT else function.value
    )
    result = data_frame.pivot(
        on=step.pivot_on,
        on_columns=pivot_values,
        index=step.group_by,
        values=list(step.aggregate_on),
        aggregate_function=aggregate_function,
    )
    return result


def require_columns(
    schema_names: list[str],
    columns: list[str],
    *,
    operation: str,
    data_file: DataFile | None = None,
) -> None:
    """Raise an actionable error when an operation references missing columns."""
    missing = list(dict.fromkeys(column for column in columns if column not in schema_names))
    if missing:
        available = ", ".join(schema_names) or "<none>"
        file_context = f" in {data_file.name!r}" if data_file is not None else ""
        msg = (
            f"{operation}{file_context} references missing column(s): {missing}. "
            f"Available columns: {available}."
        )
        raise ValueError(msg)


def aggregation_expression(column: str, function: AggregationFunction | ProcessingPlaceholder) -> pl.Expr:
    """Build a Polars aggregation expression from the closed function vocabulary."""
    if not isinstance(function, AggregationFunction):
        msg = f"Unresolved aggregation placeholder: {function}"
        raise ValueError(msg)
    expression = pl.col(column)
    operations = {
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
    return operations[function]().alias(column)


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


def pl_build_filter_expr(column: str, *, value: Any) -> pl.Expr:
    """Treat integer filters on the ``datetime`` column as ReEDS years."""
    if column == "datetime" and isinstance(value, int | list):
        if isinstance(value, list):
            return pl.col("datetime").dt.year().is_in(value)
        return pl.col("datetime").dt.year() == value
    column_expression = pl.col(column)
    if isinstance(value, list):
        return column_expression.cast(pl.String).is_in([str(item) for item in value])
    return column_expression.cast(pl.String) == str(value)
