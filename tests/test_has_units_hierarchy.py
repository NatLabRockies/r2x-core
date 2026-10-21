"""Test the HasUnits vs HasPerUnit class hierarchy."""

from typing import Annotated

import pytest
from infrasys import Component

from r2x_core.units import HasPerUnit, HasUnits, Unit, UnitSystem, set_unit_system


class Sensor(HasUnits, Component):
    """A sensor that only reports absolute values."""

    name: str
    temperature: Annotated[float, Unit("°C")]
    pressure: Annotated[float, Unit("Pa")]


class Generator(HasPerUnit, Component):
    """A generator with base values and per-unit fields."""

    name: str
    base_power: Annotated[float, Unit("MVA")]
    rated_voltage: Annotated[float, Unit("kV")]
    rating: Annotated[float, Unit("pu", base="base_power")]
    voltage: Annotated[float, Unit("pu", base="rated_voltage")]


def test_has_units_with_absolute_values():
    """Test HasUnits with only absolute unit fields."""
    sensor = Sensor(name="TempSensor1", temperature=25.0, pressure=101325.0)
    assert sensor.temperature == 25.0
    assert sensor.pressure == 101325.0


def test_has_units_repr_formatting():
    """Test HasUnits repr includes unit labels."""
    sensor = Sensor(name="TempSensor1", temperature=25.0, pressure=101325.0)
    repr_str = repr(sensor)
    assert "25.0 °C" in repr_str
    assert "101325.0 Pa" in repr_str


def test_has_per_units_with_pu_input():
    """Test HasPerUnit with per-unit input values."""
    gen = Generator(
        name="Gen1",
        base_power=100.0,
        rated_voltage=13.8,
        rating=0.8,
        voltage=1.0,
    )
    assert gen.rating == 0.8
    assert gen.voltage == 1.0


def test_has_per_units_with_natural_unit_input():
    """Test HasPerUnit with natural unit dict input."""
    gen = Generator(
        name="Gen2",
        base_power=100.0,
        rated_voltage=13.8,
        rating={"value": 80.0, "unit": "MW"},  # type: ignore[arg-type]
        voltage={"value": 13.8, "unit": "kV"},  # type: ignore[arg-type]
    )
    assert gen.rating == pytest.approx(0.8, abs=1e-6)
    assert gen.voltage == pytest.approx(1.0, abs=1e-6)


def test_has_per_units_repr_device_base():
    """Test HasPerUnit repr in device base mode."""
    set_unit_system(UnitSystem.DEVICE_BASE)
    gen = Generator(
        name="Gen1",
        base_power=100.0,
        rated_voltage=13.8,
        rating=0.8,
        voltage=1.0,
    )
    repr_str = repr(gen)
    assert "0.8 pu" in repr_str
    assert "1.0 pu" in repr_str


def test_has_per_units_repr_natural_units():
    """Test HasPerUnit repr in natural units mode."""
    set_unit_system(UnitSystem.NATURAL_UNITS)
    gen = Generator(
        name="Gen1",
        base_power=100.0,
        rated_voltage=13.8,
        rating=0.8,
        voltage=1.0,
    )
    repr_str = repr(gen)
    assert "80" in repr_str
    assert "MVA" in repr_str
    assert "13.8" in repr_str
    assert "kV" in repr_str
    set_unit_system(UnitSystem.DEVICE_BASE)


def test_class_hierarchy_isinstance_sensor():
    """Test isinstance checks for HasUnits sensor."""
    sensor = Sensor(name="TempSensor1", temperature=25.0, pressure=101325.0)
    assert isinstance(sensor, HasUnits)
    assert not isinstance(sensor, HasPerUnit)


def test_class_hierarchy_isinstance_generator():
    """Test isinstance checks for HasPerUnit generator."""
    gen = Generator(
        name="Gen1",
        base_power=100.0,
        rated_voltage=13.8,
        rating=0.8,
        voltage=1.0,
    )
    assert isinstance(gen, HasUnits)
    assert isinstance(gen, HasPerUnit)


def test_has_units_system_base_is_none():
    """HasUnits models without system-base support return None."""
    sensor = Sensor(name="TempSensor1", temperature=25.0, pressure=101325.0)
    assert sensor.system_base is None


def test_has_per_units_system_base_can_be_set():
    """Set the system base through the public binding method."""
    gen = Generator(
        name="Gen1",
        base_power=100.0,
        rated_voltage=13.8,
        rating=0.8,
        voltage=1.0,
    )
    gen.bind_system_base(150.0)
    assert gen.system_base == 150.0


def test_has_per_units_system_base_repr():
    """Test HasPerUnit repr with system base set."""
    set_unit_system(UnitSystem.SYSTEM_BASE)
    gen = Generator(
        name="Gen1",
        base_power=100.0,
        rated_voltage=13.8,
        rating=0.8,
        voltage=1.0,
    )
    gen.bind_system_base(150.0)
    repr_str = repr(gen)
    assert "pu (system)" in repr_str
    set_unit_system(UnitSystem.DEVICE_BASE)


def test_mixed_units_conversion():
    """Test conversion with mixed natural and pu inputs."""
    gen = Generator(
        name="Gen3",
        base_power=100.0,
        rated_voltage=13.8,
        rating={"value": 90.0, "unit": "MVA"},  # type: ignore[arg-type]
        voltage=1.05,
    )
    assert gen.rating == pytest.approx(0.9, abs=1e-6)
    assert gen.voltage == 1.05


def test_unit_specs_contains_exactly_annotated_fields():
    """The class-level registry contains only fields with Unit metadata."""
    assert set(Sensor.unit_specs) == {"temperature", "pressure"}
    assert set(Generator.unit_specs) == {"base_power", "rated_voltage", "rating", "voltage"}
    assert Generator.unit_specs["rating"].base_unit == "MVA"


def test_same_named_classes_resolve_their_own_base_units():
    """Class-name collisions do not affect per-unit conversion."""

    def make_generator(base_unit: str) -> type[Component]:
        class Generator(HasUnits, Component):
            base_power: Annotated[float, Unit(base_unit)]
            rating: Annotated[float, Unit("pu", base="base_power")]

        return Generator

    mva_generator = make_generator("MVA")
    kva_generator = make_generator("kVA")

    mva_instance = mva_generator(
        name="MVA generator",
        base_power=100.0,
        rating={"value": 80.0, "unit": "MVA"},  # type: ignore[arg-type]
    )
    kva_instance = kva_generator(
        name="kVA generator",
        base_power=100.0,
        rating={"value": 80.0, "unit": "kVA"},  # type: ignore[arg-type]
    )

    assert mva_instance.rating == pytest.approx(0.8)
    assert kva_instance.rating == pytest.approx(0.8)


def test_missing_base_unit_field_raises_at_class_creation():
    """Reject a base reference that does not name a unit-annotated field."""
    with pytest.raises(TypeError, match="missing_base"):

        class InvalidComponent(HasUnits, Component):
            rating: Annotated[float, Unit("pu", base="missing_base")]
