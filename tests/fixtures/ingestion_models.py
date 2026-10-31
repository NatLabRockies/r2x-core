"""Component and supplemental models for configured-ingestion tests."""

from infrasys import Component, SupplementalAttribute
from pydantic import Field


class PSSEBus(Component):
    """Bus model used by the illustrative RAW decoder."""

    number: int
    base_kv: float = Field(gt=0)


class PSSEGenerator(Component):
    """Generator linked to a bus by its component name."""

    bus: PSSEBus
    active_power_mw: float = Field(ge=0)
    available: bool = True


class BusGeo(SupplementalAttribute):
    """Supplemental region label for a bus."""

    region: str


class NestedValuesComponent(Component):
    """Component used to verify parser handling of assembled object and list values."""

    max_active_power: dict[str, float]
    coordinates: list[float | None]
    members: list[int | None]
    geographic_info: dict[str, object]
