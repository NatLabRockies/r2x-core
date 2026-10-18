import pytest

from r2x_core import Rule


@pytest.fixture
def rules_simple() -> list[Rule]:
    """Translation rules between source and target fixture components."""

    rules = [
        {
            "source": {"kind": "component", "component_type": "BusComponent"},
            "target": {"kind": "component", "component_types": ["NodeComponent"]},
            "version": 1,
            "field_map": {
                "name": "name",
                "uuid": "uuid",
                "kv_rating": "voltage_kv",
                "demand_mw": "load_mw",
                "area": "zone",
            },
            "defaults": {"area": "unspecified"},
        },
        {
            "source": {"kind": "component", "component_type": "LineComponent"},
            "target": {"kind": "component", "component_types": ["CircuitComponent"]},
            "version": 1,
            "field_map": {
                "name": "name",
                "uuid": "uuid",
                "r_pu": "resistance_ohm",
                "x_pu": "reactance_ohm",
                "capacity_mw": "thermal_limit_mw",
            },
            "defaults": {"capacity_mw": 0.0},
        },
        {
            "source": {"kind": "component", "component_type": "PlantComponent"},
            "target": {"kind": "component", "component_types": ["StationComponent"]},
            "version": 1,
            "field_map": {
                "name": "name",
                "uuid": "uuid",
                "max_output_mw": "capacity_mw",
                "min_output_mw": "min_stable_level_mw",
                "resource": "fuel_type",
            },
            "defaults": {"resource": "unknown"},
        },
    ]
    return Rule.from_records(rules)
