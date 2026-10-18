"""Source-side test system with canonical component types."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import numpy as np
import pytest
from infrasys import Component, SingleTimeSeries, SupplementalAttribute
from pydantic import Field

from r2x_core.system import System


class BusComponent(Component):
    """Simplified source bus representation."""

    voltage_kv: float = Field(default=0.0, description="Nominal operating voltage in kV.")
    load_mw: float = Field(default=0.0, description="Connected load in MW.")
    zone: str = Field(default="", description="Planning zone identifier.")


class LineComponent(Component):
    """Transmission line in the source system."""

    resistance_ohm: float = Field(default=0.0, description="Series resistance in ohms.")
    reactance_ohm: float = Field(default=0.0, description="Series reactance in ohms.")
    thermal_limit_mw: float = Field(default=0.0, description="Thermal capacity in MW.")


class PlantComponent(Component):
    """Generating plant representation."""

    capacity_mw: float = Field(default=0.0, description="Maximum output in MW.")
    min_stable_level_mw: float = Field(default=0.0, description="Minimum operating level in MW.")
    fuel_type: str = Field(default="", description="Primary fuel used by the plant.")


class BusGeographicInfo(SupplementalAttribute):
    """Supplemental attribute with geographic information for buses."""

    latitude: float = Field(default=0.0, description="Latitude in degrees")
    longitude: float = Field(default=0.0, description="Longitude in degrees")
    location_name: str = Field(default="", description="Location name")


class ReviewEmissionAttribute(SupplementalAttribute):
    """Emission supplemental attribute used by record-builder tests."""

    rate: float
    emission_type: str


def _attach_bus_time_series(system: System, bus: BusComponent) -> None:
    """Attach deterministic time series data for translation tests."""
    load_profile = SingleTimeSeries.from_array(
        data=np.array([100.0, 105.0, 110.0, 108.0], dtype=float),
        name="load_profile",
        initial_timestamp=datetime(2024, 1, 1),
        resolution=timedelta(hours=1),
    )
    system.add_time_series(load_profile, bus)


def build_source_system() -> System:
    """Construct a System populated with representative source components."""
    system = System(name="SourceFixture", system_base=100.0)

    bus_component = BusComponent(
        name="bus_a",
        uuid=uuid4(),
        voltage_kv=230.0,
        load_mw=150.0,
        zone="north",
    )
    line_component = LineComponent(
        name="line_ab",
        uuid=uuid4(),
        resistance_ohm=0.02,
        reactance_ohm=0.18,
        thermal_limit_mw=300.0,
    )
    plant_component = PlantComponent(
        name="plant_alpha",
        uuid=uuid4(),
        capacity_mw=500.0,
        min_stable_level_mw=100.0,
        fuel_type="gas",
    )

    system.add_components(bus_component, line_component, plant_component)
    _attach_bus_time_series(system, bus_component)
    return system


@pytest.fixture
def source_system() -> System:
    """Pytest fixture exposing a ready-to-use source system."""
    return build_source_system()
