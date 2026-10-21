"""Tests for the translation rule executor helpers."""

from typing import cast

import pytest
from fixtures.context import FIXTURE_MODEL_MODULES
from fixtures.source_system import BusComponent, BusGeographicInfo
from infrasys import SupplementalAttribute
from infrasys.exceptions import ISNotStored
from pydantic import Field
from rust_ok import Ok

from r2x_core import (
    PluginConfig,
    PluginContext,
    Rule,
    RuleFilter,
    SupplementalAttributeRule,
    System,
    apply_rules_to_context,
    apply_single_rule,
)
from r2x_core.rules_executor import (
    attach_rule_outputs,
    resolve_component_class,
    resolve_source_class,
    resolve_supplemental_class,
)
from r2x_core.utils import RuleOutputs


def build_context(
    *,
    rules: list[Rule],
    source_system: System | None = None,
    target_system: System | None = None,
) -> PluginContext:
    """Helper to build a plugin context for executor tests."""
    source_system = source_system or System(name="executor-source")
    target_system = target_system or System(name="executor-target")
    return PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=PluginConfig(models=FIXTURE_MODEL_MODULES),
        rules=tuple(rules),
        store=None,
    )


def test_apply_rules_rejects_duplicate_rule_names(source_system, target_system):
    """Duplicate rule names trigger sorting errors before execution."""
    rule_a = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name"},
        name="dup",
    )
    rule_b = Rule(
        source_type="BusComponent",
        target_type="CircuitComponent",
        version=1,
        field_map={"name": "name"},
        name="dup",
    )

    context = build_context(
        rules=[rule_a, rule_b],
        source_system=source_system,
        target_system=target_system,
    )

    with pytest.raises(ValueError, match="Duplicate rule name"):
        apply_rules_to_context(context)


def test_apply_rules_detects_missing_dependency(source_system, target_system):
    """Rules depending on unknown names error out."""
    dependent = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name"},
        name="dependent",
        depends_on=["missing"],
    )
    context = build_context(
        rules=[dependent],
        source_system=source_system,
        target_system=target_system,
    )

    with pytest.raises(ValueError, match="depends on unknown rule"):
        apply_rules_to_context(context)


def test_apply_rules_without_source_system_skips_provenance_capture():
    """Source preservation warns and skips capture when no source system exists."""
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        system="target",
    )
    context = PluginContext(
        config=PluginConfig(models=FIXTURE_MODEL_MODULES),
        target_system=System(name="executor-target"),
        rules=(rule,),
        preserve_source=True,
    )

    with pytest.raises(ValueError, match="source_system and target_system must be set"):
        apply_rules_to_context(context)


def test_apply_single_rule_missing_source_attribute(source_system, target_system):
    """Fields missing on the source component produce Err results."""
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"unknown": "missing_attribute"},
    )
    context = build_context(
        rules=[rule],
        source_system=source_system,
        target_system=target_system,
    )

    result = apply_single_rule(rule, context=context)
    assert result.is_err()
    assert "has no attribute 'missing_attribute'" in str(result.err())


def test_apply_single_rule_getter_filter_uses_context(source_system, target_system):
    """Getter-backed filters can select components using PluginContext data."""
    from rust_ok import Ok

    def selected_fuel_type(src, *, context):
        if src.name != context.metadata["selected_name"]:
            return Ok("coal")
        return Ok(context.metadata["selected_fuel_type"])

    rule = Rule(
        source_type="PlantComponent",
        target_type="StationComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        filter=RuleFilter(getter=selected_fuel_type, op="eq", values=["gas"]),
    )
    context = build_context(
        rules=[rule],
        source_system=source_system,
        target_system=target_system,
    ).evolve(metadata={"selected_name": "plant_alpha", "selected_fuel_type": "gas"})

    result = apply_single_rule(rule, context=context)
    assert result.is_ok()
    assert result.unwrap().converted == 1


def test_apply_single_rule_getter_filter_failure(source_system, target_system):
    """Getter failures bubble out as rule failures instead of matches."""
    from rust_ok import Err

    def faulty_filter(src, *, context):
        _ = context
        return Err(ValueError("boom"))

    rule = Rule(
        source_type="PlantComponent",
        target_type="StationComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        filter=RuleFilter(getter=faulty_filter, op="eq", values=["gas"]),
    )
    context = build_context(
        rules=[rule],
        source_system=source_system,
        target_system=target_system,
    )

    result = apply_single_rule(rule, context=context)
    assert result.is_err()
    assert "Failed to evaluate filter" in str(result.err())


class DummyConfig(PluginConfig):
    pass


def test_resolve_source_class_multiple_types(monkeypatch):
    class DummyRule:
        def get_source_types(self):
            return ["A", "B"]

    ctx = PluginContext(config=DummyConfig())
    monkeypatch.setattr(
        "r2x_core.rules_executor.resolve_component_type",
        lambda t, context: Ok(BusComponent),
    )
    result = resolve_source_class(cast(Rule, DummyRule()), context=ctx)
    assert not result.is_err()


def test_apply_single_rule_reports_missing_primary_target_type(source_system, target_system):
    """Primary target resolution failures are returned as rule errors."""
    rule = Rule(
        source_type="BusComponent",
        target_type="MissingTarget",
        version=1,
    )
    result = apply_single_rule(
        rule,
        context=build_context(rules=[rule], source_system=source_system, target_system=target_system),
    )
    assert result.is_err()
    assert "MissingTarget" in str(result.err())


def test_apply_single_rule_requires_selected_system(source_system):
    """A rule cannot execute when its selected system is absent."""
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        system="target",
    )
    context = PluginContext(
        config=PluginConfig(models=FIXTURE_MODEL_MODULES),
        source_system=source_system,
    )

    result = apply_single_rule(rule, context=context)

    assert result.is_err()
    assert "System 'target' is not set" in str(result.err())


def test_apply_single_rule_requires_source_types(source_system, target_system):
    """Rules without source types return a configuration error."""
    rule = Rule(source_type=[], target_type="NodeComponent", version=1)
    context = build_context(rules=[rule], source_system=source_system, target_system=target_system)

    result = apply_single_rule(rule, context=context)

    assert result.is_err()
    assert "has no source types" in str(result.err())


def test_apply_single_rule_rejects_supplemental_primary_target(context_example):
    """A rule cannot attach supplemental outputs to a supplemental primary."""
    rule = Rule(
        source_type="BusComponent",
        target_type="BusGeographicInfo",
        version=1,
        supplemental_attributes=[SupplementalAttributeRule(target_type="BusGeographicInfo")],
    )
    result = apply_single_rule(rule, context=context_example)
    assert result.is_err()
    assert "primary target" in str(result.err())


def test_attach_rule_outputs_rejects_supplemental_primary(source_system):
    """Supplemental outputs require a primary component."""
    target_system = System(name="executor-target")
    context = build_context(
        rules=[],
        source_system=source_system,
        target_system=target_system,
    )
    outputs = RuleOutputs(
        primary=BusGeographicInfo(location_name="primary"),
        supplemental_attributes=(BusGeographicInfo(location_name="supplemental"),),
    )

    result = attach_rule_outputs(outputs, next(source_system.get_components(BusComponent)), context)

    assert result.is_err()
    assert "A primary Component is required" in str(result.err())
    assert list(target_system.iter_all_components()) == []


def test_resolve_supplemental_class_rejects_component(context_example):
    """Supplemental output types must inherit from SupplementalAttribute."""
    result = resolve_supplemental_class("NodeComponent", context=context_example)
    assert result.is_err()
    assert "SupplementalAttribute subclass" in str(result.err())


def test_resolve_component_class_rejects_non_component_type(monkeypatch):
    ctx = PluginContext(config=DummyConfig())
    monkeypatch.setattr(
        "r2x_core.rules_executor.resolve_component_type",
        lambda t, context: Ok(str),
    )

    result = resolve_component_class("NotAComponent", context=ctx, label="source")

    assert result.is_err()
    assert "is not a Component subclass" in str(result.err())


def test_apply_single_rule_no_components(monkeypatch):
    rule = Rule(source_type="B", target_type="A", version=1, system="target")
    ctx = PluginContext(config=DummyConfig(), target_system=cast(System, object()))
    monkeypatch.setattr(
        "r2x_core.rules_executor.resolve_component_type",
        lambda t, context: Ok(BusComponent),
    )
    monkeypatch.setattr("r2x_core.rules_executor.iter_components", lambda system, class_type: iter([]))
    result = apply_single_rule(rule, context=ctx)
    assert result.is_ok()


def test_attach_rule_outputs_preserves_existing_component_on_uuid_conflict(source_system):
    """A duplicate UUID fails without removing the component already stored."""
    target_system = System(name="executor-target")
    existing = BusComponent(name="existing")
    target_system.add_component(existing)
    context = build_context(
        rules=[],
        source_system=source_system,
        target_system=target_system,
    )
    duplicate = BusComponent(name="duplicate", uuid=existing.uuid)

    result = attach_rule_outputs(
        RuleOutputs(primary=duplicate),
        next(source_system.get_components(BusComponent)),
        context,
    )

    assert result.is_err()
    assert target_system.get_component_by_uuid(existing.uuid) is existing
    assert list(target_system.get_components(BusComponent)) == [existing]


def test_attach_rule_outputs_rolls_back_after_supplemental_rejection(source_system):
    """A rejected supplemental attribute rolls back earlier output attachments."""

    class RejectingGeographicInfo(SupplementalAttribute):
        location_name: str = Field(default="", description="Location name")

        def check_supplemental_attribute_addition(self) -> None:
            raise ValueError("attachment failed")

    target_system = System(name="executor-target")
    context = build_context(
        rules=[],
        source_system=source_system,
        target_system=target_system,
    )
    primary = BusComponent(name="translated")
    first = BusGeographicInfo(location_name="first")
    rejected = RejectingGeographicInfo(location_name="rejected")

    result = attach_rule_outputs(
        RuleOutputs(primary=primary, supplemental_attributes=(first, rejected)),
        next(source_system.get_components(BusComponent)),
        context,
    )

    assert result.is_err()
    assert "attachment failed" in str(result.err())
    assert not target_system.has_component(primary)
    assert list(target_system.iter_all_components()) == []
    with pytest.raises(ISNotStored):
        target_system.get_supplemental_attribute_by_uuid(first.uuid)


def test_attach_rule_outputs_requires_target_system(source_system):
    """Output attachment fails when the target system is absent."""
    context = PluginContext(
        config=DummyConfig(),
        source_system=source_system,
        target_system=None,
    )
    bus = next(source_system.get_components(BusComponent))

    result = attach_rule_outputs(RuleOutputs(primary=BusComponent(name="translated")), bus, context)

    assert result.is_err()
    assert "target_system" in str(result.err())


def test_attach_rule_outputs_rejects_supplemental_without_target_owner(source_system):
    """A supplemental attribute fails when its owner is absent from the target system."""
    target_system = System(name="executor-target")
    context = build_context(
        rules=[],
        source_system=source_system,
        target_system=target_system,
    )
    bus = next(source_system.get_components(BusComponent))
    attribute = BusGeographicInfo(
        uuid=bus.uuid,
        latitude=12.3,
        longitude=45.6,
        location_name="nowhere",
    )

    result = attach_rule_outputs(RuleOutputs(primary=attribute), bus, context)

    assert result.is_err()
    assert "Cannot attach supplemental attribute" in str(result.err())
