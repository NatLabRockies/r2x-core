"""Backend contract and runner for tabular mapping operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, Protocol, TypeAlias, TypeVar

from pydantic import BaseModel
from rust_ok import Ok, Result, is_ok

from .datafile import DataFile
from .file_reader import TabularSource
from .models import MappingStep, MatchPatternsOptions, MatchSourcePatternsOptions
from .shared_types import FrameT

HandlerOptionsT = TypeVar("HandlerOptionsT", bound=BaseModel)
HandlerInputT = TypeVar("HandlerInputT")
HandlerOutputT = TypeVar("HandlerOutputT")


class MappingStepHandler(Protocol[HandlerOptionsT, HandlerInputT, HandlerOutputT]):
    """App-scoped handler contract for a custom mapping operation."""

    @property
    def options_model(self) -> type[HandlerOptionsT]:
        """Return the Pydantic model used to validate handler options."""
        ...

    @property
    def input_type(self) -> type[HandlerInputT]:
        """Declare the input type checked before handler execution."""
        ...

    @property
    def output_type(self) -> type[HandlerOutputT]:
        """Declare the output type checked after handler execution."""
        ...

    def apply(self, value: HandlerInputT, *, options: HandlerOptionsT) -> HandlerOutputT:
        """Consume an input value and return its declared output type."""
        ...


StepHandlers = Mapping[str, MappingStepHandler[Any, Any, Any]]


TableJoinHow: TypeAlias = Literal["inner", "left", "cross"]
TableDateTimePart: TypeAlias = Literal["year", "month", "day", "hour", "minute", "second"]
TableFilterComparison: TypeAlias = Literal[
    "equals",
    "not_equal",
    "less_than",
    "greater_than",
    "greater_than_or_equal",
    "less_than_or_equal",
    "starts_with",
    "is_null",
    "is_not_null",
]
TableColumnType: TypeAlias = Literal["bool", "int64", "float64", "string", "datetime"]
TableProjectionScalar: TypeAlias = str | int | float | bool | datetime | None
TableProjectionSelection: TypeAlias = (
    tuple[Literal["column"], str]
    | tuple[Literal["value"], str]
    | tuple[Literal["typed_value"], TableColumnType, TableProjectionScalar]
    | tuple[Literal["optional_column"], str, TableColumnType]
)
TableProjection: TypeAlias = Mapping[str, TableProjectionSelection]
TableObjectProjection: TypeAlias = Mapping[str, tuple[Literal["column", "value"], str]]
TableValueSelection: TypeAlias = tuple[Literal["column", "value"], str | int | float | bool | None]
TableFillValue: TypeAlias = str | int | float | bool | list[str | int | float | bool | None] | None


class TableMappingBackend(Protocol):
    """Execute named-table operations through a representation-specific backend."""

    def join_tables(
        self,
        left: TabularSource,
        right: TabularSource,
        *,
        how: TableJoinHow,
        on: Sequence[str] | None,
        columns: Sequence[str] | None,
    ) -> TabularSource:
        """Join two named tables with explicit keys and payload columns."""
        ...

    def match_source_patterns(
        self,
        source: TabularSource,
        pattern_source: TabularSource,
        *,
        step: MatchSourcePatternsOptions,
    ) -> TabularSource:
        """Resolve one exact, numeric-range, or delimited-prefix pattern per row."""
        ...

    def match_patterns(self, source: TabularSource, *, options: MatchPatternsOptions) -> TabularSource:
        """Emit every matching static literal exact/prefix group in declared order."""
        ...

    def multiply_columns(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        output: str,
    ) -> TabularSource:
        """Multiply two existing columns into a new output column."""
        ...

    def add_columns(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        output: str,
    ) -> TabularSource:
        """Add two numeric columns into a new column."""
        ...

    def divide_columns(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        output: str,
    ) -> TabularSource:
        """Divide two numeric columns into a new float64 column."""
        ...

    def absolute_column(self, source: TabularSource, *, column: str, output: str) -> TabularSource:
        """Take the absolute value of one numeric column into a new column."""
        ...

    def casefold_column(self, source: TabularSource, *, column: str, output: str) -> TabularSource:
        """Create a full Unicode casefolded string key while retaining its source column."""
        ...

    def datetime_part(
        self,
        source: TabularSource,
        *,
        column: str,
        part: TableDateTimePart,
        output: str,
    ) -> TabularSource:
        """Extract one datetime component as an int64 output column."""
        ...

    def concat_strings(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        separator: str,
        output: str,
    ) -> TabularSource:
        """Join ordered string and int64 values into a new string column."""
        ...

    def split_column(
        self,
        source: TabularSource,
        *,
        column: str,
        separator: str,
        index: int,
        output: str,
    ) -> TabularSource:
        """Select one exact string-split part into a new column."""
        ...

    def project_columns(
        self,
        source: TabularSource,
        *,
        columns: TableProjection,
    ) -> TabularSource:
        """Project named columns and literal text into the exact output schema."""
        ...

    def materialize(self, source: TabularSource, /) -> TabularSource:
        """Snapshot one fully projected table for reuse without recomputing its upstream plan."""
        ...

    def create_object_column(
        self,
        source: TabularSource,
        *,
        columns: TableObjectProjection,
        output: str,
    ) -> TabularSource:
        """Create one plain object column from exact references and literal text."""
        ...

    def create_list_column(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        output: str,
    ) -> TabularSource:
        """Create one ordered list column from compatible exact references."""
        ...

    def filter_rows(
        self,
        source: TabularSource,
        *,
        column: str,
        comparison: TableFilterComparison,
        value: str | int | float | bool | None = None,
        other_column: str | None = None,
    ) -> TabularSource:
        """Retain rows whose exact named columns or scalar meet one comparison."""
        ...

    def choose_column(
        self,
        source: TabularSource,
        *,
        column: str,
        comparison: TableFilterComparison,
        value: str | int | float | bool | None,
        other_column: str | None,
        then: TableValueSelection,
        otherwise: TableValueSelection,
        output: str,
    ) -> TabularSource:
        """Create a row-preserving column from one comparison and two values."""
        ...

    def group_by(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        aggregates: Sequence[
            tuple[Literal["sum", "max", "mean", "count", "first", "last", "list"], str, str]
        ],
    ) -> TabularSource:
        """Group rows in first-seen order or aggregate all rows globally."""
        ...

    def unpivot(
        self,
        source: TabularSource,
        *,
        index: Sequence[str],
        columns: Mapping[str, str] | None,
        variable_name: str,
        value_name: str,
        value_type_name: str | None = None,
    ) -> TabularSource:
        """Convert explicit or all non-index wide values into ordered rows."""
        ...

    def create_rows(
        self,
        *,
        schema: Sequence[tuple[str, TableColumnType]],
        values: Sequence[Mapping[str, object]],
    ) -> TabularSource:
        """Construct a typed table from validated literal records."""
        ...

    def concat_tables(self, sources: Sequence[TabularSource]) -> TabularSource:
        """Append schema-compatible tables by name in the declared source order."""
        ...

    def unique_rows(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        keep: Literal["first", "last"],
    ) -> TabularSource:
        """Select complete unique rows and retain their selected source order."""
        ...

    def cast_column(
        self,
        source: TabularSource,
        *,
        column: str,
        dtype: TableColumnType,
    ) -> TabularSource:
        """Strictly convert one existing column to its declared scalar type."""
        ...

    def fill_null(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        value: TableFillValue = None,
        from_columns: Sequence[str] | None = None,
    ) -> TabularSource:
        """Replace nulls from one scalar, flat list, or ordered backup columns."""
        ...

    def head_rows(self, source: TabularSource, *, n: int) -> TabularSource:
        """Retain the first ``n`` rows in the source's current order."""
        ...

    def sort(
        self, source: TabularSource, *, columns: Sequence[str], descending: bool = False
    ) -> TabularSource:
        """Sort stably in one direction and place null values last."""
        ...


class MappingStepBackend(Protocol[FrameT]):
    """Execute ordered mapping steps independently of DataFile processing."""

    def apply_mapping_operation(
        self,
        step: MappingStep,
        frame: FrameT,
        *,
        source_frames: Mapping[str, FrameT],
        data_file: DataFile | None = None,
    ) -> Result[FrameT, ValueError]:
        """Apply one mapping operation to a frame."""
        ...


def apply_mapping_steps(
    frame: FrameT,
    steps: Sequence[MappingStep],
    *,
    backend: MappingStepBackend[FrameT],
    source_frames: Mapping[str, FrameT] | None = None,
    data_file: DataFile | None = None,
) -> Result[FrameT, ValueError]:
    """Run ordered mapping steps through the selected tabular backend."""
    if source_frames is None:
        source_frames = {}
    for step in steps:
        result = backend.apply_mapping_operation(
            step, frame, source_frames=source_frames, data_file=data_file
        )
        if is_ok(result):
            frame = result.value
        else:
            return result
    return Ok(frame)
