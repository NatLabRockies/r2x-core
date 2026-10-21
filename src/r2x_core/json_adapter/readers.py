"""JSON file reader adapter."""

import json
from pathlib import Path

from ..datafile import ReaderConfig
from ..file_reader import FileReader
from ..types import FileFormat, JSONFormat, JSONValue


class JSONFileReader(FileReader[JSONValue]):
    """Read JSON files into Python JSON values."""

    def supports_file_type(self, file_type: FileFormat, /) -> bool:
        """Return whether this reader supports JSON format markers."""
        return isinstance(file_type, JSONFormat)

    def read_file(
        self,
        file_type: FileFormat,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> JSONValue:
        """Read one JSON file."""
        if not self.supports_file_type(file_type):
            msg = f"JSON reader does not support {type(file_type).__name__}"
            raise ValueError(msg)
        with file_path.open(encoding="utf-8") as file:
            return json.load(file)
