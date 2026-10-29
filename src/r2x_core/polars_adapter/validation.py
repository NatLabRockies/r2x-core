"""Schema validation helpers for Polars operations."""

from __future__ import annotations

from ..datafile import DataFile


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
