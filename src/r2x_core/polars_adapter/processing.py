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
    PatternMatchGroup,
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


def pattern_attribute_dtypes(step: MatchPatternsStep) -> dict[str, DataTypeClass]:
    """Resolve stable Polars output dtypes from declared defaults and group values."""
    scalar_dtypes = {
        bool: pl.Boolean,
        int: pl.Int64,
        float: pl.Float64,
        str: pl.String,
        type(None): pl.Null,
    }
    result = {}
    for name, default in step.defaults.items():
        value = next(
            (
                group.attributes[name]
                for group in step.groups
                if name in group.attributes and group.attributes[name] is not None
            ),
            default,
        )
        result[name] = scalar_dtypes[type(value)]
    return result


def pattern_group_predicate(column: pl.Expr, group: PatternMatchGroup, *, case_sensitive: bool) -> pl.Expr:
    """Match one group's exact values or literal prefixes against a string expression."""
    predicates = []
    if group.exact:
        exact_values = group.exact if case_sensitive else [value.lower() for value in group.exact]
        predicates.append(column.is_in(exact_values))
    prefixes = group.prefixes if case_sensitive else [value.lower() for value in group.prefixes]
    predicates.extend(column.str.starts_with(prefix) for prefix in prefixes)
    return pl.any_horizontal(predicates)


def match_patterns(
    data_frame: pl.LazyFrame, *, step: MatchPatternsStep, data_file: DataFile | None = None
) -> pl.LazyFrame:
    """Emit one row per source-row and matching ordered pattern group."""
    schema = data_frame.collect_schema()
    schema_names = schema.names()
    require_columns(schema_names, [step.column], operation="match_patterns", data_file=data_file)
    if schema[step.column] != pl.String:
        msg = f"match_patterns column {step.column!r} must have a string dtype"
        raise ValueError(msg)

    output_names = [step.label_column, *step.defaults]
    collisions = sorted(set(schema_names) & set(output_names))
    if collisions:
        msg = f"match_patterns output column(s) already exist: {collisions}"
        raise ValueError(msg)

    column = exact_column_expression(step.column, column_names=schema_names)
    if not step.case_sensitive:
        column = column.str.to_lowercase()

    attribute_dtypes = pattern_attribute_dtypes(step)
    matched_frames: list[pl.LazyFrame] = []
    for group in step.groups:
        attributes = step.defaults | group.attributes
        additions = [
            pl.lit(group.label, dtype=pl.String).alias(step.label_column),
            *(pl.lit(attributes[name], dtype=attribute_dtypes[name]).alias(name) for name in step.defaults),
        ]
        matched_frames.append(
            data_frame.filter(
                pattern_group_predicate(column, group, case_sensitive=step.case_sensitive)
            ).with_columns(additions)
        )

    matched = pl.concat(matched_frames, how="vertical")
    matched_names = matched.collect_schema().names()
    return matched.select(
        [exact_column_selector(name, column_names=matched_names) for name in [*schema_names, *output_names]]
    )


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
                on=[exact_column_selector(column, column_names=schema_names) for column in value_columns],
                index=[exact_column_selector(column, column_names=schema_names) for column in step.index],
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
            require_columns(
                schema_names, list(step.column_schema), operation="column_schema", data_file=data_file
            )
            data_frame = data_frame.with_columns(
                [
                    exact_column_expression(column, column_names=schema_names).cast(
                        resolve_polars_dtype(dtype)
                    )
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


def pivot_table(
    data_frame: pl.LazyFrame, *, step: PivotStep, data_file: DataFile | None = None
) -> pl.LazyFrame:
    """Pivot exact input columns lazily through Polars' native pivot."""
    schema_names = data_frame.collect_schema().names()
    input_columns = [step.pivot_on, *step.group_by, *step.aggregate_on]
    require_columns(schema_names, input_columns, operation="pivot", data_file=data_file)
    pivot_values = (
        collect_polars_frame(
            data_frame.select(exact_column_expression(step.pivot_on, column_names=schema_names)).unique(
                maintain_order=True
            )
        )
        .to_series()
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

    occupied_names = set(schema_names) | {str(value) for value in pivot_values}

    def allocate_alias(prefix: str, *, suffixes: tuple[str, ...] = ()) -> str:
        candidate = prefix
        while candidate in occupied_names or any(
            f"{candidate}_{suffix}" in occupied_names for suffix in suffixes
        ):
            candidate = f"_{candidate}"
        occupied_names.add(candidate)
        occupied_names.update(f"{candidate}_{suffix}" for suffix in suffixes)
        return candidate

    pivot_column = allocate_alias("__r2x_pivot_key")
    index_columns = {
        column: allocate_alias(f"__r2x_pivot_index_{index}") for index, column in enumerate(step.group_by)
    }
    value_columns = {
        column: allocate_alias(
            f"__r2x_pivot_value_{index}",
            suffixes=tuple(str(value) for value in pivot_values) if len(step.aggregate_on) > 1 else (),
        )
        for index, column in enumerate(step.aggregate_on)
    }
    projection = [exact_column_expression(step.pivot_on, column_names=schema_names).alias(pivot_column)]
    projection.extend(
        exact_column_expression(column, column_names=schema_names).alias(alias)
        for column, alias in index_columns.items()
    )
    projection.extend(
        exact_column_expression(column, column_names=schema_names).alias(alias)
        for column, alias in value_columns.items()
    )
    pivot_input = data_frame.select(projection)
    result = pivot_input.pivot(
        on=pivot_column,
        on_columns=pivot_values,
        index=list(index_columns.values()),
        values=list(value_columns.values()),
        aggregate_function=pl.element().count() if function is AggregationFunction.COUNT else function.value,
    )
    restored_columns = {alias: column for column, alias in index_columns.items()}
    if len(value_columns) > 1:
        for result_column in result.collect_schema().names():
            for input_column, alias in value_columns.items():
                prefix = f"{alias}_"
                if result_column.startswith(prefix):
                    restored_columns[result_column] = f"{input_column}{result_column[len(alias) :]}"
    return result.rename(restored_columns)


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


def aggregation_expression(
    column: str, function: AggregationFunction | ProcessingPlaceholder, *, column_names: list[str]
) -> pl.Expr:
    """Build a Polars aggregation expression from the closed function vocabulary."""
    if not isinstance(function, AggregationFunction):
        msg = f"Unresolved aggregation placeholder: {function}"
        raise ValueError(msg)
    expression = exact_column_expression(column, column_names=column_names)
    return apply_aggregation(expression, function=function).alias(column)


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
