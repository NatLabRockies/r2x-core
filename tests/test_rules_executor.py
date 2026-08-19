"""Tests for the translation rule executor helpers."""

import types
from typing import Any, cast
from uuid import uuid4

import pytest
from fixtures.context import FIXTURE_MODEL_MODULES
from fixtures.source_system import BusComponent, BusGeographicInfo
from infrasys.exceptions import ISNotStored
from rust_ok import Err, Ok

from r2x_core import (
    PluginConfig,
    PluginContext,
    Rule,
    RuleFilter,
    System,
    apply_rules_to_context,
    apply_single_rule,
)
from r2x_core.rules_executor import (
    _attach_component,
    _convert_component,
    _convert_component_with_class,
    _is_supplemental_attribute,
    _resolve_component_class,
    _resolve_source_class,
    attach_rule_outputs,
    resolve_supplemental_class,
)


def _build_context(
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

    context = _build_context(
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
    context = _build_context(
        rules=[dependent],
        source_system=source_system,
        target_system=target_system,
    )

    with pytest.raises(ValueError, match="depends on unknown rule"):
        apply_rules_to_context(context)


def test_apply_single_rule_missing_source_attribute(source_system, target_system):
    """Fields missing on the source component produce Err results."""
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"unknown": "missing_attribute"},
    )
    context = _build_context(
        rules=[rule],
        source_system=source_system,
        target_system=target_system,
    )

    result = apply_single_rule(rule, context=context)
    assert result.is_err()
    assert "No attribute" in str(result.err())


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
    context = _build_context(
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

    def faulty_filter(_src, *, context):
        _ = context
        return Err(ValueError("boom"))

    rule = Rule(
        source_type="PlantComponent",
        target_type="StationComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        filter=RuleFilter(getter=faulty_filter, op="eq", values=["gas"]),
    )
    context = _build_context(
        rules=[rule],
        source_system=source_system,
        target_system=target_system,
    )

    result = apply_single_rule(rule, context=context)
    assert result.is_err()
    assert "Failed to evaluate filter" in str(result.err())


def test_attach_component_supplemental_attribute_target_missing(source_system):
    """Supplemental attributes without matching target UUID fail gracefully."""
    target_system = System(name="executor-target")
    context = _build_context(
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

    result = _attach_component(attribute, bus, context)
    assert result.is_err()
    assert "Cannot attach supplemental attribute" in str(result.err())


def test_attach_component_non_supplemental_success(source_system):
    """Non-supplemental components are added directly to the target system."""
    target_system = System(name="executor-target-success")
    context = _build_context(
        rules=[],
        source_system=source_system,
        target_system=target_system,
    )

    bus = next(source_system.get_components(BusComponent))
    result = _attach_component(bus, bus, context)
    assert result.is_ok()


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
    result = _resolve_source_class(cast(Rule, DummyRule()), context=ctx)
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
        context=_build_context(rules=[rule], source_system=source_system, target_system=target_system),
    )
    assert result.is_err()
    assert "MissingTarget" in str(result.err())


def test_apply_single_rule_rejects_supplemental_primary_target(context_example):
    """A rule cannot attach supplemental outputs to a supplemental primary."""
    rule = Rule(
        source_type="BusComponent",
        target_type="BusGeographicInfo",
        version=1,
        supplemental_attributes=[{"target_type": "BusGeographicInfo"}],
    )
    result = apply_single_rule(rule, context=context_example)
    assert result.is_err()
    assert "primary target" in str(result.err())


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

    result = _resolve_component_class("NotAComponent", context=ctx, label="source")

    assert result.is_err()
    assert "is not a Component subclass" in str(result.err())


def test_convert_component_with_class_regenerate_uuid():
    class DummyComponent:
        label = "foo"

    def dummy_create(target_class, kwargs):
        return DummyComponent()

    import r2x_core.rules_executor as re

    orig_create = re.create_target_component
    re.create_target_component = cast(Any, dummy_create)
    try:
        result = _convert_component_with_class(
            rule=cast(Rule, None),
            source_component=types.SimpleNamespace(label="foo"),
            target_class=DummyComponent,
            context=cast(PluginContext, None),
            regenerate_uuid=True,
        )
        assert result.is_ok()
    finally:
        re.create_target_component = orig_create


def test_convert_component_target_type_fail(monkeypatch):
    class DummyRule:
        pass

    monkeypatch.setattr(
        "r2x_core.rules_executor.resolve_component_type",
        lambda target_type, context: Err(TypeError("badtype not found")),
    )
    result = _convert_component(
        cast(Rule, DummyRule()), object(), "badtype", cast(PluginContext, None), False
    )
    assert result.is_err()


def test_apply_single_rule_no_components(monkeypatch):
    class DummyRule:
        def get_target_types(self):
            return ["A"]

        def get_source_types(self):
            return ["B"]

        system = "target"
        filter = None

    ctx = PluginContext(config=DummyConfig(), target_system=cast(System, object()))
    monkeypatch.setattr(
        "r2x_core.rules_executor._resolve_source_class",
        lambda rule, context: types.SimpleNamespace(is_err=lambda: False, ok=lambda: object),
    )
    monkeypatch.setattr(
        "r2x_core.rules_executor.resolve_component_type",
        lambda t, context: Ok(BusComponent),
    )
    monkeypatch.setattr(
        "r2x_core.rules_executor.iter_components", lambda sys, class_type, filter_func=None: iter([])
    )
    monkeypatch.setattr(
        "r2x_core.rules_executor.build_target_fields",
        lambda src, rule, context: types.SimpleNamespace(
            is_err=lambda: False,
            ok=lambda: {"uuid": str(uuid4())},
            map_err=lambda f: types.SimpleNamespace(is_err=lambda: False, ok=lambda: {"uuid": str(uuid4())}),
        ),
    )
    monkeypatch.setattr(
        "r2x_core.rules_executor.create_target_component", lambda target_class, kwargs: object()
    )
    monkeypatch.setattr(
        "r2x_core.rules_executor._attach_component",
        lambda component, src_component, context: types.SimpleNamespace(
            is_err=lambda: False, ok=lambda: None
        ),
    )
    result = apply_single_rule(cast(Rule, DummyRule()), context=ctx)
    assert result.is_ok()


def test_attach_rule_outputs_rolls_back_primary_on_supplemental_failure(monkeypatch, source_system):
    """Output attachment removes earlier outputs when a later output fails."""
    from types import SimpleNamespace

    calls = 0

    def attach(_component, _source, _context):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Ok(None)
        return Err(ValueError("attachment failed"))

    removed = []
    context = cast(
        PluginContext,
        SimpleNamespace(
            target_system=SimpleNamespace(
                remove_supplemental_attribute=removed.append,
                remove_component=removed.append,
                get_supplemental_attribute_by_uuid=lambda _uuid: (_ for _ in ()).throw(
                    ISNotStored("not stored")
                ),
            )
        ),
    )
    monkeypatch.setattr("r2x_core.rules_executor._attach_component", attach)
    primary = BusComponent(name="translated")
    result = attach_rule_outputs(
        SimpleNamespace(
            primary=primary,
            supplemental_attributes=(BusGeographicInfo(location_name="invalid"),),
        ),
        source_system.get_components(BusComponent).__next__(),
        context,
    )
    assert result.is_err()
    assert removed == [primary]


def test_attach_rule_outputs_rolls_back_attached_supplemental(monkeypatch, source_system):
    """Output attachment removes already-attached supplemental attributes."""
    from types import SimpleNamespace

    calls = 0
    first = BusGeographicInfo(location_name="first")
    second = BusGeographicInfo(location_name="second")

    def attach(_component, _source, _context):
        nonlocal calls
        calls += 1
        return Ok(None) if calls < 3 else Err(ValueError("attachment failed"))

    removed = []
    context = cast(
        PluginContext,
        SimpleNamespace(
            target_system=SimpleNamespace(
                remove_supplemental_attribute=removed.append,
                remove_component=removed.append,
                get_supplemental_attribute_by_uuid=lambda _uuid: (_ for _ in ()).throw(
                    ISNotStored("not stored")
                ),
            )
        ),
    )
    monkeypatch.setattr("r2x_core.rules_executor._attach_component", attach)
    primary = BusComponent(name="translated")
    result = attach_rule_outputs(
        SimpleNamespace(
            primary=primary,
            supplemental_attributes=(first, second),
        ),
        source_system.get_components(BusComponent).__next__(),
        context,
    )
    assert result.is_err()
    assert removed == [first, primary]


def test_attach_rule_outputs_propagates_supplemental_attachment_error(monkeypatch, source_system):
    """Output attachment stops when a supplemental attachment fails."""
    from types import SimpleNamespace

    calls = 0

    def attach(_component, _source, _context):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Ok(None)
        return Err(ValueError("attachment failed"))

    monkeypatch.setattr("r2x_core.rules_executor._attach_component", attach)
    context = cast(
        PluginContext,
        SimpleNamespace(
            target_system=SimpleNamespace(
                get_supplemental_attribute_by_uuid=lambda _uuid: (_ for _ in ()).throw(
                    ISNotStored("not stored")
                )
            )
        ),
    )
    result = attach_rule_outputs(
        SimpleNamespace(
            primary=BusComponent(name="translated"),
            supplemental_attributes=(BusGeographicInfo(location_name="invalid"),),
        ),
        source_system.get_components(BusComponent).__next__(),
        context,
    )
    assert result.is_err()
    assert "attachment failed" in str(result.err())


def test_attach_component_requires_target_system(source_system):
    """Component attachment fails when the target system is absent."""
    context = PluginContext(
        config=DummyConfig(),
        source_system=source_system,
        target_system=None,
    )
    bus = next(source_system.get_components(BusComponent))
    result = _attach_component(bus, bus, context)
    assert result.is_err()
    assert "target_system" in str(result.err())


def test_attach_component_get_component_by_uuid_exception():
    class DummyComponent:
        uuid = "123"

    class DummySystem:
        def get_component_by_uuid(self, uuid):
            raise Exception("fail")

        def add_supplemental_attribute(self, target, component):
            pass

    class DummyContext:
        target_system = DummySystem()

    import r2x_core.rules_executor as re

    orig_is_supp = re._is_supplemental_attribute
    re._is_supplemental_attribute = cast(Any, lambda c: True)
    try:
        result = _attach_component(DummyComponent(), DummyComponent(), cast(PluginContext, DummyContext()))
        assert result.is_err()
        assert "Cannot attach supplemental attribute" in str(result.err())
    finally:
        re._is_supplemental_attribute = orig_is_supp


def test_is_supplemental_attribute_false():
    class NotSA:
        pass

    assert not _is_supplemental_attribute(cast(Any, NotSA()))
