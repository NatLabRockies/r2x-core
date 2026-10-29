"""Minimal educational schema for the CSV tutorial."""

from infrasys import Component
from pydantic import Field


class Generator(Component):
    capacity_mw: float = Field(ge=0)
