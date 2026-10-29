import json
from pathlib import Path

import pytest

from r2x_core.versioning import VersionReader

pytestmark = pytest.mark.versioning


@pytest.fixture
def test_folder(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def version_file_detector():
    class VersionFileDetector(VersionReader):
        def read_version(self, folder_path: Path) -> str | None:
            version_file = folder_path / "VERSION"
            if version_file.exists():
                return version_file.read_text().strip()
            return None

    return VersionFileDetector()


@pytest.fixture
def json_detector():
    class JsonDetector(VersionReader):
        def read_version(self, folder_path: Path) -> str | None:
            metadata_file = folder_path / "metadata.json"
            if metadata_file.exists():
                data = json.loads(metadata_file.read_text())
                return data.get("version")
            return None

    return JsonDetector()


@pytest.fixture
def nested_path_detector():
    class NestedPathDetector(VersionReader):
        def read_version(self, folder_path: Path) -> str | None:
            nested_file = folder_path / "config" / "version.txt"
            if nested_file.exists():
                return nested_file.read_text().strip()
            return None

    return NestedPathDetector()


def test_version_detector_reads_version_file(test_folder, version_file_detector):
    test_folder.mkdir()
    version_file = test_folder / "VERSION"
    version_file.write_text("1.2.3")

    result = version_file_detector.read_version(test_folder)

    assert result == "1.2.3"


def test_version_detector_returns_none_when_file_missing(test_folder, version_file_detector):
    test_folder.mkdir()

    result = version_file_detector.read_version(test_folder)

    assert result is None


def test_version_detector_returns_none_when_folder_missing(test_folder, version_file_detector):
    result = version_file_detector.read_version(test_folder)

    assert result is None


def test_version_detector_strips_whitespace(test_folder, version_file_detector):
    test_folder.mkdir()
    version_file = test_folder / "VERSION"
    version_file.write_text("  2.0.0\n")

    result = version_file_detector.read_version(test_folder)

    assert result == "2.0.0"


def test_version_detector_reads_json_metadata(test_folder, json_detector):
    test_folder.mkdir()
    metadata_file = test_folder / "metadata.json"
    metadata_file.write_text(json.dumps({"version": "3.1.4", "author": "test"}))

    result = json_detector.read_version(test_folder)

    assert result == "3.1.4"


def test_version_detector_returns_none_for_missing_json_field(test_folder, json_detector):
    test_folder.mkdir()
    metadata_file = test_folder / "metadata.json"
    metadata_file.write_text(json.dumps({"author": "test"}))

    result = json_detector.read_version(test_folder)

    assert result is None


def test_version_detector_handles_nested_paths(test_folder, nested_path_detector):
    config_dir = test_folder / "config"
    config_dir.mkdir(parents=True)
    version_file = config_dir / "version.txt"
    version_file.write_text("5.0.0")

    result = nested_path_detector.read_version(test_folder)

    assert result == "5.0.0"


def test_version_detector_returns_none_for_missing_nested_file(test_folder, nested_path_detector):
    test_folder.mkdir()

    result = nested_path_detector.read_version(test_folder)

    assert result is None


@pytest.mark.parametrize(
    "version_string,expected",
    [
        ("1.0.0", "1.0.0"),
        ("2.3.4", "2.3.4"),
        ("0.1.0", "0.1.0"),
        ("10.20.30", "10.20.30"),
        ("abc123", "abc123"),
        ("v1.0.0", "v1.0.0"),
    ],
    ids=[
        "simple_version",
        "standard_semver",
        "pre_release",
        "double_digits",
        "git_commit",
        "with_prefix",
    ],
)
def test_version_detector_handles_version_formats(
    test_folder, version_file_detector, version_string, expected
):
    test_folder.mkdir()
    version_file = test_folder / "VERSION"
    version_file.write_text(version_string)

    result = version_file_detector.read_version(test_folder)

    assert result == expected


def test_version_detector_empty_file_returns_empty_string(test_folder, version_file_detector):
    test_folder.mkdir()
    version_file = test_folder / "VERSION"
    version_file.write_text("")

    result = version_file_detector.read_version(test_folder)

    assert result == ""


def test_multiple_detectors_on_same_folder(test_folder, version_file_detector, json_detector):
    test_folder.mkdir()
    version_file = test_folder / "VERSION"
    version_file.write_text("1.0.0")
    metadata_file = test_folder / "metadata.json"
    metadata_file.write_text(json.dumps({"version": "2.0.0"}))

    version_result = version_file_detector.read_version(test_folder)
    json_result = json_detector.read_version(test_folder)

    assert version_result == "1.0.0"
    assert json_result == "2.0.0"


def test_version_detector_with_multiline_file(test_folder, version_file_detector):
    test_folder.mkdir()
    version_file = test_folder / "VERSION"
    version_file.write_text("1.5.0\nsome other content\nmore lines")

    result = version_file_detector.read_version(test_folder)

    assert result == "1.5.0\nsome other content\nmore lines"
