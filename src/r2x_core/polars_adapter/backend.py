"""Polars implementation of the tabular backend contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, TypeAlias

import polars as pl
from rust_ok import Err, Ok, Result

from ..datafile import DataFile
from ..file_reader import DecodedSource, SourceAvailability, TabularSource
from ..models import (
    ConcatStep,
    CustomStep,
    JoinStep,
    MappingStep,
    MatchPatternsOptions,
    MatchSourcePatternsOptions,
    MatchSourcePatternsStep,
    TabularProcessing,
)
from ..tabular_backend import (
    MappingStepHandler,
    TableColumnType,
    TableDateTimePart,
    TableFillValue,
    TableFilterComparison,
    TableJoinHow,
    TableObjectProjection,
    TableProjection,
    TableValueSelection,
    apply_mapping_steps,
)
from ..types import FileProcessing
from .expressions import exact_column_expression
from .frames import collect_polars_frame
from .processing import (
    apply_polars_step,
    match_patterns,
    match_source_patterns,
    require_columns,
    unpivot_polars_frame,
)

JoinHow: TypeAlias = Literal["inner", "left", "right", "full", "semi", "anti", "cross"]
JoinValidation: TypeAlias = Literal["m:m", "m:1", "1:m", "1:1"]
PolarsDType: TypeAlias = pl.DataType | type[pl.DataType]


def comparison_expression(
    *,
    schema: pl.Schema,
    column: str,
    comparison: TableFilterComparison,
    value: str | int | float | bool | None,
    other_column: str | None,
    operation: str,
) -> pl.Expr:
    """Build one validated exact-column comparison for filtering or selection."""
    names = schema.names()
    require_columns(names, [column], operation=operation)
    if comparison == "starts_with" and schema[column] != pl.String:
        msg = f"{operation.capitalize()} starts_with column {column!r} must have a string dtype"
        raise ValueError(msg)
    expression = exact_column_expression(column, column_names=names)
    if comparison == "is_null":
        return expression.is_null()
    if comparison == "is_not_null":
        return expression.is_not_null()

    if other_column is not None:
        require_columns(names, [other_column], operation=operation)
        if schema[column] != schema[other_column]:
            msg = f"{operation.capitalize()} column types must match exactly: {column!r} and {other_column!r}"
            raise ValueError(msg)
        comparison_value = exact_column_expression(other_column, column_names=names)
    else:
        if value is None:
            return pl.lit(False)
        dtype = schema[column]
        predicate_value: str | int | float | bool | datetime = value
        if dtype.is_numeric():
            compatible = type(value) in {int, float}
        elif dtype == pl.String:
            compatible = type(value) is str
        elif dtype == pl.Boolean:
            compatible = type(value) is bool
        elif isinstance(dtype, pl.Datetime):
            compatible = type(value) is str
            if isinstance(value, str):
                try:
                    predicate_value = datetime.fromisoformat(value)
                except ValueError as error:
                    msg = f"{operation.capitalize()} value {value!r} is not an ISO datetime"
                    raise ValueError(msg) from error
        else:
            compatible = False
        if not compatible:
            msg = (
                f"{operation.capitalize()} value type {type(value).__name__} is incompatible "
                f"with column {column!r} ({dtype})"
            )
            raise ValueError(msg)
        comparison_value = pl.lit(predicate_value)

    match comparison:
        case "equals":
            return expression == comparison_value
        case "not_equal":
            return expression != comparison_value
        case "less_than":
            return expression < comparison_value
        case "greater_than":
            return expression > comparison_value
        case "greater_than_or_equal":
            return expression >= comparison_value
        case "less_than_or_equal":
            return expression <= comparison_value
        case "starts_with":
            return expression.str.starts_with(comparison_value)
        case "is_null" | "is_not_null":
            return pl.lit(False)


def join_exact_columns(
    left: pl.LazyFrame,
    right: pl.LazyFrame,
    *,
    on: list[str] | None,
    how: JoinHow,
    validate: JoinValidation,
) -> pl.LazyFrame:
    """Join named columns literally while retaining Polars join semantics."""
    if how == "cross":
        return left.join(right, how="cross")
    if on is None:
        return left.join(right, on=on, how=how, validate=validate)

    left_names = left.collect_schema().names()
    right_names = right.collect_schema().names()
    require_columns(left_names, on, operation="join")
    require_columns(right_names, on, operation="join")
    occupied_names = set(left_names) | set(right_names)
    temporary_names: dict[str, str] = {}
    for index, column in enumerate(dict.fromkeys(on)):
        temporary = f"__r2x_join_key_{index}__"
        while temporary in occupied_names or f"{temporary}_right" in occupied_names:
            temporary = f"_{temporary}"
        temporary_names[column] = temporary
        occupied_names.update((temporary, f"{temporary}_right"))

    joined = left.rename(temporary_names).join(
        right.rename(temporary_names),
        on=[temporary_names[column] for column in on],
        how=how,
        validate=validate,
    )
    restored_names = {temporary: column for column, temporary in temporary_names.items()}
    if how == "full":
        restored_names.update(
            {f"{temporary}_right": f"{column}_right" for column, temporary in temporary_names.items()}
        )
    return joined.rename(restored_names)


class PolarsTabularBackend:
    """Implement tabular processing and mapping operations with Polars."""

    def __init__(
        self,
        *,
        step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]] | None = None,
    ) -> None:
        """Configure optional app-provided handlers for custom table steps."""
        self.step_handlers = dict(step_handlers or {})

    def source_with_frame(
        self,
        source: TabularSource,
        frame: pl.LazyFrame,
        *,
        availability: SourceAvailability | None = None,
        absent_inputs: frozenset[str] | None = None,
    ) -> TabularSource:
        """Keep source-availability metadata while replacing its table frame."""
        return TabularSource(
            frame,
            self,
            availability=source.availability if availability is None else availability,
            absent_inputs=source.absent_inputs if absent_inputs is None else absent_inputs,
        )

    def process(
        self,
        frame: pl.LazyFrame,
        /,
        *,
        processing: FileProcessing,
        sources: Mapping[str, DecodedSource],
        data_file: DataFile,
    ) -> Result[pl.LazyFrame, ValueError]:
        """Apply compatible ordered operations with Polars."""
        if not isinstance(processing, TabularProcessing):
            return Err(ValueError("PolarsTabularBackend requires TabularProcessing"))
        source_frames: dict[str, pl.LazyFrame] = {}
        for name, source in sources.items():
            if isinstance(source, TabularSource) and isinstance(source.data, pl.LazyFrame):
                source_frames[name] = source.data
        return apply_mapping_steps(
            frame,
            processing.steps,
            backend=self,
            source_frames=source_frames,
            data_file=data_file,
        )

    def column_names(self, frame: pl.LazyFrame, /) -> list[str]:
        """Return the lazy frame's declared column names."""
        return frame.collect_schema().names()

    def is_empty(self, frame: pl.LazyFrame, /) -> bool:
        """Check for at least one row without collecting the complete frame."""
        return collect_polars_frame(frame.limit(1)).is_empty()

    def iter_rows(self, frame: pl.LazyFrame, /) -> Iterable[Mapping[str, object]]:
        """Collect a frame and yield named row mappings."""
        return collect_polars_frame(frame).iter_rows(named=True)

    def values(self, frame: pl.LazyFrame, field: str, /) -> list[object]:
        """Collect one named column as values."""
        try:
            index = frame.collect_schema().names().index(field)
        except ValueError as error:
            msg = f"Table has no field {field!r}"
            raise ValueError(msg) from error
        return collect_polars_frame(frame.select(pl.nth(index))).to_series().to_list()

    def join_tables(
        self,
        left: TabularSource,
        right: TabularSource,
        *,
        how: TableJoinHow,
        on: Sequence[str] | None,
        columns: Sequence[str] | None,
    ) -> TabularSource:
        """Join tabular sources with explicit payload, key, null, and row-order semantics."""
        if not isinstance(left.data, pl.LazyFrame) or not isinstance(right.data, pl.LazyFrame):
            msg = "Polars table assembly requires Polars LazyFrame sources"
            raise TypeError(msg)

        left_frame = left.data
        right_frame = right.data
        left_schema = left_frame.collect_schema()
        right_schema = right_frame.collect_schema()
        left_names = left_schema.names()
        right_names = right_schema.names()

        temporary_keys: dict[str, str] = {}
        if how == "cross":
            if on is not None:
                msg = "cross joins must omit join keys"
                raise ValueError(msg)
            payload = right_names if columns is None else columns
        else:
            if on is None:
                msg = f"{how} joins require explicit keys"
                raise ValueError(msg)
            join_keys = list(on)
            require_columns(left_names, join_keys, operation="join")
            require_columns(right_names, join_keys, operation="join")
            occupied_names = set(left_names) | set(right_names)
            if any(key == "*" or (key.startswith("^") and key.endswith("$")) for key in join_keys):
                for index, key in enumerate(join_keys):
                    temporary = f"__r2x_table_mapping_key_{index}__"
                    while temporary in occupied_names:
                        temporary = f"_{temporary}"
                    temporary_keys[key] = temporary
                    occupied_names.add(temporary)
            mismatched = [key for key in join_keys if left_schema[key] != right_schema[key]]
            if mismatched:
                msg = f"Join key types must match exactly: {mismatched}"
                raise ValueError(msg)
            payload = (
                [column for column in right_names if column not in join_keys]
                if columns is None
                else list(columns)
            )
            invalid_keys = sorted(set(payload) & set(join_keys))
            if invalid_keys:
                msg = f"Join payload columns cannot include matching keys: {invalid_keys}"
                raise ValueError(msg)

        require_columns(right_names, list(payload), operation="join payload")
        collisions = sorted(set(left_names) & set(payload))
        if collisions:
            msg = f"Join payload column(s) collide with left table: {collisions}"
            raise ValueError(msg)

        if how == "cross":
            if payload:
                right_selected = right_frame.select(
                    [exact_column_expression(column, column_names=right_names) for column in payload]
                )
                joined = left_frame.join(
                    right_selected,
                    how="cross",
                    maintain_order="left_right",
                    suffix="",
                )
            else:
                row_index = "__r2x_table_mapping_right_row__"
                while row_index in left_names or row_index in right_names:
                    row_index = f"_{row_index}"
                right_selected = right_frame.with_row_index(row_index).select(row_index)
                joined = left_frame.join(
                    right_selected,
                    how="cross",
                    maintain_order="left_right",
                ).drop(row_index)
        else:
            right_selected = right_frame.select(
                [
                    *[exact_column_expression(column, column_names=right_names) for column in join_keys],
                    *[exact_column_expression(column, column_names=right_names) for column in payload],
                ]
            )
            left_join = left_frame
            if temporary_keys:
                right_selected = right_selected.rename(temporary_keys)
                left_join = left_join.rename(temporary_keys)
            joined = left_join.join(
                right_selected,
                on=[temporary_keys.get(key, key) for key in dict.fromkeys(join_keys)],
                how=how,
                nulls_equal=False,
                maintain_order="left_right",
                suffix="",
            )
            if temporary_keys:
                joined = joined.rename({temporary: key for key, temporary in temporary_keys.items()})
        return TabularSource(
            joined,
            self,
            availability=left.availability,
            absent_inputs=left.absent_inputs | right.absent_inputs,
        )

    def match_patterns(self, source: TabularSource, *, options: MatchPatternsOptions) -> TabularSource:
        """Apply static groups, preserving the shared matcher row and case semantics."""
        frame = self.require_table_frame(source)
        return self.source_with_frame(source, match_patterns(frame, step=options))

    def match_source_patterns(
        self,
        source: TabularSource,
        pattern_source: TabularSource,
        *,
        step: MatchSourcePatternsOptions,
    ) -> TabularSource:
        """Apply the shared generic matcher to the current and pattern tables."""
        left = self.require_table_frame(source)
        right = self.require_table_frame(pattern_source)
        return self.source_with_frame(
            source,
            match_source_patterns(left, right, step=step),
            absent_inputs=source.absent_inputs | pattern_source.absent_inputs,
        )

    def multiply_columns(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        output: str,
    ) -> TabularSource:
        """Multiply two numeric columns without changing row count or replacing fields."""
        if not isinstance(source.data, pl.LazyFrame):
            msg = "Polars table assembly requires Polars LazyFrame sources"
            raise TypeError(msg)
        frame = source.data
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, list(columns), operation="multiply")
        if output in names:
            msg = f"multiply output column {output!r} already exists"
            raise ValueError(msg)
        invalid = {column: schema[column] for column in columns if not schema[column].is_numeric()}
        if invalid:
            msg = f"multiply requires numeric columns: {invalid}"
            raise ValueError(msg)
        product = exact_column_expression(columns[0], column_names=names) * exact_column_expression(
            columns[1], column_names=names
        )
        return self.source_with_frame(source, frame.with_columns(product.alias(output)))

    def add_columns(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        output: str,
    ) -> TabularSource:
        """Add two numeric columns while retaining int64 when both inputs are int64."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, list(columns), operation="add")
        if output in names:
            msg = f"add output column {output!r} already exists"
            raise ValueError(msg)
        invalid = {column: schema[column] for column in columns if not schema[column].is_numeric()}
        if invalid:
            msg = f"add requires numeric columns: {invalid}"
            raise ValueError(msg)
        expressions = [exact_column_expression(column, column_names=names) for column in columns]
        if all(schema[column] == pl.Int64 for column in columns):
            result = expressions[0] + expressions[1]
        else:
            result = expressions[0].cast(pl.Float64) + expressions[1].cast(pl.Float64)
        return self.source_with_frame(source, frame.with_columns(result.alias(output)))

    def divide_columns(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        output: str,
    ) -> TabularSource:
        """Divide two numeric columns, returning null for a zero denominator."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, list(columns), operation="divide")
        if output in names:
            msg = f"divide output column {output!r} already exists"
            raise ValueError(msg)
        invalid = {column: schema[column] for column in columns if not schema[column].is_numeric()}
        if invalid:
            msg = f"divide requires numeric columns: {invalid}"
            raise ValueError(msg)
        numerator = exact_column_expression(columns[0], column_names=names).cast(pl.Float64)
        denominator = exact_column_expression(columns[1], column_names=names).cast(pl.Float64)
        quotient = numerator / denominator
        result = pl.when(denominator != 0).then(quotient).otherwise(pl.lit(None, dtype=pl.Float64))
        return self.source_with_frame(source, frame.with_columns(result.alias(output)))

    def absolute_column(self, source: TabularSource, *, column: str, output: str) -> TabularSource:
        """Take one numeric column's absolute value without changing its dtype or rows."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, [column], operation="absolute")
        if output in names:
            msg = f"absolute output column {output!r} already exists"
            raise ValueError(msg)
        if not schema[column].is_numeric():
            msg = f"absolute requires a numeric column, got {column!r}: {schema[column]}"
            raise ValueError(msg)
        result = exact_column_expression(column, column_names=names).abs().alias(output)
        return self.source_with_frame(source, frame.with_columns(result))

    def casefold_column(self, source: TabularSource, *, column: str, output: str) -> TabularSource:
        """Create a full Unicode casefolded key, preserving nulls and the original value."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, [column], operation="casefold")
        if schema[column] != pl.String:
            msg = f"casefold requires a string column, got {column!r}: {schema[column]}"
            raise ValueError(msg)
        if output in names:
            msg = f"casefold output column {output!r} already exists"
            raise ValueError(msg)
        result = (
            exact_column_expression(column, column_names=names)
            .map_elements(str.casefold, return_dtype=pl.String, skip_nulls=True)
            .alias(output)
        )
        return self.source_with_frame(source, frame.with_columns(result))

    def datetime_part(
        self,
        source: TabularSource,
        *,
        column: str,
        part: TableDateTimePart,
        output: str,
    ) -> TabularSource:
        """Extract one datetime part, preserving nulls, row order, and availability."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, [column], operation="datetime_part")
        if output in names:
            msg = f"datetime_part output column {output!r} already exists"
            raise ValueError(msg)
        if not isinstance(schema[column], pl.Datetime):
            msg = f"datetime_part requires a datetime column, got {column!r}: {schema[column]}"
            raise ValueError(msg)
        expression = exact_column_expression(column, column_names=names)
        if part == "year":
            value = expression.dt.year()
        elif part == "month":
            value = expression.dt.month()
        elif part == "day":
            value = expression.dt.day()
        elif part == "hour":
            value = expression.dt.hour()
        elif part == "minute":
            value = expression.dt.minute()
        elif part == "second":
            value = expression.dt.second()
        else:
            msg = f"Unsupported datetime_part component {part!r}"
            raise ValueError(msg)
        return self.source_with_frame(source, frame.with_columns(value.cast(pl.Int64).alias(output)))

    def concat_strings(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        separator: str,
        output: str,
    ) -> TabularSource:
        """Concatenate ordered string or integer values, propagating nulls."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        selected = list(columns)
        if not selected:
            msg = "concat_strings requires at least one input column"
            raise ValueError(msg)
        if len(set(selected)) != len(selected):
            msg = "concat_strings columns must be unique"
            raise ValueError(msg)
        require_columns(names, selected, operation="concat_strings")
        if output in names:
            msg = f"concat_strings output column {output!r} already exists"
            raise ValueError(msg)
        invalid = {
            column: schema[column]
            for column in selected
            if schema[column] != pl.String and not schema[column].is_integer()
        }
        if invalid:
            msg = f"concat_strings requires string or integer columns: {invalid}"
            raise ValueError(msg)
        values = [exact_column_expression(column, column_names=names).cast(pl.String) for column in selected]
        result = pl.concat_str(values, separator=separator, ignore_nulls=False).alias(output)
        return self.source_with_frame(source, frame.with_columns(result))

    def split_column(
        self,
        source: TabularSource,
        *,
        column: str,
        separator: str,
        index: int,
        output: str,
    ) -> TabularSource:
        """Select one literal string-split part into a new string column."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, [column], operation="split")
        if schema[column] != pl.String:
            msg = f"split requires a string column, got {column!r}: {schema[column]}"
            raise ValueError(msg)
        if output in names:
            msg = f"split output column {output!r} already exists"
            raise ValueError(msg)
        part = (
            exact_column_expression(column, column_names=names)
            .str.split(separator, literal=True)
            .list.get(index, null_on_oob=True)
            .alias(output)
        )
        return self.source_with_frame(source, frame.with_columns(part))

    def project_columns(
        self,
        source: TabularSource,
        *,
        columns: TableProjection,
    ) -> TabularSource:
        """Emit exactly the requested columns in sorted output-name order."""
        if not isinstance(source.data, pl.LazyFrame):
            msg = "Polars table assembly requires Polars LazyFrame sources"
            raise TypeError(msg)
        frame = source.data
        schema = frame.collect_schema()
        names = schema.names()
        literal_columns: dict[str, str] = {}
        literal_expressions: list[pl.Expr] = []
        dtype_mapping = {
            "bool": pl.Boolean,
            "int64": pl.Int64,
            "float64": pl.Float64,
            "string": pl.String,
            "datetime": pl.Datetime,
        }
        occupied_names = set(names) | set(columns)
        for index, (output, selection) in enumerate(sorted(columns.items())):
            match selection:
                case ("column", _):
                    continue
                case ("value", value):
                    expression = pl.lit(value, dtype=pl.String)
                case ("typed_value", dtype, value):
                    expression = pl.lit(value, dtype=dtype_mapping[dtype])
                case ("optional_column", input_column, dtype):
                    if input_column not in names:
                        expression = pl.lit(None, dtype=dtype_mapping[dtype])
                    else:
                        source_dtype = schema[input_column]
                        if dtype == "int64" and source_dtype.is_float():
                            msg = f"cast from floating-point to integer is unsupported for column {input_column!r}"
                            raise ValueError(msg)
                        expression = exact_column_expression(input_column, column_names=names)
                        if dtype == "datetime" and source_dtype == pl.String:
                            expression = expression.str.to_datetime(strict=True)
                        else:
                            expression = expression.cast(dtype_mapping[dtype], strict=True)
            temporary = f"__r2x_table_mapping_literal_{index}__"
            while temporary in occupied_names:
                temporary = f"_{temporary}"
            literal_columns[output] = temporary
            occupied_names.add(temporary)
            literal_expressions.append(expression.alias(temporary))
        projected = frame.with_columns(literal_expressions) if literal_expressions else frame
        projected_names = projected.collect_schema().names()
        expressions: list[pl.Expr] = []
        for output, selection in sorted(columns.items()):
            match selection:
                case ("column", input_column):
                    require_columns(names, [input_column], operation="projection")
                    expression = exact_column_expression(input_column, column_names=names)
                case _:
                    expression = exact_column_expression(
                        literal_columns[output], column_names=projected_names
                    )
            expressions.append(expression.alias(output))
        return self.source_with_frame(source, projected.select(expressions))

    def materialize(self, source: TabularSource, /) -> TabularSource:
        """Eagerly snapshot one table in memory while retaining its source metadata."""
        frame = self.require_table_frame(source)
        return self.source_with_frame(source, collect_polars_frame(frame).lazy())

    def create_object_column(
        self,
        source: TabularSource,
        *,
        columns: TableObjectProjection,
        output: str,
    ) -> TabularSource:
        """Build one plain struct column from sorted named fields and literal text."""
        frame = self.require_table_frame(source)
        names = frame.collect_schema().names()
        if output in names:
            msg = f"object output column {output!r} already exists"
            raise ValueError(msg)
        if not columns:
            msg = "object requires at least one field"
            raise ValueError(msg)

        fields: list[pl.Expr] = []
        for field, (kind, value) in sorted(columns.items()):
            if kind == "column":
                require_columns(names, [value], operation="object")
                expression = exact_column_expression(value, column_names=names)
            else:
                expression = pl.lit(value, dtype=pl.String)
            fields.append(expression.alias(field))
        return self.source_with_frame(source, frame.with_columns(pl.struct(fields).alias(output)))

    def create_list_column(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        output: str,
    ) -> TabularSource:
        """Build one ordered list column, widening only int64 and float64 values."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        selected = list(columns)
        if not selected:
            msg = "list requires at least one input column"
            raise ValueError(msg)
        if len(set(selected)) != len(selected):
            msg = "list columns must be unique"
            raise ValueError(msg)
        require_columns(names, selected, operation="list")
        if output in names:
            msg = f"list output column {output!r} already exists"
            raise ValueError(msg)

        types = {schema[column] for column in selected}
        if len(types) == 1:
            element_type = next(iter(types))
        elif types == {pl.Int64, pl.Float64}:
            element_type = pl.Float64
        else:
            msg = f"list columns have incompatible element types: {types}"
            raise ValueError(msg)
        values = [exact_column_expression(column, column_names=names) for column in selected]
        if element_type == pl.Float64 and pl.Int64 in types:
            values = [value.cast(pl.Float64) for value in values]
        result = pl.concat_list([value.repeat_by(1) for value in values]).alias(output)
        return self.source_with_frame(source, frame.with_columns(result))

    def filter_rows(
        self,
        source: TabularSource,
        *,
        column: str,
        comparison: TableFilterComparison,
        value: str | int | float | bool | None = None,
        other_column: str | None = None,
    ) -> TabularSource:
        """Apply one scalar or exact-column comparison, dropping null results."""
        frame = self.require_table_frame(source)
        predicate = comparison_expression(
            schema=frame.collect_schema(),
            column=column,
            comparison=comparison,
            value=value,
            other_column=other_column,
            operation="filter",
        )
        return self.source_with_frame(source, frame.filter(predicate))

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
        """Choose compatible existing values or scalar literals for each row."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        if output in names:
            msg = f"choose output column {output!r} already exists"
            raise ValueError(msg)

        predicate = comparison_expression(
            schema=schema,
            column=column,
            comparison=comparison,
            value=value,
            other_column=other_column,
            operation="choose",
        )
        branch_types = [
            self.value_selection_type(schema, names, then),
            self.value_selection_type(schema, names, otherwise),
        ]
        output_type = self.compatible_selection_type(branch_types[0], branch_types[1])
        then_expression = self.value_selection_expression(schema, names, output_type, then)
        otherwise_expression = self.value_selection_expression(schema, names, output_type, otherwise)
        selected = pl.when(predicate).then(then_expression).otherwise(otherwise_expression).alias(output)
        return self.source_with_frame(source, frame.with_columns(selected))

    @staticmethod
    def value_selection_type(
        schema: pl.Schema, names: list[str], selection: TableValueSelection
    ) -> PolarsDType:
        """Return the declared type of one branch without collecting rows."""
        kind, value = selection
        if kind == "column":
            if not isinstance(value, str):
                msg = "choose column operand must name a string column"
                raise TypeError(msg)
            require_columns(names, [value], operation="choose")
            return schema[value]
        if value is None:
            return pl.Null
        if type(value) is bool:
            return pl.Boolean
        if type(value) is int:
            return pl.Int64
        if type(value) is float:
            return pl.Float64
        if type(value) is str:
            return pl.String
        msg = f"choose literal type {type(value).__name__} is unsupported"
        raise ValueError(msg)

    @staticmethod
    def compatible_selection_type(left: PolarsDType, right: PolarsDType) -> PolarsDType:
        """Resolve identical, null, and documented numeric branch dtypes."""
        if left == pl.Null:
            if right == pl.Null:
                msg = "choose output type cannot be inferred from two null branches"
                raise ValueError(msg)
            return right
        if right == pl.Null or left == right:
            return left
        if {left, right} == {pl.Int64, pl.Float64}:
            return pl.Float64
        msg = f"choose branch types are incompatible: {left} and {right}"
        raise ValueError(msg)

    @staticmethod
    def value_selection_expression(
        schema: pl.Schema,
        names: Sequence[str],
        output_type: PolarsDType,
        selection: TableValueSelection,
    ) -> pl.Expr:
        """Build one branch expression using strict scalar compatibility."""
        kind, value = selection
        if kind == "column":
            if not isinstance(value, str):
                msg = "choose column operand must name a string column"
                raise TypeError(msg)
            expression = exact_column_expression(value, column_names=names)
            if schema[value] == output_type:
                return expression
            return expression.cast(output_type, strict=True)
        if value is None:
            return pl.lit(None, dtype=output_type)
        if output_type == pl.Boolean:
            compatible = type(value) is bool
            literal: object = value
        elif output_type == pl.Int64:
            compatible = type(value) is int
            literal = value
        elif output_type == pl.Float64:
            compatible = type(value) in {int, float}
            literal = float(value)
        elif output_type == pl.String:
            compatible = type(value) is str
            literal = value
        else:
            msg = f"choose scalar values cannot produce {output_type}"
            raise ValueError(msg)
        if not compatible:
            msg = f"choose value type {type(value).__name__} is incompatible with output type {output_type}"
            raise ValueError(msg)
        return pl.lit(literal, dtype=output_type)

    def group_by(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        aggregates: Sequence[
            tuple[Literal["sum", "max", "mean", "count", "first", "last", "list"], str, str]
        ],
    ) -> TabularSource:
        """Group in input order and retain the declared numeric aggregate dtypes."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, list(columns), operation="group_by")
        aggregate_expressions: list[pl.Expr] = []
        for operation, column, output in aggregates:
            require_columns(names, [column], operation=f"group_by {operation}")
            dtype = schema[column]
            if operation in {"sum", "max", "mean"} and not dtype.is_numeric():
                msg = f"group_by {operation} requires a numeric column, got {column!r}: {dtype}"
                raise ValueError(msg)
            expression = exact_column_expression(column, column_names=names)
            match operation:
                case "sum":
                    result = expression.sum()
                case "max":
                    result = expression.max()
                case "mean":
                    result = expression.mean().cast(pl.Float64)
                case "count":
                    result = expression.count().cast(pl.Int64)
                case "first":
                    result = expression.first()
                case "last":
                    result = expression.last()
                case "list":
                    result = expression.implode()
            aggregate_expressions.append(result.alias(output))
        if columns:
            grouped = frame.group_by(
                [exact_column_expression(column, column_names=names) for column in columns],
                maintain_order=True,
            ).agg(aggregate_expressions)
        elif source.availability is SourceAvailability.ABSENT:
            output_schema = frame.select(aggregate_expressions).collect_schema()
            grouped = pl.DataFrame(schema=output_schema).lazy()
        else:
            grouped = frame.select(aggregate_expressions)
        return self.source_with_frame(source, grouped)

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
        """Emit sorted value blocks through one native unpivot operation."""
        frame = self.require_table_frame(source)
        names = frame.collect_schema().names()
        value_columns = (
            {name: name for name in sorted(set(names) - set(index))}
            if columns is None
            else dict(sorted(columns.items()))
        )
        unpivoted = unpivot_polars_frame(
            frame,
            index=index,
            columns=value_columns,
            variable_name=variable_name,
            value_name=value_name,
            type_policy="exact",
            value_type_name=value_type_name,
        )
        return self.source_with_frame(source, unpivoted)

    def create_rows(
        self,
        *,
        schema: Sequence[tuple[str, TableColumnType]],
        values: Sequence[Mapping[str, object]],
    ) -> TabularSource:
        """Create a Polars table with the declared schema, including zero rows."""
        dtype_mapping = {
            "bool": pl.Boolean,
            "int64": pl.Int64,
            "float64": pl.Float64,
            "string": pl.String,
            "datetime": pl.Datetime,
        }
        typed_schema = {name: dtype_mapping[dtype] for name, dtype in schema}
        frame = pl.DataFrame(values, schema=typed_schema, strict=True).lazy()
        return TabularSource(frame, self)

    def concat_tables(self, sources: Sequence[TabularSource]) -> TabularSource:
        """Align compatible fields by name and append all source rows in order."""
        if not sources:
            msg = "concat requires at least one source"
            raise ValueError(msg)
        contributing_sources = [
            source for source in sources if source.availability is SourceAvailability.PRESENT
        ]
        schema_sources = contributing_sources or list(sources)
        frames = [self.require_table_frame(source) for source in schema_sources]
        first_schema = frames[0].collect_schema()
        output_names = first_schema.names()
        output_types = dict(first_schema)
        for frame in frames[1:]:
            candidate_schema = frame.collect_schema()
            candidate_names = candidate_schema.names()
            if set(candidate_names) != set(output_names):
                msg = (
                    "concat sources must have matching column names: "
                    f"expected {output_names}, got {candidate_names}"
                )
                raise ValueError(msg)
            for column in output_names:
                first_type = output_types[column]
                next_type = candidate_schema[column]
                if first_type == next_type:
                    continue
                if {first_type, next_type} == {pl.Int64, pl.Float64}:
                    output_types[column] = pl.Float64
                    continue
                msg = f"concat column {column!r} has incompatible types: {first_type} and {next_type}"
                raise ValueError(msg)
        aligned = [
            frame.select(
                [
                    exact_column_expression(name, column_names=frame.collect_schema().names())
                    .cast(output_types[name])
                    .alias(name)
                    for name in output_names
                ]
            )
            for frame in frames
        ]
        concatenated = pl.concat(aligned, how="vertical")
        absent_inputs = frozenset().union(*(source.absent_inputs for source in sources))
        return TabularSource(
            concatenated,
            self,
            absent_inputs=absent_inputs,
        )

    def unique_rows(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        keep: Literal["first", "last"],
    ) -> TabularSource:
        """Select complete unique rows and restore selected source order."""
        frame = self.require_table_frame(source)
        names = frame.collect_schema().names()
        require_columns(names, list(columns), operation="unique")

        occupied_names = set(names)
        row_index = "__r2x_table_mapping_unique_order__"
        while row_index in occupied_names:
            row_index = f"_{row_index}"
        occupied_names.add(row_index)
        indexed = frame.with_row_index(row_index)
        indexed_names = indexed.collect_schema().names()
        key_aliases: list[str] = []
        key_expressions: list[pl.Expr] = []
        for index, column in enumerate(columns):
            alias = f"__r2x_table_mapping_unique_key_{index}__"
            while alias in occupied_names:
                alias = f"_{alias}"
            occupied_names.add(alias)
            key_aliases.append(alias)
            key_expressions.append(exact_column_expression(column, column_names=indexed_names).alias(alias))

        indexed = indexed.with_columns(key_expressions)
        selected = indexed.unique(subset=key_aliases, keep=keep, maintain_order=True)
        selected_names = selected.collect_schema().names()
        ordered = selected.sort(
            exact_column_expression(row_index, column_names=selected_names),
            maintain_order=True,
        )
        return self.source_with_frame(source, ordered.drop([row_index, *key_aliases]))

    def cast_column(
        self,
        source: TabularSource,
        *,
        column: str,
        dtype: TableColumnType,
    ) -> TabularSource:
        """Strictly cast one exact column, parsing ISO datetime text explicitly."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, [column], operation="cast")
        if dtype == "int64" and schema[column].is_float():
            msg = f"cast from floating-point to integer is unsupported for column {column!r}"
            raise ValueError(msg)
        dtype_mapping = {
            "bool": pl.Boolean,
            "int64": pl.Int64,
            "float64": pl.Float64,
            "string": pl.String,
            "datetime": pl.Datetime,
        }
        expression = exact_column_expression(column, column_names=names)
        if dtype == "datetime" and schema[column] == pl.String:
            cast = expression.str.to_datetime(strict=True)
        else:
            cast = expression.cast(dtype_mapping[dtype], strict=True)
        return self.source_with_frame(source, frame.with_columns(cast.alias(column)))

    def fill_null(
        self,
        source: TabularSource,
        *,
        columns: Sequence[str],
        value: TableFillValue = None,
        from_columns: Sequence[str] | None = None,
    ) -> TabularSource:
        """Fill nulls from a compatible scalar or ordered original columns."""
        frame = self.require_table_frame(source)
        schema = frame.collect_schema()
        names = schema.names()
        require_columns(names, list(columns), operation="fill_null")
        if value is None and from_columns is None:
            return source

        if from_columns is not None:
            require_columns(names, list(from_columns), operation="fill_null backups")
            expressions = []
            for column in columns:
                dtype = schema[column]
                incompatible = [backup for backup in from_columns if schema[backup] != dtype]
                if incompatible:
                    msg = f"fill_null backup types must match column {column!r}: {incompatible}"
                    raise ValueError(msg)
                expressions.append(
                    pl.coalesce(
                        [
                            exact_column_expression(column, column_names=names),
                            *[exact_column_expression(name, column_names=names) for name in from_columns],
                        ]
                    ).alias(column)
                )
            return self.source_with_frame(source, frame.with_columns(expressions))

        if isinstance(value, list):
            expressions = []
            for column in columns:
                dtype = schema[column]
                if not isinstance(dtype, pl.List):
                    msg = f"fill_null list values require a list column, got {column!r}: {dtype}"
                    raise ValueError(msg)
                element_type = dtype.inner
                normalized: list[object] = []
                for item in value:
                    if item is None:
                        normalized.append(None)
                    elif (
                        (element_type == pl.String and type(item) is str)
                        or (element_type == pl.Boolean and type(item) is bool)
                        or (element_type == pl.Int64 and type(item) is int)
                    ):
                        normalized.append(item)
                    elif element_type == pl.Float64 and type(item) in {int, float}:
                        normalized.append(float(item))
                    elif isinstance(element_type, pl.Datetime) and type(item) is str:
                        try:
                            normalized.append(datetime.fromisoformat(item))
                        except ValueError as error:
                            msg = f"fill_null list value {item!r} is not an ISO datetime"
                            raise ValueError(msg) from error
                    else:
                        msg = f"fill_null list value type {type(item).__name__} is incompatible with {dtype}"
                        raise ValueError(msg)
                fill = pl.lit(normalized, dtype=dtype)
                expressions.append(
                    exact_column_expression(column, column_names=names).fill_null(fill).alias(column)
                )
            return self.source_with_frame(source, frame.with_columns(expressions))

        expressions: list[pl.Expr] = []
        for column in columns:
            dtype = schema[column]
            fill_value: str | int | float | bool | datetime | None = value
            if dtype.is_integer():
                compatible = type(value) is int
            elif dtype.is_float():
                compatible = type(value) in {int, float}
            elif dtype == pl.String:
                compatible = type(value) is str
            elif dtype == pl.Boolean:
                compatible = type(value) is bool
            elif isinstance(dtype, pl.Datetime):
                compatible = type(value) is str
                if isinstance(value, str):
                    try:
                        fill_value = datetime.fromisoformat(value)
                    except ValueError as error:
                        msg = f"Fill value {value!r} is not an ISO datetime"
                        raise ValueError(msg) from error
            else:
                compatible = False
            if not compatible:
                msg = (
                    f"Fill value type {type(value).__name__} is incompatible with column {column!r} ({dtype})"
                )
                raise ValueError(msg)
            expression = exact_column_expression(column, column_names=names)
            if dtype.is_integer():
                replacement = pl.lit(fill_value).cast(dtype, strict=True)
                expression = expression.fill_null(replacement)
            else:
                expression = expression.fill_null(fill_value)
            expressions.append(expression.alias(column))
        return self.source_with_frame(source, frame.with_columns(expressions))

    def head_rows(self, source: TabularSource, *, n: int) -> TabularSource:
        """Retain the first ``n`` rows without changing schema or availability."""
        return self.source_with_frame(source, self.require_table_frame(source).head(n))

    def sort(
        self, source: TabularSource, *, columns: Sequence[str], descending: bool = False
    ) -> TabularSource:
        """Sort stably in one direction with null values last."""
        frame = self.require_table_frame(source)
        names = frame.collect_schema().names()
        require_columns(names, list(columns), operation="sort")
        return self.source_with_frame(
            source,
            frame.sort(
                [exact_column_expression(column, column_names=names) for column in columns],
                descending=descending,
                nulls_last=True,
                maintain_order=True,
            ),
        )

    @staticmethod
    def require_table_frame(source: TabularSource) -> pl.LazyFrame:
        """Require the Polars lazy representation for these table operations."""
        if not isinstance(source.data, pl.LazyFrame):
            msg = "Polars table assembly requires Polars LazyFrame sources"
            raise TypeError(msg)
        return source.data

    def apply_mapping_operation(
        self,
        step: MappingStep,
        frame: pl.LazyFrame,
        *,
        source_frames: Mapping[str, pl.LazyFrame],
        data_file: DataFile | None = None,
    ) -> Result[pl.LazyFrame, ValueError]:
        """Apply one mapping step, returning validation and Polars errors."""
        try:
            match step:
                case ConcatStep():
                    missing = [name for name in step.sources if name not in source_frames]
                    if missing:
                        msg = f"concat sources were not provided: {missing}"
                        raise ValueError(msg)
                    base_schema = tuple(frame.collect_schema().items())
                    source_names = [
                        data_file.source
                        if data_file is not None and data_file.source is not None
                        else "current table",
                        *step.sources,
                    ]
                    frames = [frame, *(source_frames[name] for name in step.sources)]
                    for name, candidate in zip(source_names[1:], frames[1:], strict=True):
                        candidate_schema = tuple(candidate.collect_schema().items())
                        if candidate_schema != base_schema:
                            msg = (
                                "concat sources must have identical schemas and column order: "
                                f"{source_names[0]!r}={dict(base_schema)!r}, "
                                f"{name!r}={dict(candidate_schema)!r}"
                            )
                            raise ValueError(msg)
                    frame = pl.concat(frames, how="vertical")
                case JoinStep():
                    if step.source not in source_frames:
                        msg = f"join source {step.source!r} was not provided"
                        raise ValueError(msg)
                    frame = join_exact_columns(
                        frame,
                        source_frames[step.source],
                        on=step.on,
                        how=step.how,
                        validate=(step.join_validation if step.join_validation is not None else "m:m"),
                    )
                case MatchSourcePatternsStep():
                    if step.source not in source_frames:
                        msg = f"match_source_patterns source {step.source!r} was not provided"
                        raise ValueError(msg)
                    frame = match_source_patterns(
                        frame,
                        source_frames[step.source],
                        step=step,
                        data_file=data_file,
                    )
                case CustomStep():
                    handler = self.step_handlers.get(step.handler)
                    if handler is None:
                        msg = f"No custom mapping handler registered for {step.handler!r}"
                        raise ValueError(msg)
                    if not isinstance(frame, handler.input_type):
                        msg = (
                            f"Custom mapping handler {step.handler!r} expects {handler.input_type.__name__}, "
                            f"received {type(frame).__name__}"
                        )
                        raise ValueError(msg)
                    options = handler.options_model.model_validate(step.kwargs)
                    output = handler.apply(frame, options=options)
                    if not isinstance(output, handler.output_type):
                        msg = (
                            f"Custom mapping handler {step.handler!r} declared {handler.output_type.__name__} "
                            f"but returned {type(output).__name__}"
                        )
                        raise ValueError(msg)
                    if not isinstance(output, pl.LazyFrame):
                        msg = f"Custom mapping handler {step.handler!r} must return a Polars LazyFrame"
                        raise ValueError(msg)
                    frame = output
                case _:
                    frame = apply_polars_step(frame, data_file=data_file, step=step)
        except (ValueError, pl.exceptions.PolarsError) as error:
            contextual_error = ValueError(f"Mapping operation {step.op!r} failed: {error}")
            contextual_error.__cause__ = error
            return Err(contextual_error)
        return Ok(frame)
