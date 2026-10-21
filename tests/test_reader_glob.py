import pytest

from r2x_core.datafile import DataFile, FileInfo, validate_glob_pattern
from r2x_core.reader import DataReader
from r2x_core.types import FileRequirement, FileType, XMLFormat


@pytest.fixture
def data_reader():
    return DataReader()


@pytest.fixture
def single_xml_dir(tmp_path):
    test_dir = tmp_path / "single_xml"
    test_dir.mkdir()
    xml_file = test_dir / "model.xml"
    xml_file.write_text("<root><data>test</data></root>")
    return test_dir


@pytest.fixture
def multi_xml_dir(tmp_path):
    test_dir = tmp_path / "multi_xml"
    test_dir.mkdir()
    for i in range(3):
        xml_file = test_dir / f"model_{i}.xml"
        xml_file.write_text(f"<root><data>test{i}</data></root>")
    return test_dir


@pytest.fixture
def empty_dir(tmp_path):
    test_dir = tmp_path / "empty"
    test_dir.mkdir()
    return test_dir


@pytest.fixture
def mixed_files_dir(tmp_path):
    test_dir = tmp_path / "mixed"
    test_dir.mkdir()
    (test_dir / "data.xml").write_text("<root></root>")
    (test_dir / "data.csv").write_text("a,b,c\n1,2,3\n")
    (test_dir / "data.json").write_text('{"key": "value"}')
    return test_dir


@pytest.fixture
def nested_dir(tmp_path):
    test_dir = tmp_path / "nested"
    test_dir.mkdir()
    (test_dir / "top.xml").write_text("<root>top</root>")

    sub_dir = test_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "nested.xml").write_text("<root>nested</root>")

    return test_dir


def test_glob_single_match(data_reader, single_xml_dir):
    data_file = DataFile(name="test_xml", glob="*.xml")

    result = data_reader.read_data_file(data_file, folder_path=single_xml_dir)

    assert result is not None


def test_glob_multiple_matches_raises_error(data_reader, multi_xml_dir):
    data_file = DataFile(name="test_xml", glob="*.xml")

    with pytest.raises(ValueError, match="Multiple files matched"):
        data_reader.read_data_file(data_file, folder_path=multi_xml_dir)


def test_glob_no_matches_raises_error(data_reader, empty_dir):
    data_file = DataFile(name="test_xml", glob="*.xml")

    with pytest.raises(FileNotFoundError, match="No files found"):
        data_reader.read_data_file(data_file, folder_path=empty_dir)


def test_glob_specific_extension(data_reader, mixed_files_dir):
    data_file = DataFile(name="test_csv", glob="*.csv")

    result = data_reader.read_data_file(data_file, folder_path=mixed_files_dir)

    assert result is not None
    collected = result.collect()
    assert len(collected) == 1


def test_glob_with_prefix(data_reader, multi_xml_dir):
    (multi_xml_dir / "special_model.xml").write_text("<root>special</root>")
    data_file = DataFile(name="test_xml", glob="special_*.xml")

    result = data_reader.read_data_file(data_file, folder_path=multi_xml_dir)

    assert result is not None


def test_glob_non_recursive(data_reader, nested_dir):
    data_file = DataFile(name="test_xml", glob="*.xml")

    result = data_reader.read_data_file(data_file, folder_path=nested_dir)

    assert result is not None


def test_glob_recursive_pattern(data_reader, nested_dir):
    data_file = DataFile(name="test_xml", glob="**/*.xml")

    with pytest.raises(ValueError, match="Multiple files matched"):
        data_reader.read_data_file(data_file, folder_path=nested_dir)


def test_glob_ignores_directories(tmp_path, data_reader):
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    xml_dir = test_dir / "model.xml"
    xml_dir.mkdir()

    data_file = DataFile(name="test_xml", glob="*.xml")

    with pytest.raises(FileNotFoundError, match="No files found"):
        data_reader.read_data_file(data_file, folder_path=test_dir)


def test_glob_optional_file_not_found(data_reader, empty_dir):
    data_file = DataFile(name="test_xml", glob="*.xml", info=FileInfo(requirement=FileRequirement.OPTIONAL))

    assert data_reader.read_data_file(data_file, folder_path=empty_dir) is None


def test_glob_character_wildcard(data_reader, tmp_path):
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    (test_dir / "file_a.xml").write_text("<root>a</root>")
    (test_dir / "file_b.xml").write_text("<root>b</root>")
    (test_dir / "file_ab.xml").write_text("<root>ab</root>")

    data_file = DataFile(name="test_xml", glob="file_?.xml")

    with pytest.raises(ValueError, match="Multiple files matched"):
        data_reader.read_data_file(data_file, folder_path=test_dir)


def test_glob_error_message_includes_suggestions(data_reader, empty_dir):
    data_file = DataFile(name="test_xml", glob="*.xml")

    with pytest.raises(FileNotFoundError) as exc_info:
        data_reader.read_data_file(data_file, folder_path=empty_dir)

    error_msg = str(exc_info.value)
    assert "No files found" in error_msg


def test_glob_multiple_matches_lists_files(data_reader, multi_xml_dir):
    data_file = DataFile(name="test_xml", glob="*.xml")

    with pytest.raises(ValueError) as exc_info:
        data_reader.read_data_file(data_file, folder_path=multi_xml_dir)

    error_msg = str(exc_info.value)
    assert "model_0.xml" in error_msg
    assert "model_1.xml" in error_msg
    assert "model_2.xml" in error_msg


def test_glob_with_reader_function(data_reader, single_xml_dir):
    from r2x_core.datafile import ReaderConfig

    def custom_reader(path):
        return path.read_text()

    data_file = DataFile(
        name="test_xml", glob="*.xml", reader=ReaderConfig(function=custom_reader, kwargs={})
    )

    result = data_reader.read_data_file(data_file, folder_path=single_xml_dir)

    assert isinstance(result, str)
    assert "<root>" in result


def test_glob_file_format_inferred_correctly(single_xml_dir):
    data_file = DataFile(name="test_xml", glob="*.xml")

    assert isinstance(data_file.file_format, XMLFormat)


def test_glob_with_json_file(data_reader, tmp_path):
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    json_file = test_dir / "data.json"
    json_file.write_text('{"key": "value", "num": 42}')

    data_file = DataFile(name="test_json", glob="*.json")

    result = data_reader.read_data_file(data_file, folder_path=test_dir)

    assert result is not None
    assert result["key"] == "value"
    assert result["num"] == 42


def test_glob_with_csv_file(data_reader, tmp_path):
    test_dir = tmp_path / "test"
    test_dir.mkdir()
    csv_file = test_dir / "data.csv"
    csv_file.write_text("a,b,c\n1,2,3\n4,5,6\n")

    data_file = DataFile(name="test_csv", glob="*.csv")

    result = data_reader.read_data_file(data_file, folder_path=test_dir)

    assert result is not None
    collected = result.collect()
    assert len(collected) == 2


def test_glob_validation_empty_pattern():
    """Test that empty glob patterns raise ValueError."""
    with pytest.raises(ValueError, match="Glob pattern cannot be empty"):
        DataFile(name="test", glob="")


def test_glob_validation_whitespace_only():
    """Test that whitespace-only glob patterns raise ValueError."""
    with pytest.raises(ValueError, match="Glob pattern cannot be empty"):
        DataFile(name="test", glob="   ")


def test_glob_validation_invalid_characters():
    """Test that glob patterns with invalid characters raise ValueError."""
    with pytest.raises(ValueError, match="invalid characters"):
        DataFile(name="test", glob="file\x00.xml")


def test_glob_validation_no_wildcards():
    """Test that patterns without wildcards raise ValueError."""
    with pytest.raises(ValueError, match="does not contain glob wildcards"):
        DataFile(name="test", glob="exact_filename.xml")


def test_glob_without_extension_raises():
    """Test that glob patterns without extensions raise ValueError."""

    data_file = DataFile(name="test", glob="*")
    with pytest.raises(ValueError, match="Cannot determine file format from glob pattern"):
        _ = data_file.file_format


def test_glob_timeseries_validation():
    """Test that glob patterns validate timeseries support."""

    data_file = DataFile(name="test", glob="*.xml", info=FileInfo(file_type=FileType.TIME_SERIES))
    with pytest.raises(ValueError, match="does not support time-series data"):
        _ = data_file.file_format


def test_glob_required_file_not_found(data_reader, empty_dir):
    """Test that missing required files raise FileNotFoundError."""
    data_file = DataFile(name="test", glob="*.xml", info=FileInfo(requirement=FileRequirement.REQUIRED))

    with pytest.raises(FileNotFoundError, match="No files found matching pattern"):
        data_reader.read_data_file(data_file, folder_path=empty_dir)


def test_glob_model_validator_both_fpath_and_glob(tmp_path):
    """Test that specifying both fpath and glob raises ValueError."""

    test_file = tmp_path / "file.xml"
    test_file.write_text("<root/>")
    with pytest.raises(ValueError):
        DataFile(name="test", fpath=test_file, glob="*.xml")


def test_glob_model_validator_neither_fpath_nor_glob():
    """Test that specifying neither fpath nor glob raises ValueError."""
    with pytest.raises(ValueError):
        DataFile(name="test")


def test_file_format_with_fpath(tmp_path):
    """Test that file_format property works with fpath."""
    xml_file = tmp_path / "model.xml"
    xml_file.write_text("<root/>")

    data_file = DataFile(name="test", fpath=xml_file)

    assert isinstance(data_file.file_format, XMLFormat)


def test_validate_glob_pattern_none():
    """Test that glob validator handles None correctly."""

    result = validate_glob_pattern(None)
    assert result is None
