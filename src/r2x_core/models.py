"""Pydantic models for mapping expressions and tabular operations."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .types import ColumnNames, JSONScalar, JSONValue, MappingExpressionOperator, NonEmptyString


class StrictConfigModel(BaseModel):
    """Base for configuration models that reject undeclared fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ColumnExpression(StrictConfigModel):
    """Read a named input column."""

    column: NonEmptyString


class LiteralExpression(StrictConfigModel):
    """Use a JSON scalar as an expression value."""

    literal: JSONScalar


class ExpressionOperation(StrictConfigModel):
    """Apply a core table operation to one or more expressions."""

    op: MappingExpressionOperator
    args: Annotated[list[Expression], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_arguments(self) -> ExpressionOperation:
        """Reject argument shapes that violate the mapping expression contract."""
        binary_operations = {"divide", "eq", "gt", "le", "multiply", "subtract"}
        unary_operations = {"is_null", "list_sort", "lowercase", "max", "mean", "strip_chars", "sum", "year"}

        if self.op in binary_operations and len(self.args) != 2:
            raise ValueError(f"{self.op} expects exactly two arguments")
        if self.op in unary_operations and len(self.args) != 1:
            raise ValueError(f"{self.op} expects exactly one argument")
        if self.op == "when" and len(self.args) != 3:
            raise ValueError("when expects a predicate, a true value, and a false value")
        if self.op == "datetime" and not 3 <= len(self.args) <= 7:
            raise ValueError("datetime expects year, month, day, and up to four optional time fields")
        if self.op in {"cast", "list_get", "split"} and len(self.args) != 2:
            raise ValueError(f"{self.op} expects exactly two arguments")

        if self.op in {"cast", "split"}:
            argument = self.args[1]
            if not isinstance(argument, LiteralExpression) or not isinstance(argument.literal, str):
                label = "type name" if self.op == "cast" else "separator"
                raise ValueError(f"{self.op} requires a literal string {label} as its second argument")
        if self.op == "list_get":
            argument = self.args[1]
            if (
                not isinstance(argument, LiteralExpression)
                or not isinstance(argument.literal, int)
                or isinstance(argument.literal, bool)
            ):
                raise ValueError("list_get requires a literal integer index as its second argument")

        return self


Expression: TypeAlias = ColumnExpression | LiteralExpression | ExpressionOperation
ExpressionOperation.model_rebuild()


class AssertStep(StrictConfigModel):
    """Reject input rows that do not satisfy a predicate."""

    op: Literal["assert"]
    predicate: Expression


class FilterStep(StrictConfigModel):
    """Retain input rows that satisfy a predicate."""

    op: Literal["filter"]
    predicate: Expression


class SelectStep(StrictConfigModel):
    """Select or rename columns using expressions."""

    op: Literal["select"]
    columns: dict[NonEmptyString, Expression]


class WithColumnsStep(StrictConfigModel):
    """Add or replace columns using expressions."""

    op: Literal["with_columns"]
    columns: dict[NonEmptyString, Expression]


class UnpivotStep(StrictConfigModel):
    """Convert selected value columns into rows."""

    op: Literal["unpivot"]
    index: ColumnNames
    value_name: NonEmptyString
    variable_name: NonEmptyString


class GroupByStep(StrictConfigModel):
    """Group rows and compute named aggregate expressions."""

    op: Literal["group_by"]
    by: ColumnNames
    agg: Annotated[dict[NonEmptyString, Expression], Field(min_length=1)]


class JoinStep(StrictConfigModel):
    """Join the current table with another named mapping node."""

    op: Literal["join"]
    source: NonEmptyString
    how: Literal["inner", "left", "right", "full", "semi", "anti", "cross"]
    on: ColumnNames | None = None
    join_validation: Literal["m:m", "m:1", "1:m", "1:1"] | None = Field(default=None, alias="validate")


class SortStep(StrictConfigModel):
    """Sort rows by the named columns."""

    op: Literal["sort"]
    by: ColumnNames


class UniqueStep(StrictConfigModel):
    """Keep unique rows, optionally identified by a subset of columns."""

    op: Literal["unique"]
    subset: ColumnNames


class CustomStep(StrictConfigModel):
    """Call an app-registered handler for a non-core mapping operation."""

    op: Literal["custom"]
    handler: NonEmptyString
    kwargs: dict[NonEmptyString, JSONValue] = Field(default_factory=dict)


MappingStep: TypeAlias = Annotated[
    AssertStep
    | FilterStep
    | SelectStep
    | WithColumnsStep
    | UnpivotStep
    | GroupByStep
    | JoinStep
    | SortStep
    | UniqueStep
    | CustomStep,
    Field(discriminator="op"),
]
