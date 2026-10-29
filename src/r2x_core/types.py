"""Shared aliases, operation vocabularies, and model unions."""

from typing import Annotated, TypeAlias

from pydantic import Field

from .models import JSONProcessing, MappingStep, TabularProcessing
from .shared_types import (
    EXTENSION_MAPPING,
    PLACEHOLDER_PATTERN,
    AggregationFunction,
    ColumnNames,
    ExpressionOperator,
    FileRequirement,
    FileType,
    FilterOperator,
    FrameT,
    JSONScalar,
    JSONValue,
    MappingExpressionOperator,
    NonEmptyString,
    PositiveInteger,
    ProcessingPlaceholder,
    Separator,
    StrictModel,
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
    "FileProcessing",
    "FileRequirement",
    "FileType",
    "FilterOperator",
    "FrameT",
    "JSONProcessing",
    "JSONScalar",
    "JSONValue",
    "MappingExpressionOperator",
    "MappingStep",
    "NonEmptyString",
    "PositiveInteger",
    "ProcessingPlaceholder",
    "Separator",
    "StrictModel",
    "TabularProcessing",
]
