"""R2X Core public API with lazy imports for fast CLI/import startup.

Eager imports are kept under ``if TYPE_CHECKING`` so IDEs and the type checker
see the full API surface for autocompletion and type checking. At runtime,
attributes are imported on first access via ``__getattr__`` and cached in
module globals.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import TYPE_CHECKING

from loguru import logger
from rust_ok import Err, Ok, Result, is_err, is_ok

TIMESERIES_DIR = "R2X_TIMESERIES_DIR"

logger.disable("r2x_core")

__version__ = version("r2x_core")

# ── Eager for IDEs / type checkers (dead code at runtime) ──────────
if TYPE_CHECKING:
    from .datafile import DataFile, FileInfo, ReaderConfig
    from .exceptions import (
        CLIError,
        ComponentCreationError,
        PluginError,
        UpgradeError,
        ValidationError,
    )
    from .file_reader import (
        ArraySource,
        DecodedSource,
        DecodedSources,
        DocumentSource,
        FileReader,
        ProcessingSource,
        SourceProcessor,
        TabularProcessor,
        TabularSource,
    )
    from .getters import getter, resolve_getter
    from .h5_adapter import H5PyFileReader, H5Reader
    from .ingestion import build_system
    from .models import (
        ColumnTimeAxis,
        ComponentInstruction,
        ComponentOwner,
        ComponentReference,
        JSONProcessing,
        RegularTimeAxis,
        SplitColumnSpec,
        SupplementalAttributeInstruction,
        TabularProcessing,
        TimeSeriesInstruction,
    )
    from .plugin_base import Plugin
    from .plugin_config import PluginConfig
    from .plugin_context import PluginContext
    from .plugin_expose import expose_plugin
    from .reader import DataReader
    from .result import RuleResult, TranslationResult
    from .rules import (
        AllOfFilter,
        AnyOfFilter,
        FieldFilter,
        GetterFilter,
        Rule,
        RuleFilter,
        SupplementalAttributeRule,
    )
    from .rules_executor import (
        apply_rules_to_context,
        apply_single_rule,
        attach_rule_outputs,
        resolve_supplemental_class,
    )
    from .store import DataStore
    from .system import System
    from .time_series import replace_single_time_series, transfer_time_series_metadata
    from .types import FileProcessing, FileRequirement, FileType
    from .units import HasPerUnit, HasUnits, Unit, UnitSystem, get_unit_system, set_unit_system
    from .utils.export import components_to_records, export_components_to_csv
    from .utils.upgrade import UpgradeStep, UpgradeType, run_upgrade_step
    from .versioning import (
        GitVersioningStrategy,
        SemanticVersioningStrategy,
        VersionReader,
        VersionStrategy,
    )

# ── Lazy at runtime ─────────────────────────────────────────────────
LAZY_IMPORTS: dict[str, str] = {
    "DataFile": ".datafile",
    "DataReader": ".reader",
    "FileInfo": ".datafile",
    "JSONProcessing": ".models",
    "ReaderConfig": ".datafile",
    "SplitColumnSpec": ".models",
    "TabularProcessing": ".models",
    "FileProcessing": ".types",
    "ArraySource": ".file_reader",
    "DecodedSource": ".file_reader",
    "DecodedSources": ".file_reader",
    "DocumentSource": ".file_reader",
    "ProcessingSource": ".file_reader",
    "TabularSource": ".file_reader",
    "SourceProcessor": ".file_reader",
    "TabularProcessor": ".file_reader",
    "ColumnTimeAxis": ".models",
    "ComponentInstruction": ".models",
    "ComponentOwner": ".models",
    "ComponentReference": ".models",
    "RegularTimeAxis": ".models",
    "SupplementalAttributeInstruction": ".models",
    "TimeSeriesInstruction": ".models",
    "build_system": ".ingestion",
    "FileRequirement": ".types",
    "FileType": ".types",
    "CLIError": ".exceptions",
    "ComponentCreationError": ".exceptions",
    "PluginError": ".exceptions",
    "UpgradeError": ".exceptions",
    "ValidationError": ".exceptions",
    "H5PyFileReader": ".h5_adapter",
    "H5Reader": ".h5_adapter",
    "FileReader": ".file_reader",
    "getter": ".getters",
    "resolve_getter": ".getters",
    "Plugin": ".plugin_base",
    "PluginConfig": ".plugin_config",
    "PluginContext": ".plugin_context",
    "expose_plugin": ".plugin_expose",
    "ProvenanceBuilder": ".provenance",
    "ProvenanceInfo": ".provenance",
    "SourceProvenance": ".provenance",
    "RuleResult": ".result",
    "TranslationResult": ".result",
    "Rule": ".rules",
    "RuleFilter": ".rules",
    "FieldFilter": ".rules",
    "GetterFilter": ".rules",
    "AnyOfFilter": ".rules",
    "AllOfFilter": ".rules",
    "SupplementalAttributeRule": ".rules",
    "apply_rules_to_context": ".rules_executor",
    "apply_single_rule": ".rules_executor",
    "attach_rule_outputs": ".rules_executor",
    "resolve_supplemental_class": ".rules_executor",
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
        module_path = LAZY_IMPORTS[name]
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
    "AllOfFilter",
    "AnyOfFilter",
    "ArraySource",
    "CLIError",
    "ColumnTimeAxis",
    "ComponentCreationError",
    "ComponentInstruction",
    "ComponentOwner",
    "ComponentReference",
    "DataFile",
    "DataReader",
    "DataStore",
    "DecodedSource",
    "DecodedSources",
    "DocumentSource",
    "Err",
    "FieldFilter",
    "FileInfo",
    "FileProcessing",
    "FileReader",
    "FileRequirement",
    "FileType",
    "GetterFilter",
    "GitVersioningStrategy",
    "H5PyFileReader",
    "H5Reader",
    "HasPerUnit",
    "HasUnits",
    "JSONProcessing",
    "Ok",
    "Plugin",
    "PluginConfig",
    "PluginContext",
    "PluginError",
    "ProcessingSource",
    "ReaderConfig",
    "RegularTimeAxis",
    "Result",
    "Rule",
    "RuleFilter",
    "RuleResult",
    "SemanticVersioningStrategy",
    "SourceProcessor",
    "SplitColumnSpec",
    "SupplementalAttributeInstruction",
    "SupplementalAttributeRule",
    "System",
    "TabularProcessing",
    "TabularProcessor",
    "TabularSource",
    "TimeSeriesInstruction",
    "TranslationResult",
    "Unit",
    "UnitSystem",
    "UpgradeError",
    "UpgradeStep",
    "UpgradeType",
    "ValidationError",
    "VersionReader",
    "VersionStrategy",
    "apply_rules_to_context",
    "apply_single_rule",
    "attach_rule_outputs",
    "build_system",
    "components_to_records",
    "export_components_to_csv",
    "expose_plugin",
    "get_unit_system",
    "getter",
    "is_err",
    "is_ok",
    "replace_single_time_series",
    "resolve_getter",
    "resolve_supplemental_class",
    "run_upgrade_step",
    "set_unit_system",
    "transfer_time_series_metadata",
]
