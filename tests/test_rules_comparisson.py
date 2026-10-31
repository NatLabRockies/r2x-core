import pytest

pytestmark = pytest.mark.rules


def test_rule_equality_by_metadata():
    """Rules are equal if they have same source_type, target_type, and version."""
    from r2x_core import Rule

    rule1 = Rule(
        source_type="Bus",
        target_type="Node",
        version=1,
        field_map={"name": "name"},
    )
    rule2 = Rule(
        source_type="Bus",
        target_type="Node",
        version=1,
        field_map={"name": "name", "extra": "extra"},  # Different field_map
    )
    # Should be equal because metadata is the same
    assert rule1 == rule2


def test_rule_inequality_different_version():
    """Rules are not equal if versions differ."""
    from r2x_core import Rule

    rule1 = Rule(
        source_type="Bus",
        target_type="Node",
        version=1,
        field_map={"name": "name"},
    )
    rule2 = Rule(
        source_type="Bus",
        target_type="Node",
        version=2,
        field_map={"name": "name"},
    )
    assert rule1 != rule2


def test_rule_hashable():
    """Rules can be used in sets based on their metadata."""
    from r2x_core import Rule

    rule1 = Rule(
        source_type="Bus",
        target_type="Node",
        version=1,
        field_map={"name": "name"},
    )
    rule2 = Rule(
        source_type="Bus",
        target_type="Node",
        version=1,
        field_map={"name": "name"},
    )
    rule_set = {rule1, rule2}
    # Both should hash the same, so set has only 1 element
    assert len(rule_set) == 1


def test_rule_post_init_multiple_sources_and_targets():
    """Rule cannot have both multiple sources and multiple targets."""
    import pytest

    from r2x_core import Rule

    with pytest.raises(NotImplementedError, match="cannot have both multiple sources and multiple targets"):
        Rule(source_type=["A", "B"], target_type=["X", "Y"], version=1, field_map={})


def test_rule_post_init_multifield_mapping_without_getter():
    """Multi-field mapping for target requires a getter function."""
    import pytest

    from r2x_core import Rule

    with pytest.raises(ValueError, match="requires a getter function"):
        Rule(source_type="A", target_type="B", version=1, field_map={"target": ["a", "b"]})


def test_rule_post_init_filter_type_error():
    """Rule.filter must be a RuleFilter."""
    import pytest

    from r2x_core import Rule

    with pytest.raises(TypeError, match="must be a RuleFilter"):
        Rule(source_type="A", target_type="B", version=1, field_map={}, filter="not_a_filter")  # type: ignore[arg-type]
