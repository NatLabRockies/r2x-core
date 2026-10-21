"""Polars implementation of the tabular backend contract."""

from __future__ import annotations

from collections.abc import Mapping
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
        """Apply one mapping step, returning validation and Polars errors."""
        try:
            match step:
                case AssertStep():
                    column_names = frame.collect_schema().names()
                    predicate = compile_polars_expression(
                        step.predicate, column_names=column_names
                    ).fill_null(False)
                    violations = frame.filter(~predicate).limit(1).collect()
                    if violations.height:
                        msg = "assert step failed for at least one row"
                        raise ValueError(msg)
                case FilterStep():
                    column_names = frame.collect_schema().names()
                    frame = frame.filter(compile_polars_expression(step.predicate, column_names=column_names))
                case SelectStep():
                    column_names = frame.collect_schema().names()
                    frame = frame.select(
                        [
                            compile_polars_expression(expr, column_names=column_names).alias(name)
                            for name, expr in step.columns.items()
                        ]
                    )
                case WithColumnsStep():
                    column_names = frame.collect_schema().names()
                    frame = frame.with_columns(
                        [
                            compile_polars_expression(expr, column_names=column_names).alias(name)
                            for name, expr in step.columns.items()
                        ]
                    )
                case UnpivotStep():
                    column_names = frame.collect_schema().names()
                    missing = set(step.index).difference(column_names)
                    if missing:
                        msg = f"unpivot index columns not found: {sorted(missing)}"
                        raise ValueError(msg)
                    value_columns = [name for name in column_names if name not in step.index]
                    if not value_columns:
                        msg = "unpivot requires at least one value column"
                        raise ValueError(msg)
                    if step.variable_name == step.value_name or {
                        step.variable_name,
                        step.value_name,
                    }.intersection(step.index):
                        msg = "unpivot output names must be distinct from each other and the index"
                        raise ValueError(msg)
                    frame = frame.unpivot(
                        on=value_columns,
                        index=step.index,
                        variable_name=step.variable_name,
                        value_name=step.value_name,
                    )
                case GroupByStep():
                    column_names = frame.collect_schema().names()
                    frame = frame.group_by(step.by, maintain_order=True).agg(
                        [
                            compile_polars_expression(expr, column_names=column_names).alias(name)
                            for name, expr in step.agg.items()
                        ]
                    )
                case JoinStep():
                    if step.source not in source_frames:
                        msg = f"join source {step.source!r} was not provided"
                        raise ValueError(msg)
                    frame = frame.join(
                        source_frames[step.source],
                        on=step.on,
                        how=step.how,
                        validate=step.join_validation or "m:m",
                    )
                case SortStep():
                    frame = frame.sort(step.by)
                case UniqueStep():
                    frame = frame.unique(subset=step.subset, keep="first", maintain_order=True)
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
                    msg = f"Unsupported mapping operation: {type(step).__name__}"
                    raise ValueError(msg)
        except (ValueError, TypeError, pl.exceptions.PolarsError) as error:
            return Err(ValueError(f"Mapping operation {step.op!r} failed: {error}"))
        return Ok(frame)
