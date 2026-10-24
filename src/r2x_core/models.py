"""Pydantic models for mapping expressions and tabular operations."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Annotated, Any, ClassVar, Literal, TypeAlias

from pydantic import (
    ConfigDict,
    Field,
    RootModel,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from .type_vocabulary import (
    AggregationFunction,
    ColumnNames,
    ExpressionOperator,
    JSONScalar,
    JSONValue,
    MappingExpressionOperator,
    NonEmptyString,
    ProcessingPlaceholder,
    Separator,
    StrictModel,
    json_values_equal,
)


class StrictConfigModel(StrictModel):
    """Base for immutable mapping configuration models."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, populate_by_name=True)


class ColumnExpression(RootModel[NonEmptyString]):
    """Read a named input column by its exact name."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class OptionalColumnExpression(StrictConfigModel):
    """Read a named input column or produce null when it is absent."""

    optional_column: NonEmptyString


class LiteralExpression(StrictConfigModel):
    """Use a JSON scalar as an expression value."""

    literal: JSONScalar


class ListLiteralExpression(StrictConfigModel):
    """Use a homogeneous JSON scalar list as a mapping membership operand."""

    values: list[JSONScalar] | ProcessingPlaceholder

    @model_validator(mode="after")
    def validate_value_types(self) -> ListLiteralExpression:
        """Reject mixed scalar types before the backend constructs a list literal."""
        if isinstance(self.values, str):
            return self
        value_types = {type(value) for value in self.values if value is not None}
        if len(value_types) > 1:
            msg = "Membership list values must use the same scalar type, excluding nulls"
            raise ValueError(msg)
        return self


class ExpressionOperation(
    RootModel[
        Annotated[
            dict[ExpressionOperator, Annotated[list["Expression"], Field(min_length=1)]],
            Field(min_length=1, max_length=1),
        ]
    ]
):
    """Apply one core table operation to its ordered expression arguments."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        json_schema_extra={
            "propertyNames": {
                "enum": [operator.value for operator in (*MappingExpressionOperator, *AggregationFunction)]
            },
        },
    )

    @property
    def op(self) -> ExpressionOperator:
        """Return the single declared operation."""
        return next(iter(self.root))

    @property
    def args(self) -> list[Expression]:
        """Return the operation's ordered arguments."""
        return next(iter(self.root.values()))

    @model_validator(mode="after")
    def validate_arguments(self) -> ExpressionOperation:
        """Reject argument shapes that violate the mapping expression contract."""
        binary_operations = {
            MappingExpressionOperator.ADD,
            MappingExpressionOperator.CAST,
            MappingExpressionOperator.DIVIDE,
            MappingExpressionOperator.EQ,
            MappingExpressionOperator.GT,
            MappingExpressionOperator.IS_IN,
            MappingExpressionOperator.LE,
            MappingExpressionOperator.LIST_GET,
            MappingExpressionOperator.MULTIPLY,
            MappingExpressionOperator.NEQ,
            MappingExpressionOperator.REPEAT_BY,
            MappingExpressionOperator.SPLIT,
            MappingExpressionOperator.STRFTIME,
            MappingExpressionOperator.STARTS_WITH,
            MappingExpressionOperator.SUBTRACT,
        }
        unary_operations = set(AggregationFunction) | {
            MappingExpressionOperator.IS_NULL,
            MappingExpressionOperator.LIST_SORT,
            MappingExpressionOperator.LOWERCASE,
            MappingExpressionOperator.MONTH,
            MappingExpressionOperator.STRIP_CHARS,
            MappingExpressionOperator.YEAR,
        }

        if self.op in binary_operations and len(self.args) != 2:
            msg = f"{self.op} expects exactly two arguments"
            raise ValueError(msg)
        if self.op in unary_operations and len(self.args) != 1:
            msg = f"{self.op} expects exactly one argument"
            raise ValueError(msg)
        if self.op is MappingExpressionOperator.WHEN and len(self.args) != 3:
            msg = "when expects a predicate, a true value, and a false value"
            raise ValueError(msg)
        if self.op is MappingExpressionOperator.DATETIME and not 3 <= len(self.args) <= 7:
            msg = "datetime expects year, month, day, and up to four optional time fields"
            raise ValueError(msg)

        if self.op is MappingExpressionOperator.IS_IN and not isinstance(self.args[1], ListLiteralExpression):
            msg = "is_in requires a typed list literal as its second argument"
            raise ValueError(msg)

        if self.op in {
            MappingExpressionOperator.CAST,
            MappingExpressionOperator.SPLIT,
            MappingExpressionOperator.STRFTIME,
        }:
            argument = self.args[1]
            if not isinstance(argument, LiteralExpression) or not isinstance(argument.literal, str):
                labels = {
                    MappingExpressionOperator.CAST: "type name",
                    MappingExpressionOperator.SPLIT: "separator",
                    MappingExpressionOperator.STRFTIME: "format string",
                }
                msg = f"{self.op} requires a literal string {labels[self.op]} as its second argument"
                raise ValueError(msg)
        if self.op is MappingExpressionOperator.LIST_GET:
            argument = self.args[1]
            index = argument.literal if isinstance(argument, LiteralExpression) else argument
            if type(index) is not int:
                msg = "list_get requires a literal integer index as its second argument"
                raise ValueError(msg)

        return self


Expression: TypeAlias = (
    ColumnExpression
    | OptionalColumnExpression
    | LiteralExpression
    | ListLiteralExpression
    | ExpressionOperation
    | StrictBool
    | StrictInt
    | StrictFloat
    | None
)
ExpressionOperation.model_rebuild(_types_namespace={"Expression": Expression})


class SourcePredicate(StrictConfigModel):
    """Select a physical input requirement when any source row matches."""

    source: NonEmptyString
    predicate: Expression


class AssertStep(StrictConfigModel):
    """Reject input rows that do not satisfy a predicate."""

    op: Literal["assert"]
    predicate: Expression
    message: NonEmptyString | None = None


class FilterStep(StrictConfigModel):
    """Retain input rows that satisfy an expression predicate."""

    op: Literal["filter"]
    predicate: Expression


class FilterColumnsStep(StrictConfigModel):
    """Retain rows matching all configured exact column values."""

    op: Literal["filter_columns"]
    filter_by: dict[NonEmptyString, JSONValue]


class SelectStep(StrictConfigModel):
    """Select or rename columns using expressions."""

    op: Literal["select"]
    columns: dict[NonEmptyString, Expression]


class SelectColumnsStep(StrictConfigModel):
    """Keep the named columns without changing their names."""

    op: Literal["select_columns"]
    select_columns: ColumnNames


class WithColumnsStep(StrictConfigModel):
    """Add or replace columns using expressions."""

    op: Literal["with_columns"]
    columns: dict[NonEmptyString, Expression]


class UnpivotStep(StrictConfigModel):
    """Convert selected value columns into rows."""

    op: Literal["unpivot"]
    index: list[NonEmptyString]
    value_name: NonEmptyString
    variable_name: NonEmptyString


class LowercaseStep(StrictConfigModel):
    """Lowercase column names and string values when enabled."""

    op: Literal["lowercase"]
    lowercase: bool | ProcessingPlaceholder = True


class DropColumnsStep(StrictConfigModel):
    """Remove named columns."""

    op: Literal["drop_columns"]
    drop_columns: ColumnNames


class RenameColumnsStep(StrictConfigModel):
    """Rename columns by mapping source names to destination names."""

    op: Literal["rename_columns"]
    column_mapping: dict[NonEmptyString, NonEmptyString]


class SplitColumnSpec(StrictConfigModel):
    """Split one string column into the declared output columns."""

    separator: Separator
    into: Annotated[list[NonEmptyString], Field(min_length=2)]

    @model_validator(mode="after")
    def validate_output_columns(self) -> SplitColumnSpec:
        """Require non-blank, distinct output names."""
        if any(not name.strip() for name in self.into):
            msg = "split output names cannot be blank"
            raise ValueError(msg)
        if len(set(self.into)) != len(self.into):
            msg = "split output names must be unique"
            raise ValueError(msg)
        return self


class SplitColumnsStep(StrictConfigModel):
    """Split named columns into multiple output columns."""

    op: Literal["split_columns"]
    split_column: dict[NonEmptyString, SplitColumnSpec]


class UnpivotColumnsStep(StrictConfigModel):
    """Unpivot selected value columns, retaining all other columns as identifiers."""

    op: Literal["unpivot_columns"]
    columns: ColumnNames
    value_name: NonEmptyString = "value"
    variable_name: NonEmptyString = "variable"


class ReplaceValuesStep(StrictConfigModel):
    """Replace exact values in compatible columns, optionally limiting the columns."""

    op: Literal["replace_values"]
    replace_values: dict[Any, Any]
    columns: ColumnNames | None = None

    @model_validator(mode="after")
    def validate_columns(self) -> ReplaceValuesStep:
        """Reject repeated columns so a scope names each target once."""
        if self.columns is not None and len(set(self.columns)) != len(self.columns):
            msg = "replace_values columns cannot contain duplicates"
            raise ValueError(msg)
        return self


class StripCharactersStep(StrictConfigModel):
    """Remove configured literal substrings from string columns."""

    op: Literal["strip_characters"]
    strip_chars: dict[NonEmptyString, Annotated[list[NonEmptyString], Field(min_length=1)]]


class CastColumnsStep(StrictConfigModel):
    """Cast columns to Polars dtype names."""

    op: Literal["cast_columns"]
    column_schema: dict[NonEmptyString, NonEmptyString]


class ScaleColumnsStep(StrictConfigModel):
    """Multiply numeric columns by configured factors."""

    op: Literal["scale_columns"]
    scale: dict[NonEmptyString, float | ProcessingPlaceholder]

    @model_validator(mode="after")
    def validate_finite_factors(self) -> ScaleColumnsStep:
        """Reject invalid scale factors before execution."""
        invalid = [
            factor for factor in self.scale.values() if isinstance(factor, float) and not isfinite(factor)
        ]
        if invalid:
            msg = "scale values must be finite numbers"
            raise ValueError(msg)
        return self


class FillNullStep(StrictConfigModel):
    """Fill null values in configured columns."""

    op: Literal["fill_null"]
    fill_null: dict[NonEmptyString, JSONValue]


class AggregateStep(StrictConfigModel):
    """Aggregate named columns, optionally grouping rows first."""

    op: Literal["aggregate"]
    aggregate_on: Annotated[
        dict[NonEmptyString, AggregationFunction | ProcessingPlaceholder], Field(min_length=1)
    ]
    group_by: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_group_columns(self) -> AggregateStep:
        """Keep grouping keys out of the aggregate mapping."""
        overlap = sorted(set(self.group_by) & set(self.aggregate_on))
        if overlap:
            msg = f"aggregate_on cannot aggregate group_by column(s): {overlap}"
            raise ValueError(msg)
        return self


class PivotStep(StrictConfigModel):
    """Pivot a long table using explicit index, key, values, and aggregation."""

    op: Literal["pivot"]
    pivot_on: NonEmptyString
    group_by: list[NonEmptyString]
    aggregate_on: Annotated[
        dict[NonEmptyString, AggregationFunction | ProcessingPlaceholder], Field(min_length=1)
    ]

    @model_validator(mode="after")
    def validate_aggregation_functions(self) -> PivotStep:
        """Require a shared aggregation because Polars pivots all value columns together."""
        functions = set(self.aggregate_on.values())
        if len(functions) > 1 and not any(
            isinstance(function, str) and function.startswith("{") for function in functions
        ):
            msg = "pivot requires one aggregation function for all value columns"
            raise ValueError(msg)
        unsupported = {
            function
            for function in self.aggregate_on.values()
            if function in {AggregationFunction.N_UNIQUE, AggregationFunction.STD, AggregationFunction.VAR}
        }
        if unsupported:
            unsupported_names = sorted(
                function.value if isinstance(function, AggregationFunction) else str(function)
                for function in unsupported
            )
            msg = f"pivot does not support aggregation function(s): {unsupported_names}"
            raise ValueError(msg)
        if self.pivot_on in self.group_by or self.pivot_on in self.aggregate_on:
            msg = "pivot_on cannot also be a group_by or aggregate_on column"
            raise ValueError(msg)
        return self


class GroupByStep(StrictConfigModel):
    """Group rows and compute named aggregate expressions."""

    op: Literal["group_by"]
    by: ColumnNames
    agg: Annotated[dict[NonEmptyString, Expression], Field(min_length=1)]


PatternAttribute: TypeAlias = StrictBool | StrictInt | StrictFloat | StrictStr | None


class PatternMatchGroup(StrictConfigModel):
    """Match one or more literal exact values or prefixes as a group."""

    label: NonEmptyString
    prefixes: list[NonEmptyString] = Field(default_factory=list)
    exact: list[NonEmptyString] = Field(default_factory=list)
    attributes: dict[NonEmptyString, PatternAttribute] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_patterns(self) -> PatternMatchGroup:
        """Require at least one exact or prefix pattern."""
        if not self.prefixes and not self.exact:
            msg = "A pattern group requires at least one prefix or exact value"
            raise ValueError(msg)
        return self


class MatchPatternsStep(StrictConfigModel):
    """Match ordered groups of literal exact values and prefixes."""

    op: Literal["match_patterns"]
    column: NonEmptyString
    label_column: NonEmptyString
    groups: Annotated[list[PatternMatchGroup], Field(min_length=1)]
    defaults: dict[NonEmptyString, PatternAttribute] = Field(default_factory=dict)
    case_sensitive: StrictBool = True

    @model_validator(mode="after")
    def validate_attribute_names(self) -> MatchPatternsStep:
        """Declare every group attribute in defaults and reserve the label column."""
        if self.label_column in self.defaults:
            msg = "label_column cannot also be a default attribute"
            raise ValueError(msg)
        declared = set(self.defaults)
        for group in self.groups:
            unknown = sorted(set(group.attributes) - declared)
            if unknown:
                msg = f"Pattern group attributes must be declared in defaults: {unknown}"
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_attribute_types(self) -> MatchPatternsStep:
        """Keep each default and group attribute on one strict scalar type."""
        attribute_types: dict[str, type] = {}
        for attribute, value in self.defaults.items():
            if value is not None:
                attribute_types[attribute] = type(value)
        for group in self.groups:
            for attribute, value in group.attributes.items():
                if value is None:
                    continue
                previous_type = attribute_types.get(attribute)
                if previous_type is not None and type(value) is not previous_type:
                    msg = f"Pattern attribute {attribute!r} has inconsistent scalar types"
                    raise ValueError(msg)
                attribute_types[attribute] = type(value)
        return self

    @model_validator(mode="after")
    def validate_attribute_ranges(self) -> MatchPatternsStep:
        """Keep numeric attributes representable by the backend scalar dtypes."""
        values = [
            *self.defaults.values(),
            *(value for group in self.groups for value in group.attributes.values()),
        ]
        for value in values:
            if type(value) is int and not -(2**63) <= value <= 2**63 - 1:
                msg = "Integer pattern attributes must fit in signed 64-bit values"
                raise ValueError(msg)
            if type(value) is float and not isfinite(value):
                msg = "Float pattern attributes must be finite"
                raise ValueError(msg)
        return self


class ConcatStep(StrictConfigModel):
    """Append prior named tables with the current table using exact schemas."""

    op: Literal["concat"]
    sources: Annotated[list[NonEmptyString], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_sources(self) -> ConcatStep:
        """Reject repeated named inputs before vertical concatenation."""
        if len(set(self.sources)) != len(self.sources):
            msg = "Concat sources must be unique"
            raise ValueError(msg)
        return self


class JoinStep(StrictConfigModel):
    """Join the current table with another named mapping node."""

    op: Literal["join"]
    source: NonEmptyString
    how: Literal["inner", "left", "right", "full", "semi", "anti", "cross"]
    on: ColumnNames | None = None
    join_validation: Literal["m:m", "m:1", "1:m", "1:1"] | None = Field(default=None, alias="validate")

    @model_validator(mode="after")
    def validate_cross_join(self) -> JoinStep:
        """Reject join options that the cross-join backend cannot apply."""
        if self.how == "cross" and (self.on is not None or self.join_validation not in {None, "m:m"}):
            msg = "cross joins cannot define keys or non-m:m validation"
            raise ValueError(msg)
        return self


class DatetimeRangeStep(StrictConfigModel):
    """Expand each start timestamp into a regular datetime sequence."""

    op: Literal["datetime_range"]
    start: NonEmptyString
    column: NonEmptyString
    periods: Annotated[int, Field(gt=0)]
    resolution_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def validate_output(self) -> DatetimeRangeStep:
        """Keep the generated axis separate from its start field."""
        if self.column == self.start:
            msg = "datetime_range output cannot replace its start column"
            raise ValueError(msg)
        return self


class HeadStep(StrictConfigModel):
    """Keep the first configured number of source rows."""

    op: Literal["head"]
    n: Annotated[int, Field(ge=0)]


class ExplodeStep(StrictConfigModel):
    """Expand list-valued columns into one row per element."""

    op: Literal["explode"]
    columns: ColumnNames

    @model_validator(mode="after")
    def validate_columns(self) -> ExplodeStep:
        """Reject repeated columns before row expansion."""
        if len(set(self.columns)) != len(self.columns):
            msg = "Explode columns must be unique"
            raise ValueError(msg)
        return self


class SortStep(StrictConfigModel):
    """Sort rows by columns and their explicit directions."""

    op: Literal["sort"]
    by: dict[NonEmptyString, Literal["asc", "desc"] | ProcessingPlaceholder]


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
    | FilterColumnsStep
    | SelectStep
    | SelectColumnsStep
    | WithColumnsStep
    | UnpivotStep
    | UnpivotColumnsStep
    | LowercaseStep
    | DropColumnsStep
    | RenameColumnsStep
    | SplitColumnsStep
    | ReplaceValuesStep
    | StripCharactersStep
    | CastColumnsStep
    | ScaleColumnsStep
    | FillNullStep
    | AggregateStep
    | PivotStep
    | GroupByStep
    | MatchPatternsStep
    | ConcatStep
    | JoinStep
    | DatetimeRangeStep
    | HeadStep
    | ExplodeStep
    | SortStep
    | UniqueStep
    | CustomStep,
    Field(discriminator="op"),
]


class TabularProcessing(StrictConfigModel):
    """Ordered tabular processing operations."""

    kind: Literal["tabular"] = "tabular"
    steps: list[MappingStep] = Field(default_factory=list)


class RenameJSONKeysStep(StrictConfigModel):
    """Recursively rename JSON object keys."""

    op: Literal["rename_keys"]
    mapping: dict[NonEmptyString, NonEmptyString]


class DropJSONKeysStep(StrictConfigModel):
    """Recursively remove JSON object keys."""

    op: Literal["drop_keys"]
    keys: ColumnNames


class FilterJSONStep(StrictConfigModel):
    """Filter JSON records by exact field values."""

    op: Literal["filter"]
    where: dict[NonEmptyString, JSONValue]


class JSONReplacement(StrictConfigModel):
    """Replace one finite JSON scalar with a finite JSON value."""

    model_config: ClassVar[ConfigDict] = ConfigDict(allow_inf_nan=False)

    old: JSONScalar
    new: JSONValue


class ReplaceJSONValuesStep(StrictConfigModel):
    """Recursively replace exact JSON scalar values."""

    op: Literal["replace_values"]
    replacements: list[JSONReplacement]

    @model_validator(mode="after")
    def validate_replacements(self) -> ReplaceJSONValuesStep:
        """Reject replacement sources that would match the same scalar."""
        for index, replacement in enumerate(self.replacements):
            if any(
                json_values_equal(replacement.old, previous.old) for previous in self.replacements[:index]
            ):
                msg = f"Duplicate replacement source value {replacement.old!r}"
                raise ValueError(msg)
        return self


class SelectJSONKeysStep(StrictConfigModel):
    """Keep only selected keys in JSON objects."""

    op: Literal["select_keys"]
    keys: ColumnNames


JSONProcessingStep: TypeAlias = Annotated[
    RenameJSONKeysStep | DropJSONKeysStep | FilterJSONStep | ReplaceJSONValuesStep | SelectJSONKeysStep,
    Field(discriminator="op"),
]


class JSONProcessing(StrictConfigModel):
    """Ordered transformations for JSON-compatible values."""

    kind: Literal["json"] = "json"
    steps: list[JSONProcessingStep] = Field(default_factory=list)


class ComponentReference(StrictConfigModel):
    """Resolve a source field as the name of a previously built component."""

    component_type: NonEmptyString
    name_field: NonEmptyString


class ComponentOwner(StrictConfigModel):
    """Select component owners by explicit names or names in source records."""

    component_type: NonEmptyString
    name: NonEmptyString | None = None
    names: list[NonEmptyString] | None = None
    name_field: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> ComponentOwner:
        """Require one unambiguous owner selection mode."""
        if sum(value is not None for value in (self.name, self.names, self.name_field)) != 1:
            msg = "An owner requires exactly one of name, names, or name_field"
            raise ValueError(msg)
        if self.names is not None and not self.names:
            msg = "An owner's names list cannot be empty"
            raise ValueError(msg)
        return self


class RegularTimeAxis(StrictConfigModel):
    """Describe samples with a fixed initial timestamp and resolution."""

    kind: Literal["regular"]
    initial_timestamp: datetime
    resolution_seconds: float = Field(gt=0)


class ColumnTimeAxis(StrictConfigModel):
    """Read sample timestamps from a source field and validate regularity."""

    kind: Literal["column"]
    column: NonEmptyString
    resolution_seconds: float | None = Field(default=None, gt=0)


TimeAxis: TypeAlias = Annotated[RegularTimeAxis | ColumnTimeAxis, Field(discriminator="kind")]


class ComponentInstruction(StrictConfigModel):
    """Construct validated components from a named source."""

    kind: Literal["component"]
    source: NonEmptyString
    component_type: NonEmptyString
    fields: dict[NonEmptyString, NonEmptyString] = Field(default_factory=dict)
    references: dict[NonEmptyString, ComponentReference] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_field_mapping(self) -> ComponentInstruction:
        """Prevent a field from being both copied and reference-resolved."""
        overlap = self.fields.keys() & self.references.keys()
        if overlap:
            msg = f"Fields cannot be both mapped and referenced: {sorted(overlap)}"
            raise ValueError(msg)
        return self


class TimeSeriesInstruction(StrictConfigModel):
    """Attach samples to owners, optionally partitioning on row-derived metadata."""

    kind: Literal["time_series"]
    source: NonEmptyString
    name: NonEmptyString
    values: NonEmptyString
    time_axis: TimeAxis
    units: NonEmptyString | None = None
    metadata: dict[NonEmptyString, JSONValue] = Field(default_factory=dict)
    metadata_columns: dict[NonEmptyString, NonEmptyString] = Field(default_factory=dict)
    skip_if_empty: bool = False
    owners: Annotated[list[ComponentOwner], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_metadata(self) -> TimeSeriesInstruction:
        """Keep literal and row-derived infrasys feature mappings unambiguous."""
        reserved = {"context", "self", "time_series"} & (self.metadata.keys() | self.metadata_columns.keys())
        if reserved:
            msg = f"Time-series metadata cannot set reserved infrasys argument(s): {sorted(reserved)}"
            raise ValueError(msg)
        overlap = self.metadata.keys() & self.metadata_columns.keys()
        if overlap:
            msg = f"Time-series literal and column metadata keys overlap: {sorted(overlap)}"
            raise ValueError(msg)
        return self


class SupplementalAttributeInstruction(StrictConfigModel):
    """Construct and attach validated supplemental attributes from a source."""

    kind: Literal["supplemental_attribute"]
    source: NonEmptyString
    attribute_type: NonEmptyString
    fields: dict[NonEmptyString, NonEmptyString] = Field(default_factory=dict)
    owners: Annotated[list[ComponentOwner], Field(min_length=1)]


ParserInstruction: TypeAlias = Annotated[
    ComponentInstruction | TimeSeriesInstruction | SupplementalAttributeInstruction,
    Field(discriminator="kind"),
]
