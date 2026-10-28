"""Build a System from named inputs and three configured output instructions."""

from __future__ import annotations

import importlib
import itertools
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import TypeAlias, TypeVar

import numpy as np
from infrasys import Component, SingleTimeSeries, SupplementalAttribute
from infrasys.exceptions import ISNotStored, ISOperationNotAllowed
from pydantic import TypeAdapter, ValidationError
from rust_ok import Err, Ok, Result, is_ok

from .file_reader import DecodedSource, DecodedSources, FileReader, SourceAvailability, TabularSource
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
from .table_mapping import TableMappingRecord, load_table_mapping
from .tabular_backend import StepHandlers, TableMappingBackend
from .types import JSONValue
from .units import ureg

ModelT = TypeVar("ModelT", Component, SupplementalAttribute)
ResultValueT = TypeVar("ResultValueT")
ResultErrorT = TypeVar("ResultErrorT", bound=Exception)
Record: TypeAlias = Mapping[str, object]
MetadataScalar: TypeAlias = str | bool | int | float
OwnerKey: TypeAlias = tuple[tuple[type[Component], str], ...]
PartitionKey: TypeAlias = tuple[
    OwnerKey,
    tuple[tuple[str, type[MetadataScalar], MetadataScalar], ...],
]


def result_value_or_raise(result: Result[ResultValueT, ResultErrorT], /) -> ResultValueT:
    """Return a successful value or raise its error at a public API boundary."""
    if is_ok(result):
        return result.value
    raise result.err()


def build_system(
    config: PluginConfig,
    /,
    *,
    name: str,
    input_folder: Path | None = None,
    readers: Mapping[str, FileReader] | None = None,
    step_handlers: StepHandlers | None = None,
    table_mapping_path: Path | None = None,
    table_mapping_backend: TableMappingBackend | None = None,
    placeholders: Mapping[str, JSONValue] | None = None,
    system_options: Mapping[str, object] | None = None,
) -> System:
    """Read inputs, optionally assemble named tables, and construct one System.

    ``table_mapping_path`` explicitly opts this ingestion call into named-table
    assembly. It is separate from exporter configuration loading.
    """
    if table_mapping_backend is not None and table_mapping_path is None:
        msg = "table_mapping_backend requires table_mapping_path"
        raise ValueError(msg)
    store = DataStore(path=input_folder)
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
    reader = DataReader(file_readers=readers, step_handlers=step_handlers)
    table_mapping_inputs: tuple[list[TableMappingRecord], TableMappingBackend] | None = None
    if table_mapping_path is not None:
        table_records = result_value_or_raise(load_table_mapping(table_mapping_path))
        if table_mapping_backend is None:
            from .polars_adapter import PolarsTabularBackend

            mapping_backend: TableMappingBackend = PolarsTabularBackend()
        else:
            mapping_backend = table_mapping_backend
        table_mapping_inputs = (table_records, mapping_backend)

    def read_sources() -> DecodedSources:
        """Read the configured one-phase or cross-boundary source graph."""
        if table_mapping_inputs is None:
            return reader.read_data_files(
                store.data_files.values(), folder_path=store.folder, placeholders=placeholders
            )
        table_records, mapping_backend = table_mapping_inputs
        return reader.read_and_assemble_records(
            store.data_files.values(),
            table_records,
            folder_path=store.folder,
            backend=mapping_backend,
            placeholders=placeholders,
        )

    try:
        sources = read_sources()
    except FileNotFoundError:
        if not store.upgrade_coordinator.can_run:
            raise
        store.upgrade_coordinator.run(store=store, reason="missing input during system construction")
        sources = read_sources()
    return build_system_from_sources(
        sources,
        config=config,
        instructions=instructions,
        name=name,
        system_options=system_options,
    )


def build_system_from_sources(
    sources: DecodedSources,
    /,
    *,
    config: PluginConfig,
    instructions: Sequence[ParserInstruction],
    name: str,
    system_options: Mapping[str, object] | None = None,
) -> System:
    """Construct one System from already decoded sources and typed instructions.

    This operation performs no configuration or input-file I/O. It resolves
    model classes through ``config.models`` and applies instructions in order.
    Missing source fields, invalid models, references, metadata, or time axes
    raise their original validation errors. Outputs attached before a later
    failure are not rolled back.
    """
    system = System(name=name, **dict(system_options or {}))
    identities: set[tuple[type[Component], str]] = set()
    for instruction in instructions:
        source = sources.get(instruction.source)
        if source is None:
            msg = f"Output source {instruction.source!r} is not available"
            raise ValueError(msg)
        if isinstance(source, TabularSource) and source.availability is SourceAvailability.ABSENT:
            msg = f"Output source {instruction.source!r} is absent"
            raise ValueError(msg)
        if isinstance(instruction, ComponentInstruction):
            component_type = result_value_or_raise(
                resolve_model_type(instruction.component_type, config=config, expected=Component)
            )
            result_value_or_raise(
                build_components(
                    system,
                    instruction,
                    source=source,
                    component_type=component_type,
                    identities=identities,
                    config=config,
                )
            )
        elif isinstance(instruction, SupplementalAttributeInstruction):
            attribute_type = result_value_or_raise(
                resolve_model_type(instruction.attribute_type, config=config, expected=SupplementalAttribute)
            )
            result_value_or_raise(
                build_supplemental_attributes(
                    system, instruction, source=source, attribute_type=attribute_type, config=config
                )
            )
        else:
            result_value_or_raise(attach_time_series(system, instruction, source=source, config=config))
    return system


def resolve_model_type(
    type_name: str,
    *,
    config: PluginConfig,
    expected: type[ModelT],
) -> Result[type[ModelT], ValueError]:
    """Resolve one registered application model by name."""
    for module_name in config.models:
        candidate = getattr(importlib.import_module(module_name), type_name, None)
        if isinstance(candidate, type) and issubclass(candidate, expected):
            return Ok(candidate)
    msg = f"Model type {type_name!r} is not a {expected.__name__} in {config.models}"
    return Err(ValueError(msg))


def build_components(
    system: System,
    instruction: ComponentInstruction,
    *,
    source: DecodedSource,
    component_type: type[Component],
    identities: set[tuple[type[Component], str]],
    config: PluginConfig,
) -> Result[None, ValueError]:
    """Validate and attach components in source order."""
    fields_result = require_fields(
        source, [*instruction.fields.values(), *(r.name_field for r in instruction.references.values())]
    )
    if not is_ok(fields_result):
        return Err(fields_result.err())

    mapped_fields = instruction.fields.keys() | instruction.references.keys()
    unknown = mapped_fields - component_type.model_fields.keys()
    if unknown:
        msg = f"Unknown fields for {component_type.__name__}: {sorted(unknown)}"
        return Err(ValueError(msg))

    for row in source.iter_rows():
        values = {
            field: row[field]
            for field in component_type.model_fields
            if field in row and field not in instruction.references
        }
        for target, column in instruction.fields.items():
            value_result = required_value(row, column)
            if not is_ok(value_result):
                return Err(value_result.err())
            values[target] = value_result.value
        for field, reference in instruction.references.items():
            reference_type_result = resolve_model_type(
                reference.component_type, config=config, expected=Component
            )
            if not is_ok(reference_type_result):
                return Err(reference_type_result.err())
            name_result = source_name(row, reference.name_field)
            if not is_ok(name_result):
                return Err(name_result.err())
            component_result = get_component(
                system, reference_type_result.value, name_result.value, label="reference"
            )
            if not is_ok(component_result):
                return Err(component_result.err())
            values[field] = component_result.value
        try:
            component = component_type.model_validate(values)
        except ValidationError as error:
            return Err(error)
        if not component.name:
            msg = f"Component {component_type.__name__} has an empty name"
            return Err(ValueError(msg))
        identity = (component_type, component.name)
        if identity in identities:
            msg = f"Duplicate component {component_type.__name__} named {component.name!r}"
            return Err(ValueError(msg))
        system.add_component(component)
        identities.add(identity)
    return Ok(None)


def build_supplemental_attributes(
    system: System,
    instruction: SupplementalAttributeInstruction,
    *,
    source: DecodedSource,
    attribute_type: type[SupplementalAttribute],
    config: PluginConfig,
) -> Result[None, ValueError]:
    """Construct and attach each validated supplemental attribute."""
    fields_result = require_fields(
        source,
        [
            *instruction.fields.values(),
            *(owner.name_field for owner in instruction.owners if owner.name_field),
        ],
    )
    if not is_ok(fields_result):
        return Err(fields_result.err())
    unknown = instruction.fields.keys() - attribute_type.model_fields.keys()
    if unknown:
        msg = f"Unknown fields for {attribute_type.__name__}: {sorted(unknown)}"
        return Err(ValueError(msg))
    owner_types: dict[str, type[Component]] = {}
    owner_cache: dict[tuple[type[Component], str], Component] = {}
    for row in source.iter_rows():
        values: dict[str, object] = {}
        for target, column in instruction.fields.items():
            value_result = required_value(row, column)
            if not is_ok(value_result):
                return Err(value_result.err())
            values[target] = value_result.value
        try:
            attribute = attribute_type.model_validate(values)
        except ValidationError as error:
            return Err(error)
        owners_result = resolve_owners(
            system,
            instruction.owners,
            config=config,
            rows=(row,),
            owner_types=owner_types,
            owner_cache=owner_cache,
        )
        if not is_ok(owners_result):
            return Err(owners_result.err())
        for owner in owners_result.value:
            system.add_supplemental_attribute(owner, attribute)
    return Ok(None)


def attach_time_series(
    system: System,
    instruction: TimeSeriesInstruction,
    *,
    source: DecodedSource,
    config: PluginConfig,
) -> Result[None, ValueError | TypeError]:
    """Attach regular samples partitioned by owner and row-derived metadata."""
    fields = [instruction.values, *instruction.metadata_columns.values()]
    if isinstance(instruction.time_axis, ColumnTimeAxis):
        fields.append(instruction.time_axis.column)
    fields.extend(owner.name_field for owner in instruction.owners if owner.name_field)
    fields_result = require_fields(source, fields)
    if not is_ok(fields_result):
        return Err(fields_result.err())
    owner_types: dict[str, type[Component]] = {}
    owner_cache: dict[tuple[type[Component], str], Component] = {}
    if any(owner.name_field for owner in instruction.owners) or instruction.metadata_columns:
        groups: dict[PartitionKey, tuple[list[Component], list[Record], dict[str, MetadataScalar]]] = {}
        for row in source.iter_rows():
            owners_result = resolve_owners(
                system,
                instruction.owners,
                config=config,
                rows=(row,),
                owner_types=owner_types,
                owner_cache=owner_cache,
            )
            if not is_ok(owners_result):
                return Err(owners_result.err())
            owners = owners_result.value
            owner_key = tuple((type(owner), owner.name) for owner in owners)
            row_metadata: dict[str, MetadataScalar] = {}
            for feature, field in instruction.metadata_columns.items():
                value_result = required_value(row, field)
                if not is_ok(value_result):
                    return Err(value_result.err())
                scalar_result = metadata_scalar(value_result.value, feature=feature)
                if not is_ok(scalar_result):
                    return Err(scalar_result.err())
                row_metadata[feature] = scalar_result.value
            metadata_key = tuple((feature, type(value), value) for feature, value in row_metadata.items())
            key = owner_key, metadata_key
            if key not in groups:
                groups[key] = owners, [], row_metadata
            groups[key][1].append(row)
        if not groups:
            if instruction.skip_if_empty:
                return Ok(None)
            msg = "Time-series source has no samples"
            return Err(ValueError(msg))
        for owners, rows, row_metadata in groups.values():
            values: list[object] = []
            axis_values: list[object] | None = (
                [] if isinstance(instruction.time_axis, ColumnTimeAxis) else None
            )
            for row in rows:
                value_result = required_value(row, instruction.values)
                if not is_ok(value_result):
                    return Err(value_result.err())
                values.append(value_result.value)
                if isinstance(instruction.time_axis, ColumnTimeAxis) and axis_values is not None:
                    axis_result = required_value(row, instruction.time_axis.column)
                    if not is_ok(axis_result):
                        return Err(axis_result.err())
                    axis_values.append(axis_result.value)
            series_result = attach_series(
                system,
                instruction,
                owners,
                values,
                axis_values,
                metadata=instruction.metadata | row_metadata,
            )
            if not is_ok(series_result):
                return Err(series_result.err())
        return Ok(None)

    if instruction.skip_if_empty and source.is_empty():
        return Ok(None)
    owners_result = resolve_owners(
        system,
        instruction.owners,
        config=config,
        rows=(),
        owner_types=owner_types,
        owner_cache=owner_cache,
    )
    if not is_ok(owners_result):
        return Err(owners_result.err())
    try:
        values = source.values(instruction.values)
        axis_values = (
            source.values(instruction.time_axis.column)
            if isinstance(instruction.time_axis, ColumnTimeAxis)
            else None
        )
    except ValueError as error:
        return Err(error)
    return attach_series(
        system, instruction, owners_result.value, values, axis_values, metadata=instruction.metadata
    )


def metadata_scalar(value: object, *, feature: str) -> Result[MetadataScalar, ValueError]:
    """Validate a row-derived infrasys feature as a finite JSON scalar."""
    if type(value) is str:
        return Ok(value)
    if type(value) is bool:
        return Ok(value)
    if type(value) is int:
        return Ok(value)
    if type(value) is float and isfinite(value):
        return Ok(value)
    msg = f"Time-series metadata column for {feature!r} must contain a non-null finite JSON scalar"
    return Err(ValueError(msg))


def attach_series(
    system: System,
    instruction: TimeSeriesInstruction,
    owners: Sequence[Component],
    values: Sequence[object],
    axis_values: Sequence[object] | None,
    *,
    metadata: Mapping[str, JSONValue],
) -> Result[None, ValueError | TypeError]:
    """Validate samples and axis, then attach one series to the selected owners."""
    if not values:
        msg = "Time-series values cannot be empty"
        return Err(ValueError(msg))
    axis_result = resolve_time_axis(instruction.time_axis, axis_values, len(values))
    if not is_ok(axis_result):
        return Err(axis_result.err())
    initial, resolution = axis_result.value
    samples = np.asarray(values)
    data = ureg.Quantity(samples, instruction.units) if instruction.units is not None else samples
    series = SingleTimeSeries.from_array(
        data=data,
        name=instruction.name,
        initial_timestamp=initial,
        resolution=resolution,
    )
    system.add_time_series(series, *owners, context=None, **metadata)
    return Ok(None)


def resolve_owners(
    system: System,
    declarations: Sequence[ComponentOwner],
    *,
    config: PluginConfig,
    rows: Iterable[Record],
    owner_types: dict[str, type[Component]] | None = None,
    owner_cache: dict[tuple[type[Component], str], Component] | None = None,
) -> Result[list[Component], ValueError]:
    """Resolve selected owners through the public type-and-name lookup."""
    records = tuple(rows)
    owners: list[Component] = []
    seen: set[tuple[type[Component], str]] = set()
    for declaration in declarations:
        component_type = owner_types.get(declaration.component_type) if owner_types is not None else None
        if component_type is None:
            type_result = resolve_model_type(declaration.component_type, config=config, expected=Component)
            if not is_ok(type_result):
                return Err(type_result.err())
            component_type = type_result.value
            if owner_types is not None:
                owner_types[declaration.component_type] = component_type
        if declaration.name is not None:
            names = [declaration.name]
        elif declaration.names is not None:
            names = declaration.names
        elif declaration.name_field is not None:
            names = []
            for row in records:
                name_result = source_name(row, declaration.name_field)
                if not is_ok(name_result):
                    return Err(name_result.err())
                names.append(name_result.value)
        else:
            msg = "Owner has no name selection"
            return Err(ValueError(msg))
        for name in names:
            identity = (component_type, name)
            if identity not in seen:
                owner = owner_cache.get(identity) if owner_cache is not None else None
                if owner is None:
                    owner_result = get_component(system, component_type, name, label="owner")
                    if not is_ok(owner_result):
                        return Err(owner_result.err())
                    owner = owner_result.value
                    if owner_cache is not None:
                        owner_cache[identity] = owner
                owners.append(owner)
                seen.add(identity)
    if not owners:
        msg = "An output instruction resolved no component owners"
        return Err(ValueError(msg))
    return Ok(owners)


def get_component(
    system: System, component_type: type[Component], name: str, *, label: str
) -> Result[Component, ValueError]:
    """Use the public lookup and report missing or ambiguous type/name pairs."""
    try:
        return Ok(system.get_component(component_type, name))
    except ISNotStored as error:
        msg = f"Missing {label} {component_type.__name__} named {name!r}"
        wrapped = ValueError(msg)
        wrapped.__cause__ = error
        return Err(wrapped)
    except ISOperationNotAllowed as error:
        msg = f"Ambiguous {label} {component_type.__name__} named {name!r}"
        wrapped = ValueError(msg)
        wrapped.__cause__ = error
        return Err(wrapped)


def resolve_time_axis(
    axis: RegularTimeAxis | ColumnTimeAxis,
    timestamps: Sequence[object] | None,
    sample_count: int,
) -> Result[tuple[datetime, timedelta], ValueError | TypeError]:
    """Validate a configured regular or explicit-column time axis."""
    if isinstance(axis, RegularTimeAxis):
        return Ok((axis.initial_timestamp, timedelta(seconds=axis.resolution_seconds)))
    if timestamps is None or len(timestamps) != sample_count:
        actual = 0 if timestamps is None else len(timestamps)
        msg = f"Time axis has {actual} values for {sample_count} samples"
        return Err(ValueError(msg))
    parsed: list[datetime] = []
    for value in timestamps:
        timestamp_result = parse_timestamp(value)
        if not is_ok(timestamp_result):
            return Err(timestamp_result.err())
        parsed.append(timestamp_result.value)
    timezone_awareness = {timestamp.utcoffset() is not None for timestamp in parsed}
    if len(timezone_awareness) > 1:
        return Err(ValueError("Time-axis values must have consistent timezone awareness"))
    deltas = [later - earlier for earlier, later in itertools.pairwise(parsed)]
    if any(delta <= timedelta(0) for delta in deltas):
        msg = "Time-axis values must be strictly increasing"
        return Err(ValueError(msg))
    if deltas and any(delta != deltas[0] for delta in deltas[1:]):
        msg = "SingleTimeSeries requires a regular time axis"
        return Err(ValueError(msg))
    resolution = timedelta(seconds=axis.resolution_seconds) if axis.resolution_seconds else None
    if deltas:
        if resolution is not None and resolution != deltas[0]:
            msg = "Configured time-axis resolution does not match timestamp values"
            return Err(ValueError(msg))
        resolution = deltas[0]
    if resolution is None:
        msg = "A one-sample time axis requires resolution_seconds"
        return Err(ValueError(msg))
    return Ok((parsed[0], resolution))


def parse_timestamp(value: object) -> Result[datetime, ValueError | TypeError]:
    """Parse a supported ISO timestamp value."""
    if isinstance(value, datetime):
        return Ok(value)
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return Err(ValueError("Invalid NumPy time-axis value NaT"))
        return Ok(value.astype("datetime64[us]").astype(datetime))
    if isinstance(value, str):
        try:
            return Ok(datetime.fromisoformat(value))
        except ValueError as error:
            msg = f"Invalid ISO time-axis value {value!r}"
            wrapped = ValueError(msg)
            wrapped.__cause__ = error
            return Err(wrapped)
    msg = f"Unsupported time-axis value {type(value).__name__}"
    return Err(TypeError(msg))


def require_fields(source: DecodedSource, required: Sequence[str]) -> Result[None, ValueError]:
    """Reject configured field names absent from a decoded source."""
    missing = sorted(set(required) - set(source.fields()))
    if missing:
        msg = f"Source has no field(s): {missing}"
        return Err(ValueError(msg))
    return Ok(None)


def required_value(row: Record, field: str) -> Result[object, ValueError]:
    """Read a required source field without conflating missing and null values."""
    if field not in row:
        msg = f"Source record has no field {field!r}"
        return Err(ValueError(msg))
    return Ok(row[field])


def source_name(row: Record, field: str) -> Result[str, ValueError]:
    """Read a non-empty component name from one source record."""
    value_result = required_value(row, field)
    if not is_ok(value_result):
        return Err(value_result.err())
    name = value_result.value
    if not isinstance(name, str) or not name:
        msg = f"Component name field {field!r} must contain a non-empty string"
        return Err(ValueError(msg))
    return Ok(name)
