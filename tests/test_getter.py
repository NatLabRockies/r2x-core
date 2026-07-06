"""Tests for rule registry getter decorator.

This module validates that the getter decorator works correctly with all usage patterns:
1. @getter - without parentheses, uses function name as registry key
2. @getter() - with empty parentheses, uses function name as registry key
3. @getter(name="custom") - with name kwarg, uses custom name as registry key
"""

import pytest


def test_getter_without_parentheses_registers_function():
    """@getter without parentheses registers function with its name."""
    from r2x_core.getters import GETTER_REGISTRY, getter

    @getter
    def my_test_getter(comp, *, context):
        _ = context
        return "test"

    assert "my_test_getter" in GETTER_REGISTRY
    assert GETTER_REGISTRY["my_test_getter"] is my_test_getter


def test_getter_with_empty_parentheses_registers_function():
    """@getter() with empty parentheses registers function with its name."""
    from r2x_core.getters import GETTER_REGISTRY, getter

    @getter()
    def my_empty_paren_getter(comp, *, context):
        _ = context
        return "test"

    assert "my_empty_paren_getter" in GETTER_REGISTRY
    assert GETTER_REGISTRY["my_empty_paren_getter"] is my_empty_paren_getter


def test_getter_with_custom_name_registers_with_that_name():
    """@getter(name="custom") registers function with custom name."""
    from r2x_core.getters import GETTER_REGISTRY, getter

    @getter(name="custom_getter_name")
    def some_function(comp, *, context):
        _ = context
        return "test"

    assert "custom_getter_name" in GETTER_REGISTRY
    assert GETTER_REGISTRY["custom_getter_name"] is some_function


def test_getter_first_arg_with_name_kwarg_raises_error():
    """Passing callable as first arg with name kwarg raises error."""
    from r2x_core.getters import getter

    def my_func(comp, *, context):
        _ = context
        return "test"

    with pytest.raises(TypeError, match="Cannot specify 'name' when using @getter without parentheses"):
        getter(my_func, name="custom")


def test_getter_with_parentheses_without_name_uses_function_name():
    """@getter() with parentheses but no name uses function name."""
    from r2x_core.getters import GETTER_REGISTRY, getter

    @getter()
    def function_with_parens(comp, *, context):
        _ = context
        return "test"

    assert "function_with_parens" in GETTER_REGISTRY


def test_getter_rejects_non_callable_first_argument():
    """@getter rejects non-callable as first positional argument."""
    from r2x_core.getters import getter

    with pytest.raises(TypeError, match="first argument must be callable or None"):
        getter("not_a_function")  # type: ignore[arg-type]


def test_getter_function_is_returned_unchanged():
    """@getter returns the function unchanged (no wrapper)."""
    from r2x_core.getters import getter

    def original_func(comp, *, context):
        """Original docstring."""
        _ = context
        return "result"

    decorated_func = getter(original_func)

    assert decorated_func is original_func
    assert decorated_func.__doc__ == "Original docstring."
    assert decorated_func(None, context=None) == "result"


def test_getter_with_empty_parentheses_returns_function_unchanged():
    """@getter() returns the decorated function unchanged."""
    from r2x_core.getters import getter

    def original_func_empty_parens(comp, *, context):
        """Original docstring."""
        _ = context
        return "result"

    decorator = getter()
    decorated_func = decorator(original_func_empty_parens)

    assert decorated_func is original_func_empty_parens
    assert decorated_func.__doc__ == "Original docstring."


def test_getter_with_custom_name_returns_function_unchanged():
    """@getter(name="...") returns the decorated function unchanged."""
    from r2x_core.getters import getter

    def original_func_with_custom_name(comp, *, context):
        """Original docstring."""
        _ = context
        return "result"

    decorator = getter(name="custom_name_test")
    decorated_func = decorator(original_func_with_custom_name)

    assert decorated_func is original_func_with_custom_name


def test_getter_prevents_duplicate_registration():
    """@getter raises error if same name registered twice."""
    from r2x_core.getters import GETTER_REGISTRY, getter

    # Clear registry for this test
    original_entries = GETTER_REGISTRY.copy()
    GETTER_REGISTRY.clear()

    try:

        @getter
        def duplicate_name(comp, *, context):
            _ = context
            return "first"

        with pytest.raises(ValueError, match="Getter 'duplicate_name' already registered"):

            @getter
            def duplicate_name(comp, *, context):
                _ = context
                return "second"

    finally:
        # Restore original registry
        GETTER_REGISTRY.clear()
        GETTER_REGISTRY.update(original_entries)


def test_getter_with_custom_name_prevents_duplicate():
    """@getter(name="...") raises error if same custom name registered twice."""
    from r2x_core.getters import GETTER_REGISTRY, getter

    original_entries = GETTER_REGISTRY.copy()
    GETTER_REGISTRY.clear()

    try:

        @getter(name="same_custom_name")
        def first_func(comp, *, context):
            _ = context
            return "first"

        with pytest.raises(ValueError, match="Getter 'same_custom_name' already registered"):

            @getter(name="same_custom_name")
            def second_func(comp, *, context):
                _ = context
                return "second"

    finally:
        GETTER_REGISTRY.clear()
        GETTER_REGISTRY.update(original_entries)


def test_getter_callable_with_result_type():
    """@getter decorated function returns Result type correctly."""
    from rust_ok import Ok

    from r2x_core.getters import GETTER_REGISTRY, getter

    @getter
    def test_getter_func(comp, *, context):
        _ = context
        return Ok(42)

    # Access the registered function to get the correct type
    getter_func = GETTER_REGISTRY["test_getter_func"]
    result = getter_func(None, context=None)
    assert result.is_ok()
    assert result.unwrap() == 42


def test_preprocess_rule_getters_passes_through_callables():
    """Callables in getter dict remain unchanged."""
    from r2x_core.getters import _preprocess_rule_getters

    def compute(comp, *, context):
        _ = context
        return "value"

    result = _preprocess_rule_getters({"field": compute})
    assert result.is_ok()
    resolved = result.unwrap()
    assert resolved["field"] is compute


def test_preprocess_rule_getters_resolves_registry_names():
    """String referencing registered getter resolves to callable."""
    from rust_ok import Ok

    from r2x_core.getters import GETTER_REGISTRY, _preprocess_rule_getters, getter

    unique_name = "registry_lookup_getter"

    if unique_name not in GETTER_REGISTRY:

        @getter(name=unique_name)
        def registry_lookup_getter(comp, *, context):
            _ = context
            return Ok("from_registry")

    result = _preprocess_rule_getters({"field": unique_name})
    assert result.is_ok()
    resolved = result.unwrap()
    assert resolved["field"] is GETTER_REGISTRY[unique_name]


def test_preprocess_rule_getters_logs_missing_registry_name(caplog):
    """Unregistered getter name emits a warning when falling back to attr lookup."""
    from r2x_core.getters import _preprocess_rule_getters

    caplog.set_level("WARNING")
    result = _preprocess_rule_getters({"field": "missing_registry_getter"})

    assert result.is_ok()
    assert any("missing_registry_getter" in record.message for record in caplog.records)


def test_preprocess_rule_getters_builds_attr_getter():
    """String path not in registry becomes attribute getter."""
    from r2x_core.getters import _preprocess_rule_getters

    class Child:
        value = 123

    class Parent:
        child = Child()

    result = _preprocess_rule_getters({"field": "child.value"})
    assert result.is_ok()
    getter_fn = result.unwrap()["field"]
    out = getter_fn(Parent(), context=None)
    assert out.is_ok()
    assert out.unwrap() == 123


def test_preprocess_rule_getters_rejects_invalid_types():
    """Invalid getter types raise a TypeError result."""
    from r2x_core.getters import _preprocess_rule_getters

    result = _preprocess_rule_getters({"field": 123})
    assert result.is_err()
    assert isinstance(result.err(), TypeError)


def test_resolve_getter_public_api_registers_and_resolves():
    """The public getter resolver should resolve registry names."""
    from rust_ok import Ok

    from r2x_core import getter, resolve_getter
    from r2x_core.getters import GETTER_REGISTRY

    getter_name = "public_api_resolve_getter"
    if getter_name not in GETTER_REGISTRY:

        @getter(name=getter_name)
        def public_api_resolve_getter(comp, *, context):
            _ = comp
            _ = context
            return Ok("resolved")

    result = resolve_getter(getter_name)
    assert result.is_ok()
    resolved = result.unwrap()
    assert resolved is GETTER_REGISTRY[getter_name]


def test_resolve_getter_callable_passthrough():
    """resolve_getter returns callable inputs unchanged."""
    from r2x_core import resolve_getter

    def passthrough_getter(comp, *, context):
        _ = comp
        _ = context
        return "ok"

    result = resolve_getter(passthrough_getter)
    assert result.is_ok()
    assert result.unwrap() is passthrough_getter
