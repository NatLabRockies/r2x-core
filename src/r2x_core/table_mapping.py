"""Load and execute strict named-table mappings."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
    model_validator,
)

from .datafile import InlineTable, parse_inline_table_rows
from .file_reader import DecodedSource, DecodedSources, SourceAvailability, TabularSource
from .models import (
    MatchPatternsOptions,
    MatchSourcePatternsOptions,
    OmitUnsetNoneConfigModel,
    StrictConfigModel,
)
from .shared_types import PLACEHOLDER_PATTERN, JSONValue, NonEmptyString, ProcessingPlaceholder
from .tabular_backend import (
    TableColumnType,
    TableDateTimePart,
    TableFilterComparison,
    TableMappingBackend,
    TableProjectionSelection,
    TableValueSelection,
)

TableScalar: TypeAlias = StrictBool | StrictInt | StrictFloat | StrictStr | None


class TableLiteral(StrictConfigModel):
    """Declare literal text in a table projection or object field."""

    value: StrictStr


class TableProjectionLiteral(StrictConfigModel):
    """Declare a scalar table-projection literal with an explicit logical type."""

    value: TableScalar
    dtype: TableColumnType

    @model_validator(mode="after")
    def validate_value(self) -> TableProjectionLiteral:
        """Require the literal to be compatible with its declared scalar type."""
        value = self.value
        if value is None:
            return self
        if self.dtype == "bool":
            compatible = type(value) is bool
        elif self.dtype == "int64":
            compatible = type(value) is int and -(2**63) <= value <= 2**63 - 1
        elif self.dtype == "float64":
            if type(value) is int:
                try:
                    compatible = isfinite(float(value))
                except OverflowError:
                    compatible = False
            else:
                compatible = type(value) is float and isfinite(value)
        elif self.dtype == "string":
            compatible = type(value) is str
        elif self.dtype == "datetime" and type(value) is str:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as error:
                msg = "datetime projection literals must be ISO-8601 strings"
                raise ValueError(msg) from error
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                msg = "datetime projection literals must be timezone-naive"
                raise ValueError(msg)
            compatible = True
        else:
            compatible = False
        if not compatible:
            msg = f"projection literal type {type(value).__name__} is incompatible with dtype {self.dtype!r}"
            raise ValueError(msg)
        return self


class TableOptionalColumn(StrictConfigModel):
    """Project a typed source column when present, or typed null when absent."""

    optional_column: NonEmptyString
    dtype: TableColumnType


class TableScalarLiteral(StrictConfigModel):
    """Declare one scalar literal in a choose branch."""

    value: TableScalar | ProcessingPlaceholder


TableProjectionValue: TypeAlias = NonEmptyString | TableLiteral | TableProjectionLiteral | TableOptionalColumn
TableObjectProjectionValue: TypeAlias = NonEmptyString | TableLiteral


class TableJoinOperation(OmitUnsetNoneConfigModel):
    """Join the current table with an earlier named table."""

    operation: Literal["join"]
    source: NonEmptyString
    how: Literal["inner", "left", "cross"]
    on: list[NonEmptyString] | None = None
    columns: list[NonEmptyString] | None = None

    @model_validator(mode="after")
    def validate_join(self) -> TableJoinOperation:
        """Require explicit unique keys except for cross joins."""
        if "on" in self.model_fields_set and self.on is None:
            msg = "join 'on' must be omitted when unused, not null"
            raise ValueError(msg)
        if "columns" in self.model_fields_set and self.columns is None:
            msg = "join 'columns' must be omitted when unused, not null"
            raise ValueError(msg)
        if self.how == "cross" and self.on is not None:
            msg = "cross joins must omit 'on'"
            raise ValueError(msg)
        if self.how != "cross" and not self.on:
            msg = f"{self.how} joins require non-empty 'on' keys"
            raise ValueError(msg)
        if self.on is not None and len(set(self.on)) != len(self.on):
            msg = "join keys must be unique"
            raise ValueError(msg)
        if self.columns is not None and len(set(self.columns)) != len(self.columns):
            msg = "join payload columns must be unique"
            raise ValueError(msg)
        return self


class TableMatchSourcePatternsOperation(MatchSourcePatternsOptions):
    """Resolve one exact, numeric-range, or delimited-prefix source pattern per row."""

    operation: Literal["match_source_patterns"]


class TableMatchPatternsOperation(MatchPatternsOptions):
    """Emit one row per matching static literal exact/prefix group."""

    operation: Literal["match_patterns"]


class TableMultiplyOperation(StrictConfigModel):
    """Multiply two columns into a new column for each input row."""

    operation: Literal["multiply"]
    columns: Annotated[list[NonEmptyString], Field(min_length=2, max_length=2)]
    output: NonEmptyString


class TableAddOperation(StrictConfigModel):
    """Add two columns into a new column for each input row."""

    operation: Literal["add"]
    columns: Annotated[list[NonEmptyString], Field(min_length=2, max_length=2)]
    output: NonEmptyString


class TableDivideOperation(StrictConfigModel):
    """Divide two columns into a new column for each input row."""

    operation: Literal["divide"]
    columns: Annotated[list[NonEmptyString], Field(min_length=2, max_length=2)]
    output: NonEmptyString


class TableAbsoluteOperation(StrictConfigModel):
    """Take the absolute value of one numeric column into a new column."""

    operation: Literal["absolute"]
    column: NonEmptyString
    output: NonEmptyString


class TableCasefoldOperation(StrictConfigModel):
    """Create a Unicode casefolded string key without changing its source column."""

    operation: Literal["casefold"]
    column: NonEmptyString
    output: NonEmptyString


class TableDateTimePartOperation(StrictConfigModel):
    """Extract one datetime component into an int64 column."""

    operation: Literal["datetime_part"]
    column: NonEmptyString
    part: TableDateTimePart
    output: NonEmptyString


class TableConcatStringsOperation(StrictConfigModel):
    """Join ordered scalar values as text in a new column."""

    operation: Literal["concat_strings"]
    columns: Annotated[list[NonEmptyString], Field(min_length=1)]
    separator: StrictStr = ""
    output: NonEmptyString

    @model_validator(mode="after")
    def validate_columns(self) -> TableConcatStringsOperation:
        """Reject repeated input references."""
        if len(set(self.columns)) != len(self.columns):
            msg = "concat_strings columns must be unique"
            raise ValueError(msg)
        return self


class TableSplitOperation(StrictConfigModel):
    """Select a zero-based part of one exact string split."""

    operation: Literal["split"]
    column: NonEmptyString
    separator: NonEmptyString
    index: Annotated[StrictInt, Field(ge=0)]
    output: NonEmptyString


class TableFilterOperation(OmitUnsetNoneConfigModel):
    """Retain rows whose named field meets one scalar or column comparison."""

    operation: Literal["filter"]
    column: NonEmptyString
    comparison: TableFilterComparison
    value: TableScalar | ProcessingPlaceholder = None
    other_column: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_operands(self) -> TableFilterOperation:
        """Require one explicit operand for binary comparisons and none for unary ones."""
        has_value = "value" in self.model_fields_set
        has_other_column = "other_column" in self.model_fields_set
        if self.comparison in {"is_null", "is_not_null"}:
            if has_value or has_other_column:
                msg = f"filter {self.comparison!r} must omit value and other_column"
                raise ValueError(msg)
        elif has_value == has_other_column:
            msg = "binary filter requires exactly one of value or other_column"
            raise ValueError(msg)
        elif has_other_column and self.other_column is None:
            msg = "filter 'other_column' must be omitted when unused, not null"
            raise ValueError(msg)
        return self


class TableChooseOperation(OmitUnsetNoneConfigModel):
    """Select one of two columns or scalar values using one flat predicate."""

    operation: Literal["choose"]
    column: NonEmptyString
    comparison: TableFilterComparison
    value: TableScalar | ProcessingPlaceholder = None
    other_column: NonEmptyString | None = None
    then: NonEmptyString | TableScalarLiteral
    otherwise: NonEmptyString | TableScalarLiteral
    output: NonEmptyString

    @model_validator(mode="after")
    def validate_operands(self) -> TableChooseOperation:
        """Require the same exact binary or unary predicate shape as filter."""
        has_value = "value" in self.model_fields_set
        has_other_column = "other_column" in self.model_fields_set
        if self.comparison in {"is_null", "is_not_null"}:
            if has_value or has_other_column:
                msg = f"choose {self.comparison!r} must omit value and other_column"
                raise ValueError(msg)
        elif has_value == has_other_column:
            msg = "choose binary predicate requires exactly one of value or other_column"
            raise ValueError(msg)
        elif has_other_column and self.other_column is None:
            msg = "choose 'other_column' must be omitted when unused, not null"
            raise ValueError(msg)
        return self


class TableAggregate(StrictConfigModel):
    """Aggregate one field into a named result column."""

    operation: Literal["sum", "max", "mean", "count", "first", "last", "list"]
    column: NonEmptyString
    output: NonEmptyString


class TableGroupByOperation(StrictConfigModel):
    """Group rows in first-seen key order or aggregate all rows globally."""

    operation: Literal["group_by"]
    columns: list[NonEmptyString]
    aggregate: Annotated[list[TableAggregate], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_group(self) -> TableGroupByOperation:
        """Require unique keys and result names outside the key columns."""
        if len(set(self.columns)) != len(self.columns):
            msg = "group_by columns must be unique"
            raise ValueError(msg)
        outputs = [aggregate.output for aggregate in self.aggregate]
        if len(set(outputs)) != len(outputs):
            msg = "group_by aggregate outputs must be unique"
            raise ValueError(msg)
        overlap = sorted(set(self.columns) & set(outputs))
        if overlap:
            msg = f"group_by aggregate outputs cannot overlap key columns: {overlap}"
            raise ValueError(msg)
        return self


class TableUnpivotOperation(OmitUnsetNoneConfigModel):
    """Convert wide values to ordered label/value rows."""

    operation: Literal["unpivot"]
    index: list[NonEmptyString]
    columns: dict[NonEmptyString, NonEmptyString] | None = None
    variable_name: NonEmptyString
    value_name: NonEmptyString
    value_type_name: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_unpivot(self) -> TableUnpivotOperation:
        """Reject duplicate identifiers and output-name collisions."""
        if len(set(self.index)) != len(self.index):
            msg = "unpivot index columns must be unique"
            raise ValueError(msg)
        if "value_type_name" in self.model_fields_set and self.value_type_name is None:
            msg = "unpivot 'value_type_name' must be omitted when unused, not null"
            raise ValueError(msg)
        names = [*self.index, self.variable_name, self.value_name]
        if self.value_type_name is not None:
            names.append(self.value_type_name)
        if len(set(names)) != len(names):
            msg = "unpivot output names must be distinct from identifiers and each other"
            raise ValueError(msg)
        if "columns" in self.model_fields_set and self.columns is None:
            msg = "unpivot 'columns' must be omitted for dynamic selection, not null"
            raise ValueError(msg)
        if self.columns is not None and not self.columns:
            msg = "unpivot columns map must be non-empty when provided"
            raise ValueError(msg)
        if self.columns is not None and len(set(self.columns.values())) != len(self.columns):
            msg = "unpivot value columns must be unique"
            raise ValueError(msg)
        return self


class TableConcatOperation(StrictConfigModel):
    """Construct one table by appending earlier tables in declared order."""

    operation: Literal["concat"]
    sources: Annotated[list[NonEmptyString], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_sources(self) -> TableConcatOperation:
        """Reject duplicate inputs whose output ordering would be ambiguous."""
        if len(set(self.sources)) != len(self.sources):
            msg = "concat sources must be unique"
            raise ValueError(msg)
        return self


class TableFirstPresentOperation(StrictConfigModel):
    """Use the first present source in declared order as a table constructor."""

    operation: Literal["first_present"]
    sources: Annotated[list[NonEmptyString], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_sources(self) -> TableFirstPresentOperation:
        """Reject repeated candidates whose precedence would be ambiguous."""
        if len(set(self.sources)) != len(self.sources):
            msg = "first_present sources must be unique"
            raise ValueError(msg)
        return self


class TableFirstNonEmptyOperation(OmitUnsetNoneConfigModel):
    """Use the first nonempty source, or a named fallback, as a table constructor."""

    operation: Literal["first_nonempty"]
    sources: Annotated[list[NonEmptyString], Field(min_length=1)]
    fallback: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_sources(self) -> TableFirstNonEmptyOperation:
        """Reject repeated candidates and an ambiguous candidate/fallback name."""
        if len(set(self.sources)) != len(self.sources):
            msg = "first_nonempty sources must be unique"
            raise ValueError(msg)
        if "fallback" in self.model_fields_set and self.fallback is None:
            msg = "first_nonempty 'fallback' must be omitted when unused, not null"
            raise ValueError(msg)
        if self.fallback in self.sources:
            msg = "first_nonempty fallback must not repeat a candidate"
            raise ValueError(msg)
        return self


class TableRowsColumn(StrictConfigModel):
    """Declare one typed column for a rows constructor."""

    name: NonEmptyString
    dtype: TableColumnType


class TableRowsOperation(StrictConfigModel):
    """Construct a table from explicitly typed literal or bound rows."""

    model_config = ConfigDict(serialize_by_alias=True)

    operation: Literal["rows"]
    row_schema: Annotated[list[TableRowsColumn], Field(min_length=1)] = Field(alias="schema")
    values: list[dict[NonEmptyString, JSONValue]] | ProcessingPlaceholder

    @model_validator(mode="after")
    def validate_schema(self) -> TableRowsOperation:
        """Require distinct output fields in constructor schema order."""
        names = [column.name for column in self.row_schema]
        if len(set(names)) != len(names):
            msg = "rows schema names must be unique"
            raise ValueError(msg)
        return self


class TableFillNullOperation(OmitUnsetNoneConfigModel):
    """Replace null values in explicitly selected columns."""

    operation: Literal["fill_null"]
    columns: Annotated[list[NonEmptyString], Field(min_length=1)]
    value: TableScalar | list[TableScalar] | ProcessingPlaceholder = None
    from_columns: Annotated[list[NonEmptyString], Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def validate_columns(self) -> TableFillNullOperation:
        """Require one fill source and unique target and backup names."""
        if len(set(self.columns)) != len(self.columns):
            msg = "fill_null columns must be unique"
            raise ValueError(msg)
        has_value = "value" in self.model_fields_set
        has_from_columns = "from_columns" in self.model_fields_set
        if has_value == has_from_columns:
            msg = "fill_null requires exactly one of value or from_columns"
            raise ValueError(msg)
        if has_from_columns and self.from_columns is None:
            msg = "fill_null 'from_columns' must be omitted when unused, not null"
            raise ValueError(msg)
        if self.from_columns is not None and len(set(self.from_columns)) != len(self.from_columns):
            msg = "fill_null from_columns must be unique"
            raise ValueError(msg)
        return self


class TableHeadOperation(StrictConfigModel):
    """Retain the first declared number of rows in their current order."""

    operation: Literal["head"]
    n: Annotated[StrictInt, Field(ge=0)]


class TableSortOperation(StrictConfigModel):
    """Sort by stable, null-last key priority."""

    operation: Literal["sort"]
    columns: Annotated[list[NonEmptyString], Field(min_length=1)]
    descending: StrictBool = False

    @model_validator(mode="after")
    def validate_columns(self) -> TableSortOperation:
        """Reject repeated sort keys."""
        if len(set(self.columns)) != len(self.columns):
            msg = "sort columns must be unique"
            raise ValueError(msg)
        return self


class TableUniqueOperation(StrictConfigModel):
    """Select complete rows by explicit keys and current row order."""

    operation: Literal["unique"]
    columns: Annotated[list[NonEmptyString], Field(min_length=1)]
    keep: Literal["first", "last"]

    @model_validator(mode="after")
    def validate_columns(self) -> TableUniqueOperation:
        """Reject duplicate selection keys."""
        if len(set(self.columns)) != len(self.columns):
            msg = "unique columns must be unique"
            raise ValueError(msg)
        return self


class TableCastOperation(StrictConfigModel):
    """Strictly convert one existing column in place."""

    operation: Literal["cast"]
    column: NonEmptyString
    dtype: TableColumnType


class TableObjectOperation(StrictConfigModel):
    """Create one plain object column from exact fields or literal text."""

    operation: Literal["object"]
    columns: dict[NonEmptyString, TableObjectProjectionValue] = Field(min_length=1)
    output: NonEmptyString


class TableListOperation(StrictConfigModel):
    """Create an ordered list column from exact input columns."""

    operation: Literal["list"]
    columns: Annotated[list[NonEmptyString], Field(min_length=1)]
    output: NonEmptyString

    @model_validator(mode="after")
    def validate_columns(self) -> TableListOperation:
        """Reject repeated input references that make the declared list ambiguous."""
        if len(set(self.columns)) != len(self.columns):
            msg = "list columns must be unique"
            raise ValueError(msg)
        return self


TableOperation: TypeAlias = Annotated[
    TableJoinOperation
    | TableMatchSourcePatternsOperation
    | TableMatchPatternsOperation
    | TableMultiplyOperation
    | TableAddOperation
    | TableDivideOperation
    | TableAbsoluteOperation
    | TableCasefoldOperation
    | TableDateTimePartOperation
    | TableConcatStringsOperation
    | TableSplitOperation
    | TableFilterOperation
    | TableChooseOperation
    | TableGroupByOperation
    | TableUnpivotOperation
    | TableConcatOperation
    | TableFirstPresentOperation
    | TableFirstNonEmptyOperation
    | TableRowsOperation
    | TableFillNullOperation
    | TableHeadOperation
    | TableSortOperation
    | TableUniqueOperation
    | TableCastOperation
    | TableObjectOperation
    | TableListOperation,
    Field(discriminator="operation"),
]


class TableMappingRecord(OmitUnsetNoneConfigModel):
    """Define one source-based named table, projection, and optional materialization boundary."""

    name: NonEmptyString
    source: NonEmptyString | None = None
    operations: list[TableOperation]
    columns: dict[NonEmptyString, TableProjectionValue] | None = Field(default=None, min_length=1)
    materialize: StrictBool = False

    @model_validator(mode="after")
    def validate_record(self) -> TableMappingRecord:
        """Require either a source or one first-position constructor."""
        if "source" in self.model_fields_set and self.source is None:
            msg = "table 'source' must be omitted for constructors, not null"
            raise ValueError(msg)
        if "columns" in self.model_fields_set and self.columns is None:
            msg = "table 'columns' must be omitted when unused, not null"
            raise ValueError(msg)
        constructor_positions = [
            index
            for index, operation in enumerate(self.operations)
            if isinstance(
                operation,
                (
                    TableConcatOperation,
                    TableFirstPresentOperation,
                    TableFirstNonEmptyOperation,
                    TableRowsOperation,
                ),
            )
        ]
        if self.source is None:
            if not constructor_positions or constructor_positions[0] != 0:
                msg = "table without 'source' must start with a rows, concat, first_present, or first_nonempty constructor"
                raise ValueError(msg)
            if len(constructor_positions) != 1:
                msg = "a table may contain only one constructor, in first position"
                raise ValueError(msg)
        elif constructor_positions:
            msg = "source-based tables cannot contain rows, concat, first_present, or first_nonempty constructors"
            raise ValueError(msg)
        return self


def reject_nonstandard_json_number(value: str, /) -> None:
    """Reject JavaScript numeric values that are not valid JSON numbers."""
    msg = f"Invalid JSON numeric constant {value!r}"
    raise ValueError(msg)


def reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject repeated JSON object members instead of accepting last-value-wins."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            msg = f"Duplicate JSON key {key!r}"
            raise ValueError(msg)
        result[key] = value
    return result


def load_table_mapping(mapping_path: Path, /) -> list[TableMappingRecord]:
    """Load one JSON array of strict named-table records."""
    raw_mapping = json.loads(
        mapping_path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
        parse_constant=reject_nonstandard_json_number,
    )
    return TypeAdapter(list[TableMappingRecord]).validate_python(
        raw_mapping,
        by_alias=True,
        by_name=False,
    )


def table_record_sources(record: TableMappingRecord, /) -> tuple[str, ...]:
    """Return the exact named sources consumed by one table record."""
    references: list[str] = []
    if record.source is not None:
        references.append(record.source)
    for operation in record.operations:
        if isinstance(operation, (TableJoinOperation, TableMatchSourcePatternsOperation)):
            references.append(operation.source)
        elif isinstance(
            operation, (TableConcatOperation, TableFirstPresentOperation, TableFirstNonEmptyOperation)
        ):
            references.extend(operation.sources)
            if isinstance(operation, TableFirstNonEmptyOperation) and operation.fallback is not None:
                references.append(operation.fallback)
    return tuple(references)


def validate_table_mapping_records(
    records: Sequence[TableMappingRecord],
    sources: Mapping[str, DecodedSource],
    *,
    initial_tables: Mapping[str, TabularSource] | None = None,
    table_names: Sequence[str] | None = None,
    declared_source_names: Sequence[str] = (),
    absent_source_names: Sequence[str] = (),
) -> set[str]:
    """Reject invalid outputs and resolve a selected table dependency closure.

    See Also
    --------
    :meth:`~r2x_core.DataReader.read_and_assemble_records` : Assemble supplied records with decoded sources.
    :doc:`table-mapping` : Table mapping configuration and assembly.
    :doc:`data-workflow` : Source and table dependency ordering.
    """
    record_names = [record.name for record in records]
    record_by_name = {record.name: record for record in records}
    record_indices = {record.name: index for index, record in enumerate(records)}
    if len(record_by_name) != len(record_names):
        msg = "Duplicate table name in table mapping"
        raise ValueError(msg)

    seeded_tables = dict(initial_tables or {})
    if any(not isinstance(name, str) or not name for name in declared_source_names):
        msg = "Declared source names must be non-empty strings"
        raise ValueError(msg)
    if any(not isinstance(name, str) or not name for name in absent_source_names):
        msg = "Absent source names must be non-empty strings"
        raise ValueError(msg)
    declared_names = set(declared_source_names)
    absent_names = set(absent_source_names)
    invalid_tables = [
        name
        for name, table in seeded_tables.items()
        if not isinstance(name, str) or not name or not isinstance(table, TabularSource)
    ]
    if invalid_tables:
        msg = "Initial tables must use non-empty string names and TabularSource values"
        raise TypeError(msg)
    conflicting_absent_names = absent_names & (sources.keys() | seeded_tables.keys() | record_by_name.keys())
    if conflicting_absent_names:
        msg = (
            "Absent source names cannot also identify decoded values or table outputs: "
            f"{sorted(conflicting_absent_names)[0]!r}"
        )
        raise ValueError(msg)
    undeclared_tables = set(seeded_tables) - record_by_name.keys()
    if undeclared_tables:
        msg = f"Initial table is not declared by the table mapping: {sorted(undeclared_tables)[0]!r}"
        raise ValueError(msg)
    seed_collisions = set(seeded_tables) & sources.keys()
    if seed_collisions:
        msg = f"Initial table collides with an input source: {sorted(seed_collisions)[0]!r}"
        raise ValueError(msg)

    collisions = (set(record_names) & sources.keys()) - seeded_tables.keys()
    if collisions:
        msg = f"Table name collides with an input source: {sorted(collisions)[0]!r}"
        raise ValueError(msg)

    if table_names is None:
        requested_names = record_names
    else:
        requested_names = list(table_names)
        if not requested_names or any(not isinstance(name, str) or not name for name in requested_names):
            msg = "table_names must contain one or more non-empty names"
            raise ValueError(msg)
        if len(set(requested_names)) != len(requested_names):
            msg = "table_names must be unique"
            raise ValueError(msg)

    required_names: set[str] = set()

    def optional_selection_candidates(record: TableMappingRecord, /) -> set[str]:
        """Return first-source candidates that may be absent for this record.

        Parameters
        ----------
        record : TableMappingRecord
            Table declaration being checked.

        Returns
        -------
        set of str
            Sources selected by a first-present or first-nonempty operation
            that are not referenced by later operations.
        """
        if (
            record.source is None
            and record.operations
            and isinstance(record.operations[0], (TableFirstPresentOperation, TableFirstNonEmptyOperation))
        ):
            constructor = record.operations[0]
            later_references = table_record_sources(record)[len(constructor.sources) :]
            return set(constructor.sources) - set(later_references)
        return set()

    def include_table(name: str, /) -> None:
        """Add a table and its table dependencies to the required closure.

        Parameters
        ----------
        name : str
            Name of a declared table output.

        Raises
        ------
        ValueError
            If the table or one of its non-optional sources is unknown, or if a
            table dependency is declared after its consumer.
        """
        if name in required_names:
            return
        record = record_by_name.get(name)
        if record is None:
            msg = f"Unknown table output {name!r}"
            raise ValueError(msg) from None

        required_names.add(name)
        record_index = record_indices[name]
        optional_candidates = optional_selection_candidates(record)
        if name in seeded_tables:
            for source_name in table_record_sources(record):
                if source_name in sources:
                    continue
                if (
                    source_name in optional_candidates
                    and source_name in absent_names
                    and source_name not in record_by_name
                ):
                    continue
                if (
                    source_name in declared_names
                    and source_name not in absent_names
                    and source_name not in record_by_name
                ):
                    continue
                if source_name in record_by_name:
                    if record_indices[source_name] >= record_index:
                        msg = f"Table source {source_name!r} is referenced before it is declared"
                        raise ValueError(msg)
                    if source_name in seeded_tables:
                        include_table(source_name)
                    continue
                msg = f"Unknown table source {source_name!r}"
                raise ValueError(msg)
            return

        for source_name in table_record_sources(record):
            if source_name in sources:
                continue
            if (
                source_name in optional_candidates
                and source_name in absent_names
                and source_name not in record_by_name
            ):
                continue
            if source_name in record_by_name:
                if record_indices[source_name] >= record_index:
                    msg = f"Table source {source_name!r} is referenced before it is declared"
                    raise ValueError(msg)
                include_table(source_name)
                continue
            msg = f"Unknown table source {source_name!r}"
            raise ValueError(msg)

    for requested_name in requested_names:
        include_table(requested_name)

    return required_names


def require_tabular_source(source: DecodedSource, /, *, name: str) -> TabularSource:
    """Require a named source to expose the public tabular-source contract."""
    if not isinstance(source, TabularSource):
        msg = f"Table mapping source {name!r} must be tabular"
        raise TypeError(msg)
    return source


def resolve_scalar_binding(
    value: TableScalar | ProcessingPlaceholder, *, placeholders: Mapping[str, JSONValue]
) -> TableScalar:
    """Resolve one whole-value binding and reject unresolved or structured results."""
    if not isinstance(value, str):
        if type(value) is float and not isfinite(value):
            msg = "Table-mapping literal must resolve to a finite number"
            raise ValueError(msg)
        return value
    match = PLACEHOLDER_PATTERN.fullmatch(value)
    if match is None:
        if PLACEHOLDER_PATTERN.search(value):
            msg = "Partial table-mapping placeholder interpolation is not supported"
            raise ValueError(msg)
        return value
    name = match.group(1)
    if name not in placeholders:
        msg = f"Table-mapping placeholder {name!r} is unresolved"
        raise ValueError(msg)
    resolved = placeholders[name]
    if resolved is None:
        return None
    if type(resolved) is bool:
        return resolved
    if type(resolved) is int:
        return resolved
    if type(resolved) is float:
        if not isfinite(resolved):
            msg = f"Table-mapping placeholder {name!r} must resolve to a finite number"
            raise ValueError(msg)
        return resolved
    if type(resolved) is str:
        return resolved
    msg = f"Table-mapping placeholder {name!r} must resolve to a scalar"
    raise ValueError(msg)


def resolve_value_operand(
    operand: NonEmptyString | TableScalarLiteral, *, placeholders: Mapping[str, JSONValue]
) -> TableValueSelection:
    """Resolve one choose branch to its exact input column or scalar value."""
    if isinstance(operand, str):
        return ("column", operand)
    return ("value", resolve_scalar_binding(operand.value, placeholders=placeholders))


def resolve_fill_value(
    value: TableScalar | list[TableScalar] | ProcessingPlaceholder,
    *,
    placeholders: Mapping[str, JSONValue],
) -> TableScalar | list[TableScalar]:
    """Resolve one scalar or flat scalar-list fill value."""
    if not isinstance(value, str):
        if type(value) is float and not isfinite(value):
            msg = "Table-mapping literal fill value must be a finite number"
            raise ValueError(msg)
        if isinstance(value, list) and any(type(item) is float and not isfinite(item) for item in value):
            msg = "Table-mapping literal fill values must contain finite numbers"
            raise ValueError(msg)
        return value
    match = PLACEHOLDER_PATTERN.fullmatch(value)
    if match is None:
        if PLACEHOLDER_PATTERN.search(value):
            msg = "Partial table-mapping placeholder interpolation is not supported"
            raise ValueError(msg)
        return value
    name = match.group(1)
    if name not in placeholders:
        msg = f"Table-mapping placeholder {name!r} is unresolved"
        raise ValueError(msg)
    bound = placeholders[name]
    if isinstance(bound, list):
        resolved = TypeAdapter(list[TableScalar]).validate_python(bound, strict=True)
        if any(type(item) is float and not isfinite(item) for item in resolved):
            msg = f"Table-mapping placeholder {name!r} must contain finite numbers"
            raise ValueError(msg)
        return resolved
    return resolve_scalar_binding(value, placeholders=placeholders)


def resolve_rows_binding(
    operation: TableRowsOperation, *, placeholders: Mapping[str, JSONValue]
) -> list[dict[str, object]]:
    """Resolve rows values and validate their exact declared shape and types."""
    values: object = operation.values
    if isinstance(values, str):
        name = values[1:-1]
        if name not in placeholders:
            msg = f"Table-mapping placeholder {name!r} is unresolved"
            raise ValueError(msg)
        values = placeholders[name]
    if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
        msg = "rows values must resolve to a list of records"
        raise ValueError(msg)
    raw_schema = {column.name: column.dtype for column in operation.row_schema}
    validated = InlineTable.model_validate({"schema": raw_schema, "rows": values})
    return parse_inline_table_rows(validated)


def assemble_tables(
    sources: DecodedSources,
    /,
    *,
    mapping_path: Path,
    backend: TableMappingBackend,
    placeholders: Mapping[str, JSONValue] | None = None,
    table_names: Sequence[str] | None = None,
    initial_tables: Mapping[str, TabularSource] | None = None,
    declared_source_names: Sequence[str] = (),
    absent_source_names: Sequence[str] = (),
) -> Mapping[str, TabularSource]:
    """Load one mapping file and assemble selected tables from decoded inputs.

    ``declared_source_names`` validates external source references on seeded
    table outputs without treating those names as decoded values.
    ``absent_source_names`` contains exact optional input names confirmed absent
    with no decoded source. It must be disjoint from decoded inputs, initial
    tables, and declared table outputs. Only ``first_present`` and
    ``first_nonempty`` constructors may skip these names; ordinary operations
    still require their sources. A record's ``materialize`` flag snapshots its
    final projected output eagerly for downstream reuse.

    See Also
    --------
    :meth:`~r2x_core.DataReader.read_and_assemble_sources` : Schedule file and table inputs together.
    :doc:`table-mapping` : Table mapping configuration and assembly.
    :doc:`data-workflow` : Source and table dependency ordering.
    """
    records = load_table_mapping(mapping_path)
    return assemble_table_records(
        sources,
        records,
        backend=backend,
        placeholders=placeholders,
        table_names=table_names,
        initial_tables=initial_tables,
        declared_source_names=declared_source_names,
        absent_source_names=absent_source_names,
    )


def assemble_table_records(
    sources: DecodedSources,
    records: Sequence[TableMappingRecord],
    /,
    *,
    backend: TableMappingBackend,
    placeholders: Mapping[str, JSONValue] | None = None,
    table_names: Sequence[str] | None = None,
    initial_tables: Mapping[str, TabularSource] | None = None,
    declared_source_names: Sequence[str] = (),
    absent_source_names: Sequence[str] = (),
) -> Mapping[str, TabularSource]:
    """Assemble selected outputs from one already validated mapping snapshot.

    Omitting ``table_names`` assembles every record, preserving the ordered
    one-phase contract. Selected records include their declared table
    dependencies. ``initial_tables`` supplies already-assembled outputs by
    name so a scheduler can reuse them without rerunning work.
    ``declared_source_names`` validates external references on seeded table
    outputs without treating those names as decoded values.
    ``absent_source_names`` identifies exact optional input names confirmed
    absent with no decoded source. It must be disjoint from decoded inputs,
    initial tables, and declared table outputs. Only ``first_present`` and
    ``first_nonempty`` constructors may skip these names; ordinary operations
    still require their sources. A record with ``materialize=True`` snapshots
    its final projected output in memory before dependent records run, so lazy
    evaluation errors can surface during assembly. Seeded ``initial_tables``
    are returned unchanged and bypass record operations, projection, and
    materialization.

    See Also
    --------
    :meth:`~r2x_core.DataReader.read_and_assemble_records` : Schedule supplied records with input files.
    :doc:`table-mapping` : Table mapping configuration and assembly.
    :doc:`data-workflow` : Source and table dependency ordering.
    """
    records = TypeAdapter(list[TableMappingRecord]).validate_python(records)
    seeded_tables = dict(initial_tables or {})
    required_names = validate_table_mapping_records(
        records,
        sources,
        initial_tables=seeded_tables,
        table_names=table_names,
        declared_source_names=declared_source_names,
        absent_source_names=absent_source_names,
    )
    bindings = placeholders or {}
    available_sources = dict(sources)
    available_sources.update(seeded_tables)
    output_tables: dict[str, TabularSource] = {}

    for record in records:
        if record.name not in required_names:
            continue
        if record.name in seeded_tables:
            output_tables[record.name] = seeded_tables[record.name]
            continue
        if record.source is not None:
            table = require_tabular_source(available_sources[record.source], name=record.source)
            operations = record.operations
        else:
            constructor = record.operations[0]
            if isinstance(constructor, TableRowsOperation):
                values = resolve_rows_binding(constructor, placeholders=bindings)
                row_schema: list[tuple[str, TableColumnType]] = [
                    (column.name, column.dtype) for column in constructor.row_schema
                ]
                table = backend.create_rows(schema=row_schema, values=values)
            elif isinstance(constructor, TableConcatOperation):
                concat_sources = [
                    require_tabular_source(available_sources[name], name=name) for name in constructor.sources
                ]
                table = backend.concat_tables(concat_sources)
            elif isinstance(constructor, TableFirstPresentOperation):
                table = None
                for source_name in constructor.sources:
                    source = available_sources.get(source_name)
                    if source is None:
                        if source_name in absent_source_names:
                            continue
                        msg = f"First-present source {source_name!r} is not available"
                        raise ValueError(msg)
                    candidate = require_tabular_source(source, name=source_name)
                    if candidate.availability is SourceAvailability.PRESENT:
                        table = candidate
                        break
                if table is None:
                    msg = f"No present source among first_present candidates {constructor.sources!r}"
                    raise ValueError(msg)
            elif isinstance(constructor, TableFirstNonEmptyOperation):
                table = None
                for source_name in constructor.sources:
                    source = available_sources.get(source_name)
                    if source is None:
                        if source_name in absent_source_names:
                            continue
                        msg = f"First-nonempty source {source_name!r} is not available"
                        raise ValueError(msg)
                    candidate = require_tabular_source(source, name=source_name)
                    if candidate.availability is SourceAvailability.PRESENT and not candidate.is_empty():
                        table = candidate
                        break
                if table is None:
                    if constructor.fallback is None:
                        msg = f"No nonempty source among first_nonempty candidates {constructor.sources!r}"
                        raise ValueError(msg)
                    table = require_tabular_source(
                        available_sources[constructor.fallback], name=constructor.fallback
                    )
            else:
                msg = f"Unsupported table constructor {constructor.operation!r}"
                raise ValueError(msg)
            operations = record.operations[1:]

        for operation in operations:
            if isinstance(operation, TableJoinOperation):
                right = require_tabular_source(available_sources[operation.source], name=operation.source)
                table = backend.join_tables(
                    table,
                    right,
                    how=operation.how,
                    on=operation.on,
                    columns=operation.columns,
                )
            elif isinstance(operation, TableMatchSourcePatternsOperation):
                pattern_source = require_tabular_source(
                    available_sources[operation.source], name=operation.source
                )
                table = backend.match_source_patterns(table, pattern_source, step=operation)
            elif isinstance(operation, TableMatchPatternsOperation):
                table = backend.match_patterns(table, options=operation)
            elif isinstance(operation, TableMultiplyOperation):
                table = backend.multiply_columns(
                    table,
                    columns=operation.columns,
                    output=operation.output,
                )
            elif isinstance(operation, TableAddOperation):
                table = backend.add_columns(
                    table,
                    columns=operation.columns,
                    output=operation.output,
                )
            elif isinstance(operation, TableDivideOperation):
                table = backend.divide_columns(
                    table,
                    columns=operation.columns,
                    output=operation.output,
                )
            elif isinstance(operation, TableAbsoluteOperation):
                table = backend.absolute_column(table, column=operation.column, output=operation.output)
            elif isinstance(operation, TableCasefoldOperation):
                table = backend.casefold_column(table, column=operation.column, output=operation.output)
            elif isinstance(operation, TableDateTimePartOperation):
                table = backend.datetime_part(
                    table,
                    column=operation.column,
                    part=operation.part,
                    output=operation.output,
                )
            elif isinstance(operation, TableConcatStringsOperation):
                table = backend.concat_strings(
                    table,
                    columns=operation.columns,
                    separator=operation.separator,
                    output=operation.output,
                )
            elif isinstance(operation, TableObjectOperation):
                projection: dict[str, tuple[Literal["column", "value"], str]] = {}
                for field, value in operation.columns.items():
                    projection[field] = (
                        ("column", value) if isinstance(value, str) else ("value", value.value)
                    )
                table = backend.create_object_column(table, columns=projection, output=operation.output)
            elif isinstance(operation, TableListOperation):
                table = backend.create_list_column(table, columns=operation.columns, output=operation.output)
            elif isinstance(operation, TableSplitOperation):
                table = backend.split_column(
                    table,
                    column=operation.column,
                    separator=operation.separator,
                    index=operation.index,
                    output=operation.output,
                )
            elif isinstance(operation, TableFilterOperation):
                value = (
                    resolve_scalar_binding(operation.value, placeholders=bindings)
                    if "value" in operation.model_fields_set
                    else None
                )
                table = backend.filter_rows(
                    table,
                    column=operation.column,
                    comparison=operation.comparison,
                    value=value,
                    other_column=operation.other_column,
                )
            elif isinstance(operation, TableChooseOperation):
                value = (
                    resolve_scalar_binding(operation.value, placeholders=bindings)
                    if "value" in operation.model_fields_set
                    else None
                )
                table = backend.choose_column(
                    table,
                    column=operation.column,
                    comparison=operation.comparison,
                    value=value,
                    other_column=operation.other_column,
                    then=resolve_value_operand(operation.then, placeholders=bindings),
                    otherwise=resolve_value_operand(operation.otherwise, placeholders=bindings),
                    output=operation.output,
                )
            elif isinstance(operation, TableGroupByOperation):
                aggregates: list[
                    tuple[Literal["sum", "max", "mean", "count", "first", "last", "list"], str, str]
                ] = [
                    (aggregate.operation, aggregate.column, aggregate.output)
                    for aggregate in operation.aggregate
                ]
                table = backend.group_by(
                    table,
                    columns=operation.columns,
                    aggregates=aggregates,
                )
            elif isinstance(operation, TableUnpivotOperation):
                table = backend.unpivot(
                    table,
                    index=operation.index,
                    columns=operation.columns,
                    variable_name=operation.variable_name,
                    value_name=operation.value_name,
                    value_type_name=operation.value_type_name,
                )
            elif isinstance(operation, TableFillNullOperation):
                if operation.from_columns is not None:
                    table = backend.fill_null(
                        table,
                        columns=operation.columns,
                        from_columns=operation.from_columns,
                    )
                else:
                    value = resolve_fill_value(operation.value, placeholders=bindings)
                    table = backend.fill_null(table, columns=operation.columns, value=value)
            elif isinstance(operation, TableHeadOperation):
                table = backend.head_rows(table, n=operation.n)
            elif isinstance(operation, TableSortOperation):
                table = backend.sort(table, columns=operation.columns, descending=operation.descending)
            elif isinstance(operation, TableUniqueOperation):
                table = backend.unique_rows(table, columns=operation.columns, keep=operation.keep)
            elif isinstance(operation, TableCastOperation):
                table = backend.cast_column(table, column=operation.column, dtype=operation.dtype)
            else:
                msg = f"Unexpected table operation {operation.operation!r} after its constructor"
                raise ValueError(msg)

        if record.columns is not None:
            projection: dict[str, TableProjectionSelection] = {}
            for output, value in record.columns.items():
                if isinstance(value, str):
                    projection[output] = ("column", value)
                elif isinstance(value, TableLiteral):
                    projection[output] = ("value", value.value)
                elif isinstance(value, TableProjectionLiteral):
                    literal = value.value
                    if value.dtype == "float64" and type(literal) is int:
                        literal = float(literal)
                    elif value.dtype == "datetime" and isinstance(literal, str):
                        literal = datetime.fromisoformat(literal)
                    projection[output] = ("typed_value", value.dtype, literal)
                else:
                    projection[output] = (
                        "optional_column",
                        value.optional_column,
                        value.dtype,
                    )
            table = backend.project_columns(table, columns=projection)

        if record.materialize:
            table = backend.materialize(table)

        output_tables[record.name] = require_tabular_source(table, name=record.name)
        available_sources[record.name] = table

    return output_tables
