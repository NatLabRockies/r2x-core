"""Utility function for validation."""

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..types import EXTENSION_MAPPING

if TYPE_CHECKING:
    from pydantic import ValidationInfo


def filter_kwargs_for(func: Callable[..., Any], *, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Filter kwargs to only include valid parameters for the given function.

    Parameters
    ----------
    func : Callable
        The function to filter kwargs for
    kwargs : dict[str, Any]
        The keyword arguments to filter

    Returns
    -------
    dict[str, Any]
        Filtered kwargs containing only valid parameters
    """
    sig = inspect.signature(func)
    valid_params = set(sig.parameters.keys())
    return {k: v for k, v in kwargs.items() if k in valid_params}


def filter_kwargs_by_signatures(
    kwargs: dict[str, Any], *, callables: list[Callable[..., Any]]
) -> dict[str, Any]:
    """Filter kwargs to those accepted by the provided callables."""
    valid_params: set[str] = set()
    for callable_obj in callables:
        valid_params.update(inspect.signature(callable_obj).parameters.keys())
    return {k: v for k, v in kwargs.items() if k in valid_params}


def validate_glob_pattern(pattern: str | None) -> str | None:
    """Validate that a string is a valid glob pattern.

    Parameters
    ----------
    pattern : str | None
        The glob pattern to validate

    Returns
    -------
    str | None
        The validated pattern

    Raises
    ------
    ValueError
        If the pattern is invalid (empty, only whitespace, or contains invalid characters)
    """
    if pattern is None:
        return None

    if not pattern or not pattern.strip():
        msg = "Glob pattern cannot be empty"
        raise ValueError(msg)

    invalid_chars = set("\x00")
    if any(char in pattern for char in invalid_chars):
        msg = f"Glob pattern contains invalid characters: {pattern}"
        raise ValueError(msg)

    if not any(wildcard in pattern for wildcard in ["*", "?", "[", "]"]):
        msg = f"Pattern '{pattern}' does not contain glob wildcards (*, ?, [, ]). Use 'fpath' for exact filenames."
        raise ValueError(msg)

    return pattern


def validate_file_extension(path: Path, *, info: "ValidationInfo") -> Path:
    """Validate that the file path has a supported extension.

    This is a Pydantic validator that checks if the file extension from the
    provided path exists as a key in the module-level `EXTENSION_MAPPING`.

    Parameters
    ----------
    value : str
        The file path string to validate, provided by Pydantic.
    info : pydantic.ValidationInfo
        Pydantic's validation context. Required by the validator signature
        but not used in this function.

    Returns
    -------
    Path
        The original file path string if its extension is valid.

    Raises
    ------
    AssertionError
        If the input `value` is not a string.
    ValueError
        If the file path has no extension.
    KeyError
        If the file's extension is not found in `EXTENSION_MAPPING`.

    Notes
    -----
    This function is intended for use as a Pydantic model validator (e.g.,
    with `@field_validator` or `AfterValidator`) and should not be called directly.
    """
    if info is None:
        raise ValueError("Pydantic validation context is missing.")
    if not isinstance(path, Path):
        raise TypeError(f"Expected Path, got {type(path).__name__}")
    ext = path.suffix.lower()
    if ext not in EXTENSION_MAPPING:
        msg = f"{ext=} not found on `EXTENSION_MAPPING`. "
        msg += "Check spelling of file type or verify it is a supported `FileFormat`."
        msg += f"List of supported `FileFormat`: {EXTENSION_MAPPING.keys()}"
        raise KeyError(msg)
    return path
