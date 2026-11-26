"""Component and supplemental models for configured-ingestion tests."""

from typing import Self

from infrasys import Component, SupplementalAttribute
from pydantic import ConfigDict, Field, field_validator, model_validator


class PSSEBus(Component):
    """Bus model used by the illustrative RAW decoder."""

    number: int
    base_kv: float = Field(gt=0)


class PSSERevalidatedBus(PSSEBus):
    """Bus configured to revalidate nested instances."""

    model_config = ConfigDict(revalidate_instances="always")


class PSSEGenerator(Component):
    """Generator linked to a bus by its component name."""

    bus: PSSEBus
    active_power_mw: float = Field(ge=0)
    available: bool = True


class PSSERevalidatedGenerator(PSSEGenerator):
    """Generator whose bus is revalidated when nested."""

    bus: PSSERevalidatedBus


class PSSESwitchingGenerator(Component):
    """Generator whose validator replaces its bus with another reference."""

    bus: PSSEBus
    alternate_bus: PSSEBus

    @model_validator(mode="after")
    def switch_bus(self) -> Self:
        """Replace the primary bus during model validation."""
        if self.bus is not self.alternate_bus:
            self.bus = self.alternate_bus
        return self


class PSSEBusGroup(Component):
    """Group of buses linked by component reference."""

    buses: list[PSSEBus]


class PSSERevalidatedBusGroup(Component):
    """Group whose buses are revalidated when nested."""

    buses: list[PSSERevalidatedBus]


class PSSEReorderedBusGroup(Component):
    """Group whose validation mutates the incoming reference list."""

    buses: list[PSSEBus]

    @field_validator("buses", mode="before")
    @classmethod
    def reverse_buses(cls, value: object) -> object:
        """Reverse the supplied list in place."""
        if isinstance(value, list):
            value.reverse()
        return value


class PSSEShortenedBusGroup(PSSEBusGroup):
    """Group whose validator removes a member."""

    @field_validator("buses", mode="before")
    @classmethod
    def remove_bus(cls, value: object) -> object:
        """Remove one supplied reference in place."""
        if isinstance(value, list) and value:
            value.pop()
        return value


class PSSEExpandedBusGroup(PSSEBusGroup):
    """Group whose validator adds a member."""

    @field_validator("buses", mode="before")
    @classmethod
    def duplicate_bus(cls, value: object) -> object:
        """Append one supplied reference in place."""
        if isinstance(value, list) and value:
            value.append(value[0])
        return value


class PSSESubstitutedBusGroup(PSSEBusGroup):
    """Group whose validator replaces one member with another."""

    @field_validator("buses", mode="before")
    @classmethod
    def substitute_bus(cls, value: object) -> object:
        """Replace the first supplied reference in place."""
        if isinstance(value, list) and len(value) > 1:
            value[0] = value[1]
        return value


class PSSEDeletedBusGroup(Component):
    """Group whose model validator deletes the reference field."""

    buses: list[PSSEBus]

    @model_validator(mode="after")
    def delete_buses(self) -> Self:
        """Remove the validated reference field."""
        del self.buses
        return self


class PSSETupleBusGroup(Component):
    """Group with a tuple that Pydantic can coerce from a list."""

    buses: tuple[PSSEBus, ...]


class PSSERequiredBusGroup(Component):
    """Group that requires at least one bus."""

    buses: list[PSSEBus] = Field(min_length=1)


class BusGeo(SupplementalAttribute):
    """Supplemental region label for a bus."""

    region: str


class NestedValuesComponent(Component):
    """Component used to verify parser handling of assembled object and list values."""

    max_active_power: dict[str, float]
    coordinates: list[float | None]
    members: list[int | None]
    geographic_info: dict[str, object]
