"""Polars implementation of the tabular backend contract."""

from __future__ import annotations

from collections.abc import Mapping
from functools import singledispatch
from typing import Any, TypeGuard

import polars as pl
from rust_ok import Err, Ok, Result

from ..datafile import DataFile, TabularProcessing
from ..models import (
    AssertStep,
    CustomStep,
    FilterStep,
    GroupByStep,
    JoinStep,
    MappingStep,
    SelectStep,
    SortStep,
    UniqueStep,
    UnpivotStep,
    WithColumnsStep,
)
from ..tabular_backend import MappingStepHandler, TabularBackend
from .expressions import compile_polars_expression


@singledispatch
def dispatch_polars_mapping_operation(
    step: MappingStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Dispatch one mapping step to its Polars implementation."""
    raise ValueError(f"Unsupported mapping operation: {type(step).__name__}")


@dispatch_polars_mapping_operation.register
def apply_polars_assert_step(
    step: AssertStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Validate that every row satisfies the configured predicate."""
    predicate = compile_polars_expression(step.predicate).fill_null(False)
    violations = frame.filter(~predicate).limit(1).collect()
    if violations.height:
        raise ValueError("assert step failed for at least one row")
    return frame


@dispatch_polars_mapping_operation.register
def apply_polars_filter_step(
    step: FilterStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Filter rows using the configured predicate."""
    return frame.filter(compile_polars_expression(step.predicate))


@dispatch_polars_mapping_operation.register
def apply_polars_select_step(
    step: SelectStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Select and rename columns using the configured expressions."""
    return frame.select(
        [compile_polars_expression(expression).alias(name) for name, expression in step.columns.items()]
    )


@dispatch_polars_mapping_operation.register
def apply_polars_with_columns_step(
    step: WithColumnsStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Add or replace columns using the configured expressions."""
    return frame.with_columns(
        [compile_polars_expression(expression).alias(name) for name, expression in step.columns.items()]
    )


@dispatch_polars_mapping_operation.register
def apply_polars_unpivot_step(
    step: UnpivotStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Unpivot all non-index columns into variable and value columns."""
    column_names = frame.collect_schema().names()
    missing = set(step.index).difference(column_names)
    if missing:
        raise ValueError(f"unpivot index columns not found: {sorted(missing)}")
    value_columns = [name for name in column_names if name not in step.index]
    if not value_columns:
        raise ValueError("unpivot requires at least one value column")
    if step.variable_name == step.value_name or {step.variable_name, step.value_name}.intersection(
        step.index
    ):
        raise ValueError("unpivot output names must be distinct from each other and the index")
    return frame.unpivot(
        on=value_columns,
        index=list(step.index),
        variable_name=step.variable_name,
        value_name=step.value_name,
    )


@dispatch_polars_mapping_operation.register
def apply_polars_group_by_step(
    step: GroupByStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Group rows and evaluate each configured aggregate expression."""
    return frame.group_by(list(step.by), maintain_order=True).agg(
        [compile_polars_expression(expression).alias(name) for name, expression in step.agg.items()]
    )


@dispatch_polars_mapping_operation.register
def apply_polars_join_step(
    step: JoinStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Join the current frame with a named source frame."""
    if step.source not in source_frames:
        raise ValueError(f"join source {step.source!r} was not provided")
    join_options: dict[str, Any] = {"how": step.how}
    if step.on is not None:
        join_options["on"] = list(step.on)
    if step.join_validation is not None:
        join_options["validate"] = step.join_validation
    return frame.join(source_frames[step.source], **join_options)


@dispatch_polars_mapping_operation.register
def apply_polars_sort_step(
    step: SortStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Sort rows by the configured columns."""
    return frame.sort(list(step.by))


@dispatch_polars_mapping_operation.register
def apply_polars_unique_step(
    step: UniqueStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Keep the first row for each configured unique subset."""
    return frame.unique(subset=list(step.subset), maintain_order=True)


@dispatch_polars_mapping_operation.register
def apply_polars_custom_step(
    step: CustomStep,
    *,
    frame: pl.LazyFrame,
    source_frames: Mapping[str, pl.LazyFrame],
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]],
) -> pl.LazyFrame:
    """Apply a registered app-provided handler to a mapping step."""
    handler = step_handlers.get(step.handler)
    if handler is None:
        raise ValueError(f"No custom mapping handler registered for {step.handler!r}")
    if not isinstance(frame, handler.input_type):
        raise ValueError(
            f"Custom mapping handler {step.handler!r} expects {handler.input_type.__name__}, "
            f"received {type(frame).__name__}"
        )
    options = handler.options_model.model_validate(step.kwargs)
    output = handler.apply(frame, options=options)
    if not isinstance(output, handler.output_type):
        raise ValueError(
            f"Custom mapping handler {step.handler!r} declared {handler.output_type.__name__} "
            f"but returned {type(output).__name__}"
        )
    if not isinstance(output, pl.LazyFrame):
        raise ValueError(f"Custom mapping handler {step.handler!r} must return a Polars LazyFrame")
    return output


class PolarsTabularBackend(TabularBackend[pl.LazyFrame]):
    """Implement tabular processing and mapping operations with Polars."""

    def __init__(
        self,
        *,
        step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]] | None = None,
    ) -> None:
        """Configure optional app-provided handlers for custom table steps."""
        self.step_handlers = dict(step_handlers or {})

    def supports_data(self, value: object, /) -> TypeGuard[pl.LazyFrame]:
        """Return whether a value is a Polars lazy frame."""
        return isinstance(value, pl.LazyFrame)

    def process(
        self,
        frame: pl.LazyFrame,
        *,
        data_file: DataFile,
        proc_spec: TabularProcessing,
    ) -> Result[pl.LazyFrame, ValueError]:
        """Apply the configured tabular processing pipeline with Polars."""
        from .processing import process_tabular_data

        try:
            return Ok(process_tabular_data(frame, data_file=data_file, proc_spec=proc_spec))
        except (ValueError, pl.exceptions.PolarsError) as error:
            return Err(ValueError(f"Processing {data_file.name!r} failed: {error}"))

    def apply_mapping_operation(
        self,
        step: MappingStep,
        frame: pl.LazyFrame,
        *,
        source_frames: Mapping[str, pl.LazyFrame],
    ) -> Result[pl.LazyFrame, ValueError]:
        """Dispatch a mapping step and translate Polars failures into Results."""
        try:
            result = dispatch_polars_mapping_operation(
                step,
                frame=frame,
                source_frames=source_frames,
                step_handlers=self.step_handlers,
            )
        except (ValueError, TypeError, pl.exceptions.PolarsError) as error:
            return Err(ValueError(f"Mapping operation {step.op!r} failed: {error}"))
        return Ok(result)
