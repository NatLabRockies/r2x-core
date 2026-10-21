"""Shared aliases, operation vocabularies, and model unions."""

from typing import Annotated, TypeAlias

from pydantic import Field

from .models import JSONProcessing, MappingStep, TabularProcessing
from .type_vocabulary import (
    EXTENSION_MAPPING,
    PLACEHOLDER_PATTERN,
    AggregationFunction,
    ColumnNames,
    ExpressionOperator,
    FileFormat,
    FileOutputT,
    FileRequirement,
    FileType,
    FilterOperator,
    FrameT,
    H5Format,
    JSONFormat,
    JSONScalar,
    JSONValue,
    MappingExpressionOperator,
    NonEmptyString,
    ParquetFormat,
    PositiveInteger,
    ProcessingPlaceholder,
    Separator,
    StrictModel,
    TableDataFormat,
    TableFormat,
    XMLFormat,
)

FileProcessing: TypeAlias = Annotated[
    TabularProcessing | JSONProcessing,
    Field(discriminator="kind"),
]

__all__ = [
    "EXTENSION_MAPPING",
    "PLACEHOLDER_PATTERN",
    "AggregationFunction",
    "ColumnNames",
    "ExpressionOperator",
    "FileFormat",
    "FileOutputT",
    "FileProcessing",
    "FileRequirement",
    "FileType",
    "FilterOperator",
    "FrameT",
    "H5Format",
    "JSONFormat",
    "JSONProcessing",
    "JSONScalar",
    "JSONValue",
    "MappingExpressionOperator",
    "MappingStep",
    "NonEmptyString",
    "ParquetFormat",
    "PositiveInteger",
    "ProcessingPlaceholder",
    "Separator",
    "StrictModel",
    "TableDataFormat",
    "TableFormat",
    "TabularProcessing",
    "XMLFormat",
]
