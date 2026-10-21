"""Base interface for file-format adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Generic

from .datafile import ReaderConfig
from .types import FileFormat, FileOutputT


class FileReader(ABC, Generic[FileOutputT]):
    """Read supported file formats into an adapter-defined output type."""

    @abstractmethod
    def supports_file_type(self, file_type: FileFormat, /) -> bool:
        """Return whether this reader can read the configured format."""
        ...

    @abstractmethod
    def read_file(
        self,
        file_type: FileFormat,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> FileOutputT:
        """Read one supported format into its output representation."""
        ...


def default_tabular_file_reader() -> FileReader[Any]:
    """Create the default Polars reader, importing Polars only when requested."""
    from .polars_adapter import PolarsTabularFileReader

    return PolarsTabularFileReader()
