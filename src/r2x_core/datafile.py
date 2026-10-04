"""Data Model for datafiles (refactored to nested models)."""

import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

from .file_types import EXTENSION_MAPPING, FileFormat, JSONFormat, TableDataFormat
from .utils import validate_file_extension, validate_glob_pattern
from .utils.files import resolve_path

_PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]+\}")
_ProcessingPlaceholder = Annotated[str, StringConstraints(pattern=r"^\{[^{}]+\}$")]
_SUPPORTED_AGGREGATIONS = frozenset(
    {"count", "first", "last", "max", "mean", "median", "min", "n_unique", "std", "sum", "var"}
)
_PIVOT_AGGREGATIONS = _SUPPORTED_AGGREGATIONS - {"n_unique", "std", "var"}


def _validate_optional_file_extension(path: Path | None, info: ValidationInfo) -> Path | None:
    """Run validate_file_extension when a path is provided."""
    if path is None:
        return None
    return validate_file_extension(path, info=info)


class FileInfo(BaseModel):
    """File metadata and properties.

    Contains descriptive information about the data file, including its role
    in the workflow, whether it contains time series data, and units for
    single-column files.

    Attributes
    ----------
    description : str | None
        Human-readable description of the file purpose.
    is_input : bool
        Whether the file is an input source. Default is True.
    is_optional : bool
        Whether the file is optional for processing. Default is False.
    is_timeseries : bool
        Whether the file contains time series data. Default is False.
    units : str | None
        Units for single-column numeric data. Default is None.

    See Also
    --------
    :class:`DataFile` : Complete data file configuration.
    """

    description: Annotated[str | None, Field(description="Description of the data file")] = None
    is_input: Annotated[bool, Field(description="Whether this is an input file")] = True
    is_optional: Annotated[bool, Field(description="Whether this file is optional")] = False
    is_timeseries: Annotated[bool, Field(description="Whether file contains time series data")] = False
    units: Annotated[str | None, Field(description="Units for single-column data")] = None


class ReaderConfig(BaseModel):
    """Reader configuration for file loading.

    Specifies how to read the data file, including keyword arguments for
    the default reader or a custom function for specialized file formats.

    Attributes
    ----------
    function : Callable[[Path], Any] | None
        Custom reader function that takes file path and returns loaded data.
        If None, uses the default reader for the file type. Default is None.
    kwargs : dict[str, Any]
        Keyword arguments passed to the reader function. Default is empty.
    header_rows : int
        Number of CSV/TSV header rows to combine. Default is 1.
    header_separator : str
        Separator between combined header cells. Default is ``|``.

    See Also
    --------
    :class:`DataFile` : Complete data file configuration.
    :class:`DataStore` : Container that uses ReaderConfig to load files.
    """

    kwargs: Annotated[dict[str, Any], Field(default_factory=dict, description="Keyword arguments for reader")]
    function: Annotated[Callable[[Path], Any] | None, Field(description="Custom reader function")] = None
    header_rows: Annotated[int, Field(ge=1, description="Number of CSV/TSV header rows to combine")] = 1
    header_separator: Annotated[
        str, Field(min_length=1, description="Separator used to combine multi-row headers")
    ] = "|"


class DataFileCandidate(BaseModel):
    """One ordered source candidate for a logical :class:`DataFile`.

    Specify exactly one of ``fpath``, ``relative_fpath``, or ``glob``. The
    candidate's file format is derived from that path, and its ``reader``
    config applies only to this source. A missing file or configured HDF5 group
    allows the next candidate to be tried. Other read failures propagate.

    Examples
    --------
    >>> from r2x_core import DataFile, DataFileCandidate, ReaderConfig
    >>> data_file = DataFile(
    ...     name="prices",
    ...     sources=[
    ...         DataFileCandidate(
    ...             relative_fpath="outputs.h5",
    ...             reader=ReaderConfig(kwargs={"group_key": "prices"}),
    ...         ),
    ...         DataFileCandidate(relative_fpath="prices.csv"),
    ...     ],
    ... )
    >>> [candidate.file_type.__class__.__name__ for candidate in data_file.sources]
    ['H5Format', 'TableFormat']
    """

    fpath: Annotated[
        Path | None,
        AfterValidator(_validate_optional_file_extension),
        Field(description="Explicit path for this source candidate"),
    ] = None
    relative_fpath: Annotated[Path | str | None, Field(description="Path relative to the DataStore folder")] = None
    glob: Annotated[str | None, AfterValidator(validate_glob_pattern), Field(description="Glob for this source")] = (
        None
    )
    reader: Annotated[
        ReaderConfig,
        Field(default_factory=ReaderConfig, description="Reader configuration for this source only"),
    ]

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def validate_source(self) -> "DataFileCandidate":
        """Require exactly one path source and validate its file format."""
        path_count = sum(
            source is not None for source in (self.fpath, self.relative_fpath, self.glob)
        )
        if path_count != 1:
            raise ValueError("A source candidate must define exactly one of fpath, relative_fpath, or glob")
        _ = self.file_type
        return self

    @computed_field
    @property
    def file_type(self) -> FileFormat:
        """Return the file format inferred from this candidate's path."""
        if self.fpath is not None:
            extension = self.fpath.suffix.lower()
        elif self.relative_fpath is not None:
            relative_path = Path(self.relative_fpath)
            extension = relative_path.suffix.lower()
        elif self.glob is not None:
            extension = "." + self.glob.rsplit(".", 1)[-1].rstrip("*?[]") if "." in self.glob else ""
        else:
            raise ValueError("A source candidate must define exactly one path source")

        if extension not in EXTENSION_MAPPING:
            raise ValueError(f"Unsupported source candidate extension {extension!r}")
        return EXTENSION_MAPPING[extension]()


class SplitColumnSpec(BaseModel):
    """Configuration for splitting a string column into named fields."""

    separator: Annotated[str, Field(min_length=1, description="Literal separator to split on")]
    into: Annotated[list[str], Field(min_length=2, description="Names for the resulting columns")]

    @model_validator(mode="after")
    def validate_output_columns(self) -> "SplitColumnSpec":
        """Require distinct, non-empty output column names."""
        if any(not name.strip() for name in self.into):
            raise ValueError("split_column output names cannot be empty")
        if len(set(self.into)) != len(self.into):
            raise ValueError("split_column output names must be unique")
        return self


class TabularProcessing(BaseModel):
    """Data transformations for tabular files (CSV, HDF5, Parquet, etc.).

    Defines a sequence of operations to apply to tabular data after loading.
    Supports column selection, filtering, reshaping, aggregation, and more.

    Attributes
    ----------
    select_columns : list[str] | None
        List of column names to keep. Removes all other columns.
    drop_columns : list[str] | None
        List of column names to remove.
    column_mapping : dict[str, str] | None
        Maps original column names to new names.
    column_schema : dict[str, str] | None
        Maps column names to data types for type coercion.
    filter_by : dict[str, Any] | None
        Conditions for filtering rows by column values.
    pivot_on : str | None
        Input column used for a long-to-wide pivot. The column must exist.
    unpivot_on : list[str] | None
        Value columns to unpivot. Remaining columns are retained as identifier
        columns, and the generated columns are named ``variable`` and ``value``.
    group_by : list[str] | None
        Columns to group by before applying ``aggregate_on``.
    aggregate_on : dict[str, str] | None
        Mapping of columns to supported aggregation functions.
    sort_by : dict[str, str] | None
        Columns and sort directions for ordering. Directions are ``asc`` or
        ``desc`` (the ``ascending`` and ``descending`` aliases are also accepted).
    distinct_on : list[str] | None
        Columns to use for deduplication.
    replace_values : dict[Any, Any] | None
        Maps old values to new values across compatible columns.
    fill_null : dict[str, Any] | None
        Specifies fill values for null entries by column.
    lowercase : bool | str
        If True, lowercase column names and string values before processing. A
        complete placeholder may defer the boolean value until processing.
    strip_chars : dict[str, list[str]] | None
        Literal strings to remove from configured columns before casting.
    scale : dict[str, float | str] | None
        Multipliers applied to numeric columns after casting. A complete
        placeholder may defer a multiplier until processing.
    split_column : dict[str, SplitColumnSpec] | None
        Split columns into named fields using a literal separator.

    See Also
    --------
    :class:`DataFile` : Uses TabularProcessing in proc_spec field.
    :class:`JSONProcessing` : Transformations for JSON files.
    """

    select_columns: Annotated[list[str] | None, Field(description="Columns to keep")] = None
    drop_columns: Annotated[list[str] | None, Field(description="Columns to remove")] = None
    column_mapping: Annotated[dict[str, str] | None, Field(description="Column rename mapping")] = None
    column_schema: Annotated[dict[str, str] | None, Field(description="Column type definitions")] = None
    filter_by: Annotated[dict[str, Any] | None, Field(description="Row filters")] = None
    pivot_on: Annotated[str | None, Field(description="Input column used for a long-to-wide pivot")] = None
    unpivot_on: Annotated[list[str] | None, Field(description="Columns to unpivot")] = None
    group_by: Annotated[list[str] | None, Field(description="Columns to group by")] = None
    aggregate_on: Annotated[dict[str, str] | None, Field(description="Aggregation spec")] = None
    sort_by: Annotated[dict[str, str] | None, Field(description="Sort specification")] = None
    distinct_on: Annotated[list[str] | None, Field(description="Columns for deduplication")] = None
    replace_values: Annotated[dict[Any, Any] | None, Field(description="Value replacement map")] = None
    fill_null: Annotated[dict[str, Any] | None, Field(description="Null fill values")] = None
    lowercase: Annotated[
        bool | _ProcessingPlaceholder,
        Field(description="Lowercase column names and string values; accepts complete placeholders"),
    ] = False
    strip_chars: Annotated[
        dict[str, list[str]] | None, Field(description="Literal strings to remove from string columns")
    ] = None
    scale: Annotated[
        dict[str, float | _ProcessingPlaceholder] | None,
        Field(description="Numeric multipliers by column; accepts complete placeholders"),
    ] = None
    split_column: Annotated[
        dict[str, SplitColumnSpec] | None, Field(description="Split string columns into named fields")
    ] = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_operations(self) -> "TabularProcessing":
        """Reject ambiguous operation combinations and invalid options."""
        if self.pivot_on and self.unpivot_on:
            raise ValueError("pivot_on and unpivot_on are mutually exclusive")
        if self.group_by and not self.aggregate_on:
            raise ValueError("group_by requires aggregate_on")
        if self.pivot_on and self.pivot_on in (self.group_by or ()):
            raise ValueError("pivot_on cannot also be a group_by column")
        if self.pivot_on and self.pivot_on in (self.aggregate_on or ()):
            raise ValueError("pivot_on cannot also be an aggregate_on column")
        if self.aggregate_on and set(self.group_by or ()) & set(self.aggregate_on):
            overlapping = sorted(set(self.group_by or ()) & set(self.aggregate_on))
            raise ValueError(f"aggregate_on cannot aggregate group_by column(s): {overlapping}")
        if self.pivot_on and self.aggregate_on:
            pivot_functions = {
                function.lower()
                for function in self.aggregate_on.values()
                if _PLACEHOLDER_PATTERN.search(function) is None
            }
            if len(pivot_functions) > 1:
                raise ValueError("pivot_on requires one aggregation function for all value columns")
            unsupported_pivot_functions = pivot_functions - _PIVOT_AGGREGATIONS
            if unsupported_pivot_functions:
                raise ValueError(
                    "pivot_on does not support aggregation function(s): "
                    + ", ".join(sorted(unsupported_pivot_functions))
                    + f". Supported pivot aggregations: {', '.join(sorted(_PIVOT_AGGREGATIONS))}."
                )
        if self.aggregate_on:
            invalid = {
                column: function
                for column, function in self.aggregate_on.items()
                if _PLACEHOLDER_PATTERN.search(function) is None
                and function.lower() not in _SUPPORTED_AGGREGATIONS
            }
            if invalid:
                raise ValueError(
                    "Unsupported aggregation function(s): "
                    + ", ".join(f"{column}={function!r}" for column, function in invalid.items())
                    + f". Supported functions: {', '.join(sorted(_SUPPORTED_AGGREGATIONS))}."
                )
        if self.scale:
            invalid_scales = {
                column: factor
                for column, factor in self.scale.items()
                if not isinstance(factor, str) and not math.isfinite(factor)
            }
            if invalid_scales:
                raise ValueError(f"scale values must be finite numbers: {invalid_scales}")
        if self.strip_chars:
            invalid_characters = {
                column: values
                for column, values in self.strip_chars.items()
                if any(not value for value in values)
            }
            if invalid_characters:
                raise ValueError(f"strip_chars values must be non-empty strings: {invalid_characters}")
        if self.sort_by:
            invalid_directions = {
                column: direction
                for column, direction in self.sort_by.items()
                if _PLACEHOLDER_PATTERN.search(direction) is None
                and direction.lower() not in {"asc", "ascending", "desc", "descending"}
            }
            if invalid_directions:
                raise ValueError(
                    "Unsupported sort direction(s): "
                    + ", ".join(f"{column}={direction!r}" for column, direction in invalid_directions.items())
                    + ". Use asc, ascending, desc, or descending."
                )
        return self


class JSONProcessing(BaseModel):
    """Data transformations for JSON files.

    Defines operations for processing JSON-structured data, including key
    selection, filtering, and value transformations.

    Attributes
    ----------
    key_mapping : dict[str, str] | None
        Maps original JSON keys to new key names.
    rename_index : str | None
        New name for the dictionary keys.
    drop_columns : list[str] | None
        Keys to remove from nested dictionaries.
    filter_by : dict[str, Any] | None
        Conditions for filtering JSON objects by key values.
    replace_values : dict[Any, Any] | None
        Maps old values to new values for replacement.
    select_keys : list[str] | None
        Select specific keys to keep.

    See Also
    --------
    :class:`DataFile` : Uses JSONProcessing in proc_spec field.
    :class:`TabularProcessing` : Transformations for tabular files.
    """

    key_mapping: Annotated[dict[str, str] | None, Field(description="Key rename mapping (JSON-specific)")] = (
        None
    )
    rename_index: Annotated[str | None, Field(description="Rename dict keys")] = None
    drop_keys: Annotated[list[str] | None, Field(description="Keys to drop from nested dicts")] = None
    filter_by: Annotated[dict[str, Any] | None, Field(description="Filter conditions")] = None
    replace_values: Annotated[dict[Any, Any] | None, Field(description="Value replacement map")] = None
    select_keys: Annotated[list[str] | None, Field(description="Select certain keys.")] = None

    model_config = ConfigDict(extra="forbid")


FileProcessing = TabularProcessing | JSONProcessing


class DataFile(BaseModel):
    """Data file configuration with nested structure.

    Defines how to locate and process one logical dataset. Configure either
    exactly one top-level path source or an ordered ``sources`` list of
    :class:`DataFileCandidate` instances. Candidate-specific readers are tried
    in order only when their file or configured HDF5 group is absent. Malformed
    or otherwise invalid existing sources fail without falling back. The
    logical ``proc_spec`` is applied once to data from the selected candidate.

    For records and DataStore JSON, ``sources`` is a list of candidate objects
    with one of ``fpath``, ``relative_fpath``, or ``glob``, plus an optional
    ``reader`` object. Candidate paths determine each candidate's format. Do
    not combine ``sources`` with top-level path or reader fields.

    Parameters
    ----------
    name : str
        Unique identifier for this file mapping.
    fpath : Path | None, optional
        Absolute path to the data file. Exactly one of fpath, relative_fpath,
        or glob must be specified. Default is None.
    relative_fpath : Path | str | None, optional
        Path relative to DataStore folder. Default is None.
    glob : str | None, optional
        Glob pattern to locate files. Default is None.
    sources : list[DataFileCandidate] | None, optional
        Ordered path and reader configurations. Mutually exclusive with
        top-level path fields and ``reader``. Default is None.
    info : FileInfo | None, optional
        File metadata including role, optionality, time series flag.
        Default is None.
    reader : ReaderConfig | None, optional
        Reader configuration specifying kwargs and custom functions.
        Default is None.
    proc_spec : FileProcessing | None, optional
        Data transformations (TabularProcessing or JSONProcessing).
        Default is None.

    Raises
    ------
    ValueError
        If path sources are not exactly one top-level path or one or more
        source candidates, or if source declarations conflict.
    ValueError
        If file type does not support time series, or its processing model is
        incompatible with the file format.

    See Also
    --------
    :class:`FileInfo` : File metadata.
    :class:`ReaderConfig` : Reader configuration.
    :class:`TabularProcessing` : Transformations for tabular files.
    :class:`JSONProcessing` : Transformations for JSON files.
    :class:`DataStore` : Container that manages DataFile instances.
    """

    name: Annotated[str, Field(description="Name of the mapping")]
    fpath: Annotated[
        Path | None,
        AfterValidator(_validate_optional_file_extension),
        Field(description="Absolute file path"),
    ] = None
    relative_fpath: Annotated[Path | str | None, Field(description="Relative file path")] = None
    glob: Annotated[str | None, AfterValidator(validate_glob_pattern), Field(description="Glob pattern")] = (
        None
    )
    sources: Annotated[
        list[DataFileCandidate] | None,
        Field(description="Ordered source candidates for this logical data file"),
    ] = None
    info: Annotated[FileInfo | None, Field(description="File metadata")] = None
    reader: Annotated[ReaderConfig | None, Field(description="Reader configuration")] = None
    proc_spec: Annotated[FileProcessing | None, Field(description="Data transformations")] = None

    model_config = ConfigDict(frozen=True)

    @field_validator("proc_spec", mode="before")
    @classmethod
    def parse_processing_for_file_format(cls, value: Any, info: ValidationInfo) -> Any:
        """Parse mapping configurations with the model required by their format."""
        if not isinstance(value, dict):
            return value

        sources = info.data.get("sources")
        if sources:
            format_type = type(sources[0].file_type)
        else:
            glob = info.data.get("glob")
            if glob is not None:
                extension = "." + glob.rsplit(".", 1)[-1].rstrip("*?[]") if "." in glob else ""
            else:
                path = info.data.get("fpath") or info.data.get("relative_fpath")
                if path is None:
                    return value
                extension = Path(path).suffix.lower()
            format_type = EXTENSION_MAPPING.get(extension)
        if format_type is None:
            return value
        if issubclass(format_type, TableDataFormat):
            return TabularProcessing.model_validate(value)
        if issubclass(format_type, JSONFormat):
            return JSONProcessing.model_validate(value)
        return value

    @model_validator(mode="after")
    def validate_path_sources(self) -> "DataFile":
        """Validate that exactly one of fpath, relative_fpath, or glob is specified."""
        paths_set = sum([self.fpath is not None, self.relative_fpath is not None, self.glob is not None])
        if self.sources is not None:
            if not self.sources:
                raise ValueError("sources must contain at least one candidate")
            if paths_set:
                raise ValueError("Specify either top-level path fields or sources, not both")
            if self.reader is not None:
                raise ValueError("Configure readers on each source candidate, not on DataFile")
            if self.info and self.info.is_timeseries:
                unsupported = [
                    type(candidate.file_type).__name__
                    for candidate in self.sources
                    if not candidate.file_type.supports_timeseries
                ]
                if unsupported:
                    raise ValueError(
                        "Time-series data is not supported by source format(s): " + ", ".join(unsupported)
                    )
            return self
        if paths_set == 0:
            msg = "Exactly one of 'fpath', 'relative_fpath', 'glob', or 'sources' must be specified"
            raise ValueError(msg)
        if paths_set > 1:
            msg = "Multiple path sources specified. Use exactly one of: 'fpath', 'relative_fpath', or 'glob'"
            raise ValueError(msg)

        if self.fpath is not None:
            is_optional = self.info.is_optional if self.info else False
            has_template = _PLACEHOLDER_PATTERN.search(str(self.fpath)) is not None
            if not is_optional and not has_template and not self.fpath.exists():
                msg = f"File not found: {self.fpath}"
                raise FileNotFoundError(msg)

        return self

    @model_validator(mode="after")
    def validate_processing_model(self) -> "DataFile":
        """Ensure the processing model matches the file's format."""
        if self.proc_spec is None:
            return self

        file_types = [candidate.file_type for candidate in self.sources] if self.sources else [self.file_type]
        for file_type in file_types:
            if isinstance(file_type, TableDataFormat):
                if not isinstance(self.proc_spec, TabularProcessing):
                    raise ValueError(
                        f"Tabular files require TabularProcessing, got {type(self.proc_spec).__name__}."
                    )
            elif isinstance(file_type, JSONFormat):
                if not isinstance(self.proc_spec, JSONProcessing):
                    raise ValueError(f"JSON files require JSONProcessing, got {type(self.proc_spec).__name__}.")
            else:
                raise ValueError(
                    f"{type(file_type).__name__} files do not support processing specifications."
                )
        return self

    @computed_field
    @property
    def file_type(self) -> FileFormat:
        """Computed file type based on file extension or primary candidate."""
        if self.sources is not None:
            file_type = self.sources[0].file_type
            if self.info and self.info.is_timeseries and not file_type.supports_timeseries:
                raise ValueError(f"File type {type(file_type).__name__} does not support time series data")
            return file_type
        if self.fpath is not None:
            extension = self.fpath.suffix.lower()
        elif self.relative_fpath is not None:
            rel_path = (
                Path(self.relative_fpath) if isinstance(self.relative_fpath, str) else self.relative_fpath
            )
            extension = rel_path.suffix.lower()
        elif self.glob is not None:
            if "." in self.glob:
                extension = "." + self.glob.rsplit(".", 1)[-1].rstrip("*?[]")
            else:
                msg = "Cannot determine file type from glob pattern without extension"
                raise ValueError(msg)
        else:
            msg = "Either fpath, relative_fpath, or glob must be set"
            raise ValueError(msg)

        if extension not in EXTENSION_MAPPING:
            msg = f"{extension=} not found on EXTENSION_MAPPING"
            raise ValueError(msg)
        file_type_class = EXTENSION_MAPPING[extension]

        if self.info and self.info.is_timeseries and not file_type_class.supports_timeseries:
            msg = f"File type {file_type_class.__name__} does not support time series data"
            raise ValueError(msg)

        return file_type_class()

    @classmethod
    def from_record(cls, record: dict[str, Any], *, folder_path: Path) -> "DataFile":
        """Build a DataFile from a single path or ordered source candidates.

        Relative paths are resolved against ``folder_path``. Candidate paths
        are allowed to be absent so later sources can be tried. Glob patterns
        are retained for resolution when the data file is read.
        """
        record_copy = dict(record)
        info = record_copy.get("info")
        is_optional = bool(info.get("is_optional")) if isinstance(info, dict) else False
        if record_copy.get("sources") is not None:
            if any(record_copy.get(field) is not None for field in ("fpath", "relative_fpath", "glob")):
                raise ValueError("Specify either top-level path fields or sources, not both")
            if record_copy.get("reader") is not None:
                raise ValueError("Configure readers on each source candidate, not on DataFile")
            resolved_sources: list[dict[str, Any]] = []
            for source in record_copy["sources"]:
                if not isinstance(source, dict):
                    raise TypeError("Each source candidate record must be an object")
                source_copy = dict(source)
                source_path_fields = [
                    field for field in ("fpath", "relative_fpath", "glob") if source_copy.get(field) is not None
                ]
                if len(source_path_fields) != 1:
                    raise ValueError(
                        "Each source candidate record must define exactly one of fpath, relative_fpath, or glob"
                    )
                source_path_field = source_path_fields[0]
                if source_path_field != "glob":
                    source_copy["fpath"] = cls._resolve_record_path(
                        source_copy.pop(source_path_field),
                        folder_path=folder_path,
                        must_exist=False,
                    )
                    source_copy.pop("relative_fpath", None)
                resolved_sources.append(source_copy)
            record_copy["sources"] = resolved_sources
            return cls.model_validate(record_copy)

        path_fields = [
            field for field in ("fpath", "relative_fpath", "glob") if record_copy.get(field) is not None
        ]
        if len(path_fields) != 1:
            raise ValueError(
                "Each data file record must define exactly one of fpath, relative_fpath, or glob"
            )

        path_field = path_fields[0]
        if path_field == "glob":
            return cls.model_validate(record_copy)

        raw_path = record_copy[path_field]
        has_template = _PLACEHOLDER_PATTERN.search(str(raw_path)) is not None
        resolved = cls._resolve_record_path(
            raw_path,
            folder_path=folder_path,
            must_exist=not is_optional and not has_template,
        )
        record_copy.pop("relative_fpath", None)
        record_copy["fpath"] = resolved
        return cls.model_validate(record_copy)

    @classmethod
    def from_records(cls, records: list[dict[str, Any]], *, folder_path: Path) -> list["DataFile"]:
        """Construct multiple DataFile instances from JSON records."""
        data_files: list[DataFile] = []
        errors: list[ValidationError] = []

        for idx, record in enumerate(records):
            try:
                data_files.append(cls.from_record(record, folder_path=folder_path))

            except ValidationError as exc:
                errors.append(exc)

            except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
                path_error = isinstance(exc, FileNotFoundError)
                errors.append(
                    ValidationError.from_exception_data(
                        title=f"Record[{idx}] {'path resolution' if path_error else 'invalid path source'} error",
                        line_errors=[
                            {
                                "type": "value_error",
                                "input": str(exc),
                                "loc": ("fpath" if path_error else "path",),
                                "ctx": {"error": str(exc), "exc_type": type(exc).__name__},
                            }
                        ],
                    )
                )

        if errors:
            # NOTE: Why adding type ignore
            # For some reason, line_errors should be of type "list[InitErrorDetails]", but we are returning
            # "list[ErrorDetails]". I think this is not a potential bug in the future and will use ignore the type.
            line_errors = [line for err in errors for line in err.errors()]
            raise ValidationError.from_exception_data(
                title="Invalid data file records",
                line_errors=line_errors,  # type: ignore
            )

        return data_files

    @staticmethod
    def _resolve_record_path(
        raw_path: str | Path,
        *,
        folder_path: Path,
        must_exist: bool = True,
    ) -> Path:
        """Resolve a raw path into an absolute path with optional checking."""
        result = resolve_path(raw_path, base_folder=folder_path, must_exist=must_exist)
        if result.is_err():
            raise result.err()

        # Safe because we verified result is Ok above
        path = result.ok()
        assert path is not None, "Expected Path from Ok result"
        return path
