"""Component record export and CSV serialization."""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path
from typing import Any

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

    # Use a generator to avoid holding all component dicts in memory
    # simultaneously. The result is still a list (public API contract),
    # but the generator prevents holding both the component objects AND
    # the serialized dicts in memory at the same time.
    def _iter_records():
        """Yield one record dict at a time with filtering and key mapping applied."""
        for component in system.get_components(Component, filter_func=filter_func):
            record = component.model_dump()
            if fields is not None:
                record = {k: v for k, v in record.items() if k in fields}
            if key_mapping is not None:
                record = {key_mapping.get(k, k): v for k, v in record.items()}
            yield record

    return list(_iter_records())


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
    records = components_to_records(system, filter_func=filter_func, fields=fields, key_mapping=key_mapping)

    if not records:
        logger.warning("No components to export")
        return

    fpath = Path(file_path)
    fpath.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(records[0].keys())

    with open(fpath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", **dict_writer_kwargs)
        writer.writeheader()
        writer.writerows(records)
    logger.info("Exported {} components to {}", len(records), fpath)
