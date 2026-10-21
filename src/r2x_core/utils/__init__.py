"""Utilities for r2x-core with lazy imports for the public utility API."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .export import components_to_records, export_components_to_csv
    from .files import (
        audit_file,
        backup_folder,
        get_fpath,
        get_r2x_cache_path,
        resolve_glob_pattern,
        resolve_path,
    )
    from .iteration import iter_components
    from .overrides import merge_with_overrides
    from .parser import create_component
    from .rules import (
        RuleOutputs,
        build_attr_getter,
        build_component_kwargs,
        build_target_fields,
        create_rule_outputs,
        create_target_component,
        evaluate_rule_filter,
        resolve_component_type,
        sort_rules_by_dependencies,
        to_attr_source,
    )
    from .upgrade import UpgradeCoordinator, UpgradeStep, UpgradeType, run_upgrade_step, shall_we_upgrade
    from .validation import (
        filter_kwargs_by_signatures,
        filter_kwargs_for,
        validate_file_extension,
        validate_glob_pattern,
    )
    from .version import UNKNOWN_VERSION, get_package_version, warn_if_persisted_version_newer_than_installed

LAZY_IMPORTS: dict[str, str] = {
    "UNKNOWN_VERSION": ".version",
    "RuleOutputs": ".rules",
    "UpgradeCoordinator": ".upgrade",
    "UpgradeStep": ".upgrade",
    "UpgradeType": ".upgrade",
    "audit_file": ".files",
    "backup_folder": ".files",
    "build_attr_getter": ".rules",
    "build_component_kwargs": ".rules",
    "build_target_fields": ".rules",
    "components_to_records": ".export",
    "create_component": ".parser",
    "create_rule_outputs": ".rules",
    "create_target_component": ".rules",
    "evaluate_rule_filter": ".rules",
    "export_components_to_csv": ".export",
    "filter_kwargs_by_signatures": ".validation",
    "filter_kwargs_for": ".validation",
    "get_fpath": ".files",
    "get_package_version": ".version",
    "get_r2x_cache_path": ".files",
    "iter_components": ".iteration",
    "merge_with_overrides": ".overrides",
    "resolve_component_type": ".rules",
    "resolve_glob_pattern": ".files",
    "resolve_path": ".files",
    "run_upgrade_step": ".upgrade",
    "shall_we_upgrade": ".upgrade",
    "sort_rules_by_dependencies": ".rules",
    "to_attr_source": ".rules",
    "validate_file_extension": ".validation",
    "validate_glob_pattern": ".validation",
    "warn_if_persisted_version_newer_than_installed": ".version",
}


def __getattr__(name: str) -> object:
    """Lazily import and cache public utility attributes on first access."""
    try:
        module_path = LAZY_IMPORTS[name]
    except KeyError:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg) from None

    import importlib

    mod = importlib.import_module(module_path, __package__)
    attr = getattr(mod, name)
    globals()[name] = attr
    return attr


__all__ = [
    "UNKNOWN_VERSION",
    "RuleOutputs",
    "UpgradeCoordinator",
    "UpgradeStep",
    "UpgradeType",
    "audit_file",
    "backup_folder",
    "build_attr_getter",
    "build_component_kwargs",
    "build_target_fields",
    "components_to_records",
    "create_component",
    "create_rule_outputs",
    "create_target_component",
    "evaluate_rule_filter",
    "export_components_to_csv",
    "filter_kwargs_by_signatures",
    "filter_kwargs_for",
    "get_fpath",
    "get_package_version",
    "get_r2x_cache_path",
    "iter_components",
    "merge_with_overrides",
    "resolve_component_type",
    "resolve_glob_pattern",
    "resolve_path",
    "run_upgrade_step",
    "shall_we_upgrade",
    "sort_rules_by_dependencies",
    "to_attr_source",
    "validate_file_extension",
    "validate_glob_pattern",
    "warn_if_persisted_version_newer_than_installed",
]
