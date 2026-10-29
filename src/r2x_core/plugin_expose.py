"""Expose decorator for function-based plugins.

The @expose_plugin decorator marks functions as plugin entry points for CLI discovery.
It is a zero-overhead marker that does not modify function behavior.

Example:
    @expose_plugin
    def break_generators(system: System, config: BreakGensConfig) -> Result[System, str]:
        ...
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def expose_plugin(func: F) -> F:
    """Mark a function as an exposed plugin entry point.

    This is a zero-overhead marker decorator for AST-grep discovery.
    The function is returned unchanged with __r2x_exposed__ set to True.

    Parameters
    ----------
    func : callable
        The function to decorate

    Returns
    -------
    callable
        The original function, unchanged

    Raises
    ------
    TypeError
        If func is not callable

    Examples
    --------
    >>> from r2x_core import expose_plugin, System, PluginConfig
    >>> from rust_ok import Ok, Result

    >>> class MyConfig(PluginConfig):
    ...     threshold: int = 5

    >>> @expose_plugin
    ... def my_transform(system: System, config: MyConfig) -> Result[System, str]:
    ...     return Ok(system)

    >>> my_transform.__r2x_exposed__
    True
    """
    if not callable(func):
        msg = f"expose_plugin() argument must be callable, got {type(func).__name__}"
        raise TypeError(msg)

    func.__r2x_exposed__ = True
    return func
