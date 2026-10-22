"""Tests for tagged component filters and their executor integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fixtures.context import FIXTURE_MODEL_MODULES
from fixtures.target_system import StationComponent
from pydantic import TypeAdapter, ValidationError
from rust_ok import Ok

from r2x_core import (
    AllOfFilter,
    AnyOfFilter,
    FieldFilter,
    GetterFilter,
    PluginConfig,
    PluginContext,
    Rule,
    RuleFilter,
    System,
    apply_rules_to_context,
)

if TYPE_CHECKING:
    from r2x_core import RuleFilter as RuleFilterType


class Dummy:
    def __init__(self, **attrs: object) -> None:
        for key, value in attrs.items():
            setattr(self, key, value)


def run_rule_with_filter(filter_spec: RuleFilterType, source_system: System) -> tuple[int, System]:
    """Apply a filtered rule and return conversion count and target system."""
    config = PluginConfig(models=FIXTURE_MODEL_MODULES)
    rule = Rule(
        source_type="PlantComponent",
        target_type="StationComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        filter=filter_spec,
    )
    target_system = System(name="FilteredTarget", auto_add_composed_components=True)
    context = PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=config,
        rules=(rule,),
        store=None,
    )
    result = apply_rules_to_context(context)
    return result.total_converted, target_system


def test_field_filter_casefold_and_missing_values() -> None:
    filt = FieldFilter(field="kind", op="eq", values=["gas"])

    assert filt.matches(Dummy(kind="GAS"))
    assert not filt.matches(Dummy(kind="coal"))
    assert not FieldFilter(field="missing", op="eq", values=["gas"]).matches(Dummy())
    assert FieldFilter(field="missing", op="eq", values=["gas"], on_missing="include").matches(Dummy())


@pytest.mark.parametrize(
    ("op", "candidate", "values", "expected"),
    [
        ("eq", "alpha", ["alpha"], True),
        ("neq", "alpha", ["beta"], True),
        ("in", "alpha", ["alpha", "beta"], True),
        ("not_in", "alpha", ["beta"], True),
        ("geq", 500, [400], True),
        ("startswith", "plant_alpha", ["plant_"], True),
        ("not_startswith", "station_alpha", ["plant_"], True),
        ("endswith", "plant_alpha", ["alpha"], True),
        ("endswith", "plant_beta", ["alpha"], False),
    ],
)
def test_field_filter_operators(op: str, candidate: object, values: list[object], expected: bool) -> None:
    filt = FieldFilter(field="value", op=op, values=values)

    assert filt.matches(Dummy(value=candidate)) is expected


def test_composite_filters_compose_tagged_children() -> None:
    filt = AnyOfFilter(
        filters=[
            FieldFilter(field="kind", op="eq", values=["coal"]),
            FieldFilter(field="kind", op="eq", values=["gas"]),
        ]
    )
    all_filter = AllOfFilter(
        filters=[
            FieldFilter(field="kind", op="eq", values=["gas"]),
            FieldFilter(field="capacity", op="geq", values=[400]),
        ]
    )

    assert filt.matches(Dummy(kind="gas"))
    assert all_filter.matches(Dummy(kind="gas", capacity=500))
    assert not all_filter.matches(Dummy(kind="gas", capacity=300))


def test_rule_filter_round_trips_tagged_records() -> None:
    adapter = TypeAdapter(RuleFilter)
    filter_spec = adapter.validate_python(
        {
            "kind": "any_of",
            "filters": [
                {"kind": "field", "field": "kind", "op": "eq", "values": ["coal"]},
                {"kind": "field", "field": "status", "op": "eq", "values": ["active"]},
            ],
        }
    )

    assert adapter.validate_python(filter_spec.model_dump()) == filter_spec
    assert filter_spec.model_dump()["kind"] == "any_of"


def test_getter_filter_uses_registered_getters_and_context() -> None:
    from r2x_core.getters import GETTER_REGISTRY, getter

    getter_name = "rule_filter_selected_fuel"
    if getter_name not in GETTER_REGISTRY:

        @getter(name=getter_name)
        def selected_fuel(source: object, *, context: PluginContext):
            return Ok(context.metadata["selected_fuel"])

    filt = GetterFilter(getter=getter_name, op="eq", values=["GAS"])
    context = PluginContext(
        config=PluginConfig(models=FIXTURE_MODEL_MODULES),
        metadata={"selected_fuel": "gas"},
    )

    assert filt.matches(Dummy(), context=context)


def test_rule_executor_honors_field_filters(source_system: System) -> None:
    converted, target_system = run_rule_with_filter(
        FieldFilter(field="fuel_type", op="eq", values=["gas"]), source_system
    )

    stations = list(target_system.get_components(StationComponent))
    assert converted == 1
    assert stations and stations[0].name == "plant_alpha"


def test_rule_filter_models_reject_invalid_shapes() -> None:
    adapter = TypeAdapter(RuleFilter)

    with pytest.raises(ValidationError):
        adapter.validate_python({"field": "kind", "op": "eq", "values": ["gas"]})
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"kind": "field", "field": "kind", "getter": "selected_fuel_type", "op": "eq", "values": ["gas"]}
        )
    with pytest.raises(ValidationError):
        FieldFilter(field="kind", op="geq", values=[1, 2])
    with pytest.raises(ValidationError):
        FieldFilter(field="name", op="startswith", values=[123])
    with pytest.raises(ValidationError):
        GetterFilter(getter=123, op="eq", values=["gas"])
    with pytest.raises(ValidationError):
        AnyOfFilter(filters=[])


def test_getter_filter_rejects_plain_value_result() -> None:
    def invalid_getter(source: object, *, context: PluginContext) -> int:
        _ = source, context
        return 42

    filt = GetterFilter(getter=invalid_getter, op="eq", values=[42])
    context = PluginContext(config=PluginConfig(models=FIXTURE_MODEL_MODULES))

    with pytest.raises(TypeError, match="Filter getter must return Ok or Err, got int"):
        filt.matches(Dummy(), context=context)
