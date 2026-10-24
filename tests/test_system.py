"""Tests for r2x_core.System class."""

from pathlib import Path
from typing import Annotated

import pytest
from infrasys import Component, SingleTimeSeries
from infrasys.exceptions import ISFileExists
from pydantic import BaseModel

from r2x_core import System, units


class SystemPowerLimits(BaseModel):
    minimum: float
    maximum: float


class SystemUnitComponent(units.HasUnits, Component):
    base_power: Annotated[float, units.Unit("MW")]
    limits: Annotated[SystemPowerLimits, units.Unit("MW", base="base_power")]


class PerUnitComponentFixture(units.HasPerUnit, Component):
    """Minimal HasPerUnit component for system tests."""

    name: str


@pytest.fixture
def example_system():
    return System(100.0, name="TestSystem", description="A test system")


def test_system_creation():
    """Test creating a system instance."""
    system = System(name="TestSystem")
    assert system.name == "TestSystem"
    assert isinstance(system, System)


def test_to_json_raises_on_existing_file_without_overwrite(tmp_path):
    """Test that to_json raises error when file exists and overwrite=False."""
    system = System(name="TestSystem")
    output_file = tmp_path / "system.json"
    system.to_json(filename=output_file)

    with pytest.raises(ISFileExists):
        system.to_json(filename=output_file, overwrite=False)


def test_system_accessors(example_system):
    """Test creating system with description."""
    system = example_system
    assert system.name == "TestSystem"
    assert system.description == "A test system"
    assert system.base_power == 100.0


def test_system_str_representation(example_system):
    """Test string representation."""
    system = example_system
    str_repr = str(system)
    assert "TestSystem" in str_repr
    assert "System" in str_repr
    assert repr(system) == str(system)


def test_system_str_shows_components(example_system):
    """Ensure __str__ reports component count when present."""
    system = example_system
    system.add_components(Component(name="component"))
    assert "components=1" in str(system)
    assert "system_base=100.0" in str(system)


def test_add_components_with_conflicting_system_base_raises():
    """Ensure adding a HasPerUnit component with a different base raises."""
    system = System(100.0, name="Conflicting")
    component = PerUnitComponentFixture(name="HasPU")
    component.bind_system_base(200.0)

    with pytest.raises(ValueError, match="already has system_base"):
        system.add_components(component)

    assert not system.has_component(component)
    assert component.system_base == 200.0


@pytest.mark.parametrize("invalid_first", [False, True])
def test_add_components_rejects_invalid_base_without_mutating_batch(invalid_first: bool) -> None:
    system = System(100.0, name="Batch")
    existing = Component(name="existing")
    system.add_components(existing)
    valid = PerUnitComponentFixture(name="valid")
    invalid = PerUnitComponentFixture(name="invalid")
    invalid.bind_system_base(200.0)
    batch = [invalid, valid] if invalid_first else [valid, invalid]

    with pytest.raises(ValueError, match="already has system_base"):
        system.add_components(*batch)

    assert list(system.get_components(Component)) == [existing]
    assert valid.system_base is None
    assert invalid.system_base == 200.0


@pytest.mark.parametrize(
    "fname",
    ["system_json.json", Path("system.json")],
    ids=["str_path", "pathlib_path"],
)
def test_to_json_with_fname(fname, tmp_path, example_system):
    import json

    system = example_system
    out_path = tmp_path / fname
    result = system.to_json(filename=out_path, overwrite=True, indent=2)
    assert result is None
    assert out_path.exists()
    content = json.loads(out_path.read_text())
    assert "name" in content.get("system", content)


def test_to_json_bytes_with_no_args(example_system):
    import orjson

    system = example_system

    json_str = system.to_json_bytes()
    assert isinstance(json_str, bytes)
    json_deserialized = orjson.loads(json_str)
    assert "name" in json_deserialized
    assert json_deserialized["name"] == "TestSystem"


def test_to_json_adds_system_block_when_data_overrides(example_system):
    """Ensure custom data dict receives serialized system when missing."""
    import orjson

    system = example_system
    payload = {"metadata": "value"}
    output = system.to_json_bytes(data=payload)

    assert isinstance(output, bytes)
    json_data = orjson.loads(output)
    assert json_data["metadata"] == "value"
    assert "system" in json_data
    assert json_data["system"]["name"] == "TestSystem"


def test_roundtrip_serialization(tmp_path):
    """Test complete save/load roundtrip."""
    original = System(name="RoundtripTest", description="Testing roundtrip")

    original.add_components(Component(name="dummy"))
    file_path = tmp_path / "roundtrip.json"
    original.to_json(filename=file_path)
    loaded = System.from_json(file_path)

    assert loaded.name == original.name
    assert loaded.description == original.description
    assert len(list(loaded.get_components(Component))) == 1


def test_system_round_trip_preserves_structured_per_unit_values(tmp_path: Path) -> None:
    system = System(name="UnitRoundtrip")
    component = SystemUnitComponent(
        name="generator",
        base_power=50.0,
        limits=SystemPowerLimits(minimum=-40.0, maximum=40.0),
    )
    system.add_components(component)

    path = tmp_path / "unit-roundtrip.json"
    system.to_json(filename=path)
    loaded = System.from_json(path)
    restored = loaded.get_component(SystemUnitComponent, name="generator")

    assert restored.limits.minimum == -0.8
    assert restored.limits.maximum == 0.8


def test_to_json_with_overwrite(tmp_path):
    """Test overwriting existing JSON file."""
    system1 = System(name="System1")
    system2 = System(name="System2")
    system1.add_components(Component(name="dummy1"))
    system2.add_components(Component(name="dummy2"))
    output_file = tmp_path / "system.json"

    system1.to_json(filename=output_file)
    assert output_file.exists()

    system2.to_json(filename=output_file, overwrite=True)

    loaded = System.from_json(output_file)
    assert loaded.name == "System2"


def test_to_json_no_overwrite_raises(tmp_path):
    """Test that to_json raises error when file exists and overwrite=False."""
    system = System(name="TestSystem")
    output_file = tmp_path / "system.json"

    system.to_json(filename=output_file)

    with pytest.raises(ISFileExists):
        system.to_json(filename=output_file, overwrite=False)


def test_to_json_bytes_with_time_series(caplog):
    """Test serializing system with time series to stdout."""
    from datetime import datetime, timedelta

    import numpy as np

    original_system = System(name="TestSystem", description="Test stdout with time series")

    component = Component(name="TestComponent")
    original_system.add_components(component)
    ts_data = SingleTimeSeries.from_array(
        data=np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
        name="test_variable",
        initial_timestamp=datetime(2024, 1, 1),
        resolution=timedelta(hours=1),
    )
    original_system.add_time_series(ts_data, component)

    json_bytes = original_system.to_json_bytes()
    assert json_bytes is not None

    deserialized_system = System.from_json(json_bytes)
    assert isinstance(deserialized_system, System)
    assert deserialized_system.uuid == original_system.uuid
    component_deserialized = deserialized_system.get_component(Component, name="TestComponent")
    assert deserialized_system.has_time_series(component_deserialized)


def test_from_json_bytes_missing_time_series_raises():
    """Missing time series data in bytes should raise KeyError."""
    with pytest.raises(KeyError, match="time series information"):
        System.from_json(b'{"name":"NoTimeSeries"}')


def test_from_json_bytes_missing_directory_raises():
    """Missing time series directory entry should raise KeyError."""
    import orjson

    payload = {"name": "NoDirectory", "time_series": {"metadata": "exists"}}
    with pytest.raises(KeyError, match="time series directory"):
        System.from_json(orjson.dumps(payload))


def test_from_json_with_invalid_source_type_raises():
    """Non-str/path/bytes source should raise NotImplementedError."""
    with pytest.raises(NotImplementedError):
        System.from_json(123)  # type: ignore[arg-type]


def test_from_json_sets_system_base_on_has_per_unit_component():
    """When deserializing, HasPerUnit components should get the system base."""
    system = System(250.0, name="HasPUSystem")
    component = PerUnitComponentFixture(name="HasPU")
    system.add_components(component)

    json_bytes = system.to_json_bytes()
    assert json_bytes is not None

    loaded = System.from_json(json_bytes)
    loaded_component = loaded.get_component(PerUnitComponentFixture, name="HasPU")
    assert loaded_component.system_base == loaded.base_power
