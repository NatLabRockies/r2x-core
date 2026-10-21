"""Tests for the UnitSpec class."""

from typing import Annotated

import pytest
from infrasys import Component
from pydantic import BaseModel, ValidationError
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from r2x_core.units import HasUnits, Unit
from r2x_core.units.specs import UnitSpec


def test_unitspec_dict_input_no_base():
    """Test UnitSpec validation with dict input when base is None."""

    class SimpleModel(BaseModel):
        """Model with unit field but no base."""

        power: Annotated[float, Unit("MW")]

    model = SimpleModel(power={"value": 100.0, "unit": "MW"})  # type: ignore[arg-type]
    assert model.power == 100.0


def test_unitspec_dict_input_with_conversion():
    """Test UnitSpec validation with dict input and unit conversion."""

    class Generator(HasUnits, Component):
        """Generator with units."""

        base_power: Annotated[float, Unit("MVA")]
        rating: Annotated[float, Unit("pu", base="base_power")]

    gen = Generator(name="Gen1", base_power=100.0, rating={"value": 80.0, "unit": "MVA"})  # type: ignore[arg-type]
    assert gen.rating == 0.8


def test_unitspec_base_unit_binding_rejects_conflicts():
    spec = UnitSpec(unit="pu", base="base_power")
    spec.bind_base_unit("MVA")
    spec.bind_base_unit("MVA")

    with pytest.raises(ValueError, match="already bound as 'MVA'"):
        spec.bind_base_unit("kVA")


def test_unitspec_invalid_input_type():
    """Test UnitSpec validation raises ValidationError for invalid input types."""

    class TestModel(BaseModel):
        """Test model."""

        value: Annotated[float, Unit("MVA")]

    with pytest.raises(ValidationError):
        TestModel(value="invalid")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        TestModel(value=[1, 2, 3])  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        TestModel(value={"invalid": "dict"})  # type: ignore[arg-type]


def test_unitspec_get_pydantic_json_schema():
    """Test that JSON schema generation works for UnitSpec."""
    spec = UnitSpec(unit="MVA", base=None)

    def mock_handler(schema: core_schema.CoreSchema) -> JsonSchemaValue:
        return {"type": "number"}

    result = spec.__get_pydantic_json_schema__(core_schema.float_schema(), mock_handler)  # type: ignore[arg-type]

    # Should return the result of handler(core_schema.float_schema())
    assert result == {"type": "number"}


def test_unitspec_serialization_in_model():
    """Test that UnitSpec fields serialize correctly in Pydantic models."""

    class Generator(BaseModel):
        """Generator model."""

        name: str
        base_power: Annotated[float, Unit("MVA")]
        rating: Annotated[float, Unit("pu", base="base_power")]

    schema = Generator.model_json_schema()

    # The fields with UnitSpec should have number type in schema
    assert schema["properties"]["base_power"]["type"] == "number"
    assert schema["properties"]["rating"]["type"] == "number"


def test_unitspec_no_base_field():
    """Test UnitSpec with no base field (simple unit)."""

    class SimpleModel(BaseModel):
        """Model with simple unit field."""

        voltage: Annotated[float, Unit("kV")]

    model1 = SimpleModel(voltage=13.8)
    assert model1.voltage == 13.8

    model2 = SimpleModel(voltage={"value": 13.8, "unit": "kV"})  # type: ignore[arg-type]
    assert model2.voltage == 13.8

    model3 = SimpleModel(voltage={"value": 13800.0, "unit": "V"})  # type: ignore[arg-type]
    assert model3.voltage == 13800.0
