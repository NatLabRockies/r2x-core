"""Polars implementation of the tabular backend contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import polars as pl
from rust_ok import Err, Ok, Result

from ..datafile import DataFile
from ..file_reader import DecodedSource, TabularSource
from ..models import CustomStep, JoinStep, MappingStep, TabularProcessing
from ..tabular_backend import MappingStepHandler, apply_mapping_steps
from ..types import FileProcessing
from .processing import apply_polars_step


class PolarsTabularBackend:
    """Implement tabular processing and mapping operations with Polars."""

    def __init__(
        self,
        *,
        step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]] | None = None,
    ) -> None:
        """Configure optional app-provided handlers for custom table steps."""
        self.step_handlers = dict(step_handlers or {})

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

    def iter_rows(self, frame: pl.LazyFrame, /) -> Iterable[Mapping[str, object]]:
        """Collect a frame and yield named row mappings."""
        return frame.collect().iter_rows(named=True)

    def values(self, frame: pl.LazyFrame, field: str, /) -> list[object]:
        """Collect one named column as values."""
        try:
            index = frame.collect_schema().names().index(field)
        except ValueError as error:
            msg = f"Table has no field {field!r}"
            raise ValueError(msg) from error
        return frame.select(pl.nth(index)).collect().to_series().to_list()

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
