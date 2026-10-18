"""Rule identity and explicit source/target validation tests."""

import pytest
from pydantic import ValidationError

from r2x_core import ComponentSource, ComponentTarget, Rule


def test_rule_equality_uses_source_target_and_version() -> None:
    """Field mappings do not alter a Rule's identity."""
    first = Rule(
        source=ComponentSource(component_type="Bus"),
        target=ComponentTarget(component_types=("Node",)),
        version=1,
        field_map={"name": "name"},
    )
    second = Rule(
        source=ComponentSource(component_type="Bus"),
        target=ComponentTarget(component_types=("Node",)),
        version=1,
        field_map={"name": "name", "extra": "extra"},
    )

    assert first == second
    assert hash(first) == hash(second)


def test_rule_inequality_distinguishes_version() -> None:
    """Different Rule versions have distinct identities."""
    first = Rule(
        source=ComponentSource(component_type="Bus"),
        target=ComponentTarget(component_types=("Node",)),
        version=1,
    )
    second = Rule(
        source=ComponentSource(component_type="Bus"),
        target=ComponentTarget(component_types=("Node",)),
        version=2,
    )

    assert first != second


def test_rule_is_hashable() -> None:
    """Equal typed Rules deduplicate in a set."""
    first = Rule(
        source=ComponentSource(component_type="Bus"),
        target=ComponentTarget(component_types=("Node",)),
        version=1,
    )
    second = Rule(
        source=ComponentSource(component_type="Bus"),
        target=ComponentTarget(component_types=("Node",)),
        version=1,
    )

    assert len({first, second}) == 1


def test_component_target_supports_multiple_outputs_from_one_source() -> None:
    """One source may explicitly target multiple component classes."""
    rule = Rule(
        source=ComponentSource(component_type="Bus"),
        target=ComponentTarget(component_types=("Node", "Circuit")),
        version=1,
    )

    assert rule.target.component_types == ("Node", "Circuit")


def test_rule_records_reject_ambiguous_multiple_sources() -> None:
    """Source lists are not accepted as an implicit source-selection policy."""
    with pytest.raises(ValidationError):
        Rule.from_records(
            [
                {
                    "source": ["Bus", "Line"],
                    "target": {"kind": "component", "component_types": ["Node"]},
                    "version": 1,
                }
            ]
        )


def test_multi_field_rule_mapping_requires_getter() -> None:
    """Combining multiple source fields requires a declared getter."""
    with pytest.raises(ValueError, match="requires a getter function"):
        Rule(
            source=ComponentSource(component_type="A"),
            target=ComponentTarget(component_types=("B",)),
            version=1,
            field_map={"target": ["a", "b"]},
        )


def test_filter_must_be_typed() -> None:
    """Invalid filter data is rejected by Pydantic validation."""
    with pytest.raises(ValidationError):
        Rule(
            source=ComponentSource(component_type="A"),
            target=ComponentTarget(component_types=("B",)),
            version=1,
            filter="not_a_filter",
        )
