"""Configuration models for input data files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, ClassVar

from pydantic import AfterValidator, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import InitErrorDetails
from rust_ok import is_err

from .types import (
    EXTENSION_MAPPING,
    PLACEHOLDER_PATTERN,
    FileFormat,
    FileProcessing,
    FileRequirement,
    FileType,
    JSONFormat,
    StrictModel,
    TableDataFormat,
)
from .utils.files import resolve_path
from .utils.validation import validate_file_extension, validate_glob_pattern


def extension_for_path_source(path_source: Path | str | None, /) -> str | None:
    """Return the extension encoded by one configured path source."""
    if path_source is None:
        return None
    suffix = Path(path_source).suffix.lower()
    return suffix.rstrip("*?[]") or None


class FileInfo(StrictModel):
    """Describe data semantics and availability for one input file."""

    description: str | None = None
    file_type: FileType = FileType.STATIC
    requirement: FileRequirement = FileRequirement.REQUIRED
    units: str | None = None


class ReaderConfig(StrictModel):
    """Configure a custom reader or pass keyword arguments to a built-in one."""

    kwargs: dict[str, Any] = Field(default_factory=dict)
    function: Callable[..., Any] | None = None


class DataFile(StrictModel):
    """Describe one input file, its reader, metadata, and ordered processing."""

    name: str
    fpath: Annotated[Path | None, AfterValidator(validate_file_extension)] = None
    relative_fpath: Path | str | None = None
    glob: Annotated[str | None, AfterValidator(validate_glob_pattern)] = None
    info: FileInfo = Field(default_factory=FileInfo)
    reader: ReaderConfig = Field(default_factory=ReaderConfig)
    proc_spec: FileProcessing | None = None

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def validate_data_file(self) -> DataFile:
        """Validate path sources and ensure processing matches the file format."""
        path_sources = [self.fpath, self.relative_fpath, self.glob]
        configured_sources = [path for path in path_sources if path is not None]
        if len(configured_sources) != 1:
            msg = "Exactly one of 'fpath', 'relative_fpath', or 'glob' must be specified"
            raise ValueError(msg)

        if self.fpath is not None:
            has_template = PLACEHOLDER_PATTERN.search(str(self.fpath)) is not None
            is_optional = self.info.requirement is FileRequirement.OPTIONAL
            if not is_optional and not has_template and not self.fpath.exists():
                msg = f"File not found: {self.fpath}"
                raise FileNotFoundError(msg)

        if self.proc_spec is not None:
            file_format = self.file_format
            if isinstance(file_format, TableDataFormat) and self.proc_spec.kind != "tabular":
                msg = "Tabular files require TabularProcessing."
                raise ValueError(msg)
            if isinstance(file_format, JSONFormat) and self.proc_spec.kind != "json":
                msg = "JSON files require JSONProcessing."
                raise ValueError(msg)
            if not isinstance(file_format, TableDataFormat | JSONFormat):
                msg = f"{type(file_format).__name__} files do not support processing specifications."
                raise ValueError(msg)
        return self

    @property
    def file_format(self) -> FileFormat:
        """Return the physical file format inferred from its path source."""
        path_source = next(
            (path for path in (self.fpath, self.relative_fpath, self.glob) if path is not None),
            None,
        )
        extension = extension_for_path_source(path_source)
        if extension is None:
            if self.glob is not None:
                msg = "Cannot determine file format from glob pattern without an extension"
            else:
                msg = "A path source is required to determine the file format"
            raise ValueError(msg)
        try:
            file_format_class = EXTENSION_MAPPING[extension]
        except KeyError:
            msg = f"Unsupported file extension {extension!r}. Supported: {', '.join(EXTENSION_MAPPING)}"
            raise ValueError(msg) from None

        if self.info.file_type is FileType.TIME_SERIES and not file_format_class.supports_timeseries:
            msg = f"File format {file_format_class.__name__} does not support time-series data"
            raise ValueError(msg)
        return file_format_class()

    @classmethod
    def from_record(cls, record: dict[str, Any], *, folder_path: Path) -> DataFile:
        """Build a DataFile record with relative paths resolved against a folder."""
        record_copy = dict(record)
        info = record_copy.get("info")
        is_optional = (
            isinstance(info, dict) and info.get("requirement", FileRequirement.REQUIRED.value) == "optional"
        )
        path_fields = [
            field for field in ("fpath", "relative_fpath", "glob") if record_copy.get(field) is not None
        ]
        if len(path_fields) != 1:
            msg = "Each data file record must define exactly one of fpath, relative_fpath, or glob"
            raise ValueError(msg)

        path_field = path_fields[0]
        if path_field == "glob":
            return cls.model_validate(record_copy)

        raw_path = record_copy[path_field]
        has_template = PLACEHOLDER_PATTERN.search(str(raw_path)) is not None
        resolved = cls.resolve_record_path(
            raw_path,
            folder_path=folder_path,
            must_exist=not is_optional and not has_template,
        )
        record_copy.pop("relative_fpath", None)
        record_copy["fpath"] = resolved
        return cls.model_validate(record_copy)

    @classmethod
    def from_records(cls, records: list[dict[str, Any]], *, folder_path: Path) -> list[DataFile]:
        """Construct multiple DataFile instances and aggregate invalid records."""
        data_files: list[DataFile] = []
        errors: list[ValidationError] = []

        for idx, record in enumerate(records):
            try:
                data_files.append(cls.from_record(record, folder_path=folder_path))
            except ValidationError as error:
                errors.append(error)
            except (FileNotFoundError, KeyError, TypeError, ValueError) as error:
                path_error = isinstance(error, FileNotFoundError)
                errors.append(
                    ValidationError.from_exception_data(
                        title=f"Record[{idx}] {'path resolution' if path_error else 'invalid path source'} error",
                        line_errors=[
                            {
                                "type": "value_error",
                                "input": str(error),
                                "loc": ("fpath" if path_error else "path",),
                                "ctx": {"error": error, "exc_type": type(error).__name__},
                            }
                        ],
                    )
                )

        if errors:
            line_errors: list[InitErrorDetails] = []
            for error in errors:
                for details in error.errors():
                    init_error: InitErrorDetails = {
                        "type": details["type"],
                        "loc": details["loc"],
                        "input": details["input"],
                    }
                    if "ctx" in details:
                        init_error["ctx"] = details["ctx"]
                    line_errors.append(init_error)
            raise ValidationError.from_exception_data(
                title="Invalid data file records",
                line_errors=line_errors,
            )

        return data_files

    @staticmethod
    def resolve_record_path(
        raw_path: str | Path,
        *,
        folder_path: Path,
        must_exist: bool = True,
    ) -> Path:
        """Resolve a raw path under a folder and optionally require it to exist."""
        result = resolve_path(raw_path, base_folder=folder_path, must_exist=must_exist)
        if is_err(result):
            raise result.err()
        return result.unwrap()
