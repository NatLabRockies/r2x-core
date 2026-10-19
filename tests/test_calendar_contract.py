"""Calendar regressions through the configured public source contract."""

import polars as pl
import pytest
from pydantic import ValidationError

from r2x_core import CalendarSource


@pytest.mark.parametrize(
    ("year", "samples", "february_samples"),
    [(1900, 8760, 672), (2000, 8784, 696), (2100, 8760, 672)],
)
def test_calendar_observes_gregorian_century_rules(year: int, samples: int, february_samples: int) -> None:
    source = CalendarSource(name="weather", year=year, resolution_seconds=3600)

    frame = source.to_frame()

    assert frame.height == samples
    assert frame.filter(pl.col("month") == 2).height == february_samples
    assert frame["hour_index"].to_list() == list(range(samples))
    assert frame[-1, "timestamp"].month == 12
    assert frame[-1, "timestamp"].day == 31
    assert frame[-1, "timestamp"].hour == 23


@pytest.mark.parametrize("year", [True, 0, 10000, [], [2012, 2012]])
def test_calendar_rejects_invalid_or_ambiguous_years(year: object) -> None:
    with pytest.raises(ValidationError):
        CalendarSource.model_validate({"name": "weather", "year": year, "resolution_seconds": 3600})
