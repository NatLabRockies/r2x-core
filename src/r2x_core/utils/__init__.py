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
    create_target_component,
    evaluate_rule_filter,
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

__all__ = [
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
    "create_target_component",
    "evaluate_rule_filter",
    "export_components_to_csv",
    "filter_kwargs_by_signatures",
    "filter_valid_kwargs",
    "get_fpath",
    "get_r2x_cache_path",
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
]
