"""Relational expansion of grouped values over an explicit keyed grid."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl
from rust_ok import Err, Ok, Result


def expand_keyed_grid(
    values: pl.DataFrame,
    grid: pl.DataFrame,
    /,
    *,
    group_columns: Sequence[str],
    value_keys: Sequence[str],
    grid_keys: Sequence[str],
    order_columns: Sequence[str],
    value_columns: Sequence[str],
    fill_values: Mapping[str, bool | int | float | str | None],
    round_digits: int | None = None,
) -> Result[pl.DataFrame, ValueError]:
    """Expand each group to every grid row and fill absent keyed values."""
    groups = tuple(group_columns)
    source_keys = tuple(value_keys)
    target_keys = tuple(grid_keys)
    order = tuple(order_columns)
    outputs = tuple(value_columns)
    if not groups or not source_keys or len(source_keys) != len(target_keys) or not order or not outputs:
        return Err(ValueError("group, key, order, and value columns must be explicitly configured"))
    if len(set(groups)) != len(groups) or len(set(source_keys)) != len(source_keys):
        return Err(ValueError("group and value-key columns must be unique"))
    if len(set(target_keys)) != len(target_keys) or len(set(order)) != len(order):
        return Err(ValueError("grid-key and order columns must be unique"))
    if len(set(outputs)) != len(outputs) or set(fill_values) - set(outputs):
        return Err(ValueError("value columns must be unique and every fill must target a value column"))
    if round_digits is not None and round_digits < 0:
        return Err(ValueError("round_digits must be non-negative"))

    required_values = set(groups) | set(source_keys) | set(outputs)
    required_grid = set(target_keys) | set(order)
    missing_values = sorted(required_values - set(values.columns))
    missing_grid = sorted(required_grid - set(grid.columns))
    if missing_values or missing_grid:
        return Err(ValueError(f"Missing grid input columns: values={missing_values}, grid={missing_grid}"))

    data_key_columns = [*groups, *source_keys]
    if values.select(data_key_columns).is_duplicated().any():
        return Err(ValueError(f"values contain duplicate group keys {data_key_columns}"))
    if grid.select(list(order)).is_duplicated().any():
        return Err(ValueError(f"grid contains duplicate order keys {list(order)}"))

    try:
        group_values = values.select(list(groups)).unique(maintain_order=True)
        full_grid = group_values.join(grid.select([*target_keys, *order]), how="cross")
        key_mapping = dict(zip(target_keys, source_keys, strict=True))
        if key_mapping:
            full_grid = full_grid.rename(key_mapping)
        expanded = full_grid.join(
            values.select([*data_key_columns, *outputs]),
            on=data_key_columns,
            how="left",
            maintain_order="left",
        )
        if fill_values:
            expanded = expanded.with_columns(
                pl.col(column).fill_null(value) for column, value in fill_values.items()
            )
        if round_digits is not None:
            expanded = expanded.with_columns(pl.col(column).round(round_digits) for column in outputs)
        return Ok(expanded.sort([*groups, *order], maintain_order=True).select([*groups, *order, *outputs]))
    except (ValueError, pl.exceptions.PolarsError) as error:
        return Err(ValueError(f"Could not expand values over the configured grid: {error}"))
