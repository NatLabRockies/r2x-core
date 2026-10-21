"""Track mapping-step features required to replace TabularProcessing."""

from typing import get_args

import pytest

from r2x_core.models import MappingStep, SortStep
from r2x_core.types import MappingExpressionOperator


def mapping_step_operations() -> set[str]:
    """Return the operation literals in the discriminated MappingStep union."""
    step_union = get_args(MappingStep)[0]
    return {
        str(operation)
        for step in get_args(step_union)
        for operation in get_args(step.model_fields["op"].annotation)
    }


@pytest.mark.xfail(strict=True, reason="parity item 1: add a pivot mapping step")
def test_mapping_steps_include_pivot() -> None:
    assert "pivot" in mapping_step_operations()


@pytest.mark.xfail(strict=True, reason="parity item 2: add a drop-columns mapping step")
def test_mapping_steps_include_drop_columns() -> None:
    assert {"drop", "drop_columns"} & mapping_step_operations()


@pytest.mark.xfail(strict=True, reason="parity item 3: add sort direction to SortStep")
def test_sort_step_includes_direction() -> None:
    assert {"direction", "directions", "ascending", "descending"} & set(SortStep.model_fields)


@pytest.mark.xfail(strict=True, reason="parity item 4: add replace-values expression or step")
def test_mapping_steps_include_replace_values() -> None:
    operations = mapping_step_operations() | {op.value for op in MappingExpressionOperator}
    assert {"replace", "replace_values"} & operations
