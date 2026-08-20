#!/usr/bin/env python3
"""Classify files under a candidate r2x-core DataStore directory."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

KNOWN_EXTENSIONS = {
    ".csv": "TableFormat",
    ".tsv": "TableFormat",
    ".h5": "H5Format",
    ".hdf5": "H5Format",
    ".parquet": "ParquetFormat",
    ".json": "JSONFormat",
    ".xml": "XMLFormat",
}


def walk_files(root: Path, max_depth: int | None) -> list[Path]:
    """Return files below root, optionally bounded by relative depth."""
    root = root.resolve()
    root_depth = len(root.parts)
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if max_depth is not None and len(path.parts) - root_depth > max_depth:
            continue
        files.append(path)
    return files


def main() -> int:
    """Parse arguments and print a file-format inventory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--list-unknown", action="store_true")
    args = parser.parse_args()

    root = args.path.expanduser().resolve()
    if not root.exists():
        print(f"error: path not found: {root}")
        return 2
    if not root.is_dir():
        print(f"error: not a directory: {root}")
        return 2

    files = walk_files(root, args.max_depth)
    counts: Counter[str] = Counter()
    unknown: list[Path] = []
    for path in files:
        format_name = KNOWN_EXTENSIONS.get(path.suffix.lower())
        if format_name is None:
            unknown.append(path)
        else:
            counts[format_name] += 1

    print(f"DataStore root: {root}")
    print(f"Total files: {len(files)}")
    print("By format:")
    for format_name, count in sorted(counts.items()):
        print(f"- {format_name}: {count}")
    print(f"Unknown-format files: {len(unknown)}")
    if args.list_unknown:
        for path in unknown:
            print(f"  - {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
