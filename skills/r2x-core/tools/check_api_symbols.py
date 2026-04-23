#!/usr/bin/env python3
r"""Check that key r2x-core public API symbols still exist.

Default behavior checks the *installed* `r2x_core` package (for example
from PyPI). Use ``--repo`` only when you intentionally want to check a
source checkout.

The target path must be the r2x_core package root directory (the folder
that contains ``plugin_base.py``, ``rules.py``, ``store.py``, etc.).

Examples
--------
# Check installed package (recommended)
uvx --from python --with r2x-core python \\
    src/skills/r2x-core/tools/check_api_symbols.py

# Check a source checkout directly
uvx --from python python \\
    src/skills/r2x-core/tools/check_api_symbols.py \\
    --repo src/r2x_core

# Print resolved package root
uvx --from python --with r2x-core python \\
    src/skills/r2x-core/tools/check_api_symbols.py --print-root
"""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path

REQUIRED: dict[str, tuple[str, ...]] = {
    "plugin_base.py": ("Plugin",),
    "plugin_config.py": ("PluginConfig",),
    "plugin_context.py": ("PluginContext",),
    "plugin_expose.py": ("expose_plugin",),
    "rules.py": ("Rule", "RuleFilter"),
    "rules_executor.py": ("apply_rules_to_context", "apply_single_rule"),
    "result.py": ("RuleResult", "TranslationResult"),
    "store.py": ("DataStore",),
    "datafile.py": (
        "DataFile",
        "FileInfo",
        "ReaderConfig",
        "TabularProcessing",
        "JSONProcessing",
    ),
    "reader.py": ("DataReader",),
    "file_types.py": ("FileFormat", "H5Format"),
    "system.py": ("System",),
    "units/__init__.py": (
        "HasUnits",
        "HasPerUnit",
        "Unit",
        "UnitSystem",
        "get_unit_system",
        "set_unit_system",
    ),
    "versioning.py": (
        "VersionStrategy",
        "SemanticVersioningStrategy",
        "GitVersioningStrategy",
        "VersionReader",
    ),
    "utils/__init__.py": (
        "UpgradeStep",
        "UpgradeType",
        "run_upgrade_step",
        "create_component",
        "components_to_records",
        "export_components_to_csv",
    ),
    "exceptions.py": (
        "CLIError",
        "ComponentCreationError",
        "PluginError",
        "UpgradeError",
        "ValidationError",
    ),
}


def has_symbol(text: str, symbol: str) -> bool:
    """Check if the given symbol is defined or re-exported in the text of a Python file."""
    pattern = re.compile(rf"^\s*(def|class)\s+{re.escape(symbol)}\b", re.MULTILINE)
    if pattern.search(text):
        return True
    # Allow re-exports via `from .x import Symbol` or `Symbol = ...`
    reexport = re.compile(
        rf"(^|\s)(from\s+\S+\s+import[^\n]*\b{re.escape(symbol)}\b|{re.escape(symbol)}\s*=)",
        re.MULTILINE,
    )
    return bool(reexport.search(text))


def looks_like_r2x_core_root(path: Path) -> bool:
    """Heuristic check to see if the given path looks like the root of the r2x_core package."""
    return (path / "plugin_base.py").exists() and (path / "rules.py").exists()


def unique_paths(paths: list[Path]) -> list[Path]:
    """Return a list of unique paths, preserving order."""
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def discover_candidates(repo_arg: Path | None) -> list[Path]:
    """Discover candidate paths for the r2x_core package root, based on the provided repo_arg and common patterns."""
    candidates: list[Path] = []

    if repo_arg is not None:
        candidates.append(repo_arg.expanduser())

    spec = importlib.util.find_spec("r2x_core")
    if spec and spec.origin:
        candidates.append(Path(spec.origin).resolve().parent)

    starts = [Path.cwd(), Path(__file__).resolve().parent]
    for start in starts:
        for parent in [start, *start.parents]:
            candidates.append(parent / "src" / "r2x_core")
            candidates.append(parent / "r2x_core")

    return unique_paths(candidates)


def resolve_repo(repo_arg: Path | None) -> Path | None:
    """Resolve the r2x_core package root path from the given repo_arg or discovered candidates."""
    for candidate in discover_candidates(repo_arg):
        if looks_like_r2x_core_root(candidate):
            return candidate.resolve()
    return None


def check_symbols(repo: Path) -> list[str]:
    """Check that all required symbols are present in their respective files under the given repo path. Return a list of missing items."""
    missing: list[str] = []
    for rel_file, symbols in REQUIRED.items():
        fpath = repo / rel_file
        if not fpath.exists():
            missing.append(f"missing file: {fpath}")
            continue

        text = fpath.read_text(encoding="utf-8")
        for symbol in symbols:
            if not has_symbol(text, symbol):
                missing.append(f"{rel_file}: missing symbol {symbol}")  # noqa: PERF401
    return missing


def main() -> int:
    """Parse arguments, resolve the r2x_core package root, and check API symbols."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Optional path to r2x_core package root (folder containing plugin_base.py)",
    )
    parser.add_argument("--print-root", action="store_true", help="Print resolved package path")
    parser.add_argument("--verbose", action="store_true", help="Print candidate search paths")
    args = parser.parse_args()

    if args.verbose:
        print("Candidates:")
        for p in discover_candidates(args.repo):
            print(f"- {p}")

    repo = resolve_repo(args.repo)
    if repo is None:
        print("Could not locate r2x_core package root.")
        print(
            "Install r2x-core from PyPI and run via: "
            "uvx --from python --with r2x-core python <script>"
        )
        print("Or provide --repo <path-to-r2x_core-package-root> for source checkouts.")
        return 2

    if args.print_root:
        print(repo)

    missing = check_symbols(repo)
    if missing:
        print("API drift detected:")
        for item in missing:
            print(f"- {item}")
        return 1

    print("API symbol check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
