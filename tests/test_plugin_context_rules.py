"""Tests for PluginContext rule lookup methods."""

import pytest

from r2x_core import Rule
from r2x_core.plugin_config import PluginConfig
from r2x_core.plugin_context import PluginContext
from r2x_core.system import System


class SimpleConfig(PluginConfig):
    """Test config."""


@pytest.fixture
def sample_rules():
    """Create sample rules for testing."""
    rule_dicts = [
        {
            "source_type": "BusComponent",
            "target_type": "NodeComponent",
            "version": 1,
            "field_map": {"name": "name", "uuid": "uuid"},
        },
        {
            "source_type": "BusComponent",
            "target_type": "NodeComponent",
            "version": 2,
            "field_map": {"name": "name", "uuid": "uuid"},
        },
        {
            "source_type": "LineComponent",
            "target_type": "CircuitComponent",
            "version": 1,
            "field_map": {"name": "name", "uuid": "uuid"},
        },
    ]
    return tuple(Rule.from_records(rule_dicts))


def test_get_rule_by_exact_match(sample_rules):
    """Test getting a rule by source, target, and version."""
    ctx = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    rule = ctx.get_rule("BusComponent", target_type="NodeComponent", version=1)
    assert rule.version == 1
    assert rule.source_type == "BusComponent"
    assert rule.target_type == "NodeComponent"


def test_get_rule_default_version(sample_rules):
    """Test getting a rule with default version from config."""

    class ConfigWithVersions(PluginConfig):
        pass

    ctx = PluginContext(
        config=ConfigWithVersions(active_versions={"BusComponent": 2}),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    rule = ctx.get_rule("BusComponent", target_type="NodeComponent")
    assert rule.version == 2


def test_get_rule_not_found(sample_rules):
    """Test getting a rule that doesn't exist."""
    ctx = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    with pytest.raises(KeyError, match="No rule found"):
        ctx.get_rule("NonExistent", target_type="AlsoNone", version=1)


def test_list_available_conversions(sample_rules):
    """Test listing available conversions."""
    ctx = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    conversions = ctx.list_available_conversions()

    # Check that conversions are returned as dict with sorted ConversionOption objects
    assert isinstance(conversions, dict)
    assert "BusComponent" in conversions
    assert "LineComponent" in conversions

    # Values should be sorted lists of ConversionOption objects
    for targets in conversions.values():
        assert isinstance(targets, list)
        for target in targets:
            assert hasattr(target, "target_type")
            assert hasattr(target, "version")


def test_get_rules_for_source(sample_rules):
    """Test getting all rules for a specific source type."""
    ctx = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    bus_rules = ctx.get_rules_for_source("BusComponent")
    assert len(bus_rules) == 2  # Two versions
    for rule in bus_rules:
        assert "BusComponent" in rule.get_source_types()


def test_get_rules_for_conversion(sample_rules):
    """Test getting all versions of a conversion."""
    ctx = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    conversions = ctx.get_rules_for_conversion("BusComponent", target_type="NodeComponent")
    assert len(conversions) == 2  # Two versions
    for rule in conversions:
        assert "BusComponent" in rule.get_source_types()
        assert "NodeComponent" in rule.get_target_types()


def test_empty_rules():
    """Test with empty rules."""
    ctx = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=(),
    )

    conversions = ctx.list_available_conversions()
    assert conversions == {}

    bus_rules = ctx.get_rules_for_source("BusComponent")
    assert bus_rules == []

    conversions = ctx.get_rules_for_conversion("BusComponent", target_type="NodeComponent")
    assert conversions == []
