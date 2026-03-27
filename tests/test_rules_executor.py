"""Tests for the translation rule executor helpers."""

import types
from uuid import uuid4

import pytest
from fixtures.context import FIXTURE_MODEL_MODULES
from fixtures.source_system import BusComponent, BusGeographicInfo

from r2x_core import (
    PluginConfig,
    PluginContext,
    Rule,
    System,
    apply_rules_to_context,
    apply_single_rule,
)
from r2x_core.rules_executor import (
    _attach_component,
    _convert_component,
    _convert_component_with_class,
    _is_supplemental_attribute,
    _resolve_source_class,
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
        def get_source_types(self): return ["A", "B"]
    ctx = PluginContext(config=DummyConfig())
    monkeypatch.setattr(
        "r2x_core.rules_executor._resolve_component_type",
        lambda t, context: types.SimpleNamespace(
            is_err=lambda: False,
            ok=lambda: object,
            map_err=lambda f: types.SimpleNamespace(is_err=lambda: False, ok=lambda: object)
        ),
    )
    result = _resolve_source_class(DummyRule(), context=ctx)
    assert not result.is_err()


def test_convert_component_with_class_regenerate_uuid():
    class DummyComponent:
        label = "foo"
    def dummy_create(target_class, kwargs): return DummyComponent()
    import r2x_core.rules_executor as re
    orig_create = re._create_target_component
    re._create_target_component = dummy_create
    try:
        result = _convert_component_with_class(
            rule=None,
            source_component=types.SimpleNamespace(label="foo"),
            target_class=DummyComponent,
            context=None,
            regenerate_uuid=True,
        )
        assert result.is_ok()
    finally:
        re._create_target_component = orig_create


def test_convert_component_target_type_fail(monkeypatch):
    class DummyRule:
        pass
    def fail_resolve(target_type, context):
        class DummyResult:
            def map_err(self, f): return self
            def and_then(self, f): return self
            def is_err(self): return True
            def ok(self): return None
        return DummyResult()
    monkeypatch.setattr("r2x_core.rules_executor._resolve_component_type", fail_resolve)
    result = _convert_component(DummyRule(), object(), "badtype", None, False)
    assert result.is_err()


def test_apply_single_rule_no_components(monkeypatch):
    class DummyRule:
        def get_target_types(self): return ["A"]
        def get_source_types(self): return ["B"]
        system = "target"
        filter = None
    ctx = PluginContext(config=DummyConfig(), target_system=object())
    monkeypatch.setattr("r2x_core.rules_executor._resolve_source_class", lambda rule, context: types.SimpleNamespace(is_err=lambda: False, ok=lambda: object))
    monkeypatch.setattr("r2x_core.rules_executor._resolve_component_type", lambda t, context: types.SimpleNamespace(is_err=lambda: False, ok=lambda: object, map_err=lambda f: types.SimpleNamespace(is_err=lambda: False, ok=lambda: object)))
    monkeypatch.setattr("r2x_core.rules_executor._iter_system_components", lambda sys, class_type, filter_func=None: iter([]))
    monkeypatch.setattr("r2x_core.rules_executor._build_target_fields", lambda src, rule, context: types.SimpleNamespace(is_err=lambda: False, ok=lambda: {"uuid": str(uuid4())}, map_err=lambda f: types.SimpleNamespace(is_err=lambda: False, ok=lambda: {"uuid": str(uuid4())})))
    monkeypatch.setattr("r2x_core.rules_executor._create_target_component", lambda target_class, kwargs: object())
    monkeypatch.setattr("r2x_core.rules_executor._attach_component", lambda component, src_component, context: types.SimpleNamespace(is_err=lambda: False, ok=lambda: None))
    result = apply_single_rule(DummyRule(), context=ctx)
    assert result.is_ok()


def test_attach_component_get_component_by_uuid_exception():
    class DummyComponent:
        uuid = "123"
    class DummySystem:
        def get_component_by_uuid(self, uuid): raise Exception("fail")
        def add_supplemental_attribute(self, target, component): pass
    class DummyContext:
        target_system = DummySystem()
    import r2x_core.rules_executor as re
    orig_is_supp = re._is_supplemental_attribute
    re._is_supplemental_attribute = lambda c: True
    try:
        result = _attach_component(DummyComponent(), DummyComponent(), DummyContext())
        assert result.is_err()
        assert "Cannot attach supplemental attribute" in str(result.err())
    finally:
        re._is_supplemental_attribute = orig_is_supp


def test_is_supplemental_attribute_false():
    class NotSA:
        pass
    assert not _is_supplemental_attribute(NotSA())
