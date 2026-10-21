"""Tests for structured types with unit conversion."""

from typing import Annotated

import pytest
from infrasys import Component
from pydantic import BaseModel, ValidationError

from r2x_core.units import HasUnits, Unit


class UpDown(BaseModel):
    up: float
    down: float


class MinMax(BaseModel):
    min: float
    max: float


class IntLimits(BaseModel):
    min: int
    max: int


class MixedLimits(BaseModel):
    min_float: float
    max_int: int
    nominal: float


class OptionalFields(BaseModel):
    required: float
    optional: float | None = None


def test_structured_type_with_unit_conversion():
    class Generator(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        ramp_limits: Annotated[UpDown, Unit("MW/min", base="base_power")]

    gen = Generator(
        name="Gen1",
        base_power=100.0,
        ramp_limits=UpDown(up=10.0, down=8.0),
    )

    assert gen.ramp_limits.up == 0.1
    assert gen.ramp_limits.down == 0.08


def test_nested_unit_aware_model_uses_its_unit_specs():
    class UnitAwareLimits(HasUnits, BaseModel):
        power: Annotated[float, Unit("MW")]
        fraction: Annotated[float, Unit("pu", base="power")]

    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        limits: Annotated[UnitAwareLimits, Unit("MW", base="base_power")]

    device = Device(
        name="Dev1",
        base_power=100.0,
        limits=UnitAwareLimits(power=20.0, fraction=0.5),
    )

    assert device.limits.power == 0.2
    assert device.limits.fraction == 0.5


def test_structured_type_without_base():
    class Bus(HasUnits, Component):
        voltage_limits: Annotated[MinMax, Unit("kV")]

    bus = Bus(
        name="Bus1",
        voltage_limits=MinMax(min=132.0, max=138.0),
    )

    assert bus.voltage_limits.min == 132.0
    assert bus.voltage_limits.max == 138.0


def test_structured_type_optional():
    class Generator(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        limits: Annotated[MinMax | None, Unit("MW", base="base_power")] = None

    gen1 = Generator(name="Gen1", base_power=100.0)
    assert gen1.limits is None

    gen2 = Generator(
        name="Gen2",
        base_power=100.0,
        limits=MinMax(min=20.0, max=80.0),
    )
    assert gen2.limits is not None
    assert gen2.limits.min == 0.2
    assert gen2.limits.max == 0.8


def test_structured_type_serialization():
    class Battery(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        power_limits: Annotated[MinMax, Unit("MW", base="base_power")]

    battery = Battery(
        name="Batt1",
        base_power=50.0,
        power_limits=MinMax(min=-40.0, max=40.0),
    )

    serialized = battery.model_dump()

    assert isinstance(serialized["power_limits"], dict)
    assert serialized["power_limits"]["min"] == -0.8
    assert serialized["power_limits"]["max"] == 0.8

    deserialized = Battery.model_validate(serialized)
    assert isinstance(deserialized, Battery)


def test_same_structured_type_different_units():
    class Component1(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        power_limits: Annotated[MinMax, Unit("MW", base="base_power")]

    class Component2(HasUnits, Component):
        voltage_limits: Annotated[MinMax, Unit("kV")]

    comp1 = Component1(
        name="C1",
        base_power=100.0,
        power_limits=MinMax(min=20.0, max=80.0),
    )

    comp2 = Component2(
        name="C2",
        voltage_limits=MinMax(min=132.0, max=138.0),
    )

    assert comp1.power_limits.min == 0.2
    assert comp2.voltage_limits.min == 132.0


def test_nested_float_only():
    class ComplexLimits(BaseModel):
        value: float
        label: str
        enabled: bool

    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        limits: Annotated[ComplexLimits, Unit("MW", base="base_power")]

    device = Device(
        name="Dev1",
        base_power=100.0,
        limits=ComplexLimits(value=50.0, label="test", enabled=True),
    )

    assert device.limits.value == 0.5
    assert device.limits.label == "test"
    assert device.limits.enabled is True


def test_structured_type_with_int_fields():
    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        int_limits: Annotated[IntLimits, Unit("MW", base="base_power")]

    with pytest.raises(ValidationError) as exc_info:
        Device(
            name="Dev1",
            base_power=100.0,
            int_limits=IntLimits(min=10, max=90),
        )

    assert "int_from_float" in str(exc_info.value)


def test_structured_type_with_mixed_types():
    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        mixed: Annotated[MixedLimits, Unit("MW", base="base_power")]

    with pytest.raises(ValidationError) as exc_info:
        Device(
            name="Dev1",
            base_power=50.0,
            mixed=MixedLimits(min_float=10.5, max_int=45, nominal=25.0),
        )

    assert "int_from_float" in str(exc_info.value)


def test_structured_type_with_zero_values():
    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        limits: Annotated[MinMax, Unit("MW", base="base_power")]

    device = Device(
        name="Dev1",
        base_power=100.0,
        limits=MinMax(min=0.0, max=100.0),
    )

    assert device.limits.min == 0.0
    assert device.limits.max == 1.0


def test_structured_type_with_negative_values():
    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        limits: Annotated[MinMax, Unit("MW", base="base_power")]

    device = Device(
        name="Dev1",
        base_power=100.0,
        limits=MinMax(min=-50.0, max=75.0),
    )

    assert device.limits.min == -0.5
    assert device.limits.max == 0.75


def test_structured_type_json_round_trip():
    class Battery(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        power_limits: Annotated[MinMax, Unit("MW", base="base_power")]

    battery = Battery(
        name="Batt1",
        base_power=50.0,
        power_limits=MinMax(min=-40.0, max=40.0),
    )

    json_str = battery.model_dump_json()
    deserialized = Battery.model_validate_json(json_str)

    assert deserialized.power_limits.min == -0.8
    assert deserialized.power_limits.max == 0.8
    assert deserialized.base_power == 50.0


def test_multiple_structured_type_fields():
    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        power_limits: Annotated[MinMax, Unit("MW", base="base_power")]
        ramp_limits: Annotated[UpDown, Unit("MW/min", base="base_power")]

    device = Device(
        name="Dev1",
        base_power=100.0,
        power_limits=MinMax(min=20.0, max=80.0),
        ramp_limits=UpDown(up=10.0, down=8.0),
    )

    assert device.power_limits.min == 0.2
    assert device.power_limits.max == 0.8
    assert device.ramp_limits.up == 0.1
    assert device.ramp_limits.down == 0.08


def test_structured_type_different_base_values():
    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        limits: Annotated[MinMax, Unit("MW", base="base_power")]

    device1 = Device(
        name="Dev1",
        base_power=100.0,
        limits=MinMax(min=20.0, max=80.0),
    )

    device2 = Device(
        name="Dev2",
        base_power=50.0,
        limits=MinMax(min=20.0, max=40.0),
    )

    assert device1.limits.min == 0.2
    assert device1.limits.max == 0.8
    assert device2.limits.min == 0.4
    assert device2.limits.max == 0.8


def test_structured_type_optional_fields_inside():
    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        limits: Annotated[OptionalFields, Unit("MW", base="base_power")]

    device1 = Device(
        name="Dev1",
        base_power=100.0,
        limits=OptionalFields(required=50.0),
    )

    assert device1.limits.required == 0.5
    assert device1.limits.optional is None

    device2 = Device(
        name="Dev2",
        base_power=100.0,
        limits=OptionalFields(required=50.0, optional=25.0),
    )

    assert device2.limits.required == 0.5
    assert device2.limits.optional == 0.25


def test_structured_type_reassignment():
    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        limits: Annotated[MinMax, Unit("MW", base="base_power")]

    device = Device(
        name="Dev1",
        base_power=100.0,
        limits=MinMax(min=20.0, max=80.0),
    )

    assert device.limits.min == 0.2
    assert device.limits.max == 0.8

    device.limits = MinMax(min=30.0, max=70.0)

    assert device.limits.min == 0.3
    assert device.limits.max == 0.7


def test_structured_type_preserves_instance_type():
    class Device(HasUnits, Component):
        base_power: Annotated[float, Unit("MVA")]
        limits: Annotated[MinMax, Unit("MW", base="base_power")]

    device = Device(
        name="Dev1",
        base_power=100.0,
        limits=MinMax(min=20.0, max=80.0),
    )

    assert isinstance(device.limits, MinMax)
    assert type(device.limits) is MinMax
