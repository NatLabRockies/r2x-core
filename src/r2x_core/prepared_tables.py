"""Typed configuration models for tables prepared from physical files."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .datafile import DataFile, TabularProcessing

NonEmptyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PreparedTableError(ValueError):
    """A named prepared table could not be read or validated."""


class SelectFirst(BaseModel):
    """Stable duplicate-key selection policy for a many-to-one join."""

    order_by: dict[NonEmptyName, Literal["asc", "desc"]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", frozen=True)


class TableJoin(BaseModel):
    """Explicit relational join from one physical data file."""

    source: NonEmptyName
    on: Annotated[dict[NonEmptyName, NonEmptyName], Field(min_length=1)]
    columns: Annotated[dict[NonEmptyName, NonEmptyName], Field(min_length=1)]
    how: Literal["left", "inner"] = "left"
    cardinality: Literal["m:1", "1:m", "m:m"] = "m:1"
    select_first: SelectFirst | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_columns(self) -> TableJoin:
        """Require unique keys and payload, without repeating join keys as payload."""
        if len(set(self.on.values())) != len(self.on):
            raise ValueError("right join-key references must be unique")
        if self.cardinality != "m:1" and self.how != "inner":
            raise ValueError("expanding joins require how='inner'")
        if self.cardinality != "m:1" and self.select_first is not None:
            raise ValueError("select_first is only valid for m:1 joins")
        if len(set(self.columns.values())) != len(self.columns):
            raise ValueError("join payload output columns must be unique")
        source_overlap = set(self.on.values()) & set(self.columns)
        if source_overlap:
            raise ValueError(
                f"join payload references cannot repeat right join keys: {sorted(source_overlap)}"
            )
        output_overlap = set(self.on.values()) & set(self.columns.values())
        if output_overlap:
            raise ValueError(f"join payload outputs cannot repeat right join keys: {sorted(output_overlap)}")
        return self


class PreparedTable(BaseModel):
    """A table built from one physical file and optional physical-file joins."""

    name: NonEmptyName
    source: NonEmptyName
    required_columns: Annotated[list[NonEmptyName], Field(min_length=1)]
    joins: list[TableJoin] = Field(default_factory=list)
    proc_spec: TabularProcessing | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_required_columns(self) -> PreparedTable:
        """Require a unique list of required result columns."""
        if len(set(self.required_columns)) != len(self.required_columns):
            raise ValueError("required_columns must be unique")
        return self


class FileMapping(BaseModel):
    """Validated physical-file and prepared-table mapping."""

    files: list[DataFile]
    tables: list[PreparedTable]

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_names_and_sources(self) -> FileMapping:
        """Ensure names are unique and every table source names a physical file."""
        file_names = [data_file.name for data_file in self.files]
        table_names = [table.name for table in self.tables]
        if len(set(file_names)) != len(file_names):
            raise ValueError("file mapping contains duplicate physical file names")
        if len(set(table_names)) != len(table_names):
            raise ValueError("file mapping contains duplicate prepared table names")
        collisions = set(file_names) & set(table_names)
        if collisions:
            raise ValueError(f"file and table names must be unique across the mapping: {sorted(collisions)}")

        known_files = set(file_names)
        for table in self.tables:
            sources = [table.source, *(join.source for join in table.joins)]
            unknown = sorted(set(sources) - known_files)
            if unknown:
                raise ValueError(
                    f"prepared table {table.name!r} references unknown physical file(s): {unknown}"
                )
        return self


class FileMappingDocument(BaseModel):
    """JSON envelope used to load file mappings before resolving file paths."""

    files: list[dict[str, object]]
    tables: list[PreparedTable]

    model_config = ConfigDict(extra="forbid")
