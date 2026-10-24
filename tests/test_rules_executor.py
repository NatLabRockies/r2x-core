"""Tests for the translation rule executor helpers."""

from typing import ClassVar, cast

import pytest
from fixtures.context import FIXTURE_MODEL_MODULES
from fixtures.source_system import BusComponent, BusGeographicInfo
from infrasys import Component, SupplementalAttribute
from infrasys.exceptions import ISAlreadyAttached, ISNotStored, ISOperationNotAllowed
from pydantic import Field, field_validator
from rust_ok import Ok, Result

from r2x_core import (
    FieldFilter,
    GetterFilter,
    PluginConfig,
    PluginContext,
    Rule,
    SupplementalAttributeRule,
    System,
    apply_rules_to_context,
    apply_single_rule,
)
from r2x_core.rules_executor import (
    RuleApplicationStats,
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
    model_modules: tuple[str, ...] = FIXTURE_MODEL_MODULES,
) -> PluginContext:
    """Build a plugin context for executor tests."""
    source_system = source_system or System(name="executor-source")
    target_system = target_system or System(name="executor-target")
    return PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=PluginConfig(models=model_modules),
        rules=tuple(rules),
        store=None,
    )


def apply_rule(
    rule: Rule,
    *,
    source_system: System,
    target_system: System,
    model_modules: tuple[str, ...] = FIXTURE_MODEL_MODULES,
) -> Result[RuleApplicationStats, ValueError]:
    """Execute a rule against the supplied test systems."""
    return apply_single_rule(
        rule,
        context=build_context(
            rules=[rule],
            source_system=source_system,
            target_system=target_system,
            model_modules=model_modules,
        ),
    )


def root_cause(error: BaseException) -> BaseException:
    """Return the originating exception from a contextual error chain."""
    while error.__cause__ is not None:
        error = error.__cause__
    return error


def attach_outputs(
    outputs: RuleOutputs,
    *,
    source_system: System,
    target_system: System,
    source_component: Component | None = None,
) -> Result[None, ValueError]:
    """Attach outputs to a real target system using executor test context."""
    source = (
        source_component if source_component is not None else next(source_system.get_components(BusComponent))
    )
    context = build_context(rules=[], source_system=source_system, target_system=target_system)
    return attach_rule_outputs(outputs, source, context)


VALIDATOR_FAILURE = TypeError("validator implementation defect")


class RejectingBusComponent(BusComponent):
    """Component addition rejection used to inspect executor error chains."""

    rejection: ClassVar[ValueError] = ValueError("component addition rejected")

    def check_component_addition(self) -> None:
        raise self.rejection


class TypeErrorBusComponent(BusComponent):
    """Component that exposes a programming error during addition checks."""

    failure: ClassVar[TypeError] = TypeError("component addition defect")

    def check_component_addition(self) -> None:
        raise self.failure


class TypeErrorValidatingComponent(BusComponent):
    """Component whose model validator exposes a programming defect."""

    @field_validator("name")
    @classmethod
    def reject_name(cls, value: str) -> str:
        raise VALIDATOR_FAILURE


class TypeErrorValidatingSupplemental(SupplementalAttribute):
    """Supplemental model whose validator exposes a programming defect."""

    location_name: str = Field(default="", description="Location name")

    @field_validator("location_name")
    @classmethod
    def reject_location_name(cls, value: str) -> str:
        raise VALIDATOR_FAILURE


class ComposedComponent(Component):
    """Component with list composition for rollback ownership regressions."""

    children: list[Component] = Field(default_factory=list)
    detail: str = ""


class ComposedRuleTarget(ComposedComponent):
    """Rule target with a composed child and grandchild created by defaults."""

    child: ComposedComponent = Field(
        default_factory=lambda: ComposedComponent(
            name="rule-child",
            children=[ComposedComponent(name="rule-grandchild")],
        )
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
    result = apply_rule(rule, source_system=source_system, target_system=target_system)
    assert result.is_err()
    assert "has no attribute 'missing_attribute'" in str(result.err())


def test_apply_single_rule_skips_components_rejected_by_filter():
    source_system = System(name="executor-source")
    source_system.add_component(BusComponent(name="unselected"))
    target_system = System(name="executor-target")
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name"},
        filter=FieldFilter(field="name", op="eq", values=["selected"]),
    )

    result = apply_rule(rule, source_system=source_system, target_system=target_system)

    assert result.is_ok()
    assert result.unwrap().converted == 0
    assert list(target_system.iter_all_components()) == []


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
        filter=GetterFilter(getter=selected_fuel_type, op="eq", values=["gas"]),
    )
    context = build_context(
        rules=[rule],
        source_system=source_system,
        target_system=target_system,
    ).evolve(metadata={"selected_name": "plant_alpha", "selected_fuel_type": "gas"})

    result = apply_single_rule(rule, context=context)
    assert result.is_ok()
    assert result.unwrap().converted == 1


@pytest.mark.parametrize("failure_stage", ["filter", "getter", "attachment"])
def test_apply_single_rule_preserves_originating_error(source_system, failure_stage):
    """Filter, output-construction, and attachment context retain their cause."""
    from rust_ok import Err

    failure = ValueError("translation callback failed")

    def faulty_callback(source: object, *, context: PluginContext):
        _ = source, context
        return Err(failure)

    target_type = "RejectingBusComponent" if failure_stage == "attachment" else "NodeComponent"
    target_system = System(name="executor-target")
    rule = Rule(
        source_type="BusComponent",
        target_type=target_type,
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        filter=(
            GetterFilter(getter=faulty_callback, op="eq", values=["match"])
            if failure_stage == "filter"
            else None
        ),
        getters={"area": faulty_callback} if failure_stage == "getter" else {},
    )
    if failure_stage == "attachment":
        RejectingBusComponent.rejection = failure
    result = apply_rule(
        rule,
        source_system=source_system,
        target_system=target_system,
        model_modules=(*FIXTURE_MODEL_MODULES, __name__),
    )

    assert result.is_err()
    assert root_cause(result.err()) is failure
    assert list(target_system.iter_all_components()) == []
    if failure_stage == "attachment":
        assert "Failed to attach component" in str(result.err())
    if failure_stage == "filter":
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
    result = apply_rule(rule, source_system=source_system, target_system=target_system)
    assert result.is_err()
    assert "MissingTarget" in str(result.err())
    assert isinstance(result.err().__cause__, TypeError)


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
    result = apply_rule(rule, source_system=source_system, target_system=target_system)

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
    outputs = RuleOutputs(
        primary=BusGeographicInfo(location_name="primary"),
        supplemental_attributes=(BusGeographicInfo(location_name="supplemental"),),
    )

    result = attach_outputs(outputs, source_system=source_system, target_system=target_system)

    assert result.is_err()
    assert "A primary Component is required" in str(result.err())
    assert list(target_system.iter_all_components()) == []


def test_standalone_supplemental_rejection_preserves_owner_and_cause(source_system):
    """A rejected standalone supplemental does not modify its existing owner."""
    failure = ValueError("supplemental rejected")

    class RejectingGeographicInfo(SupplementalAttribute):
        location_name: str = Field(default="")

        def check_supplemental_attribute_addition(self) -> None:
            raise failure

    source = next(source_system.get_components(BusComponent))
    owner = BusComponent(name="target owner", uuid=source.uuid)
    target_system = System(name="executor-target")
    target_system.add_component(owner)
    attribute = RejectingGeographicInfo(location_name="rejected")

    result = attach_outputs(
        RuleOutputs(primary=attribute),
        source_system=source_system,
        target_system=target_system,
    )

    assert result.is_err()
    assert root_cause(result.err()) is failure
    assert target_system.get_component_by_uuid(owner.uuid) is owner
    with pytest.raises(ISNotStored):
        target_system.get_supplemental_attribute_by_uuid(attribute.uuid)


def test_supplemental_rollback_failure_preserves_both_errors(source_system):
    """A callback detaching an earlier output remains visible as cleanup failure."""
    failure = ValueError("later supplemental rejected")
    target_system = System(name="executor-target")
    primary = BusComponent(name="translated")
    first = BusGeographicInfo(location_name="first")

    class RejectingGeographicInfo(SupplementalAttribute):
        location_name: str = Field(default="")

        def check_supplemental_attribute_addition(self) -> None:
            target_system.remove_supplemental_attribute(first)
            raise failure

    result = attach_outputs(
        RuleOutputs(
            primary=primary,
            supplemental_attributes=(first, RejectingGeographicInfo(location_name="rejected")),
        ),
        source_system=source_system,
        target_system=target_system,
    )

    assert result.is_err()
    assert "Failed to roll back rule outputs" in str(result.err())
    assert isinstance(result.err().__cause__, ExceptionGroup)
    failures = result.err().__cause__.exceptions
    assert failure in failures
    assert any(isinstance(error, ISNotStored) for error in failures)
    assert not target_system.has_component(primary)
    with pytest.raises(ISNotStored):
        target_system.get_supplemental_attribute_by_uuid(first.uuid)


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
    duplicate = BusComponent(name="duplicate", uuid=existing.uuid)

    result = attach_outputs(
        RuleOutputs(primary=duplicate), source_system=source_system, target_system=target_system
    )

    assert result.is_err()
    assert target_system.get_component_by_uuid(existing.uuid) is existing
    assert list(target_system.get_components(BusComponent)) == [existing]


@pytest.mark.parametrize(
    ("exception_type", "expected_error"),
    [(ValueError, True), (TypeError, False), (RuntimeError, False)],
    ids=["expected-value-error", "unexpected-type-error", "unexpected-runtime-error"],
)
def test_attach_rule_outputs_rolls_back_after_supplemental_failure(
    source_system, exception_type, expected_error
):
    """Rollback preserves existing state for expected and unexpected failures."""
    failure = exception_type("supplemental attachment rejected")

    class RejectingGeographicInfo(SupplementalAttribute):
        location_name: str = Field(default="", description="Location name")

        def check_supplemental_attribute_addition(self) -> None:
            raise failure

    target_system = System(name="executor-target", auto_add_composed_components=True)
    shared = ComposedComponent(name="existing-child", detail="preserve child")
    existing_parent = ComposedComponent(name="existing-parent", children=[shared], detail="preserve parent")
    target_system.add_component(existing_parent)
    existing_attribute = BusGeographicInfo(location_name="preserve attribute")
    target_system.add_supplemental_attribute(shared, existing_attribute)
    unrelated = ComposedComponent(name="unrelated", detail="preserve unrelated")
    target_system.add_component(unrelated)
    leaf = ComposedComponent(name="new-leaf", detail="owned leaf")
    branch = ComposedComponent(name="new-branch", children=[leaf], detail="owned branch")
    primary = ComposedComponent(name="translated", children=[shared, branch], detail="owned primary")
    first = BusGeographicInfo(location_name="first")
    outputs = RuleOutputs(
        primary=primary,
        supplemental_attributes=(first, RejectingGeographicInfo(location_name="rejected")),
    )

    if expected_error:
        result = attach_outputs(outputs, source_system=source_system, target_system=target_system)
        assert result.is_err()
        assert "supplemental attachment rejected" in str(result.err())
        assert root_cause(result.err()) is failure
    else:
        with pytest.raises(exception_type, match="supplemental attachment rejected") as raised:
            attach_outputs(outputs, source_system=source_system, target_system=target_system)
        assert raised.value is failure

    assert not target_system.has_component(primary)
    assert not target_system.has_component(branch)
    assert not target_system.has_component(leaf)
    assert target_system.get_component_by_uuid(shared.uuid) is shared
    assert shared.detail == "preserve child"
    assert target_system.get_component_by_uuid(existing_parent.uuid) is existing_parent
    assert target_system.list_child_components(existing_parent) == [shared]
    assert target_system.get_component_by_uuid(unrelated.uuid) is unrelated
    assert unrelated.detail == "preserve unrelated"
    assert target_system.get_supplemental_attribute_by_uuid(existing_attribute.uuid) is existing_attribute
    assert target_system.has_supplemental_attribute_association(shared, existing_attribute)
    with pytest.raises(ISNotStored):
        target_system.get_supplemental_attribute_by_uuid(first.uuid)


def test_apply_single_rule_retains_auto_added_composed_graph(source_system):
    """Rule execution keeps newly auto-added children and their field references."""
    target_system = System(name="executor-target", auto_add_composed_components=True)
    rule = Rule(
        source_type="BusComponent",
        target_type="ComposedRuleTarget",
        version=1,
        field_map={"name": "name"},
    )
    context = build_context(
        rules=[rule],
        source_system=source_system,
        target_system=target_system,
        model_modules=(*FIXTURE_MODEL_MODULES, __name__),
    )

    result = apply_single_rule(rule, context=context)

    assert result.is_ok()
    primary = next(target_system.get_components(ComposedRuleTarget))
    child = primary.child
    grandchild = child.children[0]
    assert target_system.get_component_by_uuid(primary.uuid) is primary
    assert target_system.get_component_by_uuid(child.uuid) is child
    assert target_system.get_component_by_uuid(grandchild.uuid) is grandchild
    assert primary.child is child
    assert child.children == [grandchild]
    assert target_system.list_child_components(primary) == [child]


def test_attach_rule_outputs_cleans_children_after_primary_check_failure(source_system):
    """Children added before a primary callback failure are rolled back too."""
    failure = TypeError("primary component check failed")

    class RejectingPrimary(ComposedComponent):
        def check_component_addition(self) -> None:
            raise failure

    target_system = System(name="executor-target", auto_add_composed_components=True)
    leaf = ComposedComponent(name="leaf")
    child = ComposedComponent(name="child", children=[leaf])
    primary = RejectingPrimary(name="rejecting-primary", children=[child])

    with pytest.raises(TypeError) as raised:
        attach_outputs(RuleOutputs(primary=primary), source_system=source_system, target_system=target_system)

    assert raised.value is failure
    assert not target_system.has_component(primary)
    assert not target_system.has_component(child)
    assert not target_system.has_component(leaf)
    assert list(target_system.iter_all_components()) == []


def test_attach_rule_outputs_cleans_shared_diamond_graph(source_system):
    """A shared descendant is removed once after all newly attached parents."""
    failure = ValueError("reject after auto-add")

    class RejectingGeographicInfo(SupplementalAttribute):
        location_name: str = Field(default="")

        def check_supplemental_attribute_addition(self) -> None:
            raise failure

    target_system = System(name="executor-target", auto_add_composed_components=True)
    shared = ComposedComponent(name="shared-leaf")
    left = ComposedComponent(name="left", children=[shared])
    right = ComposedComponent(name="right", children=[shared])
    primary = ComposedComponent(name="diamond", children=[left, right])
    first = BusGeographicInfo(location_name="first")

    result = attach_outputs(
        RuleOutputs(
            primary=primary,
            supplemental_attributes=(first, RejectingGeographicInfo(location_name="rejected")),
        ),
        source_system=source_system,
        target_system=target_system,
    )

    assert result.is_err()
    assert "Failed to roll back" not in str(result.err())
    assert root_cause(result.err()) is failure
    for component in (primary, left, right, shared):
        assert not target_system.has_component(component)
    with pytest.raises(ISNotStored):
        target_system.get_supplemental_attribute_by_uuid(first.uuid)
    assert list(target_system.iter_all_components()) == []


def test_attach_rule_outputs_with_composed_child_requires_auto_add(source_system):
    """With auto-add disabled, a rejected graph does not mutate the target."""
    target_system = System(name="executor-target", auto_add_composed_components=False)
    existing = ComposedComponent(name="existing")
    target_system.add_component(existing)
    child = ComposedComponent(name="unattached-child")
    primary = ComposedComponent(name="parent", children=[child])

    result = attach_outputs(
        RuleOutputs(primary=primary), source_system=source_system, target_system=target_system
    )

    assert result.is_err()
    assert isinstance(root_cause(result.err()), ISOperationNotAllowed)
    assert list(target_system.iter_all_components()) == [existing]
    assert target_system.get_component_by_uuid(existing.uuid) is existing
    assert not target_system.has_component(primary)
    assert not target_system.has_component(child)


def test_attach_rule_outputs_removes_new_child_of_preexisting_component(source_system):
    """A pre-existing graph node does not silently retain its newly added child."""
    target_system = System(name="executor-target", auto_add_composed_components=True)
    existing = ComposedComponent(name="existing")
    target_system.add_component(existing)
    leaf = ComposedComponent(name="new-leaf")
    existing.children.append(leaf)
    primary = ComposedComponent(name="translated", children=[existing])
    failure = ValueError("supplemental rejected")

    class RejectingGeographicInfo(SupplementalAttribute):
        location_name: str = Field(default="")

        def check_supplemental_attribute_addition(self) -> None:
            raise failure

    first = BusGeographicInfo(location_name="first")
    result = attach_outputs(
        RuleOutputs(
            primary=primary,
            supplemental_attributes=(first, RejectingGeographicInfo(location_name="rejected")),
        ),
        source_system=source_system,
        target_system=target_system,
    )

    assert result.is_err()
    assert root_cause(result.err()) is failure
    assert target_system.get_component_by_uuid(existing.uuid) is existing
    assert existing.children == [leaf]
    assert not target_system.has_component(leaf)
    assert not target_system.has_component(primary)
    with pytest.raises(ISNotStored):
        target_system.get_supplemental_attribute_by_uuid(first.uuid)


def test_attach_rule_outputs_rejects_stored_uuid_object_collision(source_system):
    """A composed reference cannot alias a different object already in the System."""
    target_system = System(name="executor-target", auto_add_composed_components=True)
    existing = ComposedComponent(name="existing")
    target_system.add_component(existing)
    leaf = ComposedComponent(name="new-leaf")
    duplicate = ComposedComponent(name="duplicate", uuid=existing.uuid, children=[leaf])
    primary = ComposedComponent(name="translated", children=[duplicate])
    first = BusGeographicInfo(location_name="first")
    failure = ValueError("supplemental callback should not run")

    class RejectingGeographicInfo(SupplementalAttribute):
        location_name: str = Field(default="")

        def check_supplemental_attribute_addition(self) -> None:
            raise failure

    result = attach_outputs(
        RuleOutputs(
            primary=primary,
            supplemental_attributes=(first, RejectingGeographicInfo(location_name="rejected")),
        ),
        source_system=source_system,
        target_system=target_system,
    )

    assert result.is_err()
    assert "different object already stored" in str(result.err())
    assert isinstance(root_cause(result.err()), ValueError)
    assert target_system.get_component_by_uuid(existing.uuid) is existing
    assert existing.children == []
    assert not target_system.has_component(primary)
    assert not target_system.has_component(leaf)
    with pytest.raises(ISNotStored):
        target_system.get_supplemental_attribute_by_uuid(first.uuid)


def test_attach_rule_outputs_rejects_duplicate_uuid_objects_in_graph(source_system):
    """Distinct proposed components with one UUID are rejected before attachment."""
    target_system = System(name="executor-target", auto_add_composed_components=True)
    first = ComposedComponent(name="first")
    second = ComposedComponent(name="second", uuid=first.uuid)
    primary = ComposedComponent(name="translated", children=[first, second])

    result = attach_outputs(
        RuleOutputs(primary=primary), source_system=source_system, target_system=target_system
    )

    assert result.is_err()
    assert "distinct objects with UUID" in str(result.err())
    assert not target_system.has_component(primary)
    assert not target_system.has_component(first)
    assert not target_system.has_component(second)
    assert list(target_system.iter_all_components()) == []


def test_attach_rule_outputs_rejects_cyclic_composed_graph_before_mutation(source_system):
    """Cyclic component fields fail before infrasys begins recursive auto-add."""
    from graphlib import CycleError

    target_system = System(name="executor-target", auto_add_composed_components=True)
    primary = ComposedComponent(name="cycle")
    primary.children.append(primary)

    result = attach_outputs(
        RuleOutputs(primary=primary), source_system=source_system, target_system=target_system
    )

    assert result.is_err()
    assert isinstance(root_cause(result.err()), CycleError)
    assert not target_system.has_component(primary)
    assert list(target_system.iter_all_components()) == []


def test_attach_rule_outputs_rejects_malformed_composed_list_before_mutation(source_system):
    """A mixed component list is rejected before partially adding its members."""
    target_system = System(name="executor-target", auto_add_composed_components=True)
    child = ComposedComponent(name="child")
    primary = ComposedComponent.model_construct(name="malformed", children=[child, "not a component"])

    result = attach_outputs(
        RuleOutputs(primary=primary), source_system=source_system, target_system=target_system
    )

    assert result.is_err()
    assert "children" in str(result.err())
    assert not target_system.has_component(primary)
    assert not target_system.has_component(child)
    assert list(target_system.iter_all_components()) == []


@pytest.mark.parametrize("exception_type", [ValueError, TypeError, RuntimeError])
def test_attach_rule_outputs_preserves_attachment_and_rollback_failures(source_system, exception_type):
    rejection = exception_type("supplemental attachment rejected")
    target_system = System(name="executor-target", auto_add_composed_components=True)
    grandchild = ComposedComponent(name="grandchild")
    child = ComposedComponent(name="child", children=[grandchild])
    existing = ComposedComponent(name="existing")
    target_system.add_component(existing)
    leaf = ComposedComponent(name="new-leaf")
    existing.children.append(leaf)
    primary = ComposedComponent(name="translated", children=[child, existing])
    first = BusGeographicInfo(location_name="first")

    class ComponentHolder(Component):
        referenced_component: ComposedComponent

    holder = ComponentHolder(name="holder", referenced_component=primary)

    class RejectingGeographicInfo(SupplementalAttribute):
        location_name: str = Field(default="")

        def check_supplemental_attribute_addition(self) -> None:
            target_system.add_component(holder)
            raise rejection

    outputs = RuleOutputs(
        primary=primary,
        supplemental_attributes=(first, RejectingGeographicInfo(location_name="rejected")),
    )
    assert not target_system.has_component(leaf)
    if exception_type is ValueError:
        result = attach_outputs(outputs, source_system=source_system, target_system=target_system)
        assert result.is_err()
        assert "Failed to roll back rule outputs" in str(result.err())
        causes = result.err().__cause__
    else:
        with pytest.raises(ExceptionGroup) as raised:
            attach_outputs(outputs, source_system=source_system, target_system=target_system)
        causes = raised.value

    assert isinstance(causes, ExceptionGroup)
    attachment_error, *rollback_errors = causes.exceptions
    assert attachment_error is rejection
    assert rollback_errors
    assert all(isinstance(error, ISOperationNotAllowed) for error in rollback_errors)
    assert target_system.get_component_by_uuid(primary.uuid) is primary
    assert target_system.get_component_by_uuid(child.uuid) is child
    assert target_system.get_component_by_uuid(grandchild.uuid) is grandchild
    assert target_system.get_component_by_uuid(existing.uuid) is existing
    assert target_system.get_component_by_uuid(leaf.uuid) is leaf
    assert target_system.get_component_by_uuid(holder.uuid) is holder
    assert primary.children == [child, existing]
    assert child.children == [grandchild]
    assert existing.children == [leaf]
    with pytest.raises(ISNotStored):
        target_system.get_supplemental_attribute_by_uuid(first.uuid)


def test_rollback_preserves_replacement_component_and_reports_identity_conflict(source_system):
    """A replacement UUID collision is visible without deleting the replacement."""
    target_system = System(name="executor-target", auto_add_composed_components=True)
    leaf = ComposedComponent(name="implicit-leaf")
    branch = ComposedComponent(name="branch", children=[leaf])
    primary = ComposedComponent(name="primary", children=[branch])
    replacement = ComposedComponent(name="replacement", uuid=leaf.uuid)
    first = BusGeographicInfo(location_name="first")
    rejection = ValueError("supplemental rejection")

    class RejectingGeographicInfo(SupplementalAttribute):
        location_name: str = Field(default="")

        def check_supplemental_attribute_addition(self) -> None:
            target_system.remove_component(leaf, cascade_down=False)
            target_system.add_component(replacement)
            raise rejection

    result = attach_outputs(
        RuleOutputs(
            primary=primary,
            supplemental_attributes=(first, RejectingGeographicInfo(location_name="rejected")),
        ),
        source_system=source_system,
        target_system=target_system,
    )

    assert result.is_err()
    causes = result.err().__cause__
    assert isinstance(causes, ExceptionGroup)
    attachment_error, ownership_error = causes.exceptions
    assert attachment_error is rejection
    assert isinstance(ownership_error, ISAlreadyAttached)
    assert "different object during rollback" in str(ownership_error)
    assert not target_system.has_component(primary)
    assert not target_system.has_component(branch)
    assert target_system.get_component_by_uuid(leaf.uuid) is replacement
    assert list(target_system.iter_all_components()) == [replacement]
    with pytest.raises(ISNotStored):
        target_system.get_supplemental_attribute_by_uuid(first.uuid)


def test_attach_rule_outputs_reraises_component_check_type_error(source_system):
    target_system = System(name="executor-target")
    primary = TypeErrorBusComponent(name="rejected")

    with pytest.raises(TypeError) as raised:
        attach_outputs(RuleOutputs(primary=primary), source_system=source_system, target_system=target_system)

    assert raised.value is TypeErrorBusComponent.failure
    assert list(target_system.iter_all_components()) == []


@pytest.mark.parametrize(
    ("target_type", "supplemental_attributes"),
    [
        ("TypeErrorValidatingComponent", []),
        (
            "NodeComponent",
            [
                SupplementalAttributeRule(
                    target_type="TypeErrorValidatingSupplemental",
                    field_map={"location_name": "zone"},
                    optional=False,
                )
            ],
        ),
    ],
    ids=["primary", "supplemental"],
)
def test_apply_single_rule_exposes_validator_type_errors(source_system, target_type, supplemental_attributes):
    """Pydantic validator programming errors are not converted into rule Err values."""
    target_system = System(name="executor-target")
    rule = Rule(
        source_type="BusComponent",
        target_type=target_type,
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        supplemental_attributes=supplemental_attributes,
    )
    with pytest.raises(TypeError, match="validator implementation defect") as raised:
        apply_rule(
            rule,
            source_system=source_system,
            target_system=target_system,
            model_modules=(*FIXTURE_MODEL_MODULES, __name__),
        )

    assert raised.value is VALIDATOR_FAILURE
    assert list(target_system.iter_all_components()) == []


def test_supplemental_owner_programming_error_is_not_missing_owner(source_system):
    """Only ISNotStored is translated to a missing supplemental owner error."""
    with pytest.raises(AttributeError, match="uuid"):
        attach_outputs(
            RuleOutputs(primary=BusGeographicInfo(location_name="orphan")),
            source_system=source_system,
            target_system=System(name="executor-target"),
            source_component=cast(Component, object()),
        )


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
    bus = next(source_system.get_components(BusComponent))
    attribute = BusGeographicInfo(
        uuid=bus.uuid,
        latitude=12.3,
        longitude=45.6,
        location_name="nowhere",
    )

    result = attach_outputs(
        RuleOutputs(primary=attribute),
        source_system=source_system,
        target_system=target_system,
        source_component=bus,
    )

    assert result.is_err()
    assert "Cannot attach supplemental attribute" in str(result.err())
    assert isinstance(root_cause(result.err()), ISNotStored)


def test_apply_single_rule_rejects_plain_getter_result_in_system_translation(source_system):
    """A plain getter value cannot silently install the target model default."""
    from fixtures.target_system import StationComponent

    def invalid_getter(source: object, *, context: PluginContext) -> int:
        _ = source, context
        return 42

    target_system = System(name="executor-target")
    rule = Rule(
        source_type="PlantComponent",
        target_type="StationComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        getters={"max_output_mw": invalid_getter},
    )
    with pytest.raises(TypeError, match="Getter for 'max_output_mw' must return Ok or Err"):
        apply_rule(rule, source_system=source_system, target_system=target_system)

    assert list(target_system.get_components(StationComponent)) == []
