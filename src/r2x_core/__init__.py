"""R2X Core public API with lazy imports for fast CLI/import startup.

Eager imports are kept under ``if TYPE_CHECKING`` so IDEs (pyright, mypy)
see the full API surface for autocompletion and type checking. At runtime,
attributes are imported on first access via ``__getattr__`` and cached in
the module globals, dropping cold-import from ~1.4 s to ~50 ms.
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
    from .datafile import DataFile, FileInfo, JSONProcessing, ReaderConfig, TabularProcessing
    from .exceptions import (
        CLIError,
        ComponentCreationError,
        PluginError,
        UpgradeError,
        ValidationError,
    )
    from .file_types import FileFormat, H5Format
    from .getters import getter
    from .plugin_base import Plugin
    from .plugin_config import PluginConfig
    from .plugin_context import PluginContext
    from .plugin_expose import expose_plugin
    from .reader import DataReader
    from .result import RuleResult, TranslationResult
    from .rules import Rule, RuleFilter
    from .rules_executor import apply_rules_to_context, apply_single_rule
    from .store import DataStore
    from .system import System
    from .time_series import transfer_time_series_metadata
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
    "DataFile": ".datafile",
    "FileInfo": ".datafile",
    "JSONProcessing": ".datafile",
    "ReaderConfig": ".datafile",
    "TabularProcessing": ".datafile",
    "CLIError": ".exceptions",
    "ComponentCreationError": ".exceptions",
    "PluginError": ".exceptions",
    "UpgradeError": ".exceptions",
    "ValidationError": ".exceptions",
    "FileFormat": ".file_types",
    "H5Format": ".file_types",
    "getter": ".getters",
    "Plugin": ".plugin_base",
    "PluginConfig": ".plugin_config",
    "PluginContext": ".plugin_context",
    "expose_plugin": ".plugin_expose",
    "DataReader": ".reader",
    "RuleResult": ".result",
    "TranslationResult": ".result",
    "Rule": ".rules",
    "RuleFilter": ".rules",
    "apply_rules_to_context": ".rules_executor",
    "apply_single_rule": ".rules_executor",
    "DataStore": ".store",
    "System": ".system",
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
    "CLIError",
    "ComponentCreationError",
    "DataFile",
    "DataReader",
    "DataStore",
    "Err",
    "FileFormat",
    "FileInfo",
    "GitVersioningStrategy",
    "H5Format",
    "HasPerUnit",
    "HasUnits",
    "JSONProcessing",
    "Ok",
    "Plugin",
    "PluginConfig",
    "PluginContext",
    "PluginError",
    "ReaderConfig",
    "Result",
    "Rule",
    "RuleFilter",
    "RuleResult",
    "SemanticVersioningStrategy",
    "System",
    "TabularProcessing",
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
    "components_to_records",
    "create_component",
    "export_components_to_csv",
    "expose_plugin",
    "get_unit_system",
    "getter",
    "h5_readers",
    "is_err",
    "is_ok",
    "run_upgrade_step",
    "set_unit_system",
    "transfer_time_series_metadata",
]
