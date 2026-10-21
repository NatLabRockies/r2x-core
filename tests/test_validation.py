"""Tests for validation utility functions."""

from pathlib import Path

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
    """Tests for supported path extensions."""

    @pytest.mark.parametrize("extension", [".csv", ".tsv", ".h5", ".hdf5", ".json", ".xml", ".parquet"])
    def test_supported_extensions(self, extension: str) -> None:
        path = Path(f"data{extension}")

        assert validate_file_extension(path) is path

    @pytest.mark.parametrize("extension", [".CSV", ".CsV"])
    def test_uppercase_extensions(self, extension: str) -> None:
        path = Path(f"data{extension}")

        assert validate_file_extension(path) is path

    @pytest.mark.parametrize("extension", [".txt", ".pdf", ".xyz", ""])
    def test_unsupported_extensions(self, extension: str) -> None:
        path = Path(f"data{extension}")

        with pytest.raises(ValueError, match="Unsupported file extension"):
            validate_file_extension(path)

    def test_none_path(self) -> None:
        assert validate_file_extension(None) is None
