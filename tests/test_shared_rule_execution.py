"""Public behavior tests for Rule execution across component and dataset sources."""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.source_system import BusComponent, BusGeographicInfo
from fixtures.target_system import NodeComponent, StationComponent
from infrasys import Component, SupplementalAttribute
from infrasys.exceptions import ISAlreadyAttached
from pydantic import Field, ValidationError
from rust_ok import Err, Ok, Result

from r2x_core import (
    ComponentSource,
    ComponentTarget,
    DataFile,
    DatasetSource,
    DataStore,
    FixedMappingRoute,
    MappingSelection,
    OwnedSupplementalTarget,
    PluginConfig,
    PluginContext,
    Rule,
    RuleFilter,
    RuleMapping,
    RulePlan,
    RulePlanDocument,
    SelectedMappingRoute,
    SupplementalAttributeRule,
    System,
    apply_mapping_records,
    apply_rules_to_context,
    apply_single_rule,
    build_rule_outputs,
)
from r2x_core.provenance import SourceProvenance


class ReviewDependentTarget(Component):
    """Component whose composed reference must already be stored."""

    node: NodeComponent = Field(default_factory=lambda: NodeComponent(name="unregistered"))


class RejectingSupplementalAttribute(SupplementalAttribute):
    """Real infrasys attribute model that rejects attachment through its validation hook."""

    reason: str

    def check_supplemental_attribute_addition(self) -> None:
        """Reject attachment through the public SupplementalAttribute validation hook."""
        raise ISAlreadyAttached(self.reason)


def test_component_source_maps_and_attaches_primary_with_nested_attribute() -> None:
    source = System(name="source")
    bus = BusComponent(name="bus", voltage_kv=230.0, load_mw=150.0, zone="north")
    source.add_component(bus)
    target = System(name="target")
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name", "uuid": "uuid", "kv_rating": "voltage_kv"},
        supplemental_attributes=(
            SupplementalAttributeRule(
                target_type="BusGeographicInfo",
                field_map={"location_name": "zone", "latitude": "voltage_kv"},
            ),
        ),
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.successful_rules == 1
    node = next(target.get_components(NodeComponent))
    assert node.name == "bus"
    assert node.uuid == bus.uuid
    attribute = target.get_supplemental_attributes_with_component(node)[0]
    assert isinstance(attribute, BusGeographicInfo)
    assert (attribute.location_name, attribute.latitude) == ("north", 230.0)


def test_component_source_with_context_getter_filter_maps_selected_record() -> None:
    """A getter filter receives the live PluginContext and selects public inputs."""
    from rust_ok import Ok

    source = System(name="source")
    source.add_components(
        BusComponent(name="selected", zone="north"),
        BusComponent(name="excluded", zone="south"),
    )
    target = System(name="target")

    def select_by_context(record: BusComponent, *, context: PluginContext) -> Result[str, ValueError]:
        return Ok("selected" if record.name == context.metadata["selected_name"] else "excluded")

    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        filter=RuleFilter(getter=select_by_context, op="eq", values=["selected"]),
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
        metadata={"selected_name": "selected"},
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.total_converted == 1
    assert [node.name for node in target.get_components(NodeComponent)] == ["selected"]


def test_getter_filter_failure_is_reported_with_source_row() -> None:
    """Getter-filter failures become attributable rule issues."""
    from rust_ok import Err

    source = System(name="source")
    source.add_component(BusComponent(name="bus"))
    target = System(name="target")

    def reject_record(record: BusComponent, *, context: PluginContext) -> Result[str, ValueError]:
        return Err(ValueError(f"filter unavailable for {record.name} in {context.config}"))

    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name"},
        filter=RuleFilter(getter=reject_record, op="eq", values=["keep"]),
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.failed_rules == 1
    assert result.rule_results[0].issues[0].row == 1
    assert "filter unavailable" in result.rule_results[0].error
    assert list(target.get_components(NodeComponent)) == []


def test_component_source_missing_mapped_field_is_reported_without_attachment() -> None:
    """Missing source values are reported through the shared construction path."""
    source = System(name="source")
    source.add_component(BusComponent(name="bus"))
    target = System(name="target")
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "missing_source_field"},
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.failed_rules == 1
    assert result.rule_results[0].issues[0].row == 1
    assert "missing_source_field" in result.rule_results[0].error
    assert list(target.get_components(NodeComponent)) == []


def test_missing_target_model_fails_before_any_attachment() -> None:
    """Unresolvable output models are invocation configuration errors."""
    source = System(name="source")
    source.add_component(BusComponent(name="bus"))
    target = System(name="target")
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("MissingTarget",)),
        version=1,
        field_map={"name": "name"},
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    with pytest.raises(ValueError, match="MissingTarget"):
        apply_rules_to_context(context, on_error="stop")

    assert list(target.get_components(NodeComponent)) == []


def test_empty_component_source_is_a_successful_zero_output_rule() -> None:
    """An empty real source System is a successful batch with zero conversions."""
    source = System(name="source")
    target = System(name="target")
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name"},
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.success
    assert result.total_converted == 0
    assert list(target.get_components(NodeComponent)) == []


def test_duplicate_names_and_missing_dependencies_fail_before_attachment() -> None:
    """Rule ordering errors are rejected before any Rule mutates the target."""
    source = System(name="source")
    source.add_component(BusComponent(name="bus"))
    target = System(name="target")
    common = {
        "source": ComponentSource(component_type="BusComponent"),
        "target": ComponentTarget(component_types=("NodeComponent",)),
        "version": 1,
        "field_map": {"name": "name"},
    }
    duplicate_rules = (
        Rule(**common, name="duplicate"),
        Rule(**common, name="duplicate"),
    )
    missing_dependency = Rule(**common, name="dependent", depends_on=("missing",))
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=duplicate_rules,
    )

    with pytest.raises(ValueError, match="Duplicate rule name"):
        apply_rules_to_context(context, on_error="stop")
    with pytest.raises(ValueError, match="unknown rule"):
        apply_rules_to_context(context.evolve(rules=(missing_dependency,)), on_error="stop")

    assert list(target.get_components(NodeComponent)) == []


def test_primary_is_removed_when_real_system_rejects_nested_attribute() -> None:
    """A real System supplemental-validation failure rolls back the new primary."""
    source = System(name="source")
    source.add_component(BusComponent(name="bus"))
    target = System(name="target")
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        supplemental_attributes=(
            SupplementalAttributeRule(
                target_type="RejectingSupplementalAttribute",
                defaults={"reason": "supplemental association rejected"},
                optional=False,
            ),
        ),
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system", __name__)),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.failed_rules == 1
    assert "supplemental association rejected" in result.rule_results[0].error
    assert list(target.get_components(NodeComponent)) == []
    assert list(target.get_supplemental_attributes(RejectingSupplementalAttribute)) == []


def test_csv_source_constructs_component_in_explicit_target_system(tmp_path: Path) -> None:
    source_path = tmp_path / "nodes.csv"
    source_path.write_text("name,area\nnode-a,north\n", encoding="utf-8")
    store = DataStore.from_data_files(
        [DataFile(name="nodes", fpath=source_path)],
        path=tmp_path,
    )
    target = System(name="target")
    rule = Rule(
        source=DatasetSource(dataset="nodes"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name", "area": "area"},
        defaults={"kv_rating": 0.0, "demand_mw": 0.0},
        name="nodes",
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.target_system",)),
        system=target,
        target_system=target,
        store=store,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.successful_rules == 1
    node = next(target.get_components(NodeComponent))
    assert (node.name, node.area, node.kv_rating, node.demand_mw) == ("node-a", "north", 0.0, 0.0)


def test_csv_source_constructs_and_attaches_owned_supplemental_attribute(tmp_path: Path) -> None:
    source_path = tmp_path / "emissions.csv"
    source_path.write_text("owner,rate,emission_type\nnode-a,0.25,CO2\n", encoding="utf-8")
    store = DataStore.from_data_files(
        [DataFile(name="emissions", fpath=source_path)],
        path=tmp_path,
    )
    target = System(name="target")
    owner = NodeComponent(name="node-a", area="north")
    target.add_component(owner)
    rule = Rule(
        source=DatasetSource(dataset="emissions"),
        target=OwnedSupplementalTarget(
            attribute_type="ReviewEmissionAttribute",
            owner_type="NodeComponent",
            owner_field="owner",
        ),
        version=1,
        field_map={"rate": "rate", "emission_type": "emission_type"},
        name="emissions",
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        system=target,
        target_system=target,
        store=store,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.successful_rules == 1
    attribute = target.get_supplemental_attributes_with_component(owner)[0]
    assert (attribute.rate, attribute.emission_type) == (0.25, "CO2")


def test_missing_owner_skip_does_not_validate_unselected_attribute_payload(tmp_path: Path) -> None:
    """Rows without an owner are skipped before validating attribute-only values."""
    source_path = tmp_path / "emissions.csv"
    source_path.write_text(
        "owner,rate,emission_type\nabsent,invalid,CO2\nnode-a,0.25,CO2\n",
        encoding="utf-8",
    )
    store = DataStore.from_data_files([DataFile(name="emissions", fpath=source_path)], path=tmp_path)
    target = System(name="target")
    owner = NodeComponent(name="node-a")
    target.add_component(owner)
    rule = Rule(
        source=DatasetSource(dataset="emissions"),
        target=OwnedSupplementalTarget(
            attribute_type="ReviewEmissionAttribute",
            owner_type="NodeComponent",
            owner_field="owner",
            missing_owner="skip",
        ),
        version=1,
        field_map={"rate": "rate", "emission_type": "emission_type"},
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        system=target,
        target_system=target,
        store=store,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.success
    assert result.total_converted == 1
    assert result.rule_results[0].skipped == 1
    attribute = target.get_supplemental_attributes_with_component(owner)[0]
    assert attribute.rate == 0.25


@pytest.mark.parametrize(
    ("source", "target", "message"),
    [
        (
            {"kind": "component", "component_type": "BusComponent", "system": "srouce"},
            {"kind": "component", "component_types": ["NodeComponent"]},
            "system",
        ),
        (
            {"kind": "component", "component_type": "BusComponent", "sytem": "target"},
            {"kind": "component", "component_types": ["NodeComponent"]},
            "sytem",
        ),
        (
            {"kind": "dataset", "dataset": "nodes"},
            {"kind": "component", "component_types": ["NodeComponent"], "duplicate_policy": "last"},
            "duplicate_policy",
        ),
        (
            {"kind": "dataset", "dataset": "emissions"},
            {
                "kind": "owned_supplemental_attribute",
                "attribute_type": "ReviewEmissionAttribute",
                "owner_type": "NodeComponent",
                "owner_field": "owner",
                "missing_owner": "silence",
            },
            "missing_owner",
        ),
    ],
)
def test_rule_records_reject_unknown_or_invalid_source_and_target_values(
    source: dict[str, object], target: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Rule.from_records([{"source": source, "target": target, "version": 1}])


def test_component_source_can_attach_to_a_matching_owned_attribute() -> None:
    source = System(name="source")
    bus = BusComponent(name="bus", zone="north")
    source.add_component(bus)
    target = System(name="target")
    owner = NodeComponent(name="bus", uuid=bus.uuid, area="north")
    target.add_component(owner)
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=OwnedSupplementalTarget(
            attribute_type="BusGeographicInfo",
            owner_type="NodeComponent",
            owner_match={"uuid": "uuid"},
        ),
        version=1,
        field_map={"location_name": "zone"},
        defaults={"latitude": 0.0, "longitude": 0.0},
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.successful_rules == 1
    attribute = target.get_supplemental_attributes_with_component(owner)[0]
    assert isinstance(attribute, BusGeographicInfo)
    assert attribute.location_name == "north"


def test_rule_preflight_rejects_missing_component_source_before_dataset_mutation(tmp_path: Path) -> None:
    source_path = tmp_path / "nodes.csv"
    source_path.write_text("name,area\nnode-a,north\n", encoding="utf-8")
    store = DataStore.from_data_files(
        [DataFile(name="nodes", fpath=source_path)],
        path=tmp_path,
    )
    target = System(name="target")
    dataset_rule = Rule(
        source=DatasetSource(dataset="nodes"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name", "area": "area"},
        name="dataset",
    )
    component_rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name"},
        name="component",
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        target_system=target,
        store=store,
        rules=(dataset_rule, component_rule),
    )

    with pytest.raises(ValueError, match="source System"):
        apply_rules_to_context(context, on_error="stop")

    assert list(target.get_components(NodeComponent)) == []


def test_apply_single_rule_does_not_finalize_or_preserve_unrelated_source_components() -> None:
    source = System(name="source")
    converted = BusComponent(name="converted", zone="north")
    untouched = BusComponent(name="untouched", zone="south")
    source.add_components(converted, untouched)
    target = System(name="target")
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name", "uuid": "uuid", "area": "zone"},
        filter=RuleFilter(field="name", op="eq", values=["converted"]),
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
        preserve_source=True,
    )

    result = apply_single_rule(rule, context=context)

    assert result.is_ok()
    assert [component.name for component in target.get_components(NodeComponent)] == ["converted"]
    assert list(target.get_components(BusComponent)) == []
    assert target.source_provenance_info is None


def test_multi_target_attachment_failure_reports_prior_output_and_provenance() -> None:
    source = System(name="source")
    bus = BusComponent(name="source-node")
    source.add_component(bus)
    target = System(name="target", auto_add_composed_components=False)
    config = PluginConfig(models=("fixtures.source_system", "fixtures.target_system", __name__))
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent", "ReviewDependentTarget")),
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
    )
    context = PluginContext(
        config=config,
        source_system=source,
        target_system=target,
        rules=(rule,),
        preserve_source=True,
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.failed_rules == 1
    node = target.get_component(NodeComponent, "source-node")
    assert result.total_converted == 1
    assert result.rule_results[0].converted == 1
    provenance = target.get_supplemental_attributes_with_component(node, SourceProvenance)
    assert len(provenance) == 1
    assert provenance[0].source_uuid == bus.uuid
    assert list(target.get_components(BusComponent)) == []


def test_unknown_error_policy_is_rejected_before_mutation() -> None:
    source = System(name="source")
    source.add_component(BusComponent(name="bus"))
    target = System(name="target")
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name"},
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    with pytest.raises(ValueError, match="on_error"):
        apply_rules_to_context(context, on_error="stpo")

    assert list(target.get_components(NodeComponent)) == []


def test_invalid_owner_path_is_rejected_even_when_missing_owner_would_skip(tmp_path: Path) -> None:
    source_path = tmp_path / "emissions.csv"
    source_path.write_text("region\nnorth\n", encoding="utf-8")
    store = DataStore.from_data_files(
        [DataFile(name="emissions", fpath=source_path)],
        path=tmp_path,
    )
    target = System(name="target")
    target.add_component(NodeComponent(name="node", area="north"))
    rule = Rule(
        source=DatasetSource(dataset="emissions"),
        target=OwnedSupplementalTarget(
            attribute_type="BusGeographicInfo",
            owner_type="NodeComponent",
            owner_match={"region": "areaa"},
            missing_owner="skip",
        ),
        version=1,
        defaults={"location_name": "owned", "latitude": 0.0, "longitude": 0.0},
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        store=store,
        target_system=target,
        rules=(rule,),
    )

    with pytest.raises(ValueError, match=r"owner|field|path|areaa"):
        apply_rules_to_context(context, on_error="stop")

    assert target.get_supplemental_attributes_with_component(next(target.get_components(NodeComponent))) == []


def return_review_getter(source: BusComponent, *, context: PluginContext) -> Result[float, ValueError]:
    """Fail one named record to exercise visible partial translation counts."""
    if source.name == "bad":
        return Err(ValueError("review row failure"))
    return Ok(230.0)


def test_failed_rule_reports_outputs_that_remain_attached() -> None:
    source = System(name="source")
    source.add_components(BusComponent(name="good"), BusComponent(name="bad"))
    target = System(name="target")
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name"},
        getters={"kv_rating": return_review_getter},
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.failed_rules == 1
    assert [component.name for component in target.get_components(NodeComponent)] == ["good"]
    assert result.rule_results[0].converted == 1
    assert result.total_converted == 1
    assert result.rule_results[0].issues[0].row == 2


def test_rule_output_failure_does_not_remove_preexisting_supplemental_attribute() -> None:
    source = System(name="source")
    source.add_component(BusComponent(name="new-bus", zone="north"))
    target = System(name="target")
    existing = NodeComponent(name="existing")
    target.add_component(existing)
    existing_attribute = BusGeographicInfo(
        uuid=existing.uuid,
        latitude=1.0,
        longitude=2.0,
        location_name="existing",
    )
    target.add_supplemental_attribute(existing, existing_attribute)
    nested = SupplementalAttributeRule(
        target_type="BusGeographicInfo",
        defaults={
            "uuid": existing_attribute.uuid,
            "location_name": "new",
            "latitude": 3.0,
            "longitude": 4.0,
        },
    )
    rule = Rule(
        source=ComponentSource(component_type="BusComponent"),
        target=ComponentTarget(component_types=("NodeComponent",)),
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        supplemental_attributes=(nested, nested),
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        source_system=source,
        target_system=target,
        rules=(rule,),
    )

    result = apply_rules_to_context(context, on_error="stop")

    assert result.failed_rules == 1
    assert target.get_supplemental_attributes_with_component(existing) == [existing_attribute]
    assert [component.name for component in target.get_components(NodeComponent)] == ["existing"]


def test_owned_supplemental_target_requires_a_boolean_null_policy() -> None:
    with pytest.raises(ValidationError, match="nulls_equal"):
        OwnedSupplementalTarget(
            attribute_type="ReviewEmissionAttribute",
            owner_type="NodeComponent",
            owner_field="owner",
            nulls_equal="false",
        )


def test_detached_policy_records_use_the_rule_mapping_contract() -> None:
    context = PluginContext(config=PluginConfig(models=("fixtures.target_system",)))
    mapping = RuleMapping(
        name="computed-node",
        target=ComponentTarget(component_types=("NodeComponent",)),
        field_map={"name": "name", "area": "zone"},
        defaults={"kv_rating": 0.0, "demand_mw": 0.0},
    )

    outputs = build_rule_outputs(
        {"name": "computed-node", "zone": "south"},
        mapping=mapping,
        context=context,
    )

    assert outputs.is_ok()
    assert len(outputs.unwrap()) == 1
    primary = outputs.unwrap()[0].primary
    assert isinstance(primary, NodeComponent)
    assert (primary.name, primary.area, primary.kv_rating, primary.demand_mw) == (
        "computed-node",
        "south",
        0.0,
        0.0,
    )


def test_validated_rule_plan_runs_named_dataset_stage_and_resolves_detached_mapping(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "nodes.csv"
    source_path.write_text("name,area\nnode-a,north\n", encoding="utf-8")
    store = DataStore.from_data_files(
        [DataFile(name="nodes", fpath=source_path)],
        path=tmp_path,
    )
    target = System(name="target")
    context = PluginContext(
        config=PluginConfig(models=("fixtures.target_system",)),
        system=target,
        target_system=target,
        store=store,
    )
    plan_result = RulePlan.from_mapping(
        {
            "mappings": [
                {
                    "name": "computed_node",
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "field_map": {"name": "name", "area": "area"},
                }
            ],
            "rules": [
                {
                    "name": "file_nodes",
                    "source": {"kind": "dataset", "dataset": "nodes"},
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "field_map": {"name": "name", "area": "area"},
                }
            ],
            "execution": [{"name": "regions", "rules": ["file_nodes"]}],
            "required_stages": ["regions"],
            "required_rules": ["file_nodes", "computed_node"],
        },
        context=context,
    )

    assert plan_result.is_ok()
    plan = plan_result.unwrap()
    assert plan.get_mapping("computed_node").is_ok()
    result = apply_rules_to_context(context, plan=plan, stage="regions", on_error="stop")

    assert result.success
    assert [node.name for node in target.get_components(NodeComponent)] == ["node-a"]


def test_rule_reuses_named_mapping_for_stage_source(tmp_path: Path) -> None:
    source_path = tmp_path / "nodes.csv"
    source_path.write_text("name,area\nnode-a,north\n", encoding="utf-8")
    store = DataStore.from_data_files([DataFile(name="nodes", fpath=source_path)], path=tmp_path)
    target = System(name="target")
    context = PluginContext(
        config=PluginConfig(models=("fixtures.target_system",)),
        target_system=target,
        store=store,
    )
    result = RulePlan.from_mapping(
        {
            "mappings": [
                {
                    "name": "node_mapping",
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "field_map": {"name": "name", "area": "area"},
                }
            ],
            "rules": [
                {
                    "name": "nodes_rule",
                    "source": {"kind": "dataset", "dataset": "nodes"},
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "mapping_ref": "node_mapping",
                }
            ],
            "execution": [{"name": "components", "rules": ["nodes_rule"]}],
        },
        context=context,
    )

    assert result.is_ok()
    plan = result.unwrap()
    resolved_rule = plan.get_rule("nodes_rule").unwrap()
    assert Rule.model_validate(resolved_rule.rule.model_dump()) == resolved_rule.rule
    standalone = apply_single_rule(resolved_rule.rule, context=context)
    assert standalone.is_err()
    assert "resolve it through a RulePlan" in str(standalone.err())

    execution = apply_rules_to_context(
        context,
        plan=plan,
        stage="components",
        on_error="stop",
    )

    assert execution.success
    assert [(node.name, node.area) for node in target.get_components(NodeComponent)] == [("node-a", "north")]


def test_rule_plan_enforces_declared_required_datasets(tmp_path: Path) -> None:
    from r2x_core import FileInfo

    source_path = tmp_path / "optional.csv"
    source_path.write_text("name\nnode-a\n", encoding="utf-8")
    store = DataStore.from_data_files(
        [DataFile(name="optional", fpath=source_path, info=FileInfo(is_optional=True))],
        path=tmp_path,
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.target_system",)),
        store=store,
    )

    result = RulePlan.from_mapping({"required_datasets": ["optional"]}, context=context)

    assert result.is_err()
    assert "marked optional" in str(result.err())


def test_fixed_mapping_batch_uses_filter_and_reports_skips() -> None:
    target = System(name="target")
    context = PluginContext(
        config=PluginConfig(models=("fixtures.target_system",)),
        target_system=target,
    )
    plan_result = RulePlan.from_mapping(
        {
            "mappings": [
                {
                    "name": "load",
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "field_map": {"name": "name", "area": "area"},
                    "filter": {"field": "include", "op": "eq", "values": [True]},
                }
            ]
        },
        context=context,
    )
    assert plan_result.is_ok()

    result = apply_mapping_records(
        [
            {"name": "included", "area": "north", "include": True},
            {"name": "excluded", "area": "south", "include": False},
        ],
        plan=plan_result.unwrap(),
        route=FixedMappingRoute(name="load"),
        context=context,
    )

    assert result.is_ok()
    assert result.unwrap().converted == 1
    assert result.unwrap().skipped == 1
    assert [node.name for node in target.get_components(NodeComponent)] == ["included"]


def test_fixed_mapping_batch_prevalidates_all_rows_before_attachment() -> None:
    target = System(name="target")
    context = PluginContext(
        config=PluginConfig(models=("fixtures.target_system",)),
        target_system=target,
    )
    plan_result = RulePlan.from_mapping(
        {
            "mappings": [
                {
                    "name": "load",
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "field_map": {"name": "missing_name"},
                }
            ]
        },
        context=context,
    )
    assert plan_result.is_ok()

    result = apply_mapping_records(
        [{"row": 1}, {"row": 2}],
        plan=plan_result.unwrap(),
        route=FixedMappingRoute(name="load"),
        context=context,
    )

    assert result.is_err()
    assert result.err().converted == 0
    assert [issue.row for issue in result.err().issues] == [1, 2]
    assert list(target.get_components(NodeComponent)) == []


def test_selected_mapping_batch_uses_priority_and_first_name_duplicate_policy() -> None:
    target = System(name="target")
    context = PluginContext(
        config=PluginConfig(models=("fixtures.target_system",)),
        target_system=target,
    )
    plan_result = RulePlan.from_mapping(
        {
            "mappings": [
                {
                    "name": "solar_node",
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "field_map": {"name": "name", "area": "area"},
                },
                {
                    "name": "thermal_station",
                    "target": {"kind": "component", "component_types": ["StationComponent"]},
                    "field_map": {"name": "name", "resource": "area"},
                },
            ],
            "mapping_selections": [
                {
                    "name": "generators",
                    "key_field": "categories",
                    "priority": ["unmapped", "solar", "thermal"],
                    "by_key": {"solar": "solar_node", "thermal": "thermal_station"},
                    "duplicate_policy": "first",
                    "duplicate_identity": "name",
                }
            ],
        },
        context=context,
    )
    assert plan_result.is_ok()

    result = apply_mapping_records(
        [
            {"name": "shared", "area": "north", "categories": ["unmapped", "thermal", "solar"]},
            {"name": "shared", "area": "coal", "categories": ["thermal"]},
            {"name": "station", "area": "gas", "categories": ["thermal"]},
        ],
        plan=plan_result.unwrap(),
        route=SelectedMappingRoute(name="generators"),
        context=context,
    )

    assert result.is_ok()
    assert result.unwrap().converted == 2
    assert result.unwrap().skipped == 1
    assert [(node.name, node.area) for node in target.get_components(NodeComponent)] == [("shared", "north")]
    assert [(station.name, station.resource) for station in target.get_components(StationComponent)] == [
        ("station", "gas")
    ]


def test_selected_mapping_batch_reports_unmapped_category_without_partial_attachment() -> None:
    target = System(name="target")
    context = PluginContext(
        config=PluginConfig(models=("fixtures.target_system",)),
        target_system=target,
    )
    plan_result = RulePlan.from_mapping(
        {
            "mappings": [
                {
                    "name": "solar_node",
                    "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    "field_map": {"name": "name"},
                }
            ],
            "mapping_selections": [
                {
                    "name": "generators",
                    "key_field": "categories",
                    "priority": ["solar", "thermal"],
                    "by_key": {"solar": "solar_node"},
                }
            ],
        },
        context=context,
    )
    assert plan_result.is_ok()

    result = apply_mapping_records(
        [
            {"name": "mapped", "categories": ["solar"]},
            {"name": "unmapped", "categories": ["thermal"]},
        ],
        plan=plan_result.unwrap(),
        route=SelectedMappingRoute(name="generators"),
        context=context,
    )

    assert result.is_err()
    assert result.err().converted == 0
    assert result.err().issues[0].row == 2
    assert "No mapping selected" in result.err().issues[0].message
    assert list(target.get_components(NodeComponent)) == []


def test_mapping_selection_rejects_unknown_reference_and_invalid_schema() -> None:
    with pytest.raises(ValidationError, match="unknown mappings"):
        RulePlanDocument.model_validate(
            {
                "mappings": [
                    {
                        "name": "known",
                        "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    }
                ],
                "mapping_selections": [
                    {
                        "name": "choose",
                        "key_field": "categories",
                        "priority": ["solar"],
                        "by_key": {"solar": "missing"},
                    }
                ],
            }
        )

    with pytest.raises(ValidationError, match="priority"):
        MappingSelection(
            name="choose",
            key_field="categories",
            priority=("solar",),
            by_key={"wind": "known"},
        )


def test_detached_mapping_resolves_nested_attribute_getters() -> None:
    """Detached RuleMapping and executable Rule share nested getter preprocessing."""
    context = PluginContext(config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")))
    mapping = RuleMapping.from_records(
        [
            {
                "name": "computed_node",
                "target": {"kind": "component", "component_types": ["NodeComponent"]},
                "field_map": {"name": "name"},
                "supplemental_attributes": [
                    {
                        "target_type": "BusGeographicInfo",
                        "getters": {"location_name": "region"},
                        "optional": False,
                    }
                ],
            }
        ]
    )[0]

    outputs = build_rule_outputs(
        {"name": "node", "region": "north"},
        mapping=mapping,
        context=context,
    )

    assert outputs.is_ok()
    built = outputs.unwrap()[0]
    assert isinstance(built.supplemental_attributes[0], BusGeographicInfo)
    assert built.supplemental_attributes[0].location_name == "north"


@pytest.mark.parametrize(
    ("document", "required_stages", "message"),
    [
        (
            {
                "rules": [
                    {
                        "name": "one",
                        "source": {"kind": "dataset", "dataset": "nodes"},
                        "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    },
                    {
                        "name": "one",
                        "source": {"kind": "dataset", "dataset": "nodes"},
                        "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    },
                ]
            },
            (),
            "unique",
        ),
        (
            {
                "rules": [
                    {
                        "name": "one",
                        "source": {"kind": "dataset", "dataset": "nodes"},
                        "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    }
                ],
                "execution": [{"name": "regions", "rules": ["missing"]}],
            },
            (),
            "unknown executable Rules",
        ),
        ({"rules": [], "required_stages": ["regions"]}, ("regions",), "required"),
        (
            {
                "rules": [
                    {
                        "name": "one",
                        "source": {"kind": "dataset", "dataset": "missing"},
                        "target": {"kind": "component", "component_types": ["NodeComponent"]},
                    }
                ]
            },
            (),
            "not registered",
        ),
        (
            {
                "rules": [
                    {
                        "name": "one",
                        "source": {"kind": "dataset", "dataset": "nodes"},
                        "target": {"kind": "component", "component_types": ["NodeComponent"]},
                        "defaults": {"misspelled": 1},
                    }
                ]
            },
            (),
            "unknown target field",
        ),
    ],
)
def test_rule_plan_preflights_references_sources_and_target_fields(
    tmp_path: Path,
    document: dict[str, object],
    required_stages: tuple[str, ...],
    message: str,
) -> None:
    source_path = tmp_path / "nodes.csv"
    source_path.write_text("name,area\nnode-a,north\n", encoding="utf-8")
    store = DataStore.from_data_files(
        [DataFile(name="nodes", fpath=source_path)],
        path=tmp_path,
    )
    context = PluginContext(
        config=PluginConfig(models=("fixtures.target_system",)),
        store=store,
        target_system=System(name="target"),
    )

    if required_stages:
        document = {**document, "required_stages": list(required_stages)}
    result = RulePlan.from_mapping(document, context=context)

    assert result.is_err()
    assert message.casefold() in str(result.err()).casefold()
