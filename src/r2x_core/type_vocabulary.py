"""Low-level shared vocabularies and type constraints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints
from pydantic_core import core_schema

PLACEHOLDER_PATTERN: re.Pattern[str] = re.compile(r"\{([^{}]+)\}")

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JsonValue
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
PositiveInteger = Annotated[int, Field(gt=0)]
ColumnNames = Annotated[list[NonEmptyString], Field(min_length=1)]
FieldSource: TypeAlias = NonEmptyString | Annotated[list[NonEmptyString], Field(min_length=1)]
Separator = Annotated[str, StringConstraints(min_length=1, max_length=1)]
ProcessingPlaceholder = Annotated[str, StringConstraints(pattern=r"^\{[^{}]+\}$")]


class StrictModel(BaseModel):
    """Base for configuration models that reject unknown fields."""

    model_config = ConfigDict(extra="forbid")


class FileType(StrEnum):
    """Describe the kind of data represented by a file, independent of encoding."""

    STATIC = "static"
    TIME_SERIES = "time_series"


class FileRequirement(StrEnum):
    """Describe whether a configured input must be present."""

    REQUIRED = "required"
    OPTIONAL = "optional"


class AggregationFunction(StrEnum):
    """Aggregation functions supported by table processing."""

    COUNT = "count"
    FIRST = "first"
    LAST = "last"
    MAX = "max"
    MEAN = "mean"
    MEDIAN = "median"
    MIN = "min"
    N_UNIQUE = "n_unique"
    STD = "std"
    SUM = "sum"
    VAR = "var"


FileOutputT = TypeVar("FileOutputT")
FrameT = TypeVar("FrameT")


@dataclass(slots=True)
class FileFormat:
    """Lightweight marker for a supported physical file format."""

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


class MappingExpressionOperator(StrEnum):
    """Supported mapping-expression operators with stable JSON string values."""

    AND = "and"
    ANY = "any"
    CAST = "cast"
    COALESCE = "coalesce"
    CONCAT_LIST = "concat_list"
    CONCAT_STR = "concat_str"
    DATETIME = "datetime"
    DIVIDE = "divide"
    EQ = "eq"
    GT = "gt"
    IS_NULL = "is_null"
    LE = "le"
    LIST_GET = "list_get"
    LIST_SORT = "list_sort"
    LOWERCASE = "lowercase"
    MULTIPLY = "multiply"
    SPLIT = "split"
    STRIP_CHARS = "strip_chars"
    STRUCT = "struct"
    SUBTRACT = "subtract"
    WHEN = "when"
    YEAR = "year"


ExpressionOperator: TypeAlias = MappingExpressionOperator | AggregationFunction
