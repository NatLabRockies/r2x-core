import pytest

from r2x_core.exceptions import (
    CLIError,
    ComponentCreationError,
    PluginError,
    UpgradeError,
    ValidationError,
)

pytestmark = pytest.mark.core


def test_cli_error():
    """Test CLIError exception."""
    error = CLIError("test error")
    assert str(error) == "test error"


def test_plugin_error():
    """Test PluginError exception."""
    error = PluginError("plugin failed")
    assert str(error) == "plugin failed"


def test_component_creation_error():
    """Test ComponentCreationError exception."""
    error = ComponentCreationError("component failed")
    assert str(error) == "component failed"


def test_upgrade_error():
    """Test UpgradeError exception."""
    error = UpgradeError("upgrade failed")
    assert str(error) == "upgrade failed"


def test_validation_error():
    """Test ValidationError exception."""
    error = ValidationError("validation failed")
    assert str(error) == "validation failed"
