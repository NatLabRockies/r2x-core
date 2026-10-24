"""Configuration models for physical and named input sources."""

from __future__ import annotations

from math import isfinite
from pathlib import Path
from sys import float_info
from typing import ClassVar, Literal

from pydantic import ConfigDict, Field, field_validator, model_serializer, model_validator

from .models import SourcePredicate
from .types import (
    EXTENSION_MAPPING,
    PLACEHOLDER_PATTERN,
    FileProcessing,
    FileRequirement,
    FileType,
    JSONValue,
    NonEmptyString,
    ProcessingPlaceholder,
    StrictModel,
)


def extension_for_path_source(path_source: Path | str | None, /) -> str | None:
    """Return the extension encoded by one configured path source."""
    if path_source is None:
        return None
    return Path(path_source).suffix.lower().rstrip("*?[]") or None


class FileInfo(StrictModel):
    """Describe data semantics and availability for one input file."""

    description: str | None = None
    file_type: FileType = FileType.STATIC
    requirement: FileRequirement = FileRequirement.REQUIRED
    units: str | None = None


class ReaderConfig(StrictModel):
    """Select a registered format and validate options in its reader."""

    format: str | None = Field(default=None, min_length=1)
    options: dict[str, JSONValue] = Field(default_factory=dict)


InlineColumnType = Literal["bool", "int64", "float64", "string"]
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
FLOAT64_MAX = float_info.max


class InlineTable(StrictModel):
    """Define raw typed records owned by a configuration file."""

    raw_schema: dict[NonEmptyString, InlineColumnType] = Field(alias="schema", min_length=1)
    rows: list[dict[NonEmptyString, JSONValue]] | ProcessingPlaceholder = Field(default_factory=list)

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def validate_rows(self) -> InlineTable:
        """Require exact raw record shape and values compatible with the schema."""
        if isinstance(self.rows, str):
            return self
        expected = set(self.raw_schema)
        for index, row in enumerate(self.rows):
            if set(row) != expected:
                msg = f"Inline row {index} keys must exactly match schema keys {sorted(expected)}"
                raise ValueError(msg)
            for column, value in row.items():
                if value is None or (isinstance(value, str) and PLACEHOLDER_PATTERN.fullmatch(value)):
                    continue
                column_type = self.raw_schema[column]
                if column_type == "bool":
                    valid = type(value) is bool
                elif column_type == "int64":
                    valid = type(value) is int and INT64_MIN <= value <= INT64_MAX
                elif column_type == "float64":
                    valid = (type(value) is int and -FLOAT64_MAX <= value <= FLOAT64_MAX) or (
                        type(value) is float and isfinite(value)
                    )
                else:
                    valid = type(value) is str
                if not valid:
                    msg = f"Inline row {index} value for {column!r} does not match {column_type!r}"
                    raise ValueError(msg)
        return self

    @model_serializer
    def serialize(self) -> dict[str, object]:
        """Keep the external configuration key independent of the Python field name."""
        return {"schema": self.raw_schema, "rows": self.rows}


class SourceSelection(StrictModel):
    """Select an ordered named source while preserving presence semantics."""

    mode: Literal["first_present", "first_nonempty"]
    sources: list[NonEmptyString] = Field(min_length=1)
    empty_fallback: InlineTable | None = None

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_sources(self) -> SourceSelection:
        """Reject duplicate candidates whose precedence would be ambiguous."""
        if len(set(self.sources)) != len(self.sources):
            msg = "Source selection candidates must be unique"
            raise ValueError(msg)
        return self


class DataFile(StrictModel):
    """Configure one physical input or named, selected, and inline source."""

    name: str
    fpath: Path | None = None
    relative_fpath: Path | str | None = None
    glob: str | None = None
    source: str | None = None
    source_selection: SourceSelection | None = None
    inline_table: InlineTable | None = None
    required_when: SourcePredicate | None = None
    info: FileInfo = Field(default_factory=FileInfo)
    reader: ReaderConfig = Field(default_factory=ReaderConfig)
    proc_spec: FileProcessing | None = None

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    @field_validator("glob")
    @classmethod
    def validate_glob(cls, value: str | None) -> str | None:
        """Validate glob syntax without resolving runtime matches."""
        from .utils.validation import validate_glob_pattern

        return validate_glob_pattern(value)

    @model_validator(mode="after")
    def validate_source(self) -> DataFile:
        """Require exactly one physical or named source definition."""
        paths = [path for path in (self.fpath, self.relative_fpath, self.glob) if path is not None]
        source_modes = sum(
            source is not None for source in (self.source, self.source_selection, self.inline_table)
        )
        if paths and len(paths) > 1:
            msg = "A physical input requires exactly one of fpath, relative_fpath, or glob"
            raise ValueError(msg)
        if paths and source_modes:
            msg = "A named source cannot also define a physical file path"
            raise ValueError(msg)
        if not paths and source_modes != 1:
            msg = "A data file requires exactly one physical path, named source, selection, or inline table"
            raise ValueError(msg)
        if not paths and (self.reader.format is not None or self.reader.options):
            msg = "Reader settings apply only to physical inputs"
            raise ValueError(msg)
        if self.inline_table is not None and self.proc_spec is not None and self.proc_spec.kind != "tabular":
            msg = "Inline tables require tabular processing"
            raise ValueError(msg)
        if self.required_when is not None and (
            not paths or self.info.requirement is not FileRequirement.OPTIONAL
        ):
            msg = "required_when applies only to optional physical inputs"
            raise ValueError(msg)
        return self

    @property
    def format_name(self) -> str:
        """Return the explicit symbolic format or infer an unambiguous extension."""
        if self.reader.format is not None:
            return self.reader.format
        path_source = next(
            (path for path in (self.fpath, self.relative_fpath, self.glob) if path is not None),
            None,
        )
        extension = extension_for_path_source(path_source)
        if extension is None:
            msg = "Cannot infer a reader format without a path extension; configure reader.format"
            raise ValueError(msg)
        try:
            return EXTENSION_MAPPING[extension]
        except KeyError:
            msg = f"Cannot infer a reader format for extension {extension!r}; configure reader.format"
            raise ValueError(msg) from None
