"""XML file reader adapter."""

from pathlib import Path
from xml.etree import ElementTree

from ..datafile import ReaderConfig
from ..file_reader import DecodedSources, DocumentSource, FileReader


class XMLFileReader(FileReader):
    """Read XML files into their root elements."""

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        """Read one XML document into a named source."""
        if format_name != "xml":
            msg = f"XML reader cannot read format {format_name!r}"
            raise ValueError(msg)
        if reader_config.columns:
            msg = "XML reader does not support native table column declarations"
            raise ValueError(msg)
        if reader_config.options:
            msg = f"XML reader has no options: {sorted(reader_config.options)}"
            raise ValueError(msg)
        return {"data": DocumentSource(ElementTree.parse(file_path).getroot(), None)}
