"""Unit tests for helpers in r2x_core.rules_utils."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest
from fixtures.source_system import BusComponent
from fixtures.target_system import NodeComponent
from rust_ok import Err, Ok, Result

from r2x_core import Rule
from r2x_core.utils import (
    build_attr_getter,
    build_component_kwargs,
    build_target_fields,
    create_target_component,
    resolve_component_type,
)


def test_resolve_component_type_success(context_example):
    """Component types configured on the context can be resolved."""
    result = resolve_component_type("BusComponent", context=context_example)

    assert result.is_ok()
    assert result.unwrap() is BusComponent


def test_resolve_component_type_missing_returns_error(context_example):
    """Unknown component types return an error result."""
    result = resolve_component_type("NotAComponent", context=context_example)

    assert result.is_err()
    assert "NotAComponent" in str(result.err())


def test_make_attr_getter_traverses_chain():
    """Attr getter walks nested attributes and returns Ok result."""

    class Inner:
        value = 99

    class Outer:
        inner = Inner()

    getter = build_attr_getter(["inner", "value"])
    result = getter(Outer(), context=cast(Any, None))

    assert result.is_ok()
    assert result.unwrap() == 99


def test_build_target_fields_applies_defaults_and_getters(context_example):
    """Missing attributes fall back to defaults and getters override values."""

    class Source:
        name = "comp_a"
        demand = None

    def area_getter(_src: Any, *, context: Any) -> Result[str, ValueError]:
        _ = context
        return Ok("north")

    rule = Rule(
        source_type="SourceType",
        target_type="TargetType",
        version=1,
        field_map={"name": "name", "demand_mw": "demand"},
        getters={"area": area_getter},
        defaults={"demand_mw": 0.0},
    )

    result = build_target_fields(Source(), rule=rule, context=context_example)

    assert result.is_ok()
    fields = result.unwrap()
    assert fields["name"] == "comp_a"
    assert fields["demand_mw"] == 0.0
    assert fields["area"] == "north"


def test_build_target_fields_missing_attribute_without_default(context_example):
    """Missing attributes without defaults produce an error."""

    class Source:
        pass

    rule = Rule(
        source_type="SourceType",
        target_type="TargetType",
        version=1,
        field_map={"required": "missing_attr"},
    )

    result = build_target_fields(Source(), rule=rule, context=context_example)
    assert result.is_err()
    assert "missing_attr" in str(result.err())


def test_build_target_fields_getter_error_without_default(context_example):
    """Getter failures propagate when no default is defined."""

    class Source:
        value = "x"

    def faulty_getter(_src: Any, *, context: Any) -> Result[Any, ValueError]:
        _ = context
        return Err(ValueError("boom"))

    rule = Rule(
        source_type="SourceType",
        target_type="TargetType",
        version=1,
        field_map={"value": "value"},
        getters={"computed": faulty_getter},
    )

    result = build_target_fields(Source(), rule=rule, context=context_example)
    assert result.is_err()
    assert "failed" in str(result.err()).lower()


def test_build_target_fields_non_callable_getter_rejected(context_example):
    """Non-callable getter entries raise an error."""

    class Source:
        value = 1

    rule = Rule(
        source_type="SourceType",
        target_type="TargetType",
        version=1,
        field_map={"value": "value"},
        getters={"computed": "not_callable"},
    )

    result = build_target_fields(Source(), rule=rule, context=context_example)
    assert result.is_err()
    assert "not callable" in str(result.err())


def test_create_target_component_instantiates_class():
    """create_target_component simply instantiates the provided class."""

    class Dummy(NodeComponent):
        """Subclass to ensure kwargs are forwarded."""

    dummy = create_target_component(Dummy, kwargs={"name": "node_x"})

    assert isinstance(dummy, Dummy)
    assert dummy.name == "node_x"


def test_build_component_kwargs_from_parser_record(context_example):
    """Parsers should be able to reuse rules helpers with raw records."""
    record = {
        "name": "parser_component",
        "region_code": "north-zone",
        "ramp_rate_mw_per_min": 12.0,
    }

    @dataclass
    class RampLimits:
        up: float
        down: float

    def resolve_region(src: Any, *, context: Any) -> Result[NodeComponent, ValueError]:
        for node in context.target_system.get_components(NodeComponent):
            if node.area == src.region_code:
                return Ok(node)
        return Err(ValueError(f"Unknown region code {src.region_code}"))

    def convert_ramp_rate(src: Any, *, context: Any) -> Result[RampLimits, ValueError]:
        system_base = context.target_system.base_power or 1.0
        per_unit_value = src.ramp_rate_mw_per_min / system_base
        return Ok(RampLimits(up=per_unit_value, down=per_unit_value))

    rule = Rule(
        source_type="ParserRecord",
        target_type="StationComponent",
        version=1,
        field_map={"component_name": "name"},
        getters={
            "region_component": resolve_region,
            "ramp_limits": convert_ramp_rate,
        },
    )

    result = build_component_kwargs(record, rule=rule, context=context_example)

    assert result.is_ok()
    kwargs = result.unwrap()
    assert kwargs["component_name"] == "parser_component"
    assert kwargs["region_component"].area == "north-zone"
    assert kwargs["ramp_limits"].up == pytest.approx(0.12)
    assert kwargs["ramp_limits"].down == pytest.approx(0.12)


def test_make_attr_getter_returns_none_when_chain_breaks():
    """Attr getter returns Ok(None) when attribute is None mid-chain."""

    class Outer:
        inner = None

    getter = build_attr_getter(["inner", "value"])
    result = getter(Outer(), context=cast(Any, None))

    assert result.is_ok()
    assert result.unwrap() is None


def test_build_target_fields_skips_multifield_mappings(context_example):
    """Multi-field mappings in field_map are skipped for direct assignment."""

    class Source:
        name = "source_name"
        x_coord = 10.0
        y_coord = 20.0

    def coords_getter(src: Any, *, context: Any) -> Result[tuple, ValueError]:
        _ = context
        return Ok((src.x_coord, src.y_coord))

    rule = Rule(
        source_type="SourceType",
        target_type="TargetType",
        version=1,
        field_map={"name": "name", "coords": ["x_coord", "y_coord"]},
        getters={"coords": coords_getter},
    )

    result = build_target_fields(Source(), rule=rule, context=context_example)

    assert result.is_ok()
    kwargs = result.unwrap()
    assert kwargs["name"] == "source_name"
    assert kwargs["coords"] == (10.0, 20.0)


def test_build_target_fields_getter_error_uses_default(context_example):
    """Getter failures fall back to defaults when defined."""

    class Source:
        value = "x"

    def faulty_getter(_src: Any, *, context: Any) -> Result[Any, ValueError]:
        _ = context
        return Err(ValueError("boom"))

    rule = Rule(
        source_type="SourceType",
        target_type="TargetType",
        version=1,
        field_map={"value": "value"},
        getters={"computed": faulty_getter},
        defaults={"computed": "fallback_value"},
    )

    result = build_target_fields(Source(), rule=rule, context=context_example)

    assert result.is_ok()
    kwargs = result.unwrap()
    assert kwargs["computed"] == "fallback_value"


def test_evaluate_rule_filter_all_of():
    """Test evaluate_rule_filter with all_of composite filter."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    class Component:
        kind = "gas"
        capacity = 500

    filt = RuleFilter(
        all_of=[
            RuleFilter(field="kind", op="eq", values=["gas"]),
            RuleFilter(field="capacity", op="geq", values=[400]),
        ]
    )

    assert evaluate_rule_filter(Component(), rule_filter=filt)

    class FailComponent:
        kind = "gas"
        capacity = 300

    assert not evaluate_rule_filter(FailComponent(), rule_filter=filt)


def test_evaluate_rule_filter_incomplete_raises():
    """Test evaluate_rule_filter raises on incomplete leaf filter."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    class Component:
        kind = "gas"

    filt = RuleFilter.__new__(RuleFilter)
    object.__setattr__(filt, "any_of", None)
    object.__setattr__(filt, "all_of", None)
    object.__setattr__(filt, "field", None)
    object.__setattr__(filt, "op", None)
    object.__setattr__(filt, "values", None)
    object.__setattr__(filt, "prefixes", None)
    object.__setattr__(filt, "casefold", True)
    object.__setattr__(filt, "on_missing", "exclude")

    with pytest.raises(ValueError, match="must have field, op, and values"):
        evaluate_rule_filter(Component(), rule_filter=filt)


def test_evaluate_rule_filter_geq_non_numeric():
    """Test evaluate_rule_filter geq returns False for non-numeric values."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    class Component:
        capacity = "not_a_number"

    filt = RuleFilter(field="capacity", op="geq", values=[100])

    assert not evaluate_rule_filter(Component(), rule_filter=filt)
