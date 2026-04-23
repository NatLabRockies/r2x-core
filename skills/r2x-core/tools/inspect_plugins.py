#!/usr/bin/env python3
r"""Enumerate r2x-core plugins discoverable in the active environment.

Walks the ``r2x_plugin`` entry-point group, imports each target, and reports
its resolved ``PluginConfig`` subclass (with declared fields) plus the
lifecycle hooks the plugin actually implements.

Examples
--------
uvx --from python --with r2x-core python \\
    src/skills/r2x-core/tools/inspect_plugins.py

uvx --from python --with r2x-core python \\
    src/skills/r2x-core/tools/inspect_plugins.py --group r2x_plugin --verbose
"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import entry_points

DEFAULT_GROUP = "r2x_plugin"

LIFECYCLE_HOOKS: tuple[str, ...] = (
    "on_validate",
    "on_prepare",
    "on_build",
    "on_transform",
    "on_translate",
    "on_export",
    "on_cleanup",
)


def implemented_hooks(plugin_cls: type) -> list[str]:
    """Return a list of lifecycle hooks implemented by the plugin class."""
    base_hook_owners: dict[str, object | None] = dict.fromkeys(LIFECYCLE_HOOKS)
    plugin_base: type | None
    try:
        from r2x_core import Plugin as _Plugin

        plugin_base = _Plugin
    except Exception:
        plugin_base = None

    if plugin_base is not None:
        for hook in LIFECYCLE_HOOKS:
            base_hook_owners[hook] = getattr(plugin_base, hook, None)

    out: list[str] = []
    for hook in LIFECYCLE_HOOKS:
        impl = getattr(plugin_cls, hook, None)
        if impl is None:
            continue
        if base_hook_owners[hook] is None:
            out.append(hook)
            continue
        if impl is not base_hook_owners[hook]:
            out.append(hook)
    return out


def describe_config(plugin_cls: type) -> tuple[str, list[str]]:
    """Return a human-readable description of the plugin's config type, as well as a list of its fields."""
    config_type = getattr(plugin_cls, "get_config_type", lambda: None)()
    if config_type is None:
        return "<unknown>", []

    fields: list[str] = []
    model_fields = getattr(config_type, "model_fields", None)
    if model_fields:
        for name, info in model_fields.items():
            annotation = getattr(info, "annotation", "?")
            ann_repr = getattr(annotation, "__name__", repr(annotation))
            fields.append(f"{name}: {ann_repr}")
    return config_type.__name__, fields


def main() -> int:
    """Parse arguments, discover plugins via entry points, and print a report."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group", default=DEFAULT_GROUP, help=f"Entry-point group to scan (default: {DEFAULT_GROUP})"
    )
    parser.add_argument("--verbose", action="store_true", help="Print full traceback on import errors")
    args = parser.parse_args()

    eps = entry_points(group=args.group)
    if not eps:
        print(f"No entry points found for group '{args.group}'.")
        return 0

    print(f"Discovered plugins in group '{args.group}':")
    failures = 0
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            target = ep.load()
        except Exception as exc:
            failures += 1
            print(f"- {ep.name} ({ep.value}): FAILED to import: {exc!r}")
            if args.verbose:
                import traceback

                traceback.print_exc()
            continue

        if not isinstance(target, type):
            print(f"- {ep.name} ({ep.value}): not a class, got {type(target).__name__}")
            continue

        config_name, config_fields = describe_config(target)
        hooks = implemented_hooks(target)
        print(f"- {ep.name}: {target.__module__}.{target.__name__}")
        print(f"    config: {config_name}")
        for field in config_fields:
            print(f"      - {field}")
        print(f"    hooks: {', '.join(hooks) if hooks else '<none>'}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
