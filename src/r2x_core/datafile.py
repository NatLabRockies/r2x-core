"""Configuration models for physical and named input sources."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import ConfigDict, Field, field_validator, model_validator

from .types import (
    EXTENSION_MAPPING,
    FileProcessing,
    FileRequirement,
    FileType,
    JSONValue,
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


class DataFile(StrictModel):
    """Configure one physical file or a named source transformation."""

    name: str
    fpath: Path | None = None
    relative_fpath: Path | str | None = None
    glob: str | None = None
    source: str | None = None
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
        """Require either one physical path or one named processing source."""
        paths = [path for path in (self.fpath, self.relative_fpath, self.glob) if path is not None]
        if self.source is None and len(paths) != 1:
            msg = "A physical input requires exactly one of fpath, relative_fpath, or glob"
            raise ValueError(msg)
        if self.source is not None and paths:
            msg = "A named source cannot also define a physical file path"
            raise ValueError(msg)
        if self.source is not None and (self.reader.format is not None or self.reader.options):
            msg = "Reader settings apply only to physical inputs"
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
