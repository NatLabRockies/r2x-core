"""System component traversal helpers."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrasys import Component

    from .. import System


def iter_components(
    system: System,
    *,
    class_type: type[Component],
    filter_func: Callable[[Component], bool] | None = None,
) -> Generator[Component, None, None]:
    """Yield all system components of a specific type, optionally filtered."""
    yield from system.get_components(class_type, filter_func=filter_func)
