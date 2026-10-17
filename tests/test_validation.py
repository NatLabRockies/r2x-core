"""Tests for validation utility functions."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from r2x_core.utils import filter_kwargs_for
from r2x_core.utils.validation import (
    validate_file_extension,
    validate_glob_pattern,
)


class TestFilterKwargsFor:
    """Tests for filter_kwargs_for function."""

    def test_filter_kwargs_for_all_valid(self):
        """Test filter_kwargs_for with all valid parameters."""

        def sample_func(a, b, c):
            pass

        kwargs = {"a": 1, "b": 2, "c": 3}
        result = filter_kwargs_for(sample_func, kwargs=kwargs)
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_filter_kwargs_for_some_invalid(self):
        """Test filter_kwargs_for with some invalid parameters."""

        def sample_func(a, b):
            pass

        kwargs = {"a": 1, "b": 2, "c": 3, "d": 4}
        result = filter_kwargs_for(sample_func, kwargs=kwargs)
        assert result == {"a": 1, "b": 2}

    def test_filter_kwargs_for_empty(self):
        """Test filter_kwargs_for with empty kwargs."""

        def sample_func(a, b):
            pass

        kwargs = {}
        result = filter_kwargs_for(sample_func, kwargs=kwargs)
        assert result == {}

    def test_filter_kwargs_for_all_invalid(self):
        """Test filter_kwargs_for with all invalid parameters."""

        def sample_func(a, b):
            pass

        kwargs = {"c": 3, "d": 4}
        result = filter_kwargs_for(sample_func, kwargs=kwargs)
        assert result == {}

    def test_filter_kwargs_for_with_kwargs_param(self):
        """Test filter_kwargs_for with function that accepts **kwargs."""

        def sample_func(a, **kwargs):
            pass

        params = {"a": 1, "b": 2, "c": 3}
        result = filter_kwargs_for(sample_func, kwargs=params)
        assert result == {"a": 1}


class TestValidateGlobPattern:
    """Tests for validate_glob_pattern function."""

    def test_validate_glob_pattern_none(self):
        """Test validate_glob_pattern with None returns None."""
        result = validate_glob_pattern(None)
        assert result is None

    def test_validate_glob_pattern_valid_asterisk(self):
        """Test validate_glob_pattern with valid asterisk pattern."""
        pattern = "*.csv"
        result = validate_glob_pattern(pattern)
        assert result == pattern

    def test_validate_glob_pattern_valid_question_mark(self):
        """Test validate_glob_pattern with valid question mark pattern."""
        pattern = "file?.csv"
        result = validate_glob_pattern(pattern)
        assert result == pattern

    def test_validate_glob_pattern_valid_brackets(self):
        """Test validate_glob_pattern with valid brackets pattern."""
        pattern = "file[0-9].csv"
        result = validate_glob_pattern(pattern)
        assert result == pattern

    def test_validate_glob_pattern_valid_double_asterisk(self):
        """Test validate_glob_pattern with valid double asterisk pattern."""
        pattern = "**/*.csv"
        result = validate_glob_pattern(pattern)
        assert result == pattern

    def test_validate_glob_pattern_empty_string(self):
        """Test validate_glob_pattern with empty string raises ValueError."""
        with pytest.raises(ValueError, match="Glob pattern cannot be empty"):
            validate_glob_pattern("")

    def test_validate_glob_pattern_whitespace_only(self):
        """Test validate_glob_pattern with whitespace only raises ValueError."""
        with pytest.raises(ValueError, match="Glob pattern cannot be empty"):
            validate_glob_pattern("   ")

    def test_validate_glob_pattern_null_character(self):
        """Test validate_glob_pattern with null character raises ValueError."""
        with pytest.raises(ValueError, match="Glob pattern contains invalid characters"):
            validate_glob_pattern("file\x00.csv")

    def test_validate_glob_pattern_no_wildcards(self):
        """Test validate_glob_pattern without wildcards raises ValueError."""
        with pytest.raises(
            ValueError,
            match="does not contain glob wildcards",
        ):
            validate_glob_pattern("file.csv")

    def test_validate_glob_pattern_only_whitespace_around(self):
        """Test validate_glob_pattern with whitespace around pattern."""
        with pytest.raises(ValueError, match="does not contain glob wildcards"):
            validate_glob_pattern("  plain_filename  ")


class TestValidateFileExtension:
    """Tests for validate_file_extension function."""

    def test_validate_file_extension_valid_csv(self):
        """Test validate_file_extension with valid .csv extension."""
        path = Path("data.csv")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path

    def test_validate_file_extension_valid_h5(self):
        """Test validate_file_extension with valid .h5 extension."""
        path = Path("data.h5")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path

    def test_validate_file_extension_valid_hdf5(self):
        """Test validate_file_extension with valid .hdf5 extension."""
        path = Path("data.hdf5")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path

    def test_validate_file_extension_valid_json(self):
        """Test validate_file_extension with valid .json extension."""
        path = Path("data.json")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path

    def test_validate_file_extension_valid_xml(self):
        """Test validate_file_extension with valid .xml extension."""
        path = Path("data.xml")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path

    def test_validate_file_extension_valid_tsv(self):
        """Test validate_file_extension with valid .tsv extension."""
        path = Path("data.tsv")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path

    def test_validate_file_extension_valid_parquet(self):
        """Test validate_file_extension with valid .parquet extension."""
        path = Path("data.parquet")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path

    def test_validate_file_extension_uppercase_extension(self):
        """Test validate_file_extension with uppercase extension converts to lowercase."""
        path = Path("data.CSV")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path

    def test_validate_file_extension_invalid_extension(self):
        """Test validate_file_extension with invalid extension raises KeyError."""
        path = Path("data.txt")
        info = MagicMock()
        with pytest.raises(KeyError, match="not found on `EXTENSION_MAPPING`"):
            validate_file_extension(path, info=info)

    def test_validate_file_extension_unsupported_format(self):
        """Test validate_file_extension with unsupported file format raises KeyError."""
        path = Path("data.pdf")
        info = MagicMock()
        with pytest.raises(KeyError, match="not found on `EXTENSION_MAPPING`"):
            validate_file_extension(path, info=info)

    def test_validate_file_extension_message_contains_mapping_keys(self):
        """Test validate_file_extension error message contains supported formats."""
        path = Path("data.xyz")
        info = MagicMock()
        with pytest.raises(KeyError) as exc_info:
            validate_file_extension(path, info=info)
        error_msg = str(exc_info.value)
        assert "EXTENSION_MAPPING" in error_msg
        assert "FileFormat" in error_msg

    def test_validate_file_extension_none_info_assertion(self):
        """Test validate_file_extension with None info raises ValueError."""
        path = Path("data.csv")
        with pytest.raises(ValueError, match="Pydantic validation context is missing"):
            validate_file_extension(path, info=None)  # type: ignore[arg-type]

    def test_validate_file_extension_path_with_directory(self):
        """Test validate_file_extension with path containing directories."""
        path = Path("some/directory/data.csv")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path

    def test_validate_file_extension_mixed_case(self):
        """Test validate_file_extension with mixed case extension."""
        path = Path("data.CsV")
        info = MagicMock()
        result = validate_file_extension(path, info=info)
        assert result == path
