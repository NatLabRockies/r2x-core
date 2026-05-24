"""Tests for declarative rule filters and executor integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from fixtures.context import FIXTURE_MODEL_MODULES
from fixtures.target_system import StationComponent

if TYPE_CHECKING:
    from r2x_core import RuleFilter, System


class _Dummy:
    def __init__(self, **attrs):
        for key, value in attrs.items():
            setattr(self, key, value)


def test_rule_filter_matches_leaf_casefold():
    """Leaf filters respect casefolded string comparisons."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    filt = RuleFilter(field="kind", op="eq", values=["gas"])
    assert evaluate_rule_filter(_Dummy(kind="GAS"), rule_filter=filt)


def test_rule_filter_matches_any_of():
    """Composite any_of evaluates to True when any child matches."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    filt = RuleFilter(
        any_of=[
            RuleFilter(field="kind", op="eq", values=["coal"]),
            RuleFilter(field="kind", op="eq", values=["gas"]),
        ]
    )
    assert evaluate_rule_filter(_Dummy(kind="gas"), rule_filter=filt)


def test_rule_filter_matches_geq_numeric():
    """Numeric geq comparison works for thresholds."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    filt = RuleFilter(field="capacity", op="geq", values=[400])
    assert evaluate_rule_filter(_Dummy(capacity=500.0), rule_filter=filt)
    assert not evaluate_rule_filter(_Dummy(capacity=300), rule_filter=filt)


def _run_rule_with_filter(filter_spec: RuleFilter, source_system: System) -> tuple[int, System]:
    """Apply a single filtered rule and return conversion count and target system."""
    from r2x_core import PluginConfig, PluginContext, Rule, System, apply_rules_to_context

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


def test_apply_rules_respects_filter_include(source_system):
    """Inclusive filters allow matching components to convert."""

    from r2x_core import RuleFilter

    converted, target_system = _run_rule_with_filter(
        RuleFilter(field="fuel_type", op="eq", values=["gas"]),
        source_system,
    )
    stations = list(target_system.get_components(StationComponent))
    assert converted == 1
    assert stations and stations[0].name == "plant_alpha"


def test_apply_rules_respects_filter_exclude(source_system):
    """Exclusive filters prevent matching components from converting."""
    from r2x_core import RuleFilter

    converted, target_system = _run_rule_with_filter(
        RuleFilter(field="fuel_type", op="neq", values=["gas"]),
        source_system,
    )
    stations = list(target_system.get_components(StationComponent))
    assert converted == 0
    assert not stations


def test_rule_filter_startswith():
    """Test that 'startswith' operator works for RuleFilter."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    filt = RuleFilter(field="kind", op="startswith", values=["ga"])
    assert evaluate_rule_filter(_Dummy(kind="gas"), rule_filter=filt)
    assert not evaluate_rule_filter(_Dummy(kind="coal"), rule_filter=filt)


def test_rule_filter_not_startswith():
    """Test that 'not_startswith' operator works for RuleFilter."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    filt = RuleFilter(field="kind", op="not_startswith", values=["ga"])
    assert evaluate_rule_filter(_Dummy(kind="coal"), rule_filter=filt)
    assert not evaluate_rule_filter(_Dummy(kind="gas"), rule_filter=filt)


def test_apply_rules_respects_filter_prefix(source_system):
    """Rule filters with prefixes control conversion in the executor."""
    from r2x_core import RuleFilter

    converted, target_system = _run_rule_with_filter(
        RuleFilter(field="name", op="startswith", prefixes=["plant_"]),
        source_system,
    )
    stations = list(target_system.get_components(StationComponent))
    assert converted == 1
    assert stations and stations[0].name == "plant_alpha"


def test_apply_rules_respects_filter_not_prefix(source_system):
    """Negative prefix filters block matching components."""
    from r2x_core import RuleFilter

    converted, _ = _run_rule_with_filter(
        RuleFilter(field="name", op="not_startswith", prefixes=["plant_"]),
        source_system,
    )
    assert converted == 0


def test_rule_filter_matches_endswith():
    """Leaf filters with endswith operator work as expected, including casefold."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    # Standard case
    filt = RuleFilter(field="name", op="endswith", values=["alpha"])
    assert evaluate_rule_filter(_Dummy(name="plant_alpha"), rule_filter=filt)
    assert not evaluate_rule_filter(_Dummy(name="plant_beta"), rule_filter=filt)

    # Casefolded match
    filt_casefold = RuleFilter(field="name", op="endswith", values=["ALPHA"])
    assert evaluate_rule_filter(_Dummy(name="plant_alpha"), rule_filter=filt_casefold)

    # Casefold disabled
    filt_nocase = RuleFilter(field="name", op="endswith", values=["ALPHA"], casefold=False)
    assert not evaluate_rule_filter(_Dummy(name="plant_alpha"), rule_filter=filt_nocase)


def test_rule_filter_matches_startswith():
    """Leaf filters with startswith operator work as expected."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    filt = RuleFilter(field="name", op="startswith", values=["plant_"])
    assert evaluate_rule_filter(_Dummy(name="plant_alpha"), rule_filter=filt)
    assert evaluate_rule_filter(_Dummy(name="plant_beta"), rule_filter=filt)
    assert not evaluate_rule_filter(_Dummy(name="station_alpha"), rule_filter=filt)


def test_rule_filter_matches_not_startswith():
    """Leaf filters with not_startswith operator work as expected."""
    from r2x_core import RuleFilter
    from r2x_core.utils import evaluate_rule_filter

    filt = RuleFilter(field="name", op="not_startswith", values=["plant_"])
    assert evaluate_rule_filter(_Dummy(name="station_alpha"), rule_filter=filt)
    assert not evaluate_rule_filter(_Dummy(name="plant_alpha"), rule_filter=filt)
    assert not evaluate_rule_filter(_Dummy(name="plant_beta"), rule_filter=filt)


def test_rulefilter_model_validator_leaf_and_children_error():
    """RuleFilter cannot mix leaf and composition."""
    import pytest

    from r2x_core import RuleFilter

    with pytest.raises(ValueError, match="cannot mix field/op/values with any_of/all_of"):
        RuleFilter(
            field="kind", op="eq", values=["gas"], any_of=[RuleFilter(field="kind", op="eq", values=["coal"])]
        )


def test_rulefilter_model_validator_requires_leaf_or_composition():
    """RuleFilter requires either leaf or composition."""
    import pytest

    from r2x_core import RuleFilter

    with pytest.raises(ValueError, match="requires field/op/values or any_of/all_of"):
        RuleFilter()


def test_rulefilter_model_validator_both_any_of_and_all_of_error():
    """RuleFilter cannot set both any_of and all_of."""
    import pytest

    from r2x_core import RuleFilter

    with pytest.raises(ValueError, match="cannot set both any_of and all_of"):
        RuleFilter(
            any_of=[RuleFilter(field="kind", op="eq", values=["coal"])],
            all_of=[RuleFilter(field="kind", op="eq", values=["gas"])],
        )


def test_rulefilter_model_validator_leaf_field_required():
    """RuleFilter.field required for leaf filters."""
    import pytest

    from r2x_core import RuleFilter

    with pytest.raises(ValueError, match="field is required for leaf filters"):
        RuleFilter(op="eq", values=["gas"])


def test_rulefilter_model_validator_leaf_op_required():
    """RuleFilter.op required for leaf filters."""
    import pytest

    from r2x_core import RuleFilter

    with pytest.raises(ValueError, match="op is required for leaf filters"):
        RuleFilter(field="kind", values=["gas"])


def test_rulefilter_model_validator_leaf_values_required():
    """RuleFilter.values or prefixes required for leaf filters."""
    import pytest

    from r2x_core import RuleFilter

    with pytest.raises(ValueError, match="must contain at least one value"):
        RuleFilter(field="kind", op="eq")


def test_rulefilter_model_validator_geq_one_value():
    """RuleFilter.geq expects exactly one comparison value."""
    import pytest

    from r2x_core import RuleFilter

    with pytest.raises(ValueError, match="expects exactly one comparison value"):
        RuleFilter(field="capacity", op="geq", values=[1, 2])


def test_rulefilter_model_validator_prefixes_type():
    """RuleFilter.prefixes entries must be strings."""
    import pytest

    from r2x_core import RuleFilter

    with pytest.raises(ValueError) as _:
        RuleFilter(field="name", op="startswith", prefixes=cast(Any, [123]))


def test_rulefilter_normalized_values_casefold():
    """_normalized_values precomputes casefolded values if casefold=True."""
    from r2x_core import RuleFilter

    filt = RuleFilter(field="name", op="startswith", values=["Plant_A"], casefold=True)
    assert filt._normalized_values == ["plant_a"]


def test_rulefilter_normalized_values_no_casefold():
    """_normalized_values preserves original values if casefold=False."""
    from r2x_core import RuleFilter

    filt = RuleFilter(field="name", op="startswith", values=["Plant_A"], casefold=False)
    assert filt._normalized_values == ["Plant_A"]
