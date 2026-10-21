"""Backend contract and runner for tabular mapping operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, Generic, Protocol, TypeGuard, TypeVar

from pydantic import BaseModel
from rust_ok import Err, Ok, Result, is_ok

from .datafile import DataFile, TabularProcessing
from .models import MappingStep
from .types import FrameT

_HandlerOptionsT = TypeVar("_HandlerOptionsT", bound=BaseModel)
_HandlerInputT = TypeVar("_HandlerInputT")
_HandlerOutputT = TypeVar("_HandlerOutputT")


class MappingStepHandler(Protocol[_HandlerOptionsT, _HandlerInputT, _HandlerOutputT]):
    """App-scoped handler contract for a custom mapping operation."""

    @property
    def handler(self) -> str:
        """Return the handler identifier stored in configuration."""
        ...

    @property
    def options_model(self) -> type[_HandlerOptionsT]:
        """Return the Pydantic model used to validate handler options."""
        ...

    @property
    def input_type(self) -> type[_HandlerInputT]:
        """Declare the input type checked before handler execution."""
        ...

    @property
    def output_type(self) -> type[_HandlerOutputT]:
        """Declare the output type checked after handler execution."""
        ...

    def apply(self, value: _HandlerInputT, *, options: _HandlerOptionsT) -> _HandlerOutputT:
        """Consume an input value and return its declared output type."""
        ...


class TabularBackend(ABC, Generic[FrameT]):
    """Process and transform frames using one tabular execution engine."""

    @abstractmethod
    def supports_data(self, value: object, /) -> TypeGuard[FrameT]:
        """Return whether this backend handles the data value."""
        ...

    @abstractmethod
    def process(
        self,
        frame: FrameT,
        *,
        data_file: DataFile,
        proc_spec: TabularProcessing,
    ) -> Result[FrameT, ValueError]:
        """Apply tabular processing settings to a frame."""
        ...

    @abstractmethod
    def apply_mapping_operation(
        self,
        step: MappingStep,
        frame: FrameT,
        *,
        source_frames: Mapping[str, FrameT],
    ) -> Result[FrameT, ValueError]:
        """Apply one mapping operation to a frame."""
        ...


def default_tabular_backend() -> TabularBackend[Any]:
    """Create the default Polars backend, importing Polars only when requested."""
    try:
        from .polars_adapter import PolarsTabularBackend
    except ModuleNotFoundError as error:
        if error.name != "polars":
            raise
        raise ImportError(
            'The default tabular backend requires the "polars" extra. Install '
            "r2x-core[polars] or provide a TabularBackend."
        ) from error
    return PolarsTabularBackend()


def apply_mapping_steps(
    frame: FrameT,
    steps: Sequence[MappingStep],
    *,
    backend: TabularBackend[FrameT],
    source_frames: Mapping[str, FrameT] | None = None,
) -> Result[FrameT, ValueError]:
    """Run ordered mapping steps through the selected tabular backend."""
    available_sources: Mapping[str, FrameT] = {} if source_frames is None else source_frames
    current_frame: FrameT = frame
    for step in steps:
        result: Result[FrameT, ValueError] = backend.apply_mapping_operation(
            step, current_frame, source_frames=available_sources
        )
        if is_ok(result):
            current_frame = result.value
        else:
            return Err(result.err())
    return Ok(current_frame)
