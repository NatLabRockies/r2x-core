"""Small application-owned component schema, not a full PSS/E model."""

from infrasys import Component
from pydantic import Field


class PSSEBus(Component):
    """Represent one bus from the dummy case."""

    number: int = Field(gt=0)
    base_kv: float = Field(gt=0)


class PSSEGenerator(Component):
    """Represent one generator with a resolved component reference."""

    bus: PSSEBus
    active_power_mw: float = Field(ge=0)
    available: bool = True
