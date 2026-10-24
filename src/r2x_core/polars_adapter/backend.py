"""Polars implementation of the tabular backend contract."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal, TypeAlias

import polars as pl
from rust_ok import Err, Ok, Result

from ..datafile import DataFile
from ..file_reader import DecodedSource, TabularSource
from ..models import ConcatStep, CustomStep, JoinStep, MappingStep, TabularProcessing
from ..tabular_backend import MappingStepHandler, apply_mapping_steps
from ..types import FileProcessing
from .frames import collect_polars_frame
from .processing import apply_polars_step, require_columns

JoinHow: TypeAlias = Literal["inner", "left", "right", "full", "semi", "anti", "cross"]
JoinValidation: TypeAlias = Literal["m:m", "m:1", "1:m", "1:1"]


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
                        data_file.source if data_file is not None and data_file.source is not None else "current table",
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
                        validate=(
                            step.join_validation if step.join_validation is not None else "m:m"
                        ),
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
