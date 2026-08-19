"""Utilities for r2x-core."""

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
from .overrides import override_dictionary
from .parser import create_component
from .rules import (
    build_attr_getter,
    build_component_kwargs,
    build_target_fields,
    create_rule_outputs,
    create_target_component,
    evaluate_rule_filter,
    has_output_values,
    resolve_component_type,
    sort_rules_by_dependencies,
    to_attr_source,
)
from .upgrade import (
    UpgradeCoordinator,
    UpgradeStep,
    UpgradeType,
    run_upgrade_step,
    shall_we_upgrade,
)
from .validation import (
    filter_kwargs_by_signatures,
    filter_valid_kwargs,
    validate_file_extension,
    validate_glob_pattern,
)
from .version import UNKNOWN_VERSION, get_package_version, warn_if_persisted_version_newer_than_installed

__all__ = [
    "UNKNOWN_VERSION",
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
    "filter_valid_kwargs",
    "get_fpath",
    "get_package_version",
    "get_r2x_cache_path",
    "has_output_values",
    "iter_components",
    "override_dictionary",
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
