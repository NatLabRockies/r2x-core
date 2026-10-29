#!/usr/bin/env python3
"""Check that the documented r2x-core symbols exist in a package source tree."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REQUIRED: dict[str, tuple[str, ...]] = {
    "__init__.py": (
        "Plugin",
        "PluginConfig",
        "PluginContext",
        "Rule",
        "RuleFilter",
        "DataFile",
        "DataStore",
        "DataReader",
        "InlineTable",
        "InputColumn",
        "SourceSelection",
        "SourceAvailability",
        "TableMappingRecord",
        "TableMappingBackend",
        "System",
        "UnitSystem",
        "UpgradeStep",
        "VersionStrategy",
        "apply_rules_to_context",
        "apply_single_rule",
        "assemble_tables",
        "assemble_table_records",
        "build_system",
        "build_system_from_sources",
        "run_upgrade_step",
    ),
    "plugin_base.py": ("Plugin",),
    "plugin_config.py": ("PluginConfig",),
    "plugin_context.py": ("PluginContext",),
    "plugin_expose.py": ("expose_plugin",),
    "rules.py": ("Rule", "RuleFilter"),
    "models.py": (
        "TabularProcessing",
        "JSONProcessing",
        "ComponentInstruction",
        "TimeSeriesInstruction",
        "SupplementalAttributeInstruction",
        "ParserInstruction",
    ),
    "rules_executor.py": ("apply_rules_to_context", "apply_single_rule"),
    "datafile.py": (
        "DataFile",
        "FileInfo",
        "ReaderConfig",
        "InputColumn",
        "InlineTable",
        "SourceSelection",
    ),
    "store.py": ("DataStore",),
    "reader.py": (
        "DataReader",
        "read_data_files",
        "read_and_assemble_sources",
        "read_and_assemble_records",
    ),
    "ingestion.py": ("build_system", "build_system_from_sources"),
    "table_mapping.py": (
        "TableMappingRecord",
        "TableOperation",
        "assemble_tables",
        "assemble_table_records",
    ),
    "file_reader.py": (
        "DecodedSource",
        "DecodedSources",
        "TabularSource",
        "FileReader",
    ),
    "tabular_backend.py": ("TableMappingBackend",),
    "types.py": ("FileProcessing", "FileRequirement", "FileType"),
    "units/__init__.py": ("HasUnits", "HasPerUnit", "Unit", "UnitSystem"),
    "versioning.py": ("VersionStrategy", "VersionReader"),
}


def has_symbol(source: str, symbol: str) -> bool:
    """Return whether source defines or explicitly exports a named symbol."""
    escaped = re.escape(symbol)
    definition = re.compile(rf"^\s*(?:class|def)\s+{escaped}\b", re.MULTILINE)
    import_export = re.compile(rf"^\s*from\s+\S+\s+import[^\n]*\b{escaped}\b", re.MULTILINE)
    assignment = re.compile(rf"^\s*{escaped}\s*(?::[^=\n]+)?=", re.MULTILINE)
    all_export = re.compile(rf"[\"']{escaped}[\"']", re.MULTILINE)
    return bool(
        definition.search(source)
        or import_export.search(source)
        or assignment.search(source)
        or ("__all__" in source and all_export.search(source))
    )


def check_package(package_root: Path) -> list[str]:
    """Return missing files and symbols under a package root."""
    missing: list[str] = []
    for relative_path, symbols in REQUIRED.items():
        path = package_root / relative_path
        if not path.is_file():
            missing.append(f"missing file: {relative_path}")
            continue
        source = path.read_text(encoding="utf-8")
        missing.extend(
            f"{relative_path}: missing {symbol}" for symbol in symbols if not has_symbol(source, symbol)
        )
    return missing


def main() -> int:
    """Parse arguments, check the package, and print a concise result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path("src/r2x_core"),
        help="Path to the r2x_core package root (default: src/r2x_core)",
    )
    args = parser.parse_args()
    package_root = args.repo.expanduser().resolve()

    if not package_root.is_dir():
        print(f"error: package root not found: {package_root}")
        return 2

    missing = check_package(package_root)
    if missing:
        print("API symbol check failed:")
        for item in missing:
            print(f"- {item}")
        return 1

    print(f"API symbol check passed: {package_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
