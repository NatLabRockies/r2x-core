"""Typed calendar and System projections used by prepared-table sources."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Annotated, Literal

import polars as pl
from infrasys import Component, SingleTimeSeries
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from .plugin_config import PluginConfigAsset
from .plugin_context import PluginContext
from .processors import substitute_placeholders
from .utils.rules import resolve_component_type

SourceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CalendarYear = StrictInt | list[StrictInt] | Annotated[str, StringConstraints(pattern=r"^\{[^{}]+\}$")]


class CalendarSource(BaseModel):
    """Generate an ordered, year-bounded calendar table."""

    kind: Literal["calendar"] = "calendar"
    name: SourceName
    year: CalendarYear
    resolution_seconds: StrictInt = Field(gt=0)
    sample_limit: StrictInt | None = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_calendar(self) -> CalendarSource:
        """Require unique valid years and a resolution that divides one day."""
        if 86_400 % self.resolution_seconds:
            raise ValueError("CalendarSource.resolution_seconds must divide 86400")
        if isinstance(self.year, list):
            if not self.year:
                raise ValueError("CalendarSource.year cannot be an empty list")
            if len(set(self.year)) != len(self.year):
                raise ValueError("CalendarSource.year values must be unique")
            years = self.year
        elif isinstance(self.year, int):
            years = [self.year]
        else:
            years = []
        if any(year < 1 or year > 9999 for year in years):
            raise ValueError("CalendarSource.year values must be between 1 and 9999")
        return self

    def to_frame(self, *, placeholders: dict[str, object] | None = None) -> pl.DataFrame:
        """Materialize one row per sample with the configured calendar fields."""
        values = self.model_dump(mode="python")
        substituted = substitute_placeholders(values, placeholders=placeholders)
        if substituted.is_err():
            raise ValueError(f"Calendar source {self.name!r}: {substituted.err()}")
        resolved = CalendarSource.model_validate(substituted.unwrap())
        if not isinstance(resolved.year, int | list):
            raise ValueError(f"Calendar source {self.name!r} year placeholder did not resolve")
        years = resolved.year if isinstance(resolved.year, list) else [resolved.year]
        rows = []
        for year in years:
            start = datetime(year, 1, 1)
            days = 366 if calendar.isleap(year) else 365
            sample_count = days * 86_400 // resolved.resolution_seconds
            if resolved.sample_limit is not None:
                sample_count = min(sample_count, resolved.sample_limit)
            rows.extend(
                {
                    "year": year,
                    "hour_index": index,
                    "timestamp": start + timedelta(seconds=index * resolved.resolution_seconds),
                    "month": (start + timedelta(seconds=index * resolved.resolution_seconds)).month,
                }
                for index in range(sample_count)
            )
        return pl.DataFrame(
            rows,
            schema={
                "year": pl.Int32,
                "hour_index": pl.Int64,
                "timestamp": pl.Datetime("us"),
                "month": pl.Int8,
            },
            orient="row",
        )


class FirstPresentSource(BaseModel):
    """Select the first configured physical or runtime source that exists."""

    kind: Literal["first_present"] = "first_present"
    name: SourceName
    candidates: Annotated[list[SourceName], Field(min_length=1)]
    empty: Literal["select", "skip"] = "select"
    missing: Literal["none", "error"] = "error"

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_candidates(self) -> FirstPresentSource:
        """Require a non-empty ordered list of distinct candidates."""
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError("FirstPresentSource.candidates must be unique")
        if self.name in self.candidates:
            raise ValueError("FirstPresentSource cannot select itself")
        return self


class ConfigRecordsSource(BaseModel):
    """Expose a typed record list from a named plugin configuration asset."""

    kind: Literal["config_records"] = "config_records"
    name: SourceName
    asset: PluginConfigAsset
    records_key: SourceName
    columns: dict[SourceName, Literal["string", "int64", "float64", "boolean"]]

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_schema(self) -> ConfigRecordsSource:
        """Require at least one declared record column."""
        if not self.columns:
            raise ValueError("ConfigRecordsSource.columns cannot be empty")
        return self

    def to_frame(self, *, context: PluginContext) -> pl.DataFrame:
        """Load and type-check configured records without interpreting their policy."""
        asset_key = self.asset.value.removesuffix(".json")
        try:
            asset_data = context.config.load_config(assets=[self.asset])[asset_key]
        except (AttributeError, FileNotFoundError, KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"Configuration source {self.name!r} cannot load asset {asset_key!r}: {error}"
            ) from error
        records = asset_data.get(self.records_key)
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            raise ValueError(
                f"Configuration source {self.name!r} expected a record list at {asset_key}.{self.records_key}"
            )
        expected_columns = set(self.columns)
        for index, record in enumerate(records):
            if set(record) != expected_columns:
                raise ValueError(
                    f"Configuration source {self.name!r} record {index} fields must be "
                    f"{sorted(expected_columns)}, got {sorted(record)}"
                )
        dtypes = {
            "string": pl.String,
            "int64": pl.Int64,
            "float64": pl.Float64,
            "boolean": pl.Boolean,
        }
        schema = {column: dtypes[dtype] for column, dtype in self.columns.items()}
        try:
            return pl.DataFrame(records, schema=schema, orient="row", strict=True)
        except (TypeError, ValueError, pl.exceptions.PolarsError) as error:
            raise ValueError(
                f"Configuration source {self.name!r} records violate the declared schema: {error}"
            ) from error


class SystemFieldProjection(BaseModel):
    """Project one public component field into a named frame column."""

    path: SourceName
    dtype: Literal["string", "int64", "float64", "boolean"]

    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeSeriesProjection(BaseModel):
    """Project one named attached time series into indexed rows."""

    name: SourceName
    features: dict[SourceName, StrictBool | StrictInt | StrictFloat | StrictStr] = Field(default_factory=dict)
    missing: Literal["error", "skip"] = "error"

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_features(self) -> TimeSeriesProjection:
        """Reject feature names reserved by the System's time-series lookup API."""
        reserved = {"name", "time_series_type"}
        collisions = sorted(reserved & self.features.keys())
        if collisions:
            raise ValueError(f"TimeSeriesProjection.features uses reserved key(s): {collisions}")
        return self


class SystemFrameSource(BaseModel):
    """Project public fields from a configured source or target System."""

    kind: Literal["system"] = "system"
    name: SourceName
    system: Literal["source", "target"]
    component_type: SourceName
    owner_column: SourceName = "owner_name"
    fields: dict[SourceName, SystemFieldProjection] = Field(default_factory=dict)
    time_series: TimeSeriesProjection | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_projection(self) -> SystemFrameSource:
        """Keep projected columns distinct from component and series identity."""
        columns = [self.owner_column, *self.fields]
        if self.time_series is not None:
            columns.extend(("hour_index", "value"))
        if len(set(columns)) != len(columns):
            raise ValueError("SystemFrameSource projected columns must be unique")
        return self

    def to_frame(
        self, *, context: PluginContext, placeholders: dict[str, object] | None = None
    ) -> pl.DataFrame:
        """Resolve components and project configured fields without mutating the System."""
        values = self.model_dump(mode="python")
        substituted = substitute_placeholders(values, placeholders=placeholders)
        if substituted.is_err():
            raise ValueError(f"System source {self.name!r}: {substituted.err()}")
        resolved = SystemFrameSource.model_validate(substituted.unwrap())
        return resolved._project_frame(context=context)

    def _project_frame(self, *, context: PluginContext) -> pl.DataFrame:
        """Project a source after resolving its configured feature values."""
        system = context.source_system if self.system == "source" else context.target_system
        if system is None:
            raise ValueError(f"System source {self.name!r} requires the {self.system} System")
        type_result = resolve_component_type(self.component_type, context=context)
        if type_result.is_err():
            raise ValueError(f"System source {self.name!r}: {type_result.err()}")
        component_type = type_result.unwrap()
        if not isinstance(component_type, type) or not issubclass(component_type, Component):
            raise ValueError(f"System source {self.name!r} type {self.component_type!r} is not a Component")
        from .rules_executor import validate_owner_path

        for field_name, field in self.fields.items():
            path_error = validate_owner_path(component_type, field.path)
            if path_error is not None:
                raise ValueError(f"System source {self.name!r} field projection {field_name!r}: {path_error}")

        schema = {self.owner_column: pl.String}
        dtype_by_name = {
            "string": pl.String,
            "int64": pl.Int64,
            "float64": pl.Float64,
            "boolean": pl.Boolean,
        }
        schema.update({name: dtype_by_name[field.dtype] for name, field in self.fields.items()})
        if self.time_series is not None:
            schema.update({"hour_index": pl.Int64, "value": pl.Float64})

        rows: list[dict[str, object]] = []
        for component in system.get_components(component_type):
            projected = {self.owner_column: component.name}
            for name, field in self.fields.items():
                value: object = component
                for part in field.path.split("."):
                    try:
                        value = getattr(value, part)
                    except AttributeError as error:
                        raise ValueError(
                            f"System source {self.name!r} field projection {name!r} "
                            f"has no public attribute {part!r} in {field.path!r}"
                        ) from error
                    if value is None:
                        break
                projected[name] = value

            if self.time_series is None:
                rows.append(projected)
                continue

            keys = system.list_time_series_keys(
                component,
                name=self.time_series.name,
                time_series_type=SingleTimeSeries,
                **self.time_series.features,
            )
            if not keys:
                if self.time_series.missing == "skip":
                    continue
                raise ValueError(
                    f"System source {self.name!r} component {component.name!r} has no time series "
                    f"named {self.time_series.name!r}"
                )
            if len(keys) != 1:
                raise ValueError(
                    f"System source {self.name!r} component {component.name!r} has multiple matching "
                    f"time series named {self.time_series.name!r}"
                )
            series = system.get_time_series_by_key(component, keys[0])
            data = series.data
            if getattr(data, "ndim", 1) != 1:
                raise ValueError(
                    f"System source {self.name!r} time series {self.time_series.name!r} must be one-dimensional"
                )
            rows.extend(
                {**projected, "hour_index": index, "value": float(value)} for index, value in enumerate(data)
            )
        return pl.DataFrame(rows, schema=schema, orient="row")


RuntimeSource = Annotated[
    CalendarSource | ConfigRecordsSource | FirstPresentSource | SystemFrameSource,
    Field(discriminator="kind"),
]
