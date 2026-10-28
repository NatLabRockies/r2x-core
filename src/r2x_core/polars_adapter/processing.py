"""Apply ordered table operations with Polars."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import isnan
from numbers import Integral, Rational, Real
from typing import Any, Literal, TypeAlias

import polars as pl
from loguru import logger
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
    MatchPatternsOptions,
    MatchPatternsStep,
    MatchSourcePatternsOptions,
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


def logical_scalar_type_name(dtype: pl.DataType, *, column: str) -> str:
    """Resolve supported Polars scalars to backend-neutral declared type names."""
    if dtype == pl.Boolean:
        return "bool"
    if dtype == pl.Int64:
        return "int64"
    if dtype == pl.Float64:
        return "float64"
    if isinstance(dtype, pl.Datetime):
        return "datetime"
    if dtype.base_type() in {pl.String, pl.Categorical, pl.Enum}:
        return "string"
    msg = (
        f"unpivot value_type_name does not support column {column!r} with dtype {dtype}; "
        "supported types are bool, int64, float64, string, and datetime"
    )
    raise ValueError(msg)


def unpivot_polars_frame(
    data_frame: pl.LazyFrame,
    *,
    index: Sequence[str],
    columns: Mapping[str, str] | None,
    variable_name: str,
    value_name: str,
    type_policy: Literal["exact", "supertype"],
    value_type_name: str | None = None,
    data_file: DataFile | None = None,
) -> pl.LazyFrame:
    """Unpivot selected columns using an explicit value-type policy.

    See Also
    --------
    :doc:`processors` : Tabular processing behavior and unpivot semantics.
    """
    schema = data_frame.collect_schema()
    schema_names = schema.names()
    require_columns(schema_names, list(index), operation="unpivot index", data_file=data_file)
    label_columns = (
        list(columns.items())
        if columns is not None
        else [(name, name) for name in schema_names if name not in index]
    )
    if not label_columns:
        msg = "unpivot requires at least one value column"
        raise ValueError(msg)
    labels = [label for label, _ in label_columns]
    value_columns = [column for _, column in label_columns]
    require_columns(schema_names, value_columns, operation="unpivot", data_file=data_file)
    if len(set(value_columns)) != len(value_columns):
        msg = "unpivot value columns must be unique"
        raise ValueError(msg)

    output_names = [*index, variable_name, value_name]
    if value_type_name is not None:
        output_names.append(value_type_name)
    if len(set(output_names)) != len(output_names):
        msg = "unpivot output names must be distinct from identifiers and each other"
        raise ValueError(msg)

    value_types = {schema[column] for column in value_columns}
    type_names: list[str] | None = None
    if value_type_name is not None:
        type_names = [logical_scalar_type_name(schema[column], column=column) for column in value_columns]
        output_value_type = pl.String
    elif type_policy == "supertype":
        output_value_type = None
    elif len(value_types) == 1:
        output_value_type = next(iter(value_types))
    elif value_types == {pl.Int64, pl.Float64}:
        output_value_type = pl.Float64
    else:
        msg = f"unpivot value columns have incompatible types: {value_types}"
        raise ValueError(msg)

    occupied_names = set(schema_names) | set(output_names)

    def temporary_name(label: str) -> str:
        """Reserve a collision-free temporary column name.

        Parameters
        ----------
        label : str
            Descriptive part of the preferred column name.

        Returns
        -------
        str
            An unused name added to ``occupied_names``.
        """
        name = f"__r2x_unpivot_{label}__"
        while name in occupied_names:
            name = f"_{name}"
        occupied_names.add(name)
        return name

    source_name = temporary_name("source_name")
    output_label = temporary_name("output_label")
    variable = temporary_name("variable")
    value = temporary_name("value")
    type_name = temporary_name("type_name") if type_names is not None else None
    value_aliases = [temporary_name(f"value_column_{index}") for index in range(len(value_columns))]

    value_expressions = []
    for column, alias in zip(value_columns, value_aliases, strict=True):
        expression = exact_column_expression(column, column_names=schema_names)
        if output_value_type is not None and (
            value_type_name is not None or (output_value_type == pl.Float64 and schema[column] == pl.Int64)
        ):
            expression = expression.cast(output_value_type)
        value_expressions.append(expression.alias(alias))
    prepared = data_frame.select(
        [exact_column_expression(column, column_names=schema_names) for column in index] + value_expressions
    )
    prepared_names = [*index, *value_aliases]
    unpivoted = prepared.unpivot(
        on=[exact_column_selector(column, column_names=prepared_names) for column in value_aliases],
        index=[exact_column_selector(column, column_names=prepared_names) for column in index],
        variable_name=variable,
        value_name=value,
    )

    lookup_columns: dict[str, list[str]] = {source_name: value_aliases, output_label: labels}
    lookup_schema: dict[str, pl.DataType | type[pl.DataType]] = {
        source_name: pl.String,
        output_label: pl.String,
    }
    if type_names is not None and type_name is not None:
        lookup_columns[type_name] = type_names
        lookup_schema[type_name] = pl.String
    lookup = pl.DataFrame(lookup_columns, schema=lookup_schema).lazy()
    joined = unpivoted.join(
        lookup,
        left_on=variable,
        right_on=source_name,
        how="left",
        maintain_order="left",
    )
    joined_names = joined.collect_schema().names()
    result = [exact_column_expression(column, column_names=joined_names) for column in index]
    result.extend(
        (
            exact_column_expression(output_label, column_names=joined_names).alias(variable_name),
            exact_column_expression(value, column_names=joined_names).alias(value_name),
        )
    )
    if type_name is not None and value_type_name is not None:
        result.append(exact_column_expression(type_name, column_names=joined_names).alias(value_type_name))
    return joined.select(result)


def pattern_attribute_dtypes(step: MatchPatternsOptions) -> dict[str, DataTypeClass]:
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
    data_frame: pl.LazyFrame, *, step: MatchPatternsOptions, data_file: DataFile | None = None
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


def match_source_patterns(
    data_frame: pl.LazyFrame,
    pattern_source: pl.LazyFrame,
    *,
    step: MatchSourcePatternsOptions,
    data_file: DataFile | None = None,
) -> pl.LazyFrame:
    """Select one configured source pattern for each left row.

    See Also
    --------
    :doc:`table-mapping` : Source-backed table mapping operations.
    :doc:`processors` : Processing and pattern-matching behavior.
    """
    operation_name = "match_source_patterns"
    left_schema = data_frame.collect_schema()
    right_schema = pattern_source.collect_schema()
    left_names = left_schema.names()
    right_names = right_schema.names()
    require_columns(left_names, [step.column], operation=operation_name, data_file=data_file)
    require_columns(right_names, [step.pattern_column], operation=operation_name, data_file=data_file)
    if left_schema[step.column] != pl.String:
        msg = f"match_source_patterns column {step.column!r} must have a string dtype"
        raise ValueError(msg)
    if right_schema[step.pattern_column] != pl.String:
        msg = f"match_source_patterns pattern column {step.pattern_column!r} must have a string dtype"
        raise ValueError(msg)

    payload_names = [name for name in right_names if name != step.pattern_column]
    collisions = sorted(set(left_names) & set(payload_names))
    if collisions:
        msg = f"match_source_patterns output column(s) already exist: {collisions}"
        raise ValueError(msg)

    range_separator = step.range_separator if step.case_sensitive else step.range_separator.casefold()
    prefix_separator = step.prefix_separator if step.case_sensitive else step.prefix_separator.casefold()
    range_pattern = re.compile(rf"^(.*?)([0-9]+){re.escape(range_separator)}(.*?)([0-9]+)$")
    pattern_values = (
        collect_polars_frame(
            pattern_source.select(
                exact_column_expression(step.pattern_column, column_names=right_names)
            ).unique()
        )
        .to_series()
        .to_list()
    )
    for pattern in pattern_values:
        if pattern is None:
            continue
        normalized_pattern = pattern if step.case_sensitive else pattern.casefold()
        if range_separator not in normalized_pattern:
            continue
        match = range_pattern.fullmatch(normalized_pattern)
        if match is None or normalized_pattern.count(range_separator) != 1:
            msg = f"Invalid numeric range pattern {pattern!r}"
            raise ValueError(msg)
        start = match.group(2).lstrip("0") or "0"
        end = match.group(4).lstrip("0") or "0"
        if match.group(1) != match.group(3) or (len(start), start) > (len(end), end):
            msg = f"Invalid numeric range pattern {pattern!r}"
            raise ValueError(msg)

    occupied_names = set(left_names) | set(right_names)

    def temporary_name(label: str) -> str:
        """Reserve a collision-free temporary column name.

        Parameters
        ----------
        label : str
            Descriptive part of the preferred column name.

        Returns
        -------
        str
            An unused name added to ``occupied_names``.
        """
        name = f"__r2x_match_patterns_{label}__"
        while name in occupied_names:
            name = f"_{name}"
        occupied_names.add(name)
        return name

    left_index = temporary_name("left_index")
    right_index = temporary_name("right_index")
    left_value = temporary_name("left_value")
    right_pattern = temporary_name("right_pattern")
    left_prefix = temporary_name("left_prefix")
    left_number = temporary_name("left_number")
    start_prefix = temporary_name("start_prefix")
    start_number = temporary_name("start_number")
    end_prefix = temporary_name("end_prefix")
    end_number = temporary_name("end_number")
    exact_match = temporary_name("exact_match")
    range_match = temporary_name("range_match")
    prefix_match = temporary_name("prefix_match")
    match_rank = temporary_name("match_rank")
    prefix_length = temporary_name("prefix_length")

    left_indexed = data_frame.with_row_index(left_index)
    right_indexed = pattern_source.with_row_index(right_index)
    left_text = exact_column_expression(step.column, column_names=[left_index, *left_names])
    right_text = exact_column_expression(step.pattern_column, column_names=[right_index, *right_names])
    if not step.case_sensitive:
        left_text = left_text.map_elements(str.casefold, return_dtype=pl.String, skip_nulls=True)
        right_text = right_text.map_elements(str.casefold, return_dtype=pl.String, skip_nulls=True)

    left_indexed = left_indexed.with_columns(left_text.alias(left_value))
    left_indexed = left_indexed.with_columns(
        pl.col(left_value).str.extract(r"^(.*?)([0-9]+)$", 1).alias(left_prefix),
        pl.col(left_value).str.extract(r"^(.*?)([0-9]+)$", 2).alias(left_number),
    )
    right_indexed = right_indexed.with_columns(right_text.alias(right_pattern))
    if step.pattern_column in left_names:
        right_indexed = right_indexed.rename({step.pattern_column: temporary_name("source_pattern")})
    right_indexed = right_indexed.with_columns(
        pl.col(right_pattern).str.extract(range_pattern.pattern, 1).alias(start_prefix),
        pl.col(right_pattern).str.extract(range_pattern.pattern, 2).alias(start_number),
        pl.col(right_pattern).str.extract(range_pattern.pattern, 3).alias(end_prefix),
        pl.col(right_pattern).str.extract(range_pattern.pattern, 4).alias(end_number),
    )

    def normalized_decimal(column: str) -> pl.Expr:
        """Build an expression that removes leading zeroes from decimal text.

        Parameters
        ----------
        column : str
            Name of the string column to normalize.

        Returns
        -------
        polars.Expr
            Expression yielding canonical decimal digits, with zero represented
            as ``"0"``.
        """
        digits = pl.col(column).str.replace(r"^0+", "")
        return pl.when(digits == "").then(pl.lit("0")).otherwise(digits)

    normalized_left_number = temporary_name("normalized_left_number")
    normalized_start_number = temporary_name("normalized_start_number")
    normalized_end_number = temporary_name("normalized_end_number")
    left_indexed = left_indexed.with_columns(normalized_decimal(left_number).alias(normalized_left_number))
    right_indexed = right_indexed.with_columns(
        normalized_decimal(start_number).alias(normalized_start_number),
        normalized_decimal(end_number).alias(normalized_end_number),
    )

    pairs = left_indexed.join(right_indexed, how="cross")
    left_value_expr = pl.col(left_value)
    pattern_expr = pl.col(right_pattern)
    has_range = pattern_expr.str.contains(range_separator, literal=True).fill_null(False)
    exact = (~has_range) & (left_value_expr == pattern_expr)
    left_digits = pl.col(normalized_left_number)
    start_digits = pl.col(normalized_start_number)
    end_digits = pl.col(normalized_end_number)
    left_digit_length = left_digits.str.len_chars()
    start_digit_length = start_digits.str.len_chars()
    end_digit_length = end_digits.str.len_chars()
    range = (
        has_range
        & (pl.col(left_prefix) == pl.col(start_prefix))
        & (pl.col(start_prefix) == pl.col(end_prefix))
        & pl.col(left_number).str.contains(r"^[0-9]+$").fill_null(False)
        & (
            (left_digit_length > start_digit_length)
            | ((left_digit_length == start_digit_length) & (left_digits >= start_digits))
        )
        & (
            (left_digit_length < end_digit_length)
            | ((left_digit_length == end_digit_length) & (left_digits <= end_digits))
        )
    )
    pattern_length = pattern_expr.str.len_chars()
    prefix = (
        (~has_range)
        & (left_value_expr.str.slice(0, pattern_length) == pattern_expr)
        & (left_value_expr.str.slice(pattern_length, len(prefix_separator)) == prefix_separator)
    )
    matches = pairs.with_columns(
        exact.alias(exact_match),
        range.alias(range_match),
        prefix.alias(prefix_match),
    ).filter(pl.any_horizontal(pl.col(exact_match), pl.col(range_match), pl.col(prefix_match)))

    precedence = {kind: index for index, kind in enumerate(step.precedence)}
    matches = matches.with_columns(
        pl.when(pl.col(exact_match))
        .then(pl.lit(precedence["exact"]))
        .when(pl.col(range_match))
        .then(pl.lit(precedence["range"]))
        .otherwise(pl.lit(precedence["prefix"]))
        .alias(match_rank),
        pl.when(pl.col(prefix_match) & (step.prefix_policy == "longest"))
        .then(pattern_length)
        .otherwise(pl.lit(0))
        .alias(prefix_length),
    )
    best_matches = matches.sort(
        [left_index, match_rank, prefix_length, right_index],
        descending=[False, False, True, step.duplicate_policy == "last"],
        maintain_order=True,
    ).unique(subset=[left_index], keep="first", maintain_order=True)
    match_names = best_matches.collect_schema().names()
    selected = best_matches.select(
        [exact_column_selector(name, column_names=match_names) for name in [left_index, *payload_names]]
    )
    indexed_names = [left_index, *left_names]
    result = left_indexed.select(
        [exact_column_selector(name, column_names=indexed_names) for name in indexed_names]
    ).join(
        selected,
        on=left_index,
        how="left" if step.unmatched == "keep" else "inner",
        maintain_order="left",
    )
    result_names = result.collect_schema().names()
    return result.select(
        [exact_column_selector(name, column_names=result_names) for name in [*left_names, *payload_names]]
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
    """Pivot exact input columns lazily through Polars' native pivot.

    See Also
    --------
    :doc:`processors` : Tabular processing behavior and pivot options.
    """
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
        """Reserve a pivot alias without colliding with existing output names.

        Parameters
        ----------
        prefix : str
            Preferred alias.
        suffixes : tuple of str, optional
            Pivot suffixes whose generated names must also be available.

        Returns
        -------
        str
            An available alias reserved with its requested suffix names.
        """
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
