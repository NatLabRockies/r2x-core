"""Backend contract and runner for tabular mapping operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, Generic, Protocol, TypeGuard, TypeVar

from pydantic import BaseModel
from rust_ok import Ok, Result, is_ok

from .datafile import DataFile, TabularProcessing
from .models import MappingStep
from .types import FrameT

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


class MappingStepBackend(Protocol[FrameT]):
    """Execute ordered mapping steps independently of DataFile processing."""

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
    from .polars_adapter import PolarsTabularBackend

    return PolarsTabularBackend()


def apply_mapping_steps(
    frame: FrameT,
    steps: Sequence[MappingStep],
    *,
    backend: MappingStepBackend[FrameT],
    source_frames: Mapping[str, FrameT] | None = None,
) -> Result[FrameT, ValueError]:
    """Run ordered mapping steps through the selected tabular backend."""
    if source_frames is None:
        source_frames = {}
    for step in steps:
        result = backend.apply_mapping_operation(step, frame, source_frames=source_frames)
        if is_ok(result):
            frame = result.value
        else:
            return result
    return Ok(frame)
