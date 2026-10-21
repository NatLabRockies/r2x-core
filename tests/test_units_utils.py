"""Tests for the unit conversion and display functions."""

import pytest

from r2x_core.units import UnitSystem, set_unit_system
from r2x_core.units.conversion import convert_to_internal, format_for_display
from r2x_core.units.specs import UnitSpec


def test_convert_to_internal_with_int():
    spec = UnitSpec(unit="MVA")
    assert convert_to_internal(50, spec) == 50.0


def test_convert_to_internal_with_float():
    spec = UnitSpec(unit="MVA")
    assert convert_to_internal(50.5, spec) == 50.5


def test_convert_to_internal_with_invalid_type():
    spec = UnitSpec(unit="MVA")
    assert convert_to_internal("invalid", spec) == 0.0


def test_convert_to_internal_dict_missing_value_key():
    spec = UnitSpec(unit="MVA")
    assert convert_to_internal({"unit": "MVA"}, spec) == 0.0


def test_convert_to_internal_dict_missing_unit_key():
    spec = UnitSpec(unit="MVA")
    assert convert_to_internal({"value": 100.0}, spec) == 0.0


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

    assert convert_to_internal(value, spec, base_value=100.0, base_unit="MVA") == 1.0


def test_convert_to_internal_with_dimensionality_error():
    spec = UnitSpec(unit="pu", base="base_power")
    value = {"value": 100.0, "unit": "m"}

    assert convert_to_internal(value, spec, base_value=100.0, base_unit="MVA") == 1.0


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
