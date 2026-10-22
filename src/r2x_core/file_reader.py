"""Reader and processor contracts with typed decoded source representations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Generic, Protocol, TypeAlias, TypeGuard, TypeVar
from xml.etree import ElementTree

import numpy as np
from rust_ok import Err, Result

from .datafile import DataFile, ReaderConfig
from .types import FileProcessing, JSONValue

SourceDataT = TypeVar("SourceDataT")
DocumentData: TypeAlias = JSONValue | ElementTree.Element
ArrayColumn: TypeAlias = np.ndarray | list[str] | list[bytes]
ArrayData: TypeAlias = Mapping[str, ArrayColumn] | np.ndarray
DocumentDataT = TypeVar("DocumentDataT", bound=DocumentData)
ArrayDataT = TypeVar("ArrayDataT", bound=ArrayData)
Record: TypeAlias = Mapping[str, object]


class DecodedSource(ABC):
    """One decoded representation with explicit named-field access."""

    @abstractmethod
    def fields(self) -> list[str]:
        """Return names available for field mappings and selectors."""
        ...

    @abstractmethod
    def iter_rows(self) -> Iterable[Record]:
        """Iterate records for component and supplemental construction."""
        ...

    @abstractmethod
    def values(self, field: str, /) -> list[object]:
        """Select one named sample or field sequence."""
        ...

    @abstractmethod
    def process(
        self,
        processing: FileProcessing,
        *,
        sources: Mapping[str, DecodedSource],
        data_file: DataFile,
    ) -> Result[DecodedSource, ValueError]:
        """Apply operations through the processor paired with this payload."""
        ...


class SourceProcessor(Protocol[SourceDataT]):
    """Process one payload using its representation-specific implementation."""

    def process(
        self,
        data: SourceDataT,
        /,
        *,
        processing: FileProcessing,
        sources: Mapping[str, DecodedSource],
        data_file: DataFile,
    ) -> Result[SourceDataT, ValueError]:
        """Apply requested operations or return an explicit unsupported error."""
        ...


class TabularProcessor(SourceProcessor[SourceDataT], Protocol[SourceDataT]):
    """Provide record access for a native tabular representation."""

    def column_names(self, data: SourceDataT, /) -> list[str]:
        """Return table fields without converting the representation."""
        ...

    def iter_rows(self, data: SourceDataT, /) -> Iterable[Record]:
        """Yield records from the table."""
        ...

    def values(self, data: SourceDataT, field: str, /) -> list[object]:
        """Select one named column."""
        ...


@dataclass(frozen=True, slots=True)
class ProcessingSource(DecodedSource, Generic[SourceDataT]):
    """Pair a typed payload with the implementation that can process it."""

    data: SourceDataT
    processor: SourceProcessor[SourceDataT] | None

    def process(
        self,
        processing: FileProcessing,
        *,
        sources: Mapping[str, DecodedSource],
        data_file: DataFile,
    ) -> Result[DecodedSource, ValueError]:
        """Dispatch operations through the implementation paired with this payload."""
        if self.processor is None:
            return Err(ValueError(f"No processor registered for {type(self).__name__}"))
        return self.processor.process(
            self.data,
            processing=processing,
            sources=sources,
            data_file=data_file,
        ).map(lambda data: replace(self, data=data))


@dataclass(frozen=True, slots=True)
class TabularSource(ProcessingSource[SourceDataT], Generic[SourceDataT]):
    """Tabular data coupled to its backend and record-access methods."""

    processor: TabularProcessor[SourceDataT]

    def fields(self) -> list[str]:
        """Return table fields using the paired processor."""
        return self.processor.column_names(self.data)

    def iter_rows(self) -> Iterable[Record]:
        """Yield table records using the paired processor."""
        return self.processor.iter_rows(self.data)

    def values(self, field: str, /) -> list[object]:
        """Select one table column using the paired processor."""
        return self.processor.values(self.data, field)


@dataclass(frozen=True, slots=True)
class DocumentSource(ProcessingSource[DocumentDataT], Generic[DocumentDataT]):
    """Document data retained with an optional compatible processor."""

    def fields(self) -> list[str]:
        """Return fields from JSON object records."""
        value = self.json_data()
        if isinstance(value, dict):
            return list(value)
        return list(dict.fromkeys(key for row in value for key in row))

    def iter_rows(self) -> Iterable[Record]:
        """Iterate JSON object records."""
        value = self.json_data()
        if isinstance(value, dict):
            return [value]
        return value

    def values(self, field: str, /) -> list[object]:
        """Select a named JSON field."""
        value = self.json_data()
        if isinstance(value, dict):
            if field not in value:
                msg = f"Document has no field {field!r}"
                raise ValueError(msg)
            selected = value[field]
            return list(selected) if isinstance(selected, list) else [selected]
        rows = list(self.iter_rows())
        missing = [index for index, row in enumerate(rows) if field not in row]
        if missing:
            msg = f"Document records are missing field {field!r} at row(s) {missing}"
            raise ValueError(msg)
        return [row[field] for row in rows]

    def json_data(self) -> dict[str, object] | list[dict[str, object]]:
        """Validate JSON document record structure at its representation boundary."""
        data = self.data
        if not is_json_record_document(data):
            msg = (
                f"{type(data).__name__} is not a JSON record document; provide an explicit reader conversion"
            )
            raise TypeError(msg)
        return data


@dataclass(frozen=True, slots=True)
class ArraySource(ProcessingSource[ArrayDataT], Generic[ArrayDataT]):
    """Named one-dimensional arrays coupled to optional processing."""

    def fields(self) -> list[str]:
        """Return configured names for array values."""
        if isinstance(self.data, Mapping):
            if any(not isinstance(name, str) for name in self.data):
                msg = "Array source field names must be strings"
                raise TypeError(msg)
            return list(self.data)
        if isinstance(self.data, np.ndarray) and self.data.ndim == 1:
            return ["data"]
        msg = "Array sources require named one-dimensional arrays"
        raise ValueError(msg)

    def iter_rows(self) -> Iterable[Record]:
        """Iterate aligned array fields as records."""
        names = self.fields()
        arrays = {
            name: np.asarray(self.data[name] if isinstance(self.data, Mapping) else self.data)
            for name in names
        }
        if any(array.ndim != 1 for array in arrays.values()):
            msg = "Array source fields must be one-dimensional"
            raise ValueError(msg)
        lengths = {len(array) for array in arrays.values()}
        if len(lengths) > 1:
            msg = "Array source fields must have equal lengths"
            raise ValueError(msg)
        count = next(iter(lengths), 0)
        return (
            {
                name: arrays[name][index].item()
                if isinstance(arrays[name][index], np.generic)
                else arrays[name][index]
                for name in names
            }
            for index in range(count)
        )

    def values(self, field: str, /) -> list[object]:
        """Select one named one-dimensional sample array."""
        if field not in self.fields():
            msg = f"Array source has no values named {field!r}"
            raise ValueError(msg)
        values = np.asarray(self.data[field] if isinstance(self.data, Mapping) else self.data)
        if values.ndim != 1:
            msg = f"Array values must be one-dimensional, got {values.ndim}"
            raise ValueError(msg)
        return list(values)


JSONRecordDocument: TypeAlias = dict[str, object] | list[dict[str, object]]


def is_json_record_document(value: object, /) -> TypeGuard[JSONRecordDocument]:
    """Accept JSON objects or lists of objects as explicit document records."""
    from .json_adapter.processing import is_json_value

    if not is_json_value(value):
        return False
    if isinstance(value, dict):
        return all(isinstance(key, str) for key in value)
    return isinstance(value, list) and all(
        isinstance(record, dict) and all(isinstance(key, str) for key in record) for record in value
    )


DecodedSources: TypeAlias = Mapping[str, DecodedSource]


class FileReader(ABC):
    """Decode a configured format into named, typed sources."""

    @abstractmethod
    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        """Decode one file without constructing domain components."""
        ...
