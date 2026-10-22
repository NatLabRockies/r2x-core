"""Low-level shared vocabularies and type constraints."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

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


FrameT = TypeVar("FrameT")

EXTENSION_MAPPING: dict[str, str] = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".h5": "hdf5",
    ".hdf5": "hdf5",
    ".parquet": "parquet",
    ".json": "json",
    ".xml": "xml",
}

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
