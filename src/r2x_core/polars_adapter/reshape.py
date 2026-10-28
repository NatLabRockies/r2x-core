"""Reshape Polars tables and resolve reshape metadata."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

import polars as pl

from ..datafile import DataFile
from ..models import PivotStep
from ..types import AggregationFunction
from .expressions import exact_column_expression, exact_column_selector
from .frames import collect_polars_frame
from .validation import require_columns


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


def allocate_pivot_alias(prefix: str, /, *, occupied_names: set[str], suffixes: tuple[str, ...] = ()) -> str:
    """Reserve a pivot alias without colliding with existing output names.

    Parameters
    ----------
    prefix : str
        Preferred alias.
    occupied_names : set[str]
        Names already used or reserved for the pivot output.
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

    pivot_column = allocate_pivot_alias("__r2x_pivot_key", occupied_names=occupied_names)
    index_columns = {
        column: allocate_pivot_alias(f"__r2x_pivot_index_{index}", occupied_names=occupied_names)
        for index, column in enumerate(step.group_by)
    }
    value_columns = {
        column: allocate_pivot_alias(
            f"__r2x_pivot_value_{index}",
            occupied_names=occupied_names,
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
