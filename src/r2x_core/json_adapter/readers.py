"""JSON file reader adapter."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from ..datafile import ReaderConfig
from ..file_reader import DecodedSources, DocumentSource, FileReader
from ..types import JSONValue
from .processing import JSONProcessingBackend


class JSONFileReader(FileReader):
    """Read JSON files into Python JSON values."""

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        """Read one JSON document into a named source."""
        if format_name != "json":
            msg = f"JSON reader cannot read format {format_name!r}"
            raise ValueError(msg)
        if reader_config.options:
            msg = f"JSON reader has no options: {sorted(reader_config.options)}"
            raise ValueError(msg)
        with file_path.open(encoding="utf-8") as file:
            value: JSONValue = TypeAdapter(JSONValue).validate_python(json.load(file))
        return {"data": DocumentSource(value, JSONProcessingBackend())}
