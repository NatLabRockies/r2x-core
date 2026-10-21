"""Built-in file-format readers without dedicated adapter modules."""

from pathlib import Path
from xml.etree import ElementTree

from .datafile import ReaderConfig
from .file_reader import FileReader
from .types import FileFormat, XMLFormat


class XMLFileReader(FileReader[ElementTree.Element]):
    """Read XML files into their root elements."""

    def supports_file_type(self, file_type: FileFormat, /) -> bool:
        """Return whether this reader supports XML format markers."""
        return isinstance(file_type, XMLFormat)

    def read_file(
        self,
        file_type: FileFormat,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> ElementTree.Element:
        """Read one XML file and return its root element."""
        if not self.supports_file_type(file_type):
            msg = f"XML reader does not support {type(file_type).__name__}"
            raise ValueError(msg)
        return ElementTree.parse(file_path).getroot()
