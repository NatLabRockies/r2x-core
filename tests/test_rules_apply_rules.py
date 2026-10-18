"""Tests for rule-based component translation using functional dispatcher."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fixtures.context import FIXTURE_MODEL_MODULES

from r2x_core.rules import ComponentSource, ComponentTarget

if TYPE_CHECKING:
    from r2x_core import PluginContext


def test_convert_rule_single_component(context_example: PluginContext):
    """convert_rule applies a rule to all matching source components."""
    from fixtures.target_system import CircuitComponent, NodeComponent, StationComponent

    from r2x_core import apply_rules_to_context

    result = apply_rules_to_context(context_example, on_error="continue")

    assert result.success
    assert result.total_rules == 3
    assert result.total_converted == 3
    assert all(rule_result.success for rule_result in result.rule_results)
    assert all(rule_result.converted == 1 for rule_result in result.rule_results)

    target_system = context_example.target_system
    assert target_system is not None

    bus_nodes = [node for node in target_system.get_components(NodeComponent) if node.name == "bus_a"]
    assert bus_nodes and bus_nodes[0].demand_mw == 150.0

    circuits = [
        circuit for circuit in target_system.get_components(CircuitComponent) if circuit.name == "line_ab"
    ]
    assert circuits and circuits[0].capacity_mw == 300.0

    stations = [
        station for station in target_system.get_components(StationComponent) if station.name == "plant_alpha"
    ]
    assert stations and stations[0].resource == "gas"


def test_apply_rules_requires_non_empty_rule_list(source_system, target_system):
    """Plugin context without rules raises ValueError."""
    from r2x_core import PluginConfig, PluginContext, apply_rules_to_context

    context = PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=PluginConfig(models=FIXTURE_MODEL_MODULES),
        rules=(),
        store=None,
    )

    with pytest.raises(ValueError, match="has no rules"):
        apply_rules_to_context(context, on_error="continue")


def test_apply_rules_reports_resolution_errors(source_system, target_system):
    """Failed component resolution surfaces as failed rule result."""
    from r2x_core import PluginConfig, PluginContext, Rule, apply_rules_to_context

    invalid_rule = Rule(
        source=ComponentSource(component_type="MissingComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name"},
    )

    context = PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=PluginConfig(models=FIXTURE_MODEL_MODULES),
        rules=(invalid_rule,),
        store=None,
    )

    with pytest.raises(ValueError, match="MissingComponent"):
        apply_rules_to_context(context, on_error="continue")

    assert list(target_system.get_components()) == []
