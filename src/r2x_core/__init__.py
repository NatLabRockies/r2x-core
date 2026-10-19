"""R2X Core public API with lazy imports for fast CLI/import startup.

Eager imports are kept under ``if TYPE_CHECKING`` so IDEs (pyright, mypy)
see the full API surface for autocompletion and type checking. At runtime,
attributes are imported on first access via ``__getattr__`` and cached in
the module globals, dropping cold-import from ~1.4 s to ~0.17 s.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import TYPE_CHECKING

from loguru import logger
from rust_ok import Err, Ok, Result, is_err, is_ok

from . import h5_readers

TIMESERIES_DIR = "R2X_TIMESERIES_DIR"

logger.disable("r2x_core")

__version__ = version("r2x_core")

# ── Eager for IDEs / type checkers (dead code at runtime) ──────────
if TYPE_CHECKING:
    from .datafile import (
        CategoryMatchSpec,
        ColumnAddSpec,
        ColumnAssignmentSource,
        ColumnConcatSpec,
        ColumnMultiplySpec,
        ColumnPredicate,
        ConditionalAssignment,
        DataFile,
        DataValidation,
        FileInfo,
        GroupedFillSpec,
        JSONProcessing,
        LiteralAssignmentSource,
        ReaderConfig,
        RejectRowsSpec,
        RequiredColumnValues,
        SafeDivideSpec,
        SplitColumnSpec,
        StringCategorizationSpec,
        TabularProcessing,
        UnpivotAllExcept,
        WeightedMeanSpec,
    )
    from .exceptions import (
        CLIError,
        ComponentCreationError,
        PluginError,
        UpgradeError,
        ValidationError,
    )
    from .file_types import FileFormat, H5Format
    from .getters import getter, resolve_getter
    from .grid import expand_keyed_grid
    from .plugin_base import Plugin
    from .plugin_config import PluginConfig, PluginConfigAsset
    from .plugin_context import PluginContext
    from .plugin_expose import expose_plugin
    from .prepared_tables import (
        AsOfJoinSpec,
        FileMapping,
        PreparedTable,
        PreparedTableError,
        SelectFirst,
        TableJoin,
        prepare_table_frames,
    )
    from .reader import DataReader
    from .result import RuleResult, TranslationResult
    from .rules import (
        ComponentSource,
        ComponentTarget,
        DatasetSource,
        FixedMappingRoute,
        MappingSelection,
        OwnedSupplementalTarget,
        Rule,
        RuleFilter,
        RuleMapping,
        RulePlanDocument,
        RuleStage,
        SelectedMappingRoute,
        SupplementalAttributeRule,
        TimeSeriesTarget,
    )
    from .rules_executor import (
        RuleExecutionError,
        RulePlan,
        apply_mapping_records,
        apply_rules_to_context,
        apply_single_rule,
        attach_rule_outputs,
        build_rule_outputs,
        resolve_supplemental_class,
    )
    from .sources import (
        CalendarSource,
        ConfigRecordsSource,
        FirstPresentSource,
        SystemFieldProjection,
        SystemFrameSource,
        TimeSeriesProjection,
    )
    from .store import DataStore
    from .system import System
    from .time_series import replace_single_time_series, transfer_time_series_metadata
    from .units import HasPerUnit, HasUnits, Unit, UnitSystem, get_unit_system, set_unit_system
    from .utils import (
        UpgradeStep,
        UpgradeType,
        components_to_records,
        create_component,
        export_components_to_csv,
        run_upgrade_step,
    )
    from .versioning import (
        GitVersioningStrategy,
        SemanticVersioningStrategy,
        VersionReader,
        VersionStrategy,
    )

# ── Lazy at runtime ─────────────────────────────────────────────────
_LAZY_IMPORTS: dict[str, str] = {
    "ColumnAddSpec": ".datafile",
    "ColumnAssignmentSource": ".datafile",
    "ColumnConcatSpec": ".datafile",
    "ColumnMultiplySpec": ".datafile",
    "ColumnPredicate": ".datafile",
    "CategoryMatchSpec": ".datafile",
    "ConditionalAssignment": ".datafile",
    "DataFile": ".datafile",
    "DataValidation": ".datafile",
    "FileInfo": ".datafile",
    "GroupedFillSpec": ".datafile",
    "JSONProcessing": ".datafile",
    "LiteralAssignmentSource": ".datafile",
    "ReaderConfig": ".datafile",
    "RejectRowsSpec": ".datafile",
    "RequiredColumnValues": ".datafile",
    "SafeDivideSpec": ".datafile",
    "SplitColumnSpec": ".datafile",
    "StringCategorizationSpec": ".datafile",
    "TabularProcessing": ".datafile",
    "UnpivotAllExcept": ".datafile",
    "WeightedMeanSpec": ".datafile",
    "CLIError": ".exceptions",
    "ComponentCreationError": ".exceptions",
    "PluginError": ".exceptions",
    "UpgradeError": ".exceptions",
    "ValidationError": ".exceptions",
    "FileFormat": ".file_types",
    "H5Format": ".file_types",
    "expand_keyed_grid": ".grid",
    "getter": ".getters",
    "resolve_getter": ".getters",
    "Plugin": ".plugin_base",
    "PluginConfig": ".plugin_config",
    "PluginConfigAsset": ".plugin_config",
    "PluginContext": ".plugin_context",
    "AsOfJoinSpec": ".prepared_tables",
    "FileMapping": ".prepared_tables",
    "PreparedTable": ".prepared_tables",
    "PreparedTableError": ".prepared_tables",
    "SelectFirst": ".prepared_tables",
    "TableJoin": ".prepared_tables",
    "prepare_table_frames": ".prepared_tables",
    "expose_plugin": ".plugin_expose",
    "ProvenanceBuilder": ".provenance",
    "ProvenanceInfo": ".provenance",
    "SourceProvenance": ".provenance",
    "DataReader": ".reader",
    "RuleResult": ".result",
    "RuleExecutionError": ".rules_executor",
    "RulePlan": ".rules_executor",
    "TranslationResult": ".result",
    "ComponentSource": ".rules",
    "ComponentTarget": ".rules",
    "DatasetSource": ".rules",
    "FixedMappingRoute": ".rules",
    "MappingSelection": ".rules",
    "OwnedSupplementalTarget": ".rules",
    "Rule": ".rules",
    "RuleFilter": ".rules",
    "RuleMapping": ".rules",
    "RulePlanDocument": ".rules",
    "RuleStage": ".rules",
    "SelectedMappingRoute": ".rules",
    "SupplementalAttributeRule": ".rules",
    "TimeSeriesTarget": ".rules",
    "apply_mapping_records": ".rules_executor",
    "apply_rules_to_context": ".rules_executor",
    "apply_single_rule": ".rules_executor",
    "attach_rule_outputs": ".rules_executor",
    "build_rule_outputs": ".rules_executor",
    "resolve_supplemental_class": ".rules_executor",
    "CalendarSource": ".sources",
    "ConfigRecordsSource": ".sources",
    "FirstPresentSource": ".sources",
    "SystemFieldProjection": ".sources",
    "SystemFrameSource": ".sources",
    "TimeSeriesProjection": ".sources",
    "DataStore": ".store",
    "System": ".system",
    "replace_single_time_series": ".time_series",
    "transfer_time_series_metadata": ".time_series",
    "HasPerUnit": ".units",
    "HasUnits": ".units",
    "Unit": ".units",
    "UnitSystem": ".units",
    "get_unit_system": ".units",
    "set_unit_system": ".units",
    "UpgradeStep": ".utils",
    "UpgradeType": ".utils",
    "components_to_records": ".utils",
    "create_component": ".utils",
    "export_components_to_csv": ".utils",
    "run_upgrade_step": ".utils",
    "GitVersioningStrategy": ".versioning",
    "SemanticVersioningStrategy": ".versioning",
    "VersionReader": ".versioning",
    "VersionStrategy": ".versioning",
}


def __getattr__(name: str) -> object:
    """Lazily import and cache public API attributes on first access."""
    try:
        module_path = _LAZY_IMPORTS[name]
    except KeyError:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg) from None

    import importlib

    mod = importlib.import_module(module_path, __package__)
    attr = getattr(mod, name)
    # Cache in module globals so subsequent accesses are O(1)
    globals()[name] = attr
    return attr


# ── Public API ──────────────────────────────────────────────────────
__all__ = [
    "AsOfJoinSpec",
    "CLIError",
    "CalendarSource",
    "CategoryMatchSpec",
    "ColumnAddSpec",
    "ColumnAssignmentSource",
    "ColumnConcatSpec",
    "ColumnMultiplySpec",
    "ColumnPredicate",
    "ComponentCreationError",
    "ComponentSource",
    "ComponentTarget",
    "ConditionalAssignment",
    "ConfigRecordsSource",
    "DataFile",
    "DataReader",
    "DataStore",
    "DataValidation",
    "DatasetSource",
    "Err",
    "FileFormat",
    "FileInfo",
    "FileMapping",
    "FirstPresentSource",
    "FixedMappingRoute",
    "GitVersioningStrategy",
    "GroupedFillSpec",
    "H5Format",
    "HasPerUnit",
    "HasUnits",
    "JSONProcessing",
    "LiteralAssignmentSource",
    "MappingSelection",
    "Ok",
    "OwnedSupplementalTarget",
    "Plugin",
    "PluginConfig",
    "PluginConfigAsset",
    "PluginContext",
    "PluginError",
    "PreparedTable",
    "PreparedTableError",
    "ReaderConfig",
    "RejectRowsSpec",
    "RequiredColumnValues",
    "Result",
    "Rule",
    "RuleExecutionError",
    "RuleFilter",
    "RuleMapping",
    "RulePlan",
    "RulePlanDocument",
    "RuleResult",
    "RuleStage",
    "SafeDivideSpec",
    "SelectFirst",
    "SelectedMappingRoute",
    "SemanticVersioningStrategy",
    "SplitColumnSpec",
    "StringCategorizationSpec",
    "SupplementalAttributeRule",
    "System",
    "SystemFieldProjection",
    "SystemFrameSource",
    "TableJoin",
    "TabularProcessing",
    "TimeSeriesProjection",
    "TimeSeriesTarget",
    "TranslationResult",
    "Unit",
    "UnitSystem",
    "UnpivotAllExcept",
    "UpgradeError",
    "UpgradeStep",
    "UpgradeType",
    "ValidationError",
    "VersionReader",
    "VersionStrategy",
    "WeightedMeanSpec",
    "apply_mapping_records",
    "apply_rules_to_context",
    "apply_single_rule",
    "attach_rule_outputs",
    "build_rule_outputs",
    "components_to_records",
    "create_component",
    "expand_keyed_grid",
    "export_components_to_csv",
    "expose_plugin",
    "get_unit_system",
    "getter",
    "h5_readers",
    "is_err",
    "is_ok",
    "prepare_table_frames",
    "replace_single_time_series",
    "resolve_getter",
    "resolve_supplemental_class",
    "run_upgrade_step",
    "set_unit_system",
    "transfer_time_series_metadata",
]
