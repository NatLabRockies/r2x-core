#!/usr/bin/env python3
"""Inspect r2x-core entry points in the active Python environment."""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import entry_points

DEFAULT_GROUP = "r2x_plugin"
HOOKS = (
    "on_validate",
    "on_prepare",
    "on_upgrade",
    "on_build",
    "on_transform",
    "on_translate",
    "on_export",
    "on_cleanup",
)


def implemented_hooks(plugin_cls: type) -> list[str]:
    """Return lifecycle hooks implemented outside the base class."""
    base = None
    try:
        from r2x_core import Plugin

        base = Plugin
    except ImportError:
        pass

    hooks: list[str] = []
    for hook in HOOKS:
        method = getattr(plugin_cls, hook, None)
        if not callable(method):
            continue
        if base is None or getattr(base, hook, None) is not method:
            hooks.append(hook)
    return hooks


def describe_config(plugin_cls: type) -> tuple[str, list[str]]:
    """Return config type and field descriptions for a plugin class."""
    get_config_type = getattr(plugin_cls, "get_config_type", None)
    config_type = get_config_type() if callable(get_config_type) else None
    if config_type is None:
        return "<unknown>", []

    fields = getattr(config_type, "model_fields", {})
    descriptions = [f"{name}: {field.annotation!r}" for name, field in fields.items()]
    return config_type.__name__, descriptions


def main() -> int:
    """Enumerate and import entry points from the selected group."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", default=DEFAULT_GROUP)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    points = sorted(entry_points(group=args.group), key=lambda point: point.name)
    if not points:
        print(f"No entry points found for group '{args.group}'.")
        return 0

    failures = 0
    print(f"Discovered plugins in group '{args.group}':")
    for point in points:
        try:
            target = point.load()
        except Exception as exc:  # discovery must report one bad plugin and continue
            failures += 1
            print(f"- {point.name} ({point.value}): FAILED: {exc}")
            if args.verbose:
                import traceback

                traceback.print_exc()
            continue

        print(f"- {point.name}: {point.value}")
        if not isinstance(target, type):
            print(f"    target: {type(target).__name__}, not a class")
            continue
        config_name, fields = describe_config(target)
        print(f"    config: {config_name}")
        for field in fields:
            print(f"      - {field}")
        hooks = implemented_hooks(target)
        print(f"    hooks: {', '.join(hooks) if hooks else '<none>'}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
