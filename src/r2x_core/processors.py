"""Data transformation pipeline for tabular and JSON data.

This module implements a functional processing pipeline that applies transformations
to data based on specifications in DataFile configurations. Transformations are
organized by data type (Polars LazyFrame for tabular, dict for JSON) with a
registration system allowing custom transformations.

Pipeline architecture:
- Tabular: lowercase -> drop -> rename -> replace -> cast -> fill -> filter -> reshape -> aggregate -> distinct -> sort -> select
- JSON: rename_keys -> drop_columns -> select_columns -> filter -> select_keys

Tabular operation order is fixed. ``unpivot_on`` is the explicit wide-to-long
operation that retains identifier columns. ``pivot_on`` performs a long-to-wide
pivot when it names an input column and retains the legacy wide-to-long behavior
otherwise. The two are mutually exclusive. Aggregation runs after reshaping for
``unpivot_on``; ``aggregate_on`` supplies value aggregations for a real pivot.

Placeholder substitution in processing specifications uses curly braces
(e.g., {solve_year}) and requires a placeholders dictionary at processing time.

See Also
--------
:class:`~r2x_core.datafile.DataFile` : File configuration with processing specs.
:class:`~r2x_core.datafile.TabularProcessing` : Tabular data transformation config.
:class:`~r2x_core.datafile.JSONProcessing` : JSON data transformation config.
"""

import re
from collections.abc import Callable
from typing import Any

import polars as pl
from loguru import logger
from polars.datatypes.classes import DataTypeClass
from pydantic import ValidationError as PydanticValidationError
from rust_ok import Err, Ok, Result

from r2x_core.types import JSONType

from .datafile import DataFile, FileProcessing, JSONProcessing, TabularProcessing
from .exceptions import ValidationError

# Regex to find simple placeholders
_PLACEHOLDER_PATTERN = re.compile(r"\{([^}]+)\}")


def substitute_placeholders(
    value: Any, *, placeholders: dict[str, Any] | None = None
) -> Result[Any, ValueError]:
    """Replace {variable} placeholders in values using provided mapping.

    Recursively substitutes placeholders in strings, lists, and dictionaries.
    Placeholders must be complete values (e.g., {year}, not prefix_{year}).

    Parameters
    ----------
    value : Any
        String, list, dict, or scalar value potentially containing placeholders.
    placeholders : dict[str, Any] | None
        Mapping from placeholder names to replacement values. Required if
        placeholders are found in value.

    Returns
    -------
    Result[Any, ValueError]
        Ok(substituted_value) on success, Err(ValueError) if placeholders found
        without mapping or placeholder name not in mapping dictionary.

    Examples
    --------
    >>> result = substitute_placeholders("{year}", {"year": 2030})
    >>> result.unwrap()
    2030

    >>> result = substitute_placeholders({"year": "{y}"}, {"y": 2030})
    >>> result.unwrap()
    {'year': 2030}
    """
    if not isinstance(value, str | list | dict):
        return Ok(value)

    if isinstance(value, str) and "{" not in value:
        return Ok(value)

    # Track whether any substitution actually changed a value.
    # When nothing changed, return the original to allow identity checks.
    changed = False

    def substitute_value(val: Any) -> Result[Any, ValueError]:
        """Recursively substitute placeholders in a value."""
        nonlocal changed
        if isinstance(val, str):
            if "{" not in val:
                return Ok(val)

            match = _PLACEHOLDER_PATTERN.fullmatch(val)
            if match:
                var_name = match.group(1)
                if placeholders is None:
                    return Err(
                        ValueError(
                            f"Found placeholder '{{{var_name}}}' but no placeholders provided.\n"
                            "Hint: Pass placeholders parameter when calling read_data_file(), "
                            "or use literal values instead of placeholders."
                        )
                    )
                if var_name not in placeholders:
                    available = ", ".join(placeholders.keys())
                    return Err(
                        ValueError(
                            f"Placeholder '{{{var_name}}}' not found in placeholders.\n"
                            f"Available placeholders: {available}"
                        )
                    )
                changed = True
                return Ok(placeholders[var_name])

            if _PLACEHOLDER_PATTERN.search(val):
                return Err(
                    ValueError(
                        f"Found placeholder pattern in '{val}' but it's not a complete placeholder.\n"
                        "Placeholders must be the entire value, e.g., use '{variable}' not 'prefix_{variable}'"
                    )
                )
            return Ok(val)

        elif isinstance(val, list):
            new_list = []
            local_changed = False
            for item in val:
                res = substitute_value(item)
                if res.is_err():
                    return res
                assert isinstance(res, Ok), "Result should be Ok after error check"
                new_list.append(res.value)
                if res.value is not item:
                    local_changed = True
            if not local_changed:
                return Ok(val)  # preserve original
            changed = True
            return Ok(new_list)

        elif isinstance(val, dict):
            new_dict = {}
            local_changed = False
            for k, v in val.items():
                res = substitute_value(v)
                if res.is_err():
                    return res
                assert isinstance(res, Ok), "Result should be Ok after error check"
                new_dict[k] = res.value
                if res.value is not v:
                    local_changed = True
            if not local_changed:
                return Ok(val)  # preserve original
            changed = True
            return Ok(new_dict)

        return Ok(val)

    result = substitute_value(value)
    if result.is_err():
        return result
    if not changed:
        return Ok(value)
    return result


def process_tabular_data(
    data_frame: pl.LazyFrame, *, data_file: DataFile, proc_spec: TabularProcessing
) -> pl.LazyFrame:
    """Apply tabular data transformations sequentially.

    Executes the fixed tabular pipeline declared in ``TabularProcessing``.

    Operations run in this order: lowercase column names and string values,
    drop columns, rename columns, replace values, cast columns, fill nulls,
    filter rows, reshape, aggregate, deduplicate, sort, and select columns.
    ``unpivot_on`` is the explicit wide-to-long operation with identifier
    columns. ``pivot_on`` performs a long-to-wide pivot when it names an input
    column and retains its legacy wide-to-long behavior otherwise. Aggregation
    follows unpivoting, which allows long data to be grouped and normalized in
    one lazy pipeline.

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

    for fp_function in _TABULAR_PIPELINE:
        result = fp_function(data_frame, data_file=data_file, proc_spec=proc_spec, schema_names=schema_names)
        if isinstance(result, tuple):
            data_frame, schema_names = result
        else:
            data_frame = result
            schema_names = list(data_frame.collect_schema().names())

    return data_frame


def process_json_data(json_data: JSONType, *, data_file: DataFile, proc_spec: JSONProcessing) -> JSONType:
    """Apply JSON data transformations sequentially.

    Executes a pipeline of transformations (rename_keys, drop_columns, select_columns,
    filter, select_keys) on nested dict/list structures per JSONProcessing configuration.
    Transformations work recursively on nested structures.

    Parameters
    ----------
    json_data : JSONType
        Input JSON data (dict, list of dicts, or nested structures).
    data_file : DataFile
        File configuration providing context for logging and validation.
    proc_spec : JSONProcessing
        Processing specification defining transformations to apply.

    Returns
    -------
    JSONType
        Transformed JSON data with all operations applied in sequence.

    See Also
    --------
    :func:`json_rename_keys` : Apply key name mapping recursively.
    :func:`json_drop_columns` : Remove specified keys recursively.
    :func:`json_apply_filters` : Filter dicts by key-value criteria.
    """
    pipeline = [
        json_rename_keys,
        json_drop_columns,
        json_select_columns,
        json_apply_filters,
        json_select_keys,
    ]
    result = json_data
    for transform_func in pipeline:
        result = transform_func(result, data_file=data_file, proc_spec=proc_spec)

    return result


def pl_pivot_on(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> pl.LazyFrame:
    """Pivot or stack a DataFrame according to the configured pivot column.

    When ``pivot_on`` names an input column, this performs a long-to-wide pivot
    using grouped value aggregations. Polars requires the distinct output column
    values up front, so that small discovery query is collected before the lazy
    pivot plan is built. When the name is not an input column, the legacy
    wide-to-long stack behavior is used.
    """
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.pivot_on:
        return data_frame

    value_name = proc_spec.pivot_on
    if value_name not in (schema_names or []):
        if proc_spec.group_by or proc_spec.aggregate_on:
            raise ValueError(
                f"Legacy pivot_on={value_name!r} in {data_file.name!r} cannot be combined with "
                "group_by or aggregate_on. Use a pivot_on column that exists in the input schema."
            )
        logger.trace("Applying legacy pivot_on={} to {}", value_name, data_file.name)
        return data_frame.unpivot(value_name=value_name).select(value_name)

    group_columns = list(proc_spec.group_by or [])
    value_columns = list(proc_spec.aggregate_on or {})
    if not group_columns:
        excluded = {value_name, *value_columns}
        group_columns = [column for column in schema_names or [] if column not in excluded]
    if not value_columns:
        value_columns = [
            column for column in schema_names or [] if column not in {*group_columns, value_name}
        ]
    _require_columns(schema_names or [], group_columns, operation="group_by", data_file=data_file)
    _require_columns(schema_names or [], value_columns, operation="pivot_on", data_file=data_file)
    if not value_columns:
        raise ValueError(f"pivot_on in {data_file.name!r} requires at least one value column")

    functions = {function.lower() for function in (proc_spec.aggregate_on or {}).values()}
    aggregate_function = next(iter(functions), "first")
    pivot_values = (
        data_frame.select(value_name).unique(maintain_order=True).collect().get_column(value_name).to_list()
    )
    logger.debug("Pivoting {} on {} in {}", value_columns, value_name, data_file.name)
    return data_frame.pivot(
        on=value_name,
        on_columns=pivot_values,
        index=group_columns,
        values=value_columns,
        aggregate_function=aggregate_function,
    )


def _require_columns(
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
            f"Available columns: {available}. Column names are lowercased before processing."
        )


def pl_unpivot_on(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Unpivot configured value columns while retaining identifier columns."""
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.unpivot_on:
        return data_frame, schema_names

    value_columns = list(dict.fromkeys(proc_spec.unpivot_on))
    _require_columns(schema_names, value_columns, operation="unpivot_on", data_file=data_file)
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
    return result, [*index_columns, "variable", "value"]


def _compatible_replacements(mapping: dict[Any, Any], dtype: pl.DataType) -> dict[Any, Any]:
    """Select replacement keys and values representable by a column type."""
    compatible: dict[Any, Any] = {}
    for old, new in mapping.items():
        try:
            old_series = pl.Series("_replacement", [old]).cast(dtype, strict=False)
            new_series = pl.Series("_replacement", [new]).cast(dtype, strict=False)
        except (TypeError, ValueError, pl.exceptions.PolarsError):
            continue
        old_compatible = old is None or old_series.null_count() == 0
        new_compatible = new is None or new_series.null_count() == 0
        if old_compatible and new_compatible:
            compatible[None if old is None else old_series.item()] = (
                None if new is None else new_series.item()
            )
    return compatible


def pl_replace_values(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Replace configured values in every compatible column."""
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.replace_values:
        return data_frame, schema_names

    schema = data_frame.collect_schema()
    expressions = []
    for column in schema_names:
        replacements = _compatible_replacements(proc_spec.replace_values, schema[column])
        if replacements:
            expressions.append(pl.col(column).replace(replacements).alias(column))
    logger.debug("Replacing configured values in {}", data_file.name)
    return data_frame.with_columns(expressions), schema_names


def pl_fill_null(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Fill null values in configured columns."""
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.fill_null:
        return data_frame, schema_names

    columns = list(proc_spec.fill_null)
    _require_columns(schema_names, columns, operation="fill_null", data_file=data_file)
    expressions = [
        pl.col(column).fill_null(value).alias(column) for column, value in proc_spec.fill_null.items()
    ]
    logger.debug("Filling nulls in {}", data_file.name)
    return data_frame.with_columns(expressions), schema_names


def _aggregate_expression(column: str, function: str) -> pl.Expr:
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
) -> tuple[pl.LazyFrame, list[str]]:
    """Group and aggregate rows using configured Polars aggregations."""
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.aggregate_on:
        return data_frame, schema_names
    if proc_spec.pivot_on and proc_spec.pivot_on not in schema_names:
        return data_frame, schema_names

    aggregate_columns = list(proc_spec.aggregate_on)
    _require_columns(schema_names, aggregate_columns, operation="aggregate_on", data_file=data_file)
    group_columns = list(proc_spec.group_by or [])
    _require_columns(schema_names, group_columns, operation="group_by", data_file=data_file)
    expressions = [
        _aggregate_expression(column, function) for column, function in proc_spec.aggregate_on.items()
    ]
    if group_columns:
        result = data_frame.group_by(group_columns, maintain_order=True).agg(expressions)
        return result, group_columns + aggregate_columns
    return data_frame.select(expressions), aggregate_columns


def pl_distinct(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Remove duplicate rows using the configured subset of columns."""
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.distinct_on:
        return data_frame, schema_names

    columns = list(dict.fromkeys(proc_spec.distinct_on))
    _require_columns(schema_names, columns, operation="distinct_on", data_file=data_file)
    logger.debug("Removing duplicates using {} in {}", columns, data_file.name)
    return data_frame.unique(subset=columns, maintain_order=True), schema_names


def pl_sort(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Sort rows according to configured column directions."""
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.sort_by:
        return data_frame, schema_names

    columns = list(proc_spec.sort_by)
    _require_columns(schema_names, columns, operation="sort_by", data_file=data_file)
    descending = [proc_spec.sort_by[column].lower() in {"desc", "descending"} for column in columns]
    logger.debug("Sorting {} in {}", columns, data_file.name)
    return data_frame.sort(columns, descending=descending), schema_names


def pl_lowercase(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Convert all string columns to lowercase.

    Returns the transformed frame and an updated schema name list (lowercased).
    """
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    result = data_frame.with_columns(pl.col(pl.String).str.to_lowercase()).rename(
        {column: column.lower() for column in schema_names}
    )
    new_names = [name.lower() for name in schema_names]
    logger.trace("Lowercase columns: {len(schema_names)} -> {len(new_names)} cols for {data_file.name}")
    return result, new_names


def pl_drop_columns(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Drop specified columns if they exist.

    Returns the transformed frame and an updated schema name list.
    """
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.drop_columns:
        return data_frame, schema_names

    existing_cols = list(dict.fromkeys(proc_spec.drop_columns))
    _require_columns(schema_names, existing_cols, operation="drop_columns", data_file=data_file)
    logger.debug("Dropping columns {} from {}", existing_cols, data_file.name)
    new_names = [n for n in schema_names if n not in existing_cols]
    return data_frame.drop(existing_cols), new_names


def pl_rename_columns(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Rename columns based on mapping.

    Returns the transformed frame and an updated schema name list.
    """
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.column_mapping:
        return data_frame, schema_names

    valid_mapping = dict(proc_spec.column_mapping)
    _require_columns(schema_names, list(valid_mapping), operation="column_mapping", data_file=data_file)
    new_names = [valid_mapping.get(n, n) for n in schema_names]
    if len(set(new_names)) != len(new_names):
        raise ValueError(f"column_mapping in {data_file.name!r} creates duplicate column names: {new_names}")
    logger.debug("Renaming columns {} in {}", valid_mapping, data_file.name)
    return data_frame.rename(valid_mapping), new_names


def pl_cast_schema(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Cast columns to specified data types. Column names are unchanged."""
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.column_schema:
        return data_frame, schema_names

    columns = list(proc_spec.column_schema)
    _require_columns(schema_names, columns, operation="column_schema", data_file=data_file)
    cast_exprs = []
    for col, type_str in proc_spec.column_schema.items():
        polars_type = _get_polars_type(type_str)
        cast_exprs.append(pl.col(col).cast(polars_type))

    if not cast_exprs:
        return data_frame, schema_names
    logger.trace("Applying schema {} to {}", proc_spec.column_schema, data_file.name)
    return data_frame.with_columns(cast_exprs), schema_names


def pl_apply_filters(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Apply row filters. Column names are unchanged."""
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.filter_by:
        return data_frame, schema_names

    filter_columns = list(proc_spec.filter_by)
    _require_columns(schema_names, filter_columns, operation="filter_by", data_file=data_file)
    filters = [pl_build_filter_expr(col, value=value) for col, value in proc_spec.filter_by.items()]

    if not filters:
        return data_frame, schema_names
    combined_filter = filters[0]
    for filter_expr in filters[1:]:
        combined_filter = combined_filter & filter_expr
    logger.trace("Applying {} filters to {}", len(filters), data_file.name)
    return data_frame.filter(combined_filter), schema_names


def pl_select_columns(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    schema_names: list[str] | None = None,
) -> tuple[pl.LazyFrame, list[str]]:
    """Select specific columns.

    Returns the transformed frame and an updated schema name list.
    """
    if schema_names is None:
        schema_names = list(data_frame.collect_schema().names())
    if not proc_spec or not proc_spec.select_columns:
        return data_frame, schema_names

    cols_to_select = list(dict.fromkeys(proc_spec.select_columns))
    _require_columns(schema_names, cols_to_select, operation="select_columns", data_file=data_file)

    logger.trace("Selecting {} columns from {}", len(cols_to_select), data_file.name)
    return data_frame.select(cols_to_select), cols_to_select


_TABULAR_PIPELINE: list[Callable[..., Any]] = [
    pl_lowercase,
    pl_drop_columns,
    pl_rename_columns,
    pl_replace_values,
    pl_cast_schema,
    pl_fill_null,
    pl_apply_filters,
    pl_unpivot_on,
    pl_pivot_on,
    pl_aggregate,
    pl_distinct,
    pl_sort,
    pl_select_columns,
]


def json_rename_keys(json_data: JSONType, *, data_file: DataFile, proc_spec: JSONProcessing) -> JSONType:
    """Rename keys based on key mapping from JSONProcessing.

    Applies renaming recursively to nested dictionaries.
    """
    if not proc_spec or not proc_spec.key_mapping:
        return json_data

    mapping = proc_spec.key_mapping

    def rename_keys_recursive(obj: JSONType) -> JSONType:
        """Recursively rename keys in nested JSON structure.

        Parameters
        ----------
        obj : JSONType
            JSON object (dict, list, or scalar) to process.

        Returns
        -------
        JSONType
            Object with renamed keys applied recursively.
        """
        if isinstance(obj, dict):
            return {mapping.get(k, k): rename_keys_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [rename_keys_recursive(item) for item in obj]
        return obj

    logger.debug("Applying key mapping {} to {}", mapping, data_file.name)
    return rename_keys_recursive(json_data)


def json_drop_columns(json_data: JSONType, *, data_file: DataFile, proc_spec: JSONProcessing) -> JSONType:
    """Drop specified columns/keys from JSON data recursively."""
    if not proc_spec or not proc_spec.drop_keys:
        return json_data

    drop_keys = proc_spec.drop_keys

    def drop_keys_recursive(obj: JSONType) -> JSONType:
        """Recursively remove specified keys from nested JSON structure.

        Parameters
        ----------
        obj : JSONType
            JSON object (dict, list, or scalar) to process.

        Returns
        -------
        JSONType
            Object with specified keys removed recursively.
        """
        if isinstance(obj, dict):
            return {k: drop_keys_recursive(v) for k, v in obj.items() if k not in drop_keys}
        elif isinstance(obj, list):
            return [drop_keys_recursive(item) for item in obj]
        return obj

    logger.debug("Dropping columns {} from {}", drop_keys, data_file.name)
    return drop_keys_recursive(json_data)


def json_select_columns(json_data: JSONType, *, data_file: DataFile, proc_spec: JSONProcessing) -> JSONType:
    """Select specific columns/keys from JSON data."""
    if not proc_spec or not proc_spec.select_keys:
        return json_data

    columns_to_select = proc_spec.select_keys

    def select_keys_recursive(obj: JSONType) -> JSONType:
        """Recursively select specified keys from nested JSON structure.

        Parameters
        ----------
        obj : JSONType
            JSON object (dict, list, or scalar) to process.

        Returns
        -------
        JSONType
            Object with only selected keys preserved recursively.
        """
        if isinstance(obj, dict):
            return {k: select_keys_recursive(v) for k, v in obj.items() if k in columns_to_select}
        elif isinstance(obj, list):
            return [select_keys_recursive(item) for item in obj]
        return obj

    logger.trace("Selecting keys {} from {}", columns_to_select, data_file.name)
    return select_keys_recursive(json_data)


def json_apply_filters(
    json_data: JSONType,
    *,
    data_file: DataFile,
    proc_spec: JSONProcessing | None,
) -> JSONType:
    """Filter JSON data by key-value pairs."""
    if not proc_spec or not proc_spec.filter_by:
        return json_data

    filters = proc_spec.filter_by

    def matches(obj: JSONType) -> bool:
        """Check if object matches all filter criteria.

        Parameters
        ----------
        obj : JSONType
            Object to check against filters.

        Returns
        -------
        bool
            True if object is a dict and matches all filter conditions.
        """
        if not isinstance(obj, dict):
            return False
        return all(_matches_filter(obj.get(k), filter_value=v) for k, v in filters.items())

    logger.trace("Applying filter {} to {}", filters, data_file.name)

    # handle list of dicts
    if isinstance(json_data, list):
        return [obj for obj in json_data if matches(obj)]

    # handle dict
    if isinstance(json_data, dict):
        if matches(json_data):
            return json_data
        # else: filter sub-dicts
        return {k: v for k, v in json_data.items() if matches(v)}

    return json_data


def json_select_keys(
    json_data: JSONType,
    *,
    data_file: DataFile,
    proc_spec: JSONProcessing | None,
) -> JSONType:
    """Select specific keys from JSON data (dict or list of dicts)."""
    if not proc_spec or not proc_spec.select_keys:
        return json_data

    keys = set(proc_spec.select_keys)
    logger.trace("Selecting keys {} from {}", keys, data_file.name)

    if isinstance(json_data, list):
        return [{k: v for k, v in obj.items() if k in keys} for obj in json_data if isinstance(obj, dict)]

    if isinstance(json_data, dict):
        return {k: v for k, v in json_data.items() if k in keys}

    return json_data


def transform_xml_data(data: Any, *, data_file: DataFile) -> Any:
    """Transform XML data - placeholder for future implementation."""
    logger.debug("XML transformation placeholder for {}", data_file.name)
    return data


TRANSFORMATIONS: dict[type | tuple[type, ...], Callable[..., Any]] = {
    pl.LazyFrame: process_tabular_data,
    dict: process_json_data,
    # We can add more as needed: tuple: transform_xml_data, etc.
}


def apply_processing(
    data: Any,
    *,
    data_file: DataFile,
    proc_spec: FileProcessing | None,
    placeholders: dict[str, Any] | None = None,
) -> Result[Any, ValueError | ValidationError]:
    """Apply appropriate transformation based on data type.

    Parameters
    ----------
    data : Any
        Raw data to transform.
    data_file : DataFile
        Configuration with transformation instructions.
    proc_spec : FileProcessing | None
        Processing specification (TabularProcessing or JSONProcessing).
    placeholders : dict[str, Any] | None
        Dictionary mapping placeholder variable names to their values.
        Used to substitute placeholders like {solve_year} in processing settings.

    Returns
    -------
    Any
        Transformed data.

    Raises
    ------
    ValueError
        If placeholders are found in processing settings but no placeholders dict provided.
    """
    if not proc_spec:
        return Ok(data)

    spec_dict = proc_spec.model_dump()
    result_substitution = substitute_placeholders(spec_dict, placeholders=placeholders)
    if result_substitution.is_err():
        return Err(result_substitution.err())
    assert isinstance(result_substitution, Ok), "Result should be Ok after error check"
    substituted = result_substitution.value
    if substituted is not spec_dict:
        try:
            new_proc = type(proc_spec).model_validate(substituted)
        except PydanticValidationError as error:
            return Err(
                ValueError(f"Invalid processing specification after placeholder substitution: {error}")
            )
        data_file = data_file.model_copy(update={"proc_spec": new_proc})
        proc_spec = new_proc

    for registered_types, transform_func in TRANSFORMATIONS.items():
        if isinstance(data, registered_types):
            return Ok(transform_func(data, data_file=data_file, proc_spec=proc_spec))

    logger.debug("No transformation for type {} in {}", type(data).__name__, data_file.name)
    return Ok(data)


def register_transformation(data_types: type | tuple[type, ...], *, func: Callable[..., Any]) -> None:
    """Register a custom transformation function.

    Parameters
    ----------
    data_types : type or tuple of types
        Data type(s) this function can handle.
    func : TransformFunction
        Function that takes (data_file, data) and returns transformed data.

    Examples
    --------
    >>> def transform_my_data(data_file: DataFile, data: MyType) -> MyType:
    ...     # Custom transformation logic
    ...     return data
    >>> register_transformation(MyType, func=transform_my_data)
    """
    TRANSFORMATIONS[data_types] = func


def _matches_filter(value: Any, *, filter_value: Any) -> bool:
    """Check if value matches filter criteria.

    Supports both single value and list comparisons. For lists, checks membership.
    Used internally by JSON and tabular filter operations.

    Parameters
    ----------
    value : Any
        Actual value from data to test.
    filter_value : Any or list
        Target value or list of values to match against.

    Returns
    -------
    bool
        True if value equals filter_value (single) or is in filter_value (list).
    """
    if isinstance(filter_value, list):
        return bool(value in filter_value)
    return bool(value == filter_value)


def _get_polars_type(type_str: str) -> DataTypeClass:
    """Convert type name string to Polars DataType class.

    Maps common type names to Polars type objects. Supports aliases
    (e.g., 'string', 'str'; 'int', 'integer'; 'float', 'double').

    Parameters
    ----------
    type_str : str
        Type name (case-insensitive): string, str, int, int32, integer, float,
        double, bool, boolean, date, datetime.

    Returns
    -------
    DataTypeClass
        Corresponding Polars data type.

    Raises
    ------
    ValueError
        If type_str is not recognized in the type mapping.
    """
    mapping = {
        "string": pl.String,
        "str": pl.String,
        "int": pl.Int64,
        "int32": pl.Int32,
        "integer": pl.Int64,
        "float": pl.Float64,
        "double": pl.Float64,
        "bool": pl.Boolean,
        "boolean": pl.Boolean,
        "date": pl.Date,
        "datetime": pl.Datetime,
    }
    polars_type = mapping.get(type_str.lower())
    if polars_type is None:
        msg = f"Unsupported data type: {type_str}"
        raise ValueError(msg)
    return polars_type


def pl_build_filter_expr(column: str, *, value: Any) -> pl.Expr:
    """Build polars filter expression."""
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
