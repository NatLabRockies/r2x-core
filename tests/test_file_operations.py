import os
from pathlib import Path
from unittest.mock import patch

from r2x_core.utils.files import backup_folder, get_r2x_cache_path, resolve_glob_pattern


def test_backup_folder(tmp_path, caplog):
    tmp_folder = tmp_path / "folder"

    tmp_folder.mkdir()
    fpath = tmp_folder / "test.txt"
    fpath.write_text("Hello")

    result = backup_folder(tmp_folder)

    assert result.is_ok()

    assert (tmp_folder.parent / "folder_backup").exists()

    result = backup_folder(tmp_folder)
    assert "exists" in caplog.text


def test_get_r2x_cache_path_default():
    """Test get_r2x_cache_path returns correct path."""
    cache_path = get_r2x_cache_path()

    assert isinstance(cache_path, Path)
    assert "r2x" in str(cache_path)
    assert "cache" in str(cache_path)


@patch("platform.system")
def test_get_r2x_cache_path_windows(mock_system):
    """Test get_r2x_cache_path on Windows."""
    mock_system.return_value = "Windows"

    with patch.dict(os.environ, {"LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local"}):
        cache_path = get_r2x_cache_path()

        assert "r2x" in str(cache_path).lower()
        assert "cache" in str(cache_path).lower()


@patch("platform.system")
def test_get_r2x_cache_path_windows_without_localappdata(mock_system):
    """Test get_r2x_cache_path on Windows without LOCALAPPDATA set."""
    mock_system.return_value = "Windows"

    env_copy = os.environ.copy()
    env_copy.pop("LOCALAPPDATA", None)

    with patch.dict(os.environ, env_copy, clear=True):
        cache_path = get_r2x_cache_path()

        assert isinstance(cache_path, Path)
        assert "r2x" in str(cache_path).lower()


@patch("platform.system")
def test_get_r2x_cache_path_linux(mock_system):
    """Test get_r2x_cache_path on Linux."""
    mock_system.return_value = "Linux"

    cache_path = get_r2x_cache_path()

    assert ".config" in str(cache_path)
    assert "r2x" in str(cache_path)


def test_backup_folder_nonexistent():
    """Test backup_folder returns error for nonexistent folder."""
    nonexistent = Path("/nonexistent/folder/path")

    result = backup_folder(nonexistent)

    assert result.is_err()
    assert result.error is not None and "does not exist" in result.error


def test_backup_folder_string_path(tmp_path):
    """Test backup_folder with string path."""
    tmp_folder = tmp_path / "folder"
    tmp_folder.mkdir()
    (tmp_folder / "test.txt").write_text("content")

    result = backup_folder(str(tmp_folder))

    assert result.is_ok()
    assert (tmp_path / "folder_backup").exists()


def test_backup_folder_preserves_contents(tmp_path):
    """Test backup_folder preserves folder contents."""
    tmp_folder = tmp_path / "folder"
    tmp_folder.mkdir()

    (tmp_folder / "file1.txt").write_text("content1")
    (tmp_folder / "file2.txt").write_text("content2")

    subdir = tmp_folder / "subdir"
    subdir.mkdir()
    (subdir / "file3.txt").write_text("content3")

    result = backup_folder(tmp_folder)
    assert result.is_ok()

    assert (tmp_folder / "file1.txt").read_text() == "content1"
    assert (tmp_folder / "file2.txt").read_text() == "content2"
    assert (subdir / "file3.txt").read_text() == "content3"

    backup_path = tmp_path / "folder_backup"
    assert backup_path.exists()
    assert (backup_path / "file1.txt").read_text() == "content1"


def test_resolve_glob_pattern_rejects_non_pattern(tmp_path):
    file_path = tmp_path / "exact.csv"
    file_path.write_text("data")

    result = resolve_glob_pattern("exact.csv", search_dir=tmp_path)
    assert result.is_err()
    assert "does not contain glob wildcards" in str(result.err())
