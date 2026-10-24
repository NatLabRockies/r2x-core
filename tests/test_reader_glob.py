"""Resolve configured paths and globs through named source loading."""

from pathlib import Path
from xml.etree import ElementTree

import pytest

from r2x_core.datafile import DataFile, FileInfo, ReaderConfig
from r2x_core.file_reader import DecodedSources, DocumentSource, FileReader
from r2x_core.reader import DataReader
from r2x_core.types import FileRequirement, FileType
from r2x_core.utils.validation import validate_glob_pattern


@pytest.fixture
def data_reader() -> DataReader:
    return DataReader()


def xml_files(folder: Path, names: tuple[str, ...]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_text(f"<root><data>{name}</data></root>", encoding="utf-8")


def load(data_reader: DataReader, item: DataFile, folder: Path) -> object | None:
    """Load one configured name, returning None for skipped optional inputs."""
    return data_reader.read_data_files([item], folder_path=folder).get(item.name)


def test_glob_single_match_returns_native_document(data_reader: DataReader, tmp_path: Path) -> None:
    xml_files(tmp_path, ("model.xml",))
    source = load(data_reader, DataFile(name="model", glob="*.xml"), tmp_path)
    assert isinstance(source, DocumentSource)
    assert isinstance(source.data, ElementTree.Element)
    assert source.data.tag == "root"


def test_glob_multiple_matches_report_names(data_reader: DataReader, tmp_path: Path) -> None:
    xml_files(tmp_path, ("model_0.xml", "model_1.xml", "model_2.xml"))
    with pytest.raises(ValueError, match="Multiple files matched") as error:
        load(data_reader, DataFile(name="models", glob="*.xml"), tmp_path)
    assert all(name in str(error.value) for name in ("model_0.xml", "model_1.xml", "model_2.xml"))


def test_glob_no_match_is_required_or_optional(data_reader: DataReader, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No files found"):
        load(data_reader, DataFile(name="required", glob="*.xml"), tmp_path)
    optional = DataFile(name="optional", glob="*.xml", info=FileInfo(requirement=FileRequirement.OPTIONAL))
    assert load(data_reader, optional, tmp_path) is None


def test_glob_selectors_and_recursive_matches(data_reader: DataReader, tmp_path: Path) -> None:
    xml_files(tmp_path, ("special_0.xml", "ordinary.xml"))
    selected = load(data_reader, DataFile(name="special", glob="special_*.xml"), tmp_path)
    assert isinstance(selected, DocumentSource)
    assert selected.data.tag == "root"
    subdir = tmp_path / "subdir"
    xml_files(subdir, ("nested.xml",))
    with pytest.raises(ValueError, match="Multiple files matched"):
        load(data_reader, DataFile(name="all", glob="**/*.xml"), tmp_path)


def test_glob_ignores_directories_and_accepts_character_patterns(
    data_reader: DataReader, tmp_path: Path
) -> None:
    (tmp_path / "model.xml").mkdir()
    with pytest.raises(FileNotFoundError):
        load(data_reader, DataFile(name="directory", glob="*.xml"), tmp_path)
    xml_files(tmp_path, ("file_a.xml", "file_b.xml", "file_ab.xml"))
    with pytest.raises(ValueError, match="Multiple files matched"):
        load(data_reader, DataFile(name="char", glob="file_?.xml"), tmp_path)


def test_glob_format_is_inferred_but_timeseries_purpose_is_independent() -> None:
    item = DataFile(name="xml-series", glob="*.xml", info=FileInfo(file_type=FileType.TIME_SERIES))
    assert item.format_name == "xml"

    with pytest.raises(ValueError, match=r"configure reader\.format"):
        _ = DataFile(name="no-extension", glob="*").format_name


def test_glob_validation_rejects_invalid_configuration() -> None:
    for value in ("", "   "):
        with pytest.raises(ValueError, match="Glob pattern cannot be empty"):
            DataFile(name="invalid", glob=value)
    with pytest.raises(ValueError, match="invalid characters"):
        DataFile(name="invalid", glob="file\x00*.xml")
    with pytest.raises(ValueError, match="does not contain glob wildcards"):
        DataFile(name="invalid", glob="exact.xml")
    assert validate_glob_pattern(None) is None


def test_physical_path_modes_are_resolved_at_read_time(data_reader: DataReader, tmp_path: Path) -> None:
    (tmp_path / "relative.json").write_text('{"value":1}', encoding="utf-8")
    absolute = tmp_path / "absolute.json"
    absolute.write_text('{"value":2}', encoding="utf-8")
    (tmp_path / "selected.json").write_text('{"value":3}', encoding="utf-8")
    (tmp_path / "selected.json.copy").write_text('{"value":4}', encoding="utf-8")
    files = [
        DataFile(name="relative", relative_fpath="relative.json"),
        DataFile(name="absolute", fpath=absolute),
        DataFile(name="glob", glob="selected.json*", reader=ReaderConfig(format="json")),
    ]
    with pytest.raises(ValueError, match="Multiple files matched"):
        data_reader.read_data_files(files, folder_path=tmp_path)

    result = data_reader.read_data_files(files[:2], folder_path=tmp_path)
    assert result["relative"].data == {"value": 1}
    assert result["absolute"].data == {"value": 2}


def test_application_reader_handles_new_extension(data_reader: DataReader, tmp_path: Path) -> None:
    path = tmp_path / "input.uncommon"
    path.write_text("native document", encoding="utf-8")

    class PlainTextReader(FileReader):
        def read_file(
            self,
            format_name: str,
            /,
            *,
            file_path: Path,
            reader_config: ReaderConfig,
        ) -> DecodedSources:
            assert format_name == "plain_text"
            return {"data": DocumentSource(file_path.read_text(encoding="utf-8"), None)}

    reader = DataReader(file_readers={"plain_text": PlainTextReader()})
    item = DataFile(
        name="document",
        fpath=path,
        reader=ReaderConfig(format="plain_text"),
    )
    assert load(reader, item, tmp_path).data == "native document"


def test_datafile_requires_one_physical_input_mode() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        DataFile(name="neither")
    with pytest.raises(ValueError, match="exactly one"):
        DataFile(name="both", fpath=Path("file.xml"), glob="*.xml")
