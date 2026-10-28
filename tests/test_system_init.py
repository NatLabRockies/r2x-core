"""Tests for System.__init__ flexible signatures."""

import pytest

from r2x_core.system import System

pytestmark = pytest.mark.system


def test_system_default():
    """Test System() with all defaults."""
    system = System()
    assert not system.name
    assert not system.base_power


def test_system_positional_base_only():
    """Test System(200.0) with positional system_base_power."""
    system = System(200.0)
    assert system.base_power == 200.0


def test_system_positional_base_with_name():
    """Test System(200.0, name='Test')."""
    system = System(200.0, name="TestSystem")
    assert system.base_power == 200.0
    assert system.name == "TestSystem"


def test_system_name_only():
    """Test System(name='Test') with name keyword."""
    system = System(name="TestSystem")
    assert system.name == "TestSystem"
    assert not system.base_power


def test_system_both_keywords():
    """Test System(name='Test', system_base_power=200)."""
    system = System(name="TestSystem", system_base=200.0)
    assert system.base_power == 200.0
    assert system.name == "TestSystem"


def test_system_keywords_reversed_order():
    """Test System(system_base_power=200, name='Test')."""
    system = System(system_base=200.0, name="TestSystem")
    assert system.base_power == 200.0
    assert system.name == "TestSystem"


def test_system_with_description():
    """Test System with description."""
    system = System(150.0, name="TestSystem", description="A test system")
    assert system.base_power == 150.0
    assert system.name == "TestSystem"
    assert system.description == "A test system"


def test_system_with_auto_add_composed():
    """Test System with auto_add_composed_components."""
    system = System(name="TestSystem", auto_add_composed_components=False)
    assert not system.base_power
    assert system.name == "TestSystem"


def test_system_accepts_infrasys_kwargs():
    """System forwards Infrasys System kwargs such as uuid and description."""
    import uuid

    system_uuid = uuid.uuid4()
    system = System(
        name="TestSystem",
        description="A test system",
        auto_add_composed_components=False,
        uuid=system_uuid,
    )

    assert system.description == "A test system"
    assert system.uuid == system_uuid
    assert system.auto_add_composed_components is False
