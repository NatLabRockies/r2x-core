"""Shared aliases, operation vocabularies, and file-format types."""

import re
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal, TypeAlias, TypeVar

from pydantic import Field, JsonValue, StringConstraints
from pydantic_core import core_schema

PLACEHOLDER_PATTERN: re.Pattern[str] = re.compile(r"\{([^{}]+)\}")

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JsonValue
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
PositiveInteger = Annotated[int, Field(gt=0)]
ColumnNames = Annotated[list[NonEmptyString], Field(min_length=1)]
FieldSource: TypeAlias = NonEmptyString | Annotated[list[NonEmptyString], Field(min_length=1)]

FileOutputT = TypeVar("FileOutputT")
FrameT = TypeVar("FrameT")


@dataclass(slots=True)
class FileFormat:
    """Lightweight marker for a supported file format."""

    supports_timeseries: ClassVar[bool] = False

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> core_schema.CoreSchema:
        """Serialize format markers by their class name."""
        python_schema = core_schema.is_instance_schema(cls)
        return core_schema.no_info_after_validator_function(
            lambda value: value,
            python_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: instance.__class__.__name__,
                return_schema=core_schema.str_schema(),
            ),
        )


@dataclass(slots=True)
class TableFormat(FileFormat):
    """CSV, TSV, and other delimited tabular formats."""

    supports_timeseries: ClassVar[bool] = True


@dataclass(slots=True)
class H5Format(FileFormat):
    """Hierarchical HDF5 data files."""

    supports_timeseries: ClassVar[bool] = True


@dataclass(slots=True)
class ParquetFormat(FileFormat):
    """Apache Parquet columnar data files."""

    supports_timeseries: ClassVar[bool] = True


@dataclass(slots=True)
class JSONFormat(FileFormat):
    """JSON data files."""


@dataclass(slots=True)
class XMLFormat(FileFormat):
    """XML data files."""


EXTENSION_MAPPING: dict[str, type[FileFormat]] = {
    ".csv": TableFormat,
    ".tsv": TableFormat,
    ".h5": H5Format,
    ".hdf5": H5Format,
    ".parquet": ParquetFormat,
    ".json": JSONFormat,
    ".xml": XMLFormat,
}

TableDataFormat: TypeAlias = TableFormat | H5Format | ParquetFormat

FilterOperator: TypeAlias = Literal[
    "eq",
    "neq",
    "in",
    "not_in",
    "geq",
    "startswith",
    "not_startswith",
    "endswith",
]

MappingExpressionOperator: TypeAlias = Literal[
    "and",
    "any",
    "cast",
    "coalesce",
    "concat_list",
    "concat_str",
    "datetime",
    "divide",
    "eq",
    "gt",
    "is_null",
    "le",
    "list_get",
    "list_sort",
    "lowercase",
    "max",
    "mean",
    "multiply",
    "split",
    "strip_chars",
    "struct",
    "subtract",
    "sum",
    "when",
    "year",
]
