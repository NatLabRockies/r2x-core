"""Tests for typed PluginContext Rule queries."""

from typing import ClassVar

import pytest

from r2x_core import ComponentSource, ComponentTarget, Rule
from r2x_core.plugin_config import PluginConfig
from r2x_core.plugin_context import PluginContext
from r2x_core.system import System


class SimpleConfig(PluginConfig):
    """Test config."""


@pytest.fixture
def sample_rules() -> tuple[Rule, ...]:
    """Create typed Rules for source/target queries."""
    return tuple(
        Rule.from_records(
            [
                {
                    "source": {"kind": "component", "component_type": "BusComponent"},
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "version": 1,
                    "field_map": {"name": "name", "uuid": "uuid"},
                },
                {
                    "source": {"kind": "component", "component_type": "BusComponent"},
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "version": 2,
                    "field_map": {"name": "name", "uuid": "uuid"},
                },
                {
                    "source": {"kind": "component", "component_type": "LineComponent"},
                    "target": {"kind": "component", "component_types": ["CircuitComponent"]},
                    "version": 1,
                    "field_map": {"name": "name", "uuid": "uuid"},
                },
            ]
        )
    )


def test_get_rule_by_exact_typed_match(sample_rules: tuple[Rule, ...]) -> None:
    """Get one Rule by its typed source, target, and version."""
    context = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )
    source = ComponentSource(component_type="BusComponent")
    target = ComponentTarget(component_types=("NodeComponent",))

    rule = context.get_rule(source, target=target, version=1)

    assert rule.version == 1
    assert rule.source == source
    assert rule.target == target


def test_get_rule_default_version(sample_rules: tuple[Rule, ...]) -> None:
    """Default to the active component-source version from config."""

    class ConfigWithVersions(PluginConfig):
        active_versions: ClassVar[dict[str, int]] = {"BusComponent": 2}

    context = PluginContext(
        config=ConfigWithVersions(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    rule = context.get_rule(
        ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
    )

    assert rule.version == 2


def test_get_rule_not_found(sample_rules: tuple[Rule, ...]) -> None:
    """Unknown typed declarations raise KeyError."""
    context = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    with pytest.raises(KeyError, match="No rule found"):
        context.get_rule(
            ComponentSource(component_type="NonExistent"),
            target=ComponentTarget(component_types=("AlsoNone",)),
            version=1,
        )


def test_list_available_conversions(sample_rules: tuple[Rule, ...]) -> None:
    """List component-source conversions using target names and versions."""
    context = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    conversions = context.list_available_conversions()

    assert "BusComponent" in conversions
    assert "LineComponent" in conversions
    assert [option.version for option in conversions["BusComponent"]] == [1, 2]


def test_get_rules_for_source(sample_rules: tuple[Rule, ...]) -> None:
    """Return all versions for one exact typed source."""
    context = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    bus_rules = context.get_rules_for_source(ComponentSource(component_type="BusComponent"))

    assert [rule.version for rule in bus_rules] == [1, 2]


def test_get_rules_for_conversion(sample_rules: tuple[Rule, ...]) -> None:
    """Return all versions for one exact typed source/target pair."""
    context = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=sample_rules,
    )

    conversions = context.get_rules_for_conversion(
        ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
    )

    assert [rule.version for rule in conversions] == [1, 2]


def test_empty_rules() -> None:
    """Typed queries return empty collections for an empty context."""
    context = PluginContext(
        config=SimpleConfig(),
        source_system=System(name="source"),
        target_system=System(name="target"),
        rules=(),
    )

    assert context.list_available_conversions() == {}
    assert context.get_rules_for_source(ComponentSource(component_type="BusComponent")) == []
    assert (
        context.get_rules_for_conversion(
            ComponentSource(component_type="BusComponent"),
            target=ComponentTarget(component_types=("NodeComponent",)),
        )
        == []
    )
