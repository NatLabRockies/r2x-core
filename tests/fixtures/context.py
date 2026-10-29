from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from r2x_core import PluginConfig, PluginContext, Rule, System

FIXTURE_MODEL_MODULES: tuple[str, ...] = (
    "fixtures.source_system",
    "fixtures.target_system",
)


def build_config() -> PluginConfig:
    """Create a PluginConfig pointing at fixture component modules."""
    from r2x_core import PluginConfig

    return PluginConfig(models=FIXTURE_MODEL_MODULES)


def build_plugin_context(
    rules_simple: list[Rule],
    source_system: System,
    target_system: System,
) -> PluginContext:
    from r2x_core import PluginContext

    return PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=build_config(),
        rules=tuple(rules_simple),
        store=None,
    )


@pytest.fixture
def context_example(
    rules_simple: list[Rule],
    source_system: System,
    target_system: System,
) -> PluginContext:
    """PluginContext with populated systems and fixture rules."""
    return build_plugin_context(rules_simple, source_system, target_system)
