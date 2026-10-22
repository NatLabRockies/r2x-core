"""Tests for the unit conversion and display functions."""

from typing import Annotated

import pytest
from pydantic import BaseModel, ValidationError

from r2x_core import HasUnits, Unit
from r2x_core.units import UnitSystem, set_unit_system
from r2x_core.units.conversion import convert_to_internal, format_for_display
from r2x_core.units.specs import UnitSpec


class PowerModel(HasUnits, BaseModel):
    base_power: Annotated[float, Unit("MW")]
    power: Annotated[float, Unit("pu", base="base_power")]


def test_convert_to_internal_with_int():
    spec = UnitSpec(unit="MVA")
    assert convert_to_internal(50, spec) == 50.0


def test_convert_to_internal_with_float():
    spec = UnitSpec(unit="MVA")
    assert convert_to_internal(50.5, spec) == 50.5


def test_convert_to_internal_with_invalid_type():
    spec = UnitSpec(unit="MVA")
    with pytest.raises(ValueError, match="Expected"):
        convert_to_internal("invalid", spec)


def test_convert_to_internal_dict_missing_value_key():
    spec = UnitSpec(unit="MVA")
    with pytest.raises(ValueError, match=r"value.*unit"):
        convert_to_internal({"unit": "MVA"}, spec)


def test_convert_to_internal_dict_missing_unit_key():
    spec = UnitSpec(unit="MVA")
    with pytest.raises(ValueError, match=r"value.*unit"):
        convert_to_internal({"value": 100.0}, spec)


@pytest.mark.parametrize(
    ("value", "input_unit", "base_value", "base_unit", "expected"),
    [
        (5000.0, "kW", 100.0, "MW", 0.05),
        (50.0, "MVA", 100.0, "MVA", 0.5),
        (50000.0, "kVA", 100.0, "MVA", 0.5),
    ],
)
def test_convert_to_internal_normalizes_compatible_units(
    value: float, input_unit: str, base_value: float, base_unit: str, expected: float
) -> None:
    spec = UnitSpec(unit="pu", base="base_power")

    assert (
        convert_to_internal(
            {"value": value, "unit": input_unit}, spec, base_value=base_value, base_unit=base_unit
        )
        == expected
    )


def test_has_units_normalizes_prefixed_natural_unit_input() -> None:
    model = PowerModel(base_power=100.0, power={"value": 5000.0, "unit": "kW"})

    assert model.power == 0.05


@pytest.mark.parametrize(
    ("declared_unit", "value", "input_unit", "base_value", "base_unit", "expected"),
    [
        ("MW/min", 10.0, "MW/min", 100.0, "MW", 0.1),
        ("MW/min", 10000.0, "kW/min", 100.0, "MW", 0.1),
        ("MW/min", 600.0, "MW/hour", 100.0, "MW", 0.1),
        ("MW/min", 10.0, "MW/min", 100000.0, "kW", 0.1),
        ("kW/min", 10.0, "MW/min", 100.0, "MW", 0.1),
        ("MW/min**2", 10.0, "MW/min**2", 100.0, "MW", 0.1),
        ("kV", 50.0, "V", 100.0, "V", 0.5),
    ],
)
def test_convert_to_internal_normalizes_relative_quantities(
    declared_unit: str,
    value: float,
    input_unit: str,
    base_value: float,
    base_unit: str,
    expected: float,
) -> None:
    spec = UnitSpec(unit=declared_unit, base="base")

    assert (
        convert_to_internal(
            {"value": value, "unit": input_unit}, spec, base_value=base_value, base_unit=base_unit
        )
        == expected
    )


def test_has_units_converts_scalar_rates_without_losing_time_units() -> None:
    class RateModel(HasUnits, BaseModel):
        base_power: Annotated[float, Unit("MW")]
        ramp: Annotated[float, Unit("MW/min", base="base_power")]

    assert RateModel(base_power=100.0, ramp={"value": 10.0, "unit": "MW/min"}).ramp == 0.1
    assert RateModel(base_power=100.0, ramp={"value": 10000.0, "unit": "kW/min"}).ramp == 0.1


def test_convert_to_internal_translates_invalid_relative_units() -> None:
    value = {"value": 10.0, "unit": "MW/min"}

    with pytest.raises(ValueError, match="Unknown unit"):
        convert_to_internal(
            value, UnitSpec(unit="InvalidUnit", base="base"), base_value=100.0, base_unit="MW"
        )

    with pytest.raises(ValueError, match="Unknown unit"):
        convert_to_internal(
            value, UnitSpec(unit="MW/min", base="base"), base_value=100.0, base_unit="InvalidUnit"
        )


def test_has_units_rejects_incompatible_natural_unit_input() -> None:
    with pytest.raises(ValidationError, match="incompatible"):
        PowerModel(base_power=100.0, power={"value": 50.0, "unit": "kV"})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"value": "not numeric", "unit": "MW"}, "value' must be numeric"),
        ({"value": 1.0, "unit": None}, "unit' must be a non-empty string"),
        ({"value": 1.0, "unit": ""}, "unit' must be a non-empty string"),
    ],
)
def test_convert_to_internal_rejects_invalid_mapping_values(value: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        convert_to_internal(value, UnitSpec(unit="MW"))


def test_convert_to_internal_accepts_explicit_per_unit_value() -> None:
    spec = UnitSpec(unit="pu", base="base_power")

    assert convert_to_internal({"value": 0.8, "unit": "pu"}, spec) == 0.8


def test_convert_to_internal_rejects_unknown_units() -> None:
    spec = UnitSpec(unit="pu", base="base_power")

    with pytest.raises(ValueError, match="Unknown unit"):
        convert_to_internal({"value": 100.0, "unit": "InvalidUnit"}, spec, base_value=100.0, base_unit="MW")


def test_convert_to_internal_rejects_zero_base() -> None:
    spec = UnitSpec(unit="pu", base="base_power")

    with pytest.raises(ValueError, match="non-zero"):
        convert_to_internal({"value": 100.0, "unit": "MW"}, spec, base_value=0.0, base_unit="MW")


def test_convert_to_internal_converts_absolute_units() -> None:
    assert convert_to_internal({"value": 5000.0, "unit": "kW"}, UnitSpec(unit="MW")) == 5.0
    assert convert_to_internal({"value": 13800.0, "unit": "V"}, UnitSpec(unit="kV")) == 13.8


def test_convert_to_internal_does_not_treat_per_unit_as_a_physical_unit() -> None:
    with pytest.raises(ValueError, match="declared base"):
        convert_to_internal({"value": 1.0, "unit": "kg"}, UnitSpec(unit="pu"))


def test_convert_to_internal_missing_base_value():
    spec = UnitSpec(unit="pu", base="base_power")
    value = {"value": 1.0, "unit": "MVA"}

    with pytest.raises(ValueError, match=r"Base field 'base_power' is required.*not provided"):
        convert_to_internal(value, spec, base_unit="MVA")


def test_convert_to_internal_missing_base_unit():
    spec = UnitSpec(unit="pu", base="base_power")
    value = {"value": 1.0, "unit": "MVA"}

    with pytest.raises(ValueError, match=r"Base unit for field 'base_power' could not be determined"):
        convert_to_internal(value, spec, base_value=100.0)


def test_convert_to_internal_with_invalid_unit():
    spec = UnitSpec(unit="pu", base="base_power")
    value = {"value": 100.0, "unit": "InvalidUnit"}

    with pytest.raises(ValueError, match="Unknown unit"):
        convert_to_internal(value, spec, base_value=100.0, base_unit="MVA")


def test_convert_to_internal_with_dimensionality_error():
    spec = UnitSpec(unit="pu", base="base_power")
    value = {"value": 100.0, "unit": "m"}

    with pytest.raises(ValueError, match="incompatible"):
        convert_to_internal(value, spec, base_value=100.0, base_unit="MVA")


def test_format_for_display_device_base_no_base_value():
    spec = UnitSpec(unit="pu", base="base_power")
    set_unit_system(UnitSystem.DEVICE_BASE)

    assert format_for_display(0.8, spec, UnitSystem.DEVICE_BASE) == "0.8 pu"


def test_format_for_display_natural_units_no_base():
    spec = UnitSpec(unit="pu", base="base_power")

    assert format_for_display(0.8, spec, UnitSystem.NATURAL_UNITS, base_unit="MVA") == "0.8 pu"


def test_format_for_display_system_base_no_base_value():
    spec = UnitSpec(unit="pu", base="base_power")

    assert format_for_display(0.8, spec, UnitSystem.SYSTEM_BASE) == "0.8 pu"


def test_format_for_display_system_base_no_system_base():
    spec = UnitSpec(unit="pu", base="base_power")

    assert (
        format_for_display(
            0.8,
            spec,
            UnitSystem.SYSTEM_BASE,
            base_value=100.0,
            base_unit="MVA",
        )
        == "0.8 pu"
    )
