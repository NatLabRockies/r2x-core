"""Data transformation pipeline for tabular and JSON data.

This module implements a functional processing pipeline that applies transformations
to data based on specifications in DataFile configurations. Transformations are
organized by data type (Polars LazyFrame for tabular, dict for JSON) with a
registration system allowing custom transformations.

Pipeline architecture:
- Tabular: lowercase -> drop_columns -> rename -> pivot -> cast -> filter -> select
- JSON: rename_keys -> drop_columns -> select_columns -> filter -> select_keys

All placeholder substitution in filter_by specifications uses curly braces
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

    Executes a pipeline of transformations (lowercase, drop, rename, pivot, cast,
    filter, select) on a Polars LazyFrame according to TabularProcessing configuration.

    Column name resolution is done once on the input and passed through each step
    to avoid repeated ``collect_schema()`` on intermediate lazy expressions. The
    only step that triggers a fresh ``collect_schema()`` is ``pivot_on`` since
    ``unpivot`` completely restructures the columns.

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
    # Resolve column names once; track predictable changes (lowercase, drop,
    # rename, select) without fresh collect_schema() calls on intermediate
    # lazy expressions. Only pl_pivot_on needs a real schema refresh because
    # unpivot completely restructures columns.
    schema_names = list(data_frame.collect_schema().names())

    for fp_function in _TABULAR_PIPELINE:
        result = fp_function(data_frame, data_file=data_file, proc_spec=proc_spec, schema_names=schema_names)
        if isinstance(result, tuple):
            data_frame, schema_names = result
        else:
            data_frame = result
            # Only re-collect schema when columns actually changed (pivot).
            schema_names = list(data_frame.collect_schema().names())

    return data_frame


# Pipeline steps that change columns ahead of time so we can infer the new
# schema without collect_schema():
#   pl_lowercase  -> columns become lowercased versions of themselves
#   pl_drop_columns -> some columns removed
#   pl_rename_columns -> some columns renamed
#   pl_pivot_on ->  completely changes columns (needs collect_schema())
#   pl_cast_schema -> columns unchanged
#   pl_apply_filters -> columns unchanged
#   pl_select_columns -> keeps a subset
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
    """Unpivot (melt) the DataFrame based on configuration.

    Uses Polars lazy ``melt()`` instead of materializing and rebuilding the DataFrame,
    avoiding an O(rows * columns) memory and compute blowup in the middle of the
    lazy pipeline.

    This step completely restructures columns so the caller must re-collect the
    schema after this step (return type is ``pl.LazyFrame``, not a tuple).
    """
    _ = schema_names  # schema completely changes; caller re-collects
    if not proc_spec or not proc_spec.pivot_on:
        return data_frame

    value_name = proc_spec.pivot_on
    logger.trace("Pivoting columns: {} for {}", value_name, data_file.name)
    return data_frame.unpivot(value_name=value_name).select(value_name)


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

    existing_cols = [col for col in proc_spec.drop_columns if col in schema_names]
    if existing_cols:
        logger.debug("Dropping columns {} from {}", existing_cols, data_file.name)
        new_names = [n for n in schema_names if n not in existing_cols]
        return data_frame.drop(existing_cols), new_names
    return data_frame, schema_names


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

    valid_mapping = {old: new for old, new in proc_spec.column_mapping.items() if old in schema_names}
    if valid_mapping:
        logger.debug("Renaming columns {} in {}", valid_mapping, data_file.name)
        new_names = [valid_mapping.get(n, n) for n in schema_names]
        return data_frame.rename(valid_mapping), new_names
    return data_frame, schema_names


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

    cast_exprs = []
    for col, type_str in (proc_spec.column_schema or {}).items():
        if col in schema_names:
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

    filters = [
        pl_build_filter_expr(col, value=value)
        for col, value in (proc_spec.filter_by or {}).items()
        if col in schema_names
    ]

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

    # Use dict.fromkeys to maintain order while removing duplicates
    cols_to_select = list(dict.fromkeys(proc_spec.select_columns))

    valid_cols = [col for col in cols_to_select if col in schema_names]
    if not valid_cols:
        return data_frame, schema_names

    logger.trace("Selecting {} columns from {}", len(valid_cols), data_file.name)
    return data_frame.select(valid_cols), list(valid_cols)


# Pipeline steps that change columns ahead of time so we can infer the new
# schema without collect_schema():
#   pl_lowercase  -> columns become lowercased versions of themselves
#   pl_drop_columns -> some columns removed
#   pl_rename_columns -> some columns renamed
#   pl_pivot_on ->  completely changes columns (needs collect_schema())
#   pl_cast_schema -> columns unchanged
#   pl_apply_filters -> columns unchanged
#   pl_select_columns -> keeps a subset
_TABULAR_PIPELINE: list[Callable[..., Any]] = [
    pl_lowercase,
    pl_drop_columns,
    pl_rename_columns,
    pl_pivot_on,
    pl_cast_schema,
    pl_apply_filters,
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
        Used to substitute placeholders like {solve_year} in filter_by.

    Returns
    -------
    Any
        Transformed data.

    Raises
    ------
    ValueError
        If placeholders are found in filter_by but no placeholders dict provided.
    """
    if not proc_spec:
        return Ok(data)

    if proc_spec.filter_by:
        result_substitution = substitute_placeholders(proc_spec.filter_by, placeholders=placeholders)

        if result_substitution.is_err():
            error = result_substitution.err()
            return Err(error)
        assert isinstance(result_substitution, Ok), "Result should be Ok after error check"
        substituted = result_substitution.value

        # Only copy models when substitution actually changed something
        if substituted is not proc_spec.filter_by:
            new_proc = proc_spec.model_copy(update={"filter_by": substituted})
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
