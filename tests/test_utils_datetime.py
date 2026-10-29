"""Tests for general datetime parsing utilities."""

import numpy as np
import pytest

from r2x_core.utils import parse_datetime_array


def test_parse_datetime_array_applies_explicit_timezone_policy() -> None:
    values = ["2024-01-01T00:00:00-06:00"]

    wall_time = parse_datetime_array(values, strip_timezone=True)
    utc_time = parse_datetime_array(values, strip_timezone=False)

    np.testing.assert_array_equal(wall_time, np.array(["2024-01-01T00:00:00"], dtype="datetime64[us]"))
    np.testing.assert_array_equal(utc_time, np.array(["2024-01-01T06:00:00"], dtype="datetime64[us]"))


def test_parse_datetime_array_reports_invalid_value_index() -> None:
    with pytest.raises(ValueError, match="at index 1: 'not-a-datetime'"):
        parse_datetime_array(["2024-01-01T00:00:00", "not-a-datetime"], strip_timezone=True)
