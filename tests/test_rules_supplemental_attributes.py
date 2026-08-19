"""Tests for rules that produce supplemental attributes."""

from __future__ import annotations

from uuid import uuid4

from fixtures.source_system import BusComponent, BusGeographicInfo
from fixtures.target_system import NodeComponent

from r2x_core import PluginConfig, PluginContext
from r2x_core.rules import Rule
from r2x_core.rules_executor import apply_rules_to_context
from r2x_core.system import System


def _build_test_config() -> PluginConfig:
    """Create a PluginConfig pointing at fixture modules for component resolution."""
    return PluginConfig(models=("fixtures.source_system", "fixtures.target_system"))


def test_rule_creates_supplemental_attribute():
    """Test that a rule can create and attach a supplemental attribute to a component."""
    source_system = System(name="source", system_base=100.0)
    source_uuid = uuid4()
    bus_component = BusComponent(
        name="test_bus",
        uuid=source_uuid,
        voltage_kv=230.0,
        load_mw=150.0,
        zone="north",
    )
    source_system.add_component(bus_component)

    target_system = System(name="target", system_base=100.0)

    component_rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={
            "name": "name",
            "uuid": "uuid",
            "kv_rating": "voltage_kv",
            "demand_mw": "load_mw",
            "area": "zone",
        },
    )

    supplemental_rule = Rule(
        source_type="BusComponent",
        target_type="BusGeographicInfo",
        version=1,
        field_map={"location_name": "zone", "latitude": "voltage_kv", "longitude": "load_mw"},
    )

    context = PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=_build_test_config(),
        rules=(component_rule, supplemental_rule),
        store=None,
    )

    result = apply_rules_to_context(context)

    assert result.successful_rules == 2
    assert result.failed_rules == 0
    assert result.total_converted == 2

    target_nodes = list(target_system.get_components(NodeComponent))
    assert len(target_nodes) == 1
    target_node = target_nodes[0]
    assert target_node.kv_rating == 230.0
    assert target_node.demand_mw == 150.0
    assert target_node.area == "north"
    assert target_node.uuid == source_uuid

    supplemental_attrs = target_system.get_supplemental_attributes_with_component(target_node)
    assert len(supplemental_attrs) == 1
    supplemental_attr = supplemental_attrs[0]
    assert isinstance(supplemental_attr, BusGeographicInfo)
    assert supplemental_attr.location_name == "north"
    assert supplemental_attr.latitude == 230.0  # Mapped from voltage_kv
    assert supplemental_attr.longitude == 150.0  # Mapped from load_mw


def test_supplemental_attribute_without_target_component_fails():
    """Test that creating a supplemental attribute without a target component fails."""
    source_system = System(name="source", system_base=100.0)
    source_uuid = uuid4()
    bus_component = BusComponent(
        name="test_bus",
        uuid=source_uuid,
        voltage_kv=230.0,
        load_mw=150.0,
        zone="north",
    )
    source_system.add_component(bus_component)

    target_system = System(name="target", system_base=100.0)

    supplemental_rule = Rule(
        source_type="BusComponent",
        target_type="BusGeographicInfo",
        version=1,
        field_map={"location_name": "zone", "latitude": "voltage_kv", "longitude": "load_mw"},
    )

    context = PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=_build_test_config(),
        rules=(supplemental_rule,),
        store=None,
    )

    result = apply_rules_to_context(context)

    assert result.successful_rules == 0
    assert result.failed_rules == 1
    assert result.rule_results[0].error is not None
    assert "not found in target system" in result.rule_results[0].error


def test_multiple_supplemental_attributes_on_same_component():
    """Test that multiple supplemental attributes can be attached to the same component."""
    source_system = System(name="source", system_base=100.0)
    source_uuid = uuid4()
    bus_component = BusComponent(
        name="test_bus",
        uuid=source_uuid,
        voltage_kv=230.0,
        load_mw=150.0,
        zone="north",
    )
    source_system.add_component(bus_component)

    target_system = System(name="target", system_base=100.0)

    component_rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={
            "name": "name",
            "uuid": "uuid",
            "kv_rating": "voltage_kv",
            "demand_mw": "load_mw",
            "area": "zone",
        },
    )

    supplemental_rule1 = Rule(
        source_type="BusComponent",
        target_type="BusGeographicInfo",
        version=1,
        field_map={"location_name": "zone", "latitude": "voltage_kv"},
        defaults={"longitude": -122.4194},
    )

    supplemental_rule2 = Rule(
        source_type="BusComponent",
        target_type="BusGeographicInfo",
        version=2,  # Different version to avoid duplicate rule key
        field_map={"location_name": "zone", "latitude": "load_mw"},
        defaults={"longitude": -74.0060},  # Different location
    )

    context = PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=_build_test_config(),
        rules=(component_rule, supplemental_rule1, supplemental_rule2),
        store=None,
    )

    result = apply_rules_to_context(context)

    assert result.successful_rules == 3
    assert result.failed_rules == 0

    target_node = next(iter(target_system.get_components(NodeComponent)))
    supplemental_attrs = target_system.get_supplemental_attributes_with_component(target_node)
    assert len(supplemental_attrs) == 2
    assert all(isinstance(attr, BusGeographicInfo) for attr in supplemental_attrs)


def test_one_rule_creates_primary_and_multiple_supplemental_attributes():
    """A declarative rule creates and attaches all outputs from one source row."""
    source_system = System(name="source", system_base=100.0)
    source_component = BusComponent(
        name="test_bus",
        voltage_kv=230.0,
        load_mw=150.0,
        zone="north",
    )
    source_system.add_component(source_component)
    target_system = System(name="target", system_base=100.0)

    rule = Rule.from_records(
        [
            {
                "source_type": "BusComponent",
                "target_type": "NodeComponent",
                "version": 1,
                "field_map": {"name": "name", "uuid": "uuid", "kv_rating": "voltage_kv"},
                "supplemental_attributes": [
                    {
                        "target_type": "BusGeographicInfo",
                        "field_map": {
                            "location_name": "zone",
                            "latitude": "voltage_kv",
                        },
                        "defaults": {"longitude": -122.4194},
                    },
                    {
                        "target_type": "BusGeographicInfo",
                        "field_map": {
                            "location_name": "zone",
                            "longitude": "load_mw",
                        },
                        "defaults": {"latitude": 39.7392},
                    },
                ],
            }
        ]
    )[0]

    result = apply_rules_to_context(
        PluginContext(
            source_system=source_system,
            target_system=target_system,
            config=_build_test_config(),
            rules=(rule,),
        )
    )

    assert result.successful_rules == 1
    assert result.total_converted == 1
    target_node = next(iter(target_system.get_components(NodeComponent)))
    supplemental_attrs = target_system.get_supplemental_attributes_with_component(target_node)
    assert len(supplemental_attrs) == 2
    assert {attr.longitude for attr in supplemental_attrs} == {-122.4194, 150.0}
    assert {attr.latitude for attr in supplemental_attrs} == {230.0, 39.7392}


def test_rule_from_records_resolves_supplemental_getters():
    """Supplemental getter names are resolved when loading declarative records."""
    from rust_ok import Ok

    from r2x_core.getters import GETTER_REGISTRY, getter

    getter_name = "supplemental_rule_test_getter"
    if getter_name not in GETTER_REGISTRY:

        @getter(name=getter_name)
        def supplemental_rule_test_getter(_source, *, context):
            _ = context
            return Ok("north")

    rule = Rule.from_records(
        [
            {
                "source_type": "BusComponent",
                "target_type": "NodeComponent",
                "version": 1,
                "supplemental_attributes": [
                    {
                        "target_type": "BusGeographicInfo",
                        "getters": {"location_name": getter_name},
                    }
                ],
            }
        ]
    )[0]

    getter_func = rule.supplemental_attributes[0].getters["location_name"]
    assert callable(getter_func)
    assert getter_func(None, context=None).unwrap() == "north"


def test_empty_supplemental_output_is_not_attached():
    """Missing optional source fields do not create an empty supplemental attribute."""
    source_system = System(name="source", system_base=100.0)
    source_component = BusComponent(name="test_bus")
    source_system.add_component(source_component)
    target_system = System(name="target", system_base=100.0)
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        supplemental_attributes=[
            {
                "target_type": "BusGeographicInfo",
                "field_map": {"location_name": "missing_zone"},
            }
        ],
    )

    result = apply_rules_to_context(
        PluginContext(
            source_system=source_system,
            target_system=target_system,
            config=_build_test_config(),
            rules=(rule,),
        )
    )

    assert result.successful_rules == 1
    target_node = next(iter(target_system.get_components(NodeComponent)))
    assert target_system.get_supplemental_attributes_with_component(target_node) == []


def test_required_supplemental_output_reports_missing_value():
    """Required supplemental outputs fail instead of being silently omitted."""
    source_system = System(name="source", system_base=100.0)
    source_component = BusComponent(name="test_bus")
    source_system.add_component(source_component)
    target_system = System(name="target", system_base=100.0)
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        supplemental_attributes=[
            {
                "target_type": "BusGeographicInfo",
                "field_map": {"location_name": "missing_zone"},
                "optional": False,
            }
        ],
    )

    result = apply_rules_to_context(
        PluginContext(
            source_system=source_system,
            target_system=target_system,
            config=_build_test_config(),
            rules=(rule,),
        )
    )

    assert result.failed_rules == 1
    assert result.rule_results[0].error is not None
    assert "missing_zone" in result.rule_results[0].error


def test_invalid_supplemental_data_reports_rule_source_and_output():
    """Invalid supplemental values fail without attaching a partial primary output."""
    source_system = System(name="source", system_base=100.0)
    source_component = BusComponent(name="test_bus", zone="north")
    source_system.add_component(source_component)
    target_system = System(name="target", system_base=100.0)
    rule = Rule(
        name="bus_with_coordinates",
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        supplemental_attributes=[
            {
                "target_type": "BusGeographicInfo",
                "field_map": {"latitude": "zone"},
            }
        ],
    )

    result = apply_rules_to_context(
        PluginContext(
            source_system=source_system,
            target_system=target_system,
            config=_build_test_config(),
            rules=(rule,),
        )
    )

    assert result.failed_rules == 1
    error = result.rule_results[0].error
    assert error is not None
    assert "bus_with_coordinates" in error
    assert "test_bus" in error
    assert "BusGeographicInfo" in error
    assert list(target_system.get_components(NodeComponent)) == []


def test_missing_supplemental_target_type_reports_output():
    """Supplemental target types use configured modules and report resolution failures."""
    source_system = System(name="source", system_base=100.0)
    source_component = BusComponent(name="test_bus")
    source_system.add_component(source_component)
    target_system = System(name="target", system_base=100.0)
    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        supplemental_attributes=[
            {
                "target_type": "MissingSupplementalAttribute",
                "field_map": {"location_name": "zone"},
            }
        ],
    )

    result = apply_rules_to_context(
        PluginContext(
            source_system=source_system,
            target_system=target_system,
            config=_build_test_config(),
            rules=(rule,),
        )
    )

    assert result.failed_rules == 1
    error = result.rule_results[0].error
    assert error is not None
    assert "MissingSupplementalAttribute" in error
    assert "supplemental" in error
