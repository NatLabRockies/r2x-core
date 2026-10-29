"""Datetime parsing utilities."""

from collections.abc import Sequence
from datetime import UTC, datetime

import numpy as np


def parse_datetime_array(dt_strings: Sequence[str], /, *, strip_timezone: bool) -> np.ndarray:
    """Parse ISO 8601 strings into timezone-naive ``datetime64[us]`` values.

    Parameters
    ----------
    dt_strings : Sequence[str]
        ISO 8601 datetime strings to parse.
    strip_timezone : bool
        Remove timezone information without changing wall time when true. When
        false, normalize timezone-aware values to UTC before removing it.

    Returns
    -------
    numpy.ndarray
        Parsed datetimes with a microsecond-resolution ``datetime64`` dtype.
    """
    parsed: list[datetime] = []
    for index, dt_string in enumerate(dt_strings):
        try:
            dt_value = datetime.fromisoformat(dt_string)
            if dt_value.tzinfo is not None:
                if strip_timezone:
                    dt_value = dt_value.replace(tzinfo=None)
                else:
                    dt_value = dt_value.astimezone(UTC).replace(tzinfo=None)
            parsed.append(dt_value)
        except (ValueError, AttributeError) as error:
            msg = (
                f"Failed to parse datetime string at index {index}: '{dt_string}'. "
                f"Expected ISO 8601 format. Error: {error}"
            )
            raise ValueError(msg) from error

    return np.array(parsed, dtype="datetime64[us]")
