"""Build a System from named inputs and three configured output instructions."""

from __future__ import annotations

import importlib
import itertools
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from math import isfinite
from typing import TypeAlias, TypeVar

import numpy as np
from infrasys import Component, SingleTimeSeries, SupplementalAttribute
from infrasys.exceptions import ISNotStored, ISOperationNotAllowed
from pydantic import TypeAdapter
from rust_ok import is_ok

from .file_reader import DecodedSource, DecodedSources, FileReader
from .models import (
    ColumnTimeAxis,
    ComponentInstruction,
    ComponentOwner,
    ParserInstruction,
    RegularTimeAxis,
    SupplementalAttributeInstruction,
    TimeSeriesInstruction,
)
from .plugin_config import PluginConfig
from .processors import substitute_placeholders
from .reader import DataReader
from .store import DataStore
from .system import System
from .types import JSONValue
from .units import ureg

ModelT = TypeVar("ModelT", Component, SupplementalAttribute)
Record: TypeAlias = Mapping[str, object]
MetadataScalar: TypeAlias = str | bool | int | float
OwnerKey: TypeAlias = tuple[tuple[type[Component], str], ...]
PartitionKey: TypeAlias = tuple[
    OwnerKey,
    tuple[tuple[str, type[MetadataScalar], MetadataScalar], ...],
]


def build_system(
    config: PluginConfig,
    /,
    *,
    name: str,
    readers: Mapping[str, FileReader] | None = None,
    placeholders: Mapping[str, JSONValue] | None = None,
) -> System:
    """Read configured inputs and construct one System without application loops."""
    store = DataStore(config.config_path)
    store.configure_upgrades(plugin_config=config)
    store.load_file_mapping(config.fmap_path)
    raw_instructions: JSONValue = TypeAdapter(JSONValue).validate_python(
        json.loads(config.parser_rules_path.read_bytes())
    )
    substituted = substitute_placeholders(raw_instructions, placeholders=placeholders)
    if is_ok(substituted):
        instructions = TypeAdapter(list[ParserInstruction]).validate_python(substituted.value)
    else:
        raise substituted.err()
    reader = DataReader(file_readers=readers)
    try:
        sources = reader.read_data_files(
            store.data_files.values(), folder_path=store.folder, placeholders=placeholders
        )
    except FileNotFoundError:
        if not store.upgrade_coordinator.can_run:
            raise
        store.upgrade_coordinator.run(store=store, reason="missing input during system construction")
        sources = reader.read_data_files(
            store.data_files.values(), folder_path=store.folder, placeholders=placeholders
        )
    return build_system_from_sources(
        sources,
        config=config,
        instructions=instructions,
        name=name,
    )


def build_system_from_sources(
    sources: DecodedSources,
    /,
    *,
    config: PluginConfig,
    instructions: Sequence[ParserInstruction],
    name: str,
) -> System:
    """Construct one System from already decoded sources and typed instructions.

    This operation performs no configuration or input-file I/O. It resolves
    model classes through ``config.models`` and applies instructions in order.
    Missing source fields, invalid models, references, metadata, or time axes
    raise their original validation errors. Outputs attached before a later
    failure are not rolled back.
    """
    system = System(name=name)
    identities: set[tuple[type[Component], str]] = set()
    for instruction in instructions:
        source = sources.get(instruction.source)
        if source is None:
            msg = f"Output source {instruction.source!r} is not available"
            raise ValueError(msg)
        if isinstance(instruction, ComponentInstruction):
            component_type = resolve_model_type(instruction.component_type, config=config, expected=Component)
            build_components(
                system,
                instruction,
                source=source,
                component_type=component_type,
                identities=identities,
                config=config,
            )
        elif isinstance(instruction, SupplementalAttributeInstruction):
            attribute_type = resolve_model_type(
                instruction.attribute_type, config=config, expected=SupplementalAttribute
            )
            build_supplemental_attributes(
                system, instruction, source=source, attribute_type=attribute_type, config=config
            )
        else:
            attach_time_series(system, instruction, source=source, config=config)
    return system


def resolve_model_type(
    type_name: str,
    *,
    config: PluginConfig,
    expected: type[ModelT],
) -> type[ModelT]:
    """Resolve one registered application model by name."""
    for module_name in config.models:
        candidate = getattr(importlib.import_module(module_name), type_name, None)
        if isinstance(candidate, type) and issubclass(candidate, expected):
            return candidate
    msg = f"Model type {type_name!r} is not a {expected.__name__} in {config.models}"
    raise ValueError(msg)


def build_components(
    system: System,
    instruction: ComponentInstruction,
    *,
    source: DecodedSource,
    component_type: type[Component],
    identities: set[tuple[type[Component], str]],
    config: PluginConfig,
) -> None:
    """Validate and attach components in source order."""
    require_fields(
        source, [*instruction.fields.values(), *(r.name_field for r in instruction.references.values())]
    )
    mapped_fields = instruction.fields.keys() | instruction.references.keys()
    unknown = mapped_fields - component_type.model_fields.keys()
    if unknown:
        msg = f"Unknown fields for {component_type.__name__}: {sorted(unknown)}"
        raise ValueError(msg)

    for row in source.iter_rows():
        values = {
            field: row[field]
            for field in component_type.model_fields
            if field in row and field not in instruction.references
        }
        values.update({target: required_value(row, column) for target, column in instruction.fields.items()})
        for field, reference in instruction.references.items():
            reference_type = resolve_model_type(reference.component_type, config=config, expected=Component)
            name = source_name(row, reference.name_field)
            values[field] = get_component(system, reference_type, name, label="reference")
        component = component_type.model_validate(values)
        if not component.name:
            msg = f"Component {component_type.__name__} has an empty name"
            raise ValueError(msg)
        identity = (component_type, component.name)
        if identity in identities:
            msg = f"Duplicate component {component_type.__name__} named {component.name!r}"
            raise ValueError(msg)
        system.add_component(component)
        identities.add(identity)


def build_supplemental_attributes(
    system: System,
    instruction: SupplementalAttributeInstruction,
    *,
    source: DecodedSource,
    attribute_type: type[SupplementalAttribute],
    config: PluginConfig,
) -> None:
    """Construct and attach each validated supplemental attribute."""
    require_fields(
        source,
        [
            *instruction.fields.values(),
            *(owner.name_field for owner in instruction.owners if owner.name_field),
        ],
    )
    unknown = instruction.fields.keys() - attribute_type.model_fields.keys()
    if unknown:
        msg = f"Unknown fields for {attribute_type.__name__}: {sorted(unknown)}"
        raise ValueError(msg)
    for row in source.iter_rows():
        attribute = attribute_type.model_validate(
            {target: required_value(row, column) for target, column in instruction.fields.items()}
        )
        owners = resolve_owners(system, instruction.owners, config=config, rows=(row,))
        for owner in owners:
            system.add_supplemental_attribute(owner, attribute)


def attach_time_series(
    system: System,
    instruction: TimeSeriesInstruction,
    *,
    source: DecodedSource,
    config: PluginConfig,
) -> None:
    """Attach regular samples partitioned by owner and row-derived metadata."""
    fields = [instruction.values, *instruction.metadata_columns.values()]
    if isinstance(instruction.time_axis, ColumnTimeAxis):
        fields.append(instruction.time_axis.column)
    fields.extend(owner.name_field for owner in instruction.owners if owner.name_field)
    require_fields(source, fields)
    if instruction.skip_if_empty and source.is_empty():
        return

    if any(owner.name_field for owner in instruction.owners) or instruction.metadata_columns:
        groups: dict[PartitionKey, tuple[list[Component], list[Record], dict[str, MetadataScalar]]] = {}
        for row in source.iter_rows():
            owners = resolve_owners(system, instruction.owners, config=config, rows=(row,))
            owner_key = tuple((type(owner), owner.name) for owner in owners)
            row_metadata = {
                feature: metadata_scalar(required_value(row, field), feature=feature)
                for feature, field in instruction.metadata_columns.items()
            }
            metadata_key = tuple((feature, type(value), value) for feature, value in row_metadata.items())
            key = owner_key, metadata_key
            if key not in groups:
                groups[key] = owners, [], row_metadata
            groups[key][1].append(row)
        if not groups:
            msg = "Time-series source has no samples"
            raise ValueError(msg)
        for owners, rows, row_metadata in groups.values():
            values = [required_value(row, instruction.values) for row in rows]
            axis_values = (
                [required_value(row, instruction.time_axis.column) for row in rows]
                if isinstance(instruction.time_axis, ColumnTimeAxis)
                else None
            )
            attach_series(
                system,
                instruction,
                owners,
                values,
                axis_values,
                metadata=instruction.metadata | row_metadata,
            )
        return

    owners = resolve_owners(system, instruction.owners, config=config, rows=())
    values = source.values(instruction.values)
    axis_values = (
        source.values(instruction.time_axis.column)
        if isinstance(instruction.time_axis, ColumnTimeAxis)
        else None
    )
    attach_series(system, instruction, owners, values, axis_values, metadata=instruction.metadata)


def metadata_scalar(value: object, *, feature: str) -> MetadataScalar:
    """Validate a row-derived infrasys feature as a finite JSON scalar."""
    if type(value) is str:
        return value
    if type(value) is bool:
        return value
    if type(value) is int:
        return value
    if type(value) is float and isfinite(value):
        return value
    msg = f"Time-series metadata column for {feature!r} must contain a non-null finite JSON scalar"
    raise ValueError(msg)


def attach_series(
    system: System,
    instruction: TimeSeriesInstruction,
    owners: Sequence[Component],
    values: Sequence[object],
    axis_values: Sequence[object] | None,
    *,
    metadata: Mapping[str, JSONValue],
) -> None:
    """Validate samples and axis, then attach one series to the selected owners."""
    if not values:
        msg = "Time-series values cannot be empty"
        raise ValueError(msg)
    initial, resolution = resolve_time_axis(instruction.time_axis, axis_values, len(values))
    samples = np.asarray(values)
    data = ureg.Quantity(samples, instruction.units) if instruction.units is not None else samples
    series = SingleTimeSeries.from_array(
        data=data,
        name=instruction.name,
        initial_timestamp=initial,
        resolution=resolution,
    )
    system.add_time_series(series, *owners, context=None, **metadata)


def resolve_owners(
    system: System,
    declarations: Sequence[ComponentOwner],
    *,
    config: PluginConfig,
    rows: Iterable[Record],
) -> list[Component]:
    """Resolve selected owners through the public type-and-name lookup."""
    records = tuple(rows)
    owners: list[Component] = []
    seen: set[tuple[type[Component], str]] = set()
    for declaration in declarations:
        component_type = resolve_model_type(declaration.component_type, config=config, expected=Component)
        if declaration.name is not None:
            names = [declaration.name]
        elif declaration.names is not None:
            names = declaration.names
        elif declaration.name_field is not None:
            names = [source_name(row, declaration.name_field) for row in records]
        else:
            msg = "Owner has no name selection"
            raise ValueError(msg)
        for name in names:
            identity = (component_type, name)
            if identity not in seen:
                owners.append(get_component(system, component_type, name, label="owner"))
                seen.add(identity)
    if not owners:
        msg = "An output instruction resolved no component owners"
        raise ValueError(msg)
    return owners


def get_component(system: System, component_type: type[Component], name: str, *, label: str) -> Component:
    """Use the public lookup and report missing or ambiguous type/name pairs."""
    try:
        return system.get_component(component_type, name)
    except ISNotStored as error:
        msg = f"Missing {label} {component_type.__name__} named {name!r}"
        raise ValueError(msg) from error
    except ISOperationNotAllowed as error:
        msg = f"Ambiguous {label} {component_type.__name__} named {name!r}"
        raise ValueError(msg) from error


def resolve_time_axis(
    axis: RegularTimeAxis | ColumnTimeAxis,
    timestamps: Sequence[object] | None,
    sample_count: int,
) -> tuple[datetime, timedelta]:
    """Validate a configured regular or explicit-column time axis."""
    if isinstance(axis, RegularTimeAxis):
        return axis.initial_timestamp, timedelta(seconds=axis.resolution_seconds)
    if timestamps is None or len(timestamps) != sample_count:
        actual = 0 if timestamps is None else len(timestamps)
        msg = f"Time axis has {actual} values for {sample_count} samples"
        raise ValueError(msg)
    parsed = [parse_timestamp(value) for value in timestamps]
    deltas = [later - earlier for earlier, later in itertools.pairwise(parsed)]
    if any(delta <= timedelta(0) for delta in deltas):
        msg = "Time-axis values must be strictly increasing"
        raise ValueError(msg)
    if deltas and any(delta != deltas[0] for delta in deltas[1:]):
        msg = "SingleTimeSeries requires a regular time axis"
        raise ValueError(msg)
    resolution = timedelta(seconds=axis.resolution_seconds) if axis.resolution_seconds else None
    if deltas:
        if resolution is not None and resolution != deltas[0]:
            msg = "Configured time-axis resolution does not match timestamp values"
            raise ValueError(msg)
        resolution = deltas[0]
    if resolution is None:
        msg = "A one-sample time axis requires resolution_seconds"
        raise ValueError(msg)
    return parsed[0], resolution


def parse_timestamp(value: object) -> datetime:
    """Parse a supported ISO timestamp value."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, np.datetime64):
        return value.astype("datetime64[us]").astype(datetime)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as error:
            msg = f"Invalid ISO time-axis value {value!r}"
            raise ValueError(msg) from error
    msg = f"Unsupported time-axis value {type(value).__name__}"
    raise TypeError(msg)


def require_fields(source: DecodedSource, required: Sequence[str]) -> None:
    """Reject configured field names absent from a decoded source."""
    missing = sorted(set(required) - set(source.fields()))
    if missing:
        msg = f"Source has no field(s): {missing}"
        raise ValueError(msg)


def required_value(row: Record, field: str) -> object:
    """Read a required source field without conflating missing and null values."""
    if field not in row:
        msg = f"Source record has no field {field!r}"
        raise ValueError(msg)
    return row[field]


def source_name(row: Record, field: str) -> str:
    """Read a non-empty component name from one source record."""
    name = required_value(row, field)
    if not isinstance(name, str) or not name:
        msg = f"Component name field {field!r} must contain a non-empty string"
        raise ValueError(msg)
    return name
