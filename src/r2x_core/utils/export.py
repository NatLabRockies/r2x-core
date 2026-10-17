"""Component record export and CSV serialization."""

from __future__ import annotations

import csv
import os
from collections.abc import Callable, Iterator
from itertools import chain
from pathlib import Path
from typing import Any
from uuid import uuid4

from infrasys import Component
from loguru import logger


def components_to_records(
    system: Any,
    *,
    filter_func: Callable[[Component], bool] | None = None,
    fields: list[str] | None = None,
    key_mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Convert system components to a list of dictionaries (records).

    Parameters
    ----------
    system : System
        The system to extract components from.
    filter_func : Callable, optional
        Function to filter components. Should accept a component and return bool.
    fields : list, optional
        List of field names to include. If None, includes all fields.
    key_mapping : dict, optional
        Dictionary mapping component field names to record keys.

    Returns
    -------
    list[dict[str, Any]]
        List of component records as dictionaries.
    """
    return list(
        iter_component_records(system, filter_func=filter_func, fields=fields, key_mapping=key_mapping)
    )


def iter_component_records(
    system: Any,
    *,
    filter_func: Callable[[Component], bool] | None = None,
    fields: list[str] | None = None,
    key_mapping: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield component records with filtering, field selection, and key mapping."""
    for component in system.get_components(Component, filter_func=filter_func):
        record = component.model_dump()
        if fields is not None:
            record = {k: v for k, v in record.items() if k in fields}
        if key_mapping is not None:
            record = {key_mapping.get(k, k): v for k, v in record.items()}
        yield record


def export_components_to_csv(
    system: Any,
    *,
    file_path: Path | str,
    filter_func: Callable[[Component], bool] | None = None,
    fields: list[str] | None = None,
    key_mapping: dict[str, str] | None = None,
    **dict_writer_kwargs: Any,
) -> None:
    """Export all components or filtered components to a CSV file.

    Parameters
    ----------
    system : System
        The system to export components from.
    file_path : Path | str
        Output CSV file path.
    filter_func : Callable, optional
        Function to filter components by. Exports all if None.
    fields : list, optional
        List of field names to include. Exports all if None.
    key_mapping : dict, optional
        Mapping of component field names to CSV column names.
    **dict_writer_kwargs
        Additional arguments passed to csv.DictWriter.
    """
    records = iter_component_records(system, filter_func=filter_func, fields=fields, key_mapping=key_mapping)

    first_record = next(records, None)
    if first_record is None:
        logger.warning("No components to export")
        return

    fpath = Path(file_path).resolve()
    fpath.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(first_record.keys())

    destination_mode = fpath.stat().st_mode if fpath.exists() else 0o666
    candidate_path = fpath.with_name(f".r2x-export-{uuid4().hex}.tmp")
    temporary_path: Path | None = None
    try:
        with open(
            candidate_path,
            "x",
            newline="",
            opener=lambda path, flags: os.open(path, flags, mode=destination_mode),
        ) as f:
            temporary_path = candidate_path
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", **dict_writer_kwargs)
            writer.writeheader()
            count = 0
            for record in chain((first_record,), records):
                writer.writerow(record)
                count += 1
        if fpath.exists():
            temporary_path.chmod(fpath.stat().st_mode)
        temporary_path.replace(fpath)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    logger.info("Exported {} components to {}", count, fpath)
