"""Verify the ordered processing schema covers file transformations."""

from typing import get_args

import pytest

from r2x_core.models import MappingStep, SortStep
from r2x_core.types import AggregationFunction, MappingExpressionOperator


def mapping_step_operations() -> set[str]:
    """Return operation literals from the discriminated MappingStep union."""
    step_union = get_args(MappingStep)[0]
    return {
        str(operation)
        for step in get_args(step_union)
        for operation in get_args(step.model_fields["op"].annotation)
    }


pytestmark = [pytest.mark.processing, pytest.mark.table_mapping]


def test_mapping_steps_cover_processing_operations() -> None:
    operations = mapping_step_operations() | {op.value for op in MappingExpressionOperator}

    assert {
        "pivot",
        "drop_columns",
        "replace_values",
        "split_columns",
        "scale_columns",
        "filter_columns",
        "select_columns",
    } <= operations


def test_sort_step_requires_direction_per_column() -> None:
    step = SortStep.model_validate({"op": "sort", "by": {"name": "asc", "count": "desc"}})

    assert step.by == {"name": "asc", "count": "desc"}


def test_aggregation_operators_share_the_common_aggregation_vocabulary() -> None:
    assert {"max", "mean", "sum"} <= {operation.value for operation in AggregationFunction}
