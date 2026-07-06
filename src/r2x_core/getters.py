"""Registry for rules getters."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeAlias, TypeVar

from loguru import logger
from rust_ok import Err, Ok

if TYPE_CHECKING:
    from rust_ok import Result


GetterFunc: TypeAlias = Callable[..., Any]


F = TypeVar("F", bound=GetterFunc)

GETTER_REGISTRY: dict[str, GetterFunc] = {}


def getter(func: F | None = None, *, name: str | None = None) -> F | Callable[[F], F]:
    """Decorate a callable getter by name.

    Can be used in three ways:
    1. @getter - Uses function name as registry key
    2. @getter() - Uses function name as registry key (parentheses optional)
    3. @getter(name="custom_name") - Uses custom name as registry key (name kwarg required when parentheses used)

    When using parentheses, the name parameter must be provided as a keyword argument.
    """

    def _decorator(f: F) -> F:
        """Decorate function."""
        key = name or f.__name__
        if key in GETTER_REGISTRY:
            raise ValueError(f"Getter '{key}' already registered")
        GETTER_REGISTRY[key] = f
        logger.debug("Registered getter '{}'", key)
        return f

    if func is not None:
        if not callable(func):
            raise TypeError(f"getter() first argument must be callable or None, got {type(func).__name__}")
        if name is not None:
            raise TypeError(
                "Cannot specify 'name' when using @getter without parentheses. Use @getter(name='...') instead"
            )
        return _decorator(func)

    return _decorator


def resolve_getter(getter: GetterFunc | str) -> Result[GetterFunc, TypeError]:
    """Resolve a getter reference to a callable."""
    from .utils import build_attr_getter

    if callable(getter):
        return Ok(getter)
    if getter in GETTER_REGISTRY:
        return Ok(GETTER_REGISTRY[getter])
    if "." not in getter:
        logger.warning(
            "Getter '{}' not found in registry; ensure it is imported before loading rules. Falling back to attribute lookup.",
            getter,
        )
    return Ok(build_attr_getter(getter.split(".")))


def _preprocess_rule_getters(getters_dict: dict[str, Any]) -> Result[dict[str, Any], TypeError]:
    """Convert string-based getters in a rule into callables."""
    resolved: dict[str, GetterFunc] = {}
    for field, getter in getters_dict.items():
        if callable(getter):
            resolved[field] = getter
        elif isinstance(getter, str):
            result = resolve_getter(getter)
            if result.is_err():
                return Err(result.err())
            resolved_getter = result.ok()
            if resolved_getter is None:
                return Err(TypeError(f"Getter resolution returned no callable for '{field}'"))
            resolved[field] = resolved_getter
        else:
            return Err(TypeError(f"Invalid getter type for '{field}': {type(getter).__name__}"))
    return Ok(resolved)
