"""Pattern matching operations for Polars tables."""

from __future__ import annotations

import re

import polars as pl
from polars.datatypes.classes import DataTypeClass

from ..datafile import DataFile
from ..models import MatchPatternsOptions, MatchSourcePatternsOptions, PatternMatchGroup
from .expressions import exact_column_expression, exact_column_selector
from .frames import collect_polars_frame
from .validation import require_columns


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
            Expression yielding normalized decimal digits, with zero
            represented as ``"0"``.
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
