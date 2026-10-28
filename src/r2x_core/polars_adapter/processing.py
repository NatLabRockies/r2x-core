"""Apply ordered table operations with Polars."""

from __future__ import annotations

import re
from decimal import Decimal

import polars as pl
from loguru import logger

from ..datafile import DataFile
from ..models import (
    AggregateStep,
    AssertStep,
    CastColumnsStep,
    DatetimeRangeStep,
    DropColumnsStep,
    ExplodeStep,
    FillNullStep,
    FilterColumnsStep,
    FilterStep,
    GroupByStep,
    HeadStep,
    LowercaseStep,
    MatchPatternsStep,
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
from .expressions import (
    apply_aggregation,
    compile_polars_expression,
    exact_column_expression,
    exact_column_selector,
    resolve_polars_dtype,
)
from .frames import collect_polars_frame
from .matching import match_patterns
from .reshape import pivot_table, unpivot_polars_frame
from .validation import require_columns
from .value_operations import pl_build_filter_expr, replace_values


def apply_polars_step(
    data_frame: pl.LazyFrame, *, step: object, data_file: DataFile | None = None
) -> pl.LazyFrame:
    """Apply one non-join, non-custom table operation."""
    schema = data_frame.collect_schema()
    schema_names = schema.names()
    match step:
        case AssertStep():
            predicate = compile_polars_expression(step.predicate, column_names=schema_names).fill_null(False)
            violations = collect_polars_frame(data_frame.filter(~predicate).limit(1))
            if violations.height:
                msg = step.message or "assert step failed for at least one row"
                raise ValueError(msg)
        case FilterStep():
            predicate = compile_polars_expression(step.predicate, column_names=schema_names)
            data_frame = data_frame.filter(predicate)
        case FilterColumnsStep():
            require_columns(
                schema_names, list(step.filter_by), operation="filter_columns", data_file=data_file
            )
            filters = [
                pl_build_filter_expr(
                    column,
                    value=value,
                    column_names=schema_names,
                    column_dtype=schema[column],
                )
                for column, value in step.filter_by.items()
            ]
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
            data_frame = data_frame.select(
                [exact_column_expression(column, column_names=schema_names) for column in step.select_columns]
            )
        case HeadStep():
            data_frame = data_frame.head(step.n)
        case WithColumnsStep():
            data_frame = data_frame.with_columns(
                [
                    compile_polars_expression(expression, column_names=schema_names).alias(name)
                    for name, expression in step.columns.items()
                ]
            )
        case DatetimeRangeStep():
            require_columns(schema_names, [step.start], operation="datetime_range", data_file=data_file)
            datetime_dtype = schema[step.start]
            if not isinstance(datetime_dtype, pl.Datetime):
                msg = f"datetime_range start column {step.start!r} must have a datetime dtype"
                raise ValueError(msg)
            if step.column in schema_names:
                msg = f"datetime_range output column {step.column!r} already exists"
                raise ValueError(msg)
            resolution_nanoseconds = Decimal(str(step.resolution_seconds)) * Decimal(1_000_000_000)
            if resolution_nanoseconds != resolution_nanoseconds.to_integral_value():
                msg = "datetime_range resolution must be representable in nanoseconds"
                raise ValueError(msg)
            resolution_ns = int(resolution_nanoseconds)
            output_time_unit = "ns" if datetime_dtype.time_unit == "ns" or resolution_ns % 1_000 else "us"
            offset_ns = resolution_ns * (step.periods - 1)
            if offset_ns > (1 << 63) - 1:
                msg = "datetime_range span exceeds the supported datetime range"
                raise ValueError(msg)
            start = exact_column_expression(step.start, column_names=schema_names)
            if collect_polars_frame(data_frame.filter(start.is_null()).limit(1)).height:
                msg = f"datetime_range start column {step.start!r} cannot contain null values"
                raise ValueError(msg)
            start = start.cast(pl.Datetime(output_time_unit, datetime_dtype.time_zone))
            data_frame = data_frame.with_columns(
                pl.datetime_ranges(
                    start,
                    start + pl.duration(nanoseconds=offset_ns),
                    interval=f"{resolution_ns}ns",
                    time_unit=output_time_unit,
                    time_zone=datetime_dtype.time_zone,
                    closed="both",
                ).alias(step.column)
            ).explode(
                exact_column_selector(step.column, column_names=[*schema_names, step.column]),
                empty_as_null=False,
                keep_nulls=True,
            )
        case ExplodeStep():
            require_columns(schema_names, step.columns, operation="explode", data_file=data_file)
            data_frame = data_frame.explode(
                [exact_column_selector(column, column_names=schema_names) for column in step.columns],
                empty_as_null=False,
                keep_nulls=True,
            )
        case UnpivotStep():
            data_frame = unpivot_polars_frame(
                data_frame,
                index=step.index,
                columns=None,
                variable_name=step.variable_name,
                value_name=step.value_name,
                type_policy="supertype",
                value_type_name=step.value_type_name,
                data_file=data_file,
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
                on=[exact_column_selector(column, column_names=schema_names) for column in step.columns],
                index=[exact_column_selector(column, column_names=schema_names) for column in index_columns],
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
            data_frame = data_frame.drop(
                [exact_column_selector(column, column_names=schema_names) for column in step.drop_columns]
            )
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
                    exact_column_expression(column, column_names=current_names)
                    .cast(pl.String)
                    .str.split_exact(split_spec.separator, n=len(split_spec.into) - 1)
                    .struct.rename_fields(split_spec.into)
                    .alias(column)
                )
                data_frame = data_frame.with_columns(expression).unnest(
                    exact_column_selector(column, column_names=current_names)
                )
        case ReplaceValuesStep():
            data_frame = replace_values(data_frame, step=step, data_file=data_file)
        case StripCharactersStep():
            require_columns(
                schema_names, list(step.strip_chars), operation="strip_chars", data_file=data_file
            )
            expressions = []
            for column, characters in step.strip_chars.items():
                pattern = "|".join(re.escape(character) for character in characters)
                cleaned = (
                    exact_column_expression(column, column_names=schema_names)
                    .cast(pl.String)
                    .str.strip_chars()
                    .str.replace_all(pattern, "")
                )
                expressions.append(cleaned.alias(column))
            data_frame = data_frame.with_columns(expressions)
        case CastColumnsStep():
            required_columns = [
                column for column in step.column_schema if column not in step.optional_columns
            ]
            require_columns(schema_names, required_columns, operation="column_schema", data_file=data_file)
            schema = data_frame.collect_schema()
            expressions: list[pl.Expr] = []
            for column, dtype_name in step.column_schema.items():
                dtype = resolve_polars_dtype(dtype_name)
                if column in schema and dtype.is_integer() and schema[column].is_float():
                    if step.float_to_int == "reject":
                        msg = f"Cast from floating-point to integer is unsupported for column {column!r}"
                        raise ValueError(msg)
                    logger.warning(
                        "Casting floating-point column '{}' to {} truncates fractional values. "
                        "Set float_to_int='reject' to disallow this conversion.",
                        column,
                        dtype,
                    )
                if column not in schema:
                    expression = pl.lit(None, dtype=dtype)
                else:
                    expression = exact_column_expression(column, column_names=schema_names)
                    if dtype == pl.Datetime and schema[column] == pl.String:
                        expression = expression.str.to_datetime(strict=True)
                    else:
                        expression = expression.cast(dtype)
                expressions.append(expression.alias(column))
            data_frame = data_frame.with_columns(expressions)
        case ScaleColumnsStep():
            require_columns(schema_names, list(step.scale), operation="scale", data_file=data_file)
            schema = data_frame.collect_schema()
            invalid = {column: schema[column] for column in step.scale if not schema[column].is_numeric()}
            if invalid:
                msg = f"scale requires numeric columns: {invalid}"
                raise ValueError(msg)
            data_frame = data_frame.with_columns(
                [
                    exact_column_expression(column, column_names=schema_names).mul(factor).alias(column)
                    for column, factor in step.scale.items()
                ]
            )
        case FillNullStep():
            require_columns(schema_names, list(step.fill_null), operation="fill_null", data_file=data_file)
            data_frame = data_frame.with_columns(
                [
                    exact_column_expression(column, column_names=schema_names).fill_null(value).alias(column)
                    for column, value in step.fill_null.items()
                ]
            )
        case AggregateStep():
            aggregate_columns = list(step.aggregate_on)
            require_columns(schema_names, aggregate_columns, operation="aggregate_on", data_file=data_file)
            require_columns(schema_names, step.group_by, operation="group_by", data_file=data_file)
            expressions = [
                aggregation_expression(column, function, column_names=schema_names)
                for column, function in step.aggregate_on.items()
            ]
            data_frame = (
                data_frame.group_by(
                    [exact_column_expression(column, column_names=schema_names) for column in step.group_by],
                    maintain_order=True,
                ).agg(expressions)
                if step.group_by
                else data_frame.select(expressions)
            )
        case PivotStep():
            data_frame = pivot_table(data_frame, step=step, data_file=data_file)
        case GroupByStep():
            require_columns(schema_names, step.by, operation="group_by", data_file=data_file)
            data_frame = data_frame.group_by(
                [exact_column_expression(column, column_names=schema_names) for column in step.by],
                maintain_order=True,
            ).agg(
                [
                    compile_polars_expression(expression, column_names=schema_names).alias(name)
                    for name, expression in step.agg.items()
                ]
            )
        case MatchPatternsStep():
            data_frame = match_patterns(data_frame, step=step, data_file=data_file)
        case SortStep():
            columns = list(step.by)
            require_columns(schema_names, columns, operation="sort", data_file=data_file)
            data_frame = data_frame.sort(
                [exact_column_expression(column, column_names=schema_names) for column in columns],
                descending=[direction == "desc" for direction in step.by.values()],
            )
        case UniqueStep():
            require_columns(schema_names, step.subset, operation="unique", data_file=data_file)
            data_frame = data_frame.unique(
                subset=[exact_column_expression(column, column_names=schema_names) for column in step.subset],
                keep="first",
                maintain_order=True,
            )
        case _:
            msg = f"Unsupported table processing operation: {type(step).__name__}"
            raise ValueError(msg)
    return data_frame


def aggregation_expression(
    column: str, function: AggregationFunction | ProcessingPlaceholder, *, column_names: list[str]
) -> pl.Expr:
    """Build a Polars aggregation expression from the closed function vocabulary."""
    if not isinstance(function, AggregationFunction):
        msg = f"Unresolved aggregation placeholder: {function}"
        raise ValueError(msg)
    expression = exact_column_expression(column, column_names=column_names)
    return apply_aggregation(expression, function=function).alias(column)
