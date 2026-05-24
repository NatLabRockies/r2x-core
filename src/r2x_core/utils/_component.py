"""Helper functions for extracting data from the system."""

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

    This method retrieves components from the system and converts them to
    dictionary records, with optional filtering, field selection, and key mapping.

    Parameters
    ----------
    system : System
        The system to extract components from.
    filter_func : Callable, optional
        Function to filter components. Should accept a component and return bool.
        If None, converts all components in the system.
    fields : list, optional
        List of field names to include. If None, includes all fields.
    key_mapping : dict, optional
        Dictionary mapping component field names to record keys.

    Returns
    -------
    list[dict[str, Any]]
        List of component records as dictionaries.

    Examples
    --------
    Get all components as records:

    >>> records = system.components_to_records()

    Get only generators:

    >>> from my_components import Generator
    >>> records = system.components_to_records(
    ...     filter_func=lambda c: isinstance(c, Generator)
    ... )

    Get specific fields with renamed keys:

    >>> records = system.components_to_records(
    ...     fields=["name", "voltage"],
    ...     key_mapping={"voltage": "voltage_kv"}
    ... )

    See Also
    --------
    export_components_to_csv : Export components to CSV file
    get_components : Retrieve components by type with filtering
    """

    # Use a generator to avoid holding all component dicts in memory
    # simultaneously. Filter and key mapping are applied per-component
    # as we iterate.
    def _iter_records():
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
    """Export all components or filtered components to CSV file.

    This method exports components from the system to a CSV file. You can
    optionally provide a filter function to select specific components.

    Parameters
    ----------
    system : System
        The system to export components from
    file_path : PathLike
        Output CSV file path.
    filter_func : Callable, optional
        Function to filter components. Should accept a component and return bool.
        If None, exports all components in the system.
    fields : list, optional
        List of field names to include. If None, exports all fields.
    key_mapping : dict, optional
        Dictionary mapping component field names to CSV column names.
    **dict_writer_kwargs
        Additional arguments passed to csv.DictWriter.

    Examples
    --------
    Export all components:

    >>> system.export_components_to_csv(system, file_path="all_components.csv")

    Export only generators using a filter:

    >>> from my_components import Generator
    >>> system.export_components_to_csv(
    ...     system,
    ...     file_path="generators.csv",
    ...     filter_func=lambda c: isinstance(c, Generator)
    ... )

    Export buses with custom filter:

    >>> from my_components import ACBus
    >>> system.export_components_to_csv(
    ...     system,
    ...     file_path="high_voltage_buses.csv",
    ...     filter_func=lambda c: isinstance(c, ACBus) and c.voltage > 100
    ... )

    Export with field selection and renaming:

    >>> system.export_components_to_csv(
    ...     system,
    ...     file_path="buses.csv",
    ...     filter_func=lambda c: isinstance(c, ACBus),
    ...     fields=["name", "voltage"],
    ...     key_mapping={"voltage": "voltage_kv"}
    ... )

    See Also
    --------
    components_to_records : Convert components to dictionary records
    get_components : Retrieve components by type with filtering
    """
    records = components_to_records(system, filter_func=filter_func, fields=fields, key_mapping=key_mapping)

    if not records:
        logger.warning("No components to export")
        return

    fpath = Path(file_path)
    fpath.parent.mkdir(parents=True, exist_ok=True)

    # Determine fieldnames from the first record, then stream the rest
    # via an iterator so csv.DictWriter never holds all records in memory.
    fieldnames = list(records[0].keys())

    with open(fpath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, **dict_writer_kwargs)
        writer.writeheader()
        writer.writerows(records)
    logger.info("Exported {} components to {}", len(records), fpath)
