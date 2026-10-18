"""Target-side test system with companion component definitions."""

from __future__ import annotations

from uuid import uuid4

import pytest
from infrasys import Component
from pydantic import Field

from r2x_core.system import System


class NodeComponent(Component):
    """Translated equivalent of a source bus."""

    kv_rating: float = Field(default=0.0, description="Voltage rating in kV.")
    demand_mw: float = Field(default=0.0, description="Demand served at the node in MW.")
    area: str = Field(default="", description="Operational area identifier.")


class ContextScopedReviewComponent(Component):
    """Component used to verify model resolution stays scoped to PluginConfig."""


class BuilderEdgeComponent(Component):
    """Component exposing field names that collide with construction controls."""

    capacity: float = 1.0
    skip_validation: bool = False
    note: str | None = "model-default"


class CircuitComponent(Component):
    """Translated representation of a transmission asset."""

    r_pu: float = Field(default=0.0, description="Per-unit resistance on system base.")
    x_pu: float = Field(default=0.0, description="Per-unit reactance on system base.")
    capacity_mw: float = Field(default=0.0, description="Transfer capability in MW.")


class StationComponent(Component):
    """Translated generating unit representation."""

    max_output_mw: float = Field(default=0.0, description="Maximum deliverable output in MW.")
    min_output_mw: float = Field(default=0.0, description="Minimum operating point in MW.")
    resource: str = Field(default="", description="Resource category used by the unit.")


def build_target_system() -> System:
    """Construct a System populated with representative target components."""
    system = System(name="TargetFixture", system_base=100.0)
    system.add_components(
        NodeComponent(
            name="node_a",
            uuid=uuid4(),
            kv_rating=230.0,
            demand_mw=140.0,
            area="north-zone",
        ),
        CircuitComponent(
            name="circuit_ab",
            uuid=uuid4(),
            r_pu=0.02,
            x_pu=0.18,
            capacity_mw=320.0,
        ),
        StationComponent(
            name="station_alpha",
            uuid=uuid4(),
            max_output_mw=520.0,
            min_output_mw=80.0,
            resource="thermal",
        ),
    )
    return system


@pytest.fixture
def target_system() -> System:
    """Pytest fixture exposing a ready-to-use target system."""
    return build_target_system()
