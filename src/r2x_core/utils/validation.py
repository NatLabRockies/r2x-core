"""Utility function for validation."""

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..types import EXTENSION_MAPPING


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


def validate_file_extension(path: Path | None) -> Path | None:
    """Return a path with a supported extension, or propagate a validation error."""
    if path is None:
        return None
    extension = path.suffix.lower()
    if extension not in EXTENSION_MAPPING:
        msg = (
            f"Unsupported file extension {extension!r}. Supported extensions: {', '.join(EXTENSION_MAPPING)}"
        )
        raise ValueError(msg)
    return path
