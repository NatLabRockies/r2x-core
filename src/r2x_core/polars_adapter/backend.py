"""Polars implementation of the tabular backend contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeGuard

import polars as pl
from rust_ok import Err, Ok, Result

from ..datafile import DataFile
from ..models import CustomStep, JoinStep, MappingStep, TabularProcessing
from ..tabular_backend import MappingStepHandler, TabularBackend, apply_mapping_steps
from .processing import apply_polars_step


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
        return apply_mapping_steps(frame, proc_spec.steps, backend=self, data_file=data_file)

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
        except (ValueError, TypeError, pl.exceptions.PolarsError) as error:
            return Err(ValueError(f"Mapping operation {step.op!r} failed: {error}"))
        return Ok(frame)
