"""Tests for model-neutral keyed-grid expansion."""

import polars as pl
import pytest

from r2x_core.grid import expand_keyed_grid


def test_expand_keyed_grid_fills_orders_and_rounds_by_group() -> None:
    values = pl.DataFrame(
        {
            "region": ["p2", "p1", "p1"],
            "period": ["a", "a", "b"],
            "value": [2.0, 1.000003, None],
        }
    )
    grid = pl.DataFrame(
        {
            "hour": [1, 2, 3, 4],
            "period": ["a", "b", "a", "c"],
        }
    )

    result = expand_keyed_grid(
        values,
        grid,
        group_columns=["region"],
        value_keys=["period"],
        grid_keys=["period"],
        order_columns=["hour"],
        value_columns=["value"],
        fill_values={"value": 0.0},
        round_digits=5,
    )

    assert result.is_ok(), result.err()
    frame = result.ok()
    assert frame is not None
    assert frame.to_dicts() == [
        {"region": "p1", "hour": 1, "value": 1.0},
        {"region": "p1", "hour": 2, "value": 0.0},
        {"region": "p1", "hour": 3, "value": 1.0},
        {"region": "p1", "hour": 4, "value": 0.0},
        {"region": "p2", "hour": 1, "value": 2.0},
        {"region": "p2", "hour": 2, "value": 0.0},
        {"region": "p2", "hour": 3, "value": 2.0},
        {"region": "p2", "hour": 4, "value": 0.0},
    ]


@pytest.mark.parametrize(
    ("values", "grid", "message"),
    [
        (
            pl.DataFrame({"region": ["p1", "p1"], "period": ["a", "a"], "value": [1.0, 2.0]}),
            pl.DataFrame({"hour": [1], "period": ["a"]}),
            "duplicate group keys",
        ),
        (
            pl.DataFrame({"region": ["p1"], "period": ["a"], "value": [1.0]}),
            pl.DataFrame({"hour": [1, 1], "period": ["a", "b"]}),
            "duplicate order keys",
        ),
    ],
)
def test_expand_keyed_grid_rejects_ambiguous_keys(
    values: pl.DataFrame, grid: pl.DataFrame, message: str
) -> None:
    result = expand_keyed_grid(
        values,
        grid,
        group_columns=["region"],
        value_keys=["period"],
        grid_keys=["period"],
        order_columns=["hour"],
        value_columns=["value"],
        fill_values={"value": 0.0},
    )

    assert result.is_err()
    assert message in str(result.err())
