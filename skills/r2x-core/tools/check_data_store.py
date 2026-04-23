#!/usr/bin/env python3
r"""Inspect a candidate r2x-core DataStore directory.

Walks a directory tree and classifies files by the file formats r2x-core
knows how to read. Useful as a first-pass sanity check before wiring a
``DataStore`` and a list of ``DataFile`` entries.

Examples
--------
uvx --from python --with r2x-core python \\
    src/skills/r2x-core/tools/check_data_store.py /data/reeds

uvx --from python --with r2x-core python \\
    src/skills/r2x-core/tools/check_data_store.py /data/reeds --max-depth 3
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

# Conservative default extension map; r2x-core's FileFormat enum is the source
# of truth. Update this if r2x-core adds new formats.
KNOWN_EXTENSIONS: dict[str, str] = {
    ".csv": "CSV",
    ".tsv": "CSV",
    ".parquet": "PARQUET",
    ".pq": "PARQUET",
    ".json": "JSON",
    ".jsonl": "JSON",
    ".xml": "XML",
    ".h5": "HDF5",
    ".hdf5": "HDF5",
    ".hdf": "HDF5",
}


def walk_files(root: Path, max_depth: int | None) -> list[Path]:
    """Recursively walk a directory and return a list of file paths, optionally limiting recursion depth."""
    out: list[Path] = []
    root = root.resolve()
    root_depth = len(root.parts)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if max_depth is not None:
            depth = len(path.parts) - root_depth
            if depth > max_depth:
                continue
        out.append(path)
    return out


def main() -> int:
    """Parse arguments, inspect a DataStore directory, and print a report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="DataStore root directory to inspect")
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Limit recursion depth (default: unlimited)",
    )
    parser.add_argument(
        "--list-unknown",
        action="store_true",
        help="List individual files with unknown extensions",
    )
    args = parser.parse_args()

    root: Path = args.path.expanduser().resolve()
    if not root.exists():
        print(f"error: path not found: {root}")
        return 2
    if not root.is_dir():
        print(f"error: not a directory: {root}")
        return 2

    files = walk_files(root, args.max_depth)
    if not files:
        print(f"DataStore root: {root}")
        print("No files found.")
        return 0

    by_format: Counter[str] = Counter()
    unknown: list[Path] = []
    for f in files:
        fmt = KNOWN_EXTENSIONS.get(f.suffix.lower())
        if fmt is None:
            unknown.append(f)
            continue
        by_format[fmt] += 1

    print(f"DataStore root: {root}")
    print(f"Total files: {len(files)}")
    print("By format:")
    for fmt, count in sorted(by_format.items()):
        print(f"- {fmt}: {count}")
    if unknown:
        print(f"Unknown-format files: {len(unknown)}")
        if args.list_unknown:
            for f in unknown:
                print(f"  - {f.relative_to(root)}")
        else:
            print("  (rerun with --list-unknown to enumerate)")
    else:
        print("Unknown-format files: 0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
