"""Polars implementations for tabular processing."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import isnan
from numbers import Integral, Rational, Real
from typing import Any, Literal, TypeAlias

import polars as pl
from loguru import logger
from polars.datatypes.classes import DataTypeClass

from ..datafile import DataFile, TabularProcessing
from ..result import TabularTransformResult
from .expressions import resolve_polars_dtype

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


def resolve_schema_names(data_frame: pl.LazyFrame, schema_names: list[str] | None) -> list[str]:
    """Use the supplied schema names or collect them from the frame."""
    return list(data_frame.collect_schema().names()) if schema_names is None else schema_names


def unchanged_result(
    data_frame: pl.LazyFrame, schema_names: list[str]
) -> TabularTransformResult[pl.LazyFrame]:
    """Return an unchanged frame with its current schema names."""
    return TabularTransformResult(data_frame=data_frame, schema_names=schema_names)


def process_tabular_data(
    data_frame: pl.LazyFrame, *, data_file: DataFile, proc_spec: TabularProcessing
) -> pl.LazyFrame:
    """Apply tabular data transformations sequentially.

    Execute the reshape-aware pipeline declared in ``TabularProcessing``.

    Pipeline order:

    - With ``unpivot_on``: lowercase, drop, unpivot, split, replace, strip,
      rename, cast, scale, fill, filter, aggregate, distinct, sort, select.
    - Without ``unpivot_on``: lowercase, drop, split, rename, replace, strip,
      cast, scale, fill, filter, pivot, aggregate, distinct, sort, select.

    Column names are tracked between steps so transformations stay lazy. Schema
    inspection is used only for validation and for operations whose output
    columns cannot be inferred without inspecting the input schema.

    Parameters
    ----------
    data_frame : pl.LazyFrame
        Input tabular data in lazy evaluation mode.
    data_file : DataFile
        File configuration providing context for logging and validation.
    proc_spec : TabularProcessing
        Processing specification defining transformations to apply.

    Returns
    -------
    pl.LazyFrame
        Transformed LazyFrame with all operations applied in sequence.

    See Also
    --------
    :func:`pl_lowercase` : Lowercase string columns and column names.
    :func:`pl_drop_columns` : Remove specified columns.
    :func:`pl_rename_columns` : Apply column name mapping.
    """
    schema_names = list(data_frame.collect_schema().names())
    common_steps = [pl_lowercase, pl_drop_columns]
    if proc_spec.unpivot_on:
        pipeline = [
            *common_steps,
            pl_unpivot_on,
            pl_split_columns,
            pl_replace_values,
            pl_strip_chars,
            pl_rename_columns,
            pl_cast_schema,
            pl_scale,
            pl_fill_null,
            pl_apply_filters,
        ]
    else:
        pipeline = [
            *common_steps,
            pl_split_columns,
            pl_rename_columns,
            pl_replace_values,
            pl_strip_chars,
            pl_cast_schema,
            pl_scale,
            pl_fill_null,
            pl_apply_filters,
            pl_pivot_on,
        ]
    pipeline.extend([pl_aggregate, pl_distinct, pl_sort, pl_select_columns])

    for transform in pipeline:
        result = transform(data_frame, data_file=data_file, proc_spec=proc_spec, schema_names=schema_names)
        data_frame = result.data_frame
        schema_names = result.schema_names

    return data_frame


def pl_pivot_on(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Pivot a DataFrame long-to-wide using the configured pivot column.

    Perform a long-to-wide pivot using grouped value aggregations. The pivot
    column must exist in the input schema. Polars requires distinct output
    values up front, so a small discovery query is collected before the lazy
    pivot plan is built. Use ``unpivot_on`` for wide-to-long reshaping.
    """
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.pivot_on:
        return unchanged_result(data_frame, schema_names)

    value_name = proc_spec.pivot_on
    require_columns(schema_names, [value_name], operation="pivot_on", data_file=data_file)

    group_columns = list(proc_spec.group_by or [])
    value_columns = list(proc_spec.aggregate_on or {})
    if not group_columns:
        excluded = {value_name, *value_columns}
        group_columns = [column for column in schema_names if column not in excluded]
    if not value_columns:
        value_columns = [column for column in schema_names if column not in {*group_columns, value_name}]
    require_columns(schema_names, group_columns, operation="group_by", data_file=data_file)
    require_columns(schema_names, value_columns, operation="pivot_on", data_file=data_file)
    if not value_columns:
        raise ValueError(f"pivot_on in {data_file.name!r} requires at least one value column")

    functions = {function.lower() for function in (proc_spec.aggregate_on or {}).values()}
    aggregate_name = next(iter(functions), "first")
    aggregate_function = pl.element().count() if aggregate_name == "count" else aggregate_name
    pivot_values = (
        data_frame.select(value_name).unique(maintain_order=True).collect().get_column(value_name).to_list()
    )
    if any(value is None for value in pivot_values):
        raise ValueError(
            f"pivot_on in {data_file.name!r} contains null key(s) in column {value_name!r}; "
            "drop or fill null pivot keys before pivoting."
        )
    logger.debug("Pivoting {} on {} in {}", value_columns, value_name, data_file.name)
    result = data_frame.pivot(
        on=value_name,
        on_columns=pivot_values,
        index=group_columns,
        values=value_columns,
        aggregate_function=aggregate_function,
    )
    return TabularTransformResult(data_frame=result, schema_names=list(result.collect_schema().names()))


def require_columns(
    schema_names: list[str],
    columns: list[str],
    *,
    operation: str,
    data_file: DataFile,
) -> None:
    """Raise an actionable error when a transformation references missing columns."""
    missing = list(dict.fromkeys(column for column in columns if column not in schema_names))
    if missing:
        available = ", ".join(schema_names) or "<none>"
        raise ValueError(
            f"{operation} in {data_file.name!r} references missing column(s): {missing}. "
            f"Available columns at this pipeline stage: {available}."
        )


def pl_unpivot_on(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Unpivot configured value columns while retaining identifier columns."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.unpivot_on:
        return unchanged_result(data_frame, schema_names)

    value_columns = list(dict.fromkeys(proc_spec.unpivot_on))
    require_columns(schema_names, value_columns, operation="unpivot_on", data_file=data_file)
    index_columns = [column for column in schema_names if column not in value_columns]
    output_collisions = sorted({"variable", "value"} & set(index_columns))
    if output_collisions:
        raise ValueError(
            f"unpivot_on in {data_file.name!r} would overwrite existing column(s): {output_collisions}."
        )
    logger.debug("Unpivoting {} in {}", value_columns, data_file.name)
    result = data_frame.unpivot(
        on=value_columns,
        index=index_columns,
        variable_name="variable",
        value_name="value",
    )
    return TabularTransformResult(data_frame=result, schema_names=[*index_columns, "variable", "value"])


def pl_split_columns(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Split configured string columns into named fields."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.split_column:
        return unchanged_result(data_frame, schema_names)

    result = data_frame
    current_names = list(schema_names)
    for column, split_spec in proc_spec.split_column.items():
        require_columns(current_names, [column], operation="split_column", data_file=data_file)
        collisions = sorted(set(split_spec.into) & (set(current_names) - {column}))
        if collisions:
            raise ValueError(
                f"split_column in {data_file.name!r} would overwrite existing column(s): {collisions}."
            )
        split_expression = (
            pl.col(column)
            .cast(pl.String)
            .str.split_exact(split_spec.separator, n=len(split_spec.into) - 1)
            .struct.rename_fields(split_spec.into)
            .alias(column)
        )
        result = result.with_columns(split_expression).unnest(column)
        current_names = [
            name
            for existing in current_names
            for name in (split_spec.into if existing == column else [existing])
        ]
    return TabularTransformResult(data_frame=result, schema_names=current_names)


def pl_strip_chars(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Remove configured literal strings and surrounding whitespace."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.strip_chars:
        return unchanged_result(data_frame, schema_names)

    require_columns(schema_names, list(proc_spec.strip_chars), operation="strip_chars", data_file=data_file)
    expressions = []
    for column, characters in proc_spec.strip_chars.items():
        pattern = "|".join(re.escape(character) for character in characters)
        cleaned = pl.col(column).cast(pl.String).str.strip_chars()
        if pattern:
            cleaned = cleaned.str.replace_all(pattern, "")
        expressions.append(cleaned.alias(column))
    return TabularTransformResult(data_frame=data_frame.with_columns(expressions), schema_names=schema_names)


def pl_scale(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Multiply configured numeric columns by their scale factors."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.scale:
        return unchanged_result(data_frame, schema_names)

    columns = list(proc_spec.scale)
    require_columns(schema_names, columns, operation="scale", data_file=data_file)
    schema = data_frame.collect_schema()
    invalid = {column: schema[column] for column in columns if not schema[column].is_numeric()}
    if invalid:
        raise ValueError(f"scale requires numeric columns in {data_file.name!r}: {invalid}")
    expressions = [pl.col(column).mul(factor).alias(column) for column, factor in proc_spec.scale.items()]
    return TabularTransformResult(data_frame=data_frame.with_columns(expressions), schema_names=schema_names)


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


def polars_dtype_family(dtype: pl.DataType) -> ValueFamily | None:
    """Return the logical value family for a Polars dtype."""
    if dtype.is_integer():
        return "integer"
    if dtype.is_float():
        return "float"
    return DTYPE_FAMILIES.get(dtype.base_type())


def python_value_family(value: object) -> ValueFamily | None:
    """Return the logical family for a replacement value."""
    return next(
        (family for value_type, family in VALUE_FAMILIES if isinstance(value, value_type)),
        None,
    )


def pl_replace_values(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Replace values when their logical families match each column."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.replace_values:
        return unchanged_result(data_frame, schema_names)

    schema = data_frame.collect_schema()
    expressions = []
    for column in schema_names:
        dtype = schema[column]
        target_family = polars_dtype_family(dtype)
        if target_family is None:
            continue

        replacements: dict[Any, Any] = {}
        for old, new in proc_spec.replace_values.items():
            cast_values = []
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
                    source_family == "float" and isnan(cast_value) and isnan(value)
                ):
                    compatible = False
                    break
                cast_values.append(cast_value)

            if compatible:
                replacements[cast_values[0]] = cast_values[1]
        if replacements:
            expressions.append(pl.col(column).replace(replacements).alias(column))
    logger.debug("Replacing configured values in {}", data_file.name)
    return TabularTransformResult(data_frame=data_frame.with_columns(expressions), schema_names=schema_names)


def pl_fill_null(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Fill null values in configured columns."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.fill_null:
        return unchanged_result(data_frame, schema_names)

    columns = list(proc_spec.fill_null)
    require_columns(schema_names, columns, operation="fill_null", data_file=data_file)
    expressions = [
        pl.col(column).fill_null(value).alias(column) for column, value in proc_spec.fill_null.items()
    ]
    logger.debug("Filling nulls in {}", data_file.name)
    return TabularTransformResult(data_frame=data_frame.with_columns(expressions), schema_names=schema_names)


def aggregate_expression(column: str, function: str) -> pl.Expr:
    """Build a Polars aggregation expression from a validated function name."""
    expression = pl.col(column)
    operations = {
        "count": expression.count,
        "first": expression.first,
        "last": expression.last,
        "max": expression.max,
        "mean": expression.mean,
        "median": expression.median,
        "min": expression.min,
        "n_unique": expression.n_unique,
        "std": expression.std,
        "sum": expression.sum,
        "var": expression.var,
    }
    return operations[function.lower()]().alias(column)


def pl_aggregate(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Group and aggregate rows using configured Polars aggregations."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.aggregate_on:
        return unchanged_result(data_frame, schema_names)
    if proc_spec.pivot_on:
        return unchanged_result(data_frame, schema_names)

    aggregate_columns = list(proc_spec.aggregate_on)
    require_columns(schema_names, aggregate_columns, operation="aggregate_on", data_file=data_file)
    group_columns = list(proc_spec.group_by or [])
    require_columns(schema_names, group_columns, operation="group_by", data_file=data_file)
    expressions = [
        aggregate_expression(column, function) for column, function in proc_spec.aggregate_on.items()
    ]
    if group_columns:
        result = data_frame.group_by(group_columns, maintain_order=True).agg(expressions)
        return TabularTransformResult(data_frame=result, schema_names=group_columns + aggregate_columns)
    return TabularTransformResult(data_frame=data_frame.select(expressions), schema_names=aggregate_columns)


def pl_distinct(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Remove duplicate rows using the configured subset of columns."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.distinct_on:
        return unchanged_result(data_frame, schema_names)

    columns = list(dict.fromkeys(proc_spec.distinct_on))
    require_columns(schema_names, columns, operation="distinct_on", data_file=data_file)
    logger.debug("Removing duplicates using {} in {}", columns, data_file.name)
    return TabularTransformResult(
        data_frame=data_frame.unique(subset=columns, maintain_order=True), schema_names=schema_names
    )


def pl_sort(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Sort rows according to configured column directions."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.sort_by:
        return unchanged_result(data_frame, schema_names)

    columns = list(proc_spec.sort_by)
    require_columns(schema_names, columns, operation="sort_by", data_file=data_file)
    descending = [proc_spec.sort_by[column].lower() in {"desc", "descending"} for column in columns]
    logger.debug("Sorting {} in {}", columns, data_file.name)
    return TabularTransformResult(
        data_frame=data_frame.sort(columns, descending=descending), schema_names=schema_names
    )


def pl_lowercase(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Convert all string columns to lowercase.

    Returns the transformed frame and an updated schema name list (lowercased).
    """
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.lowercase:
        return unchanged_result(data_frame, schema_names)
    result = data_frame.with_columns(pl.col(pl.String).str.to_lowercase()).rename(
        {column: column.lower() for column in schema_names}
    )
    new_names = [name.lower() for name in schema_names]
    logger.trace("Lowercase columns: {len(schema_names)} -> {len(new_names)} cols for {data_file.name}")
    return TabularTransformResult(data_frame=result, schema_names=new_names)


def pl_drop_columns(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Drop specified columns if they exist.

    Returns the transformed frame and an updated schema name list.
    """
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.drop_columns:
        return unchanged_result(data_frame, schema_names)

    existing_cols = list(dict.fromkeys(proc_spec.drop_columns))
    require_columns(schema_names, existing_cols, operation="drop_columns", data_file=data_file)
    logger.debug("Dropping columns {} from {}", existing_cols, data_file.name)
    new_names = [n for n in schema_names if n not in existing_cols]
    return TabularTransformResult(data_frame=data_frame.drop(existing_cols), schema_names=new_names)


def pl_rename_columns(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Rename columns based on mapping.

    Returns the transformed frame and an updated schema name list.
    """
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.column_mapping:
        return unchanged_result(data_frame, schema_names)

    valid_mapping = dict(proc_spec.column_mapping)
    require_columns(schema_names, list(valid_mapping), operation="column_mapping", data_file=data_file)
    new_names = [valid_mapping.get(n, n) for n in schema_names]
    if len(set(new_names)) != len(new_names):
        raise ValueError(f"column_mapping in {data_file.name!r} creates duplicate column names: {new_names}")
    logger.debug("Renaming columns {} in {}", valid_mapping, data_file.name)
    return TabularTransformResult(data_frame=data_frame.rename(valid_mapping), schema_names=new_names)


def pl_cast_schema(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Cast columns to specified data types. Column names are unchanged."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.column_schema:
        return unchanged_result(data_frame, schema_names)

    columns = list(proc_spec.column_schema)
    require_columns(schema_names, columns, operation="column_schema", data_file=data_file)
    cast_exprs = []
    for col, type_str in proc_spec.column_schema.items():
        polars_type = resolve_polars_dtype(type_str)
        cast_exprs.append(pl.col(col).cast(polars_type))

    logger.trace("Applying schema {} to {}", proc_spec.column_schema, data_file.name)
    return TabularTransformResult(data_frame=data_frame.with_columns(cast_exprs), schema_names=schema_names)


def pl_apply_filters(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Apply row filters. Column names are unchanged."""
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.filter_by:
        return unchanged_result(data_frame, schema_names)

    filter_columns = list(proc_spec.filter_by)
    require_columns(schema_names, filter_columns, operation="filter_by", data_file=data_file)
    filters = [pl_build_filter_expr(col, value=value) for col, value in proc_spec.filter_by.items()]
    combined_filter = filters[0]
    for filter_expr in filters[1:]:
        combined_filter = combined_filter & filter_expr
    logger.trace("Applying {} filters to {}", len(filters), data_file.name)
    return TabularTransformResult(data_frame=data_frame.filter(combined_filter), schema_names=schema_names)


def pl_select_columns(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> TabularTransformResult[pl.LazyFrame]:
    """Select specific columns.

    Returns the transformed frame and an updated schema name list.
    """
    schema_names = resolve_schema_names(data_frame, schema_names)
    if not proc_spec.select_columns:
        return unchanged_result(data_frame, schema_names)

    cols_to_select = list(dict.fromkeys(proc_spec.select_columns))
    require_columns(schema_names, cols_to_select, operation="select_columns", data_file=data_file)

    logger.trace("Selecting {} columns from {}", len(cols_to_select), data_file.name)
    return TabularTransformResult(data_frame=data_frame.select(cols_to_select), schema_names=cols_to_select)


def pl_build_filter_expr(column: str, *, value: Any) -> pl.Expr:
    """Treat integer or integer-list filters on the literal ``datetime`` column as ReEDS years."""
    if column == "datetime" and isinstance(value, int | list):
        if isinstance(value, list):
            return pl.col("datetime").dt.year().is_in(value)
        return pl.col("datetime").dt.year() == value

    col_expr = pl.col(column)

    if isinstance(value, list):
        value = [str(v) for v in value]
        return col_expr.cast(pl.Utf8).is_in(value)

    value = str(value)
    return col_expr.cast(pl.Utf8) == value
