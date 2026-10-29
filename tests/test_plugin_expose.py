"""Tests for @expose_plugin decorator for function-based plugins.

This module validates that the expose_plugin decorator works correctly as a simple
marker for AST-grep discovery.
"""

import pytest
from rust_ok import Ok, Result

from r2x_core import System, expose_plugin
from r2x_core.plugin_config import PluginConfig


class SimpleConfig(PluginConfig):
    """Minimal config for testing."""

    name: str = "test"


pytestmark = pytest.mark.plugin


def test_expose_marks_function():
    """@expose_plugin sets __r2x_exposed__ marker attribute."""

    @expose_plugin
    def my_transform(system: System, config: SimpleConfig) -> Result[System, str]:
        """Test transform."""
        return Ok(system)

    assert hasattr(my_transform, "__r2x_exposed__")
    assert my_transform.__r2x_exposed__ is True


def test_expose_returns_function_unchanged():
    """@expose_plugin returns the function unchanged (no wrapper)."""

    def original_func(system: System, config: SimpleConfig) -> Result[System, str]:
        """Original docstring."""
        return Ok(system)

    decorated_func = expose_plugin(original_func)

    assert decorated_func is original_func
    assert decorated_func.__doc__ == "Original docstring."


def test_expose_rejects_non_callable():
    """@expose_plugin rejects non-callable argument."""
    with pytest.raises(TypeError, match="argument must be callable"):
        expose_plugin("not_a_function")  # type: ignore[arg-type]


def test_expose_preserves_signature():
    """@expose_plugin preserves the original function signature."""

    @expose_plugin
    def typed_func(system: System, config: SimpleConfig) -> Result[System, str]:
        """Test function with types."""
        return Ok(system)

    import inspect

    sig = inspect.signature(typed_func)
    params = list(sig.parameters.keys())
    assert params == ["system", "config"]
    assert sig.return_annotation == Result[System, str]


def test_expose_preserves_docstring():
    """@expose_plugin preserves function docstring."""

    @expose_plugin
    def documented_func(system: System, config: SimpleConfig) -> Result[System, str]:
        """This is a comprehensive docstring.

        It has multiple lines and details about the function.

        Parameters
        ----------
        system : System
            The system to transform
        config : SimpleConfig
            The configuration

        Returns
        -------
        Result[System, str]
            Result containing transformed system or error message
        """
        return Ok(system)

    assert "This is a comprehensive docstring." in documented_func.__doc__  # type: ignore[operator]
    assert "multiple lines" in documented_func.__doc__  # type: ignore[operator]


def test_expose_function_is_callable():
    """Exposed function remains callable."""

    @expose_plugin
    def my_callable_func(system: System, config: SimpleConfig) -> Result[System, str]:
        """Test function."""
        system.name = "modified"
        return Ok(system)

    test_system = System(name="original")
    test_config = SimpleConfig(name="test")
    result = my_callable_func(test_system, test_config)

    assert result.is_ok()
    assert result.unwrap().name == "modified"


def test_expose_with_kwargs_function():
    """@expose_plugin works with functions that accept **kwargs."""

    @expose_plugin
    def flexible_transform(
        system: System,
        config: SimpleConfig,
        **kwargs,
    ) -> Result[System, str]:
        """Transform with flexible arguments."""
        # Just verify kwargs were passed
        if kwargs:
            system.name = f"{system.name}_with_kwargs"
        return Ok(system)

    assert flexible_transform.__r2x_exposed__ is True  # type: ignore[attr-defined]
    test_system = System(name="test")
    test_config = SimpleConfig()
    result = flexible_transform(test_system, test_config, extra_param="extra_value")
    assert result.is_ok()
    assert result.unwrap().name == "test_with_kwargs"


def test_exposed_function_in_real_workflow():
    """End-to-end: expose function and call it directly."""
    from typing import TypeVar

    class MyConfig(PluginConfig):
        suffix: str = "_transformed"

    C = TypeVar("C", bound=MyConfig)

    @expose_plugin
    def transform_system(
        system: System,
        config: C,
    ) -> Result[System, str]:
        """Transform system by appending suffix."""
        system.name = f"{system.name}{config.suffix}"
        return Ok(system)

    # Verify marking
    assert transform_system.__r2x_exposed__ is True  # type: ignore[attr-defined]

    # Call it directly like a user would
    input_system = System(name="my_system")
    config = MyConfig(suffix="_v2")
    result = transform_system(input_system, config)

    assert result.is_ok()
    assert result.unwrap().name == "my_system_v2"
