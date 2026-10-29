"""Verify the saved artifact in a fresh Python process."""

from math import isclose

from tutorial_model import Generator

from r2x_core import System

system = System.from_json("output/system.json")
generators = sorted(system.get_components(Generator), key=lambda item: item.name)
assert [item.name for item in generators] == ["Alpha", "Bravo"]
assert isclose(sum(item.capacity_mw for item in generators), 165)
for generator in generators:
    print(f"{generator.name}: {generator.capacity_mw:.1f} MW")
