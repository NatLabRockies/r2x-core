"""Shared Polars frame materialization boundary."""

from __future__ import annotations

from typing import cast

import polars as pl


def collect_polars_frame(frame: pl.LazyFrame, /) -> pl.DataFrame:
    """Collect synchronously and narrow Polars' public return union."""
    # Polars types background collection as a union, but False guarantees a synchronous frame.
    return cast(pl.DataFrame, frame.collect(background=False))
