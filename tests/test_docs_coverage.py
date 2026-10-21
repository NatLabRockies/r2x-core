"""Validate that all public API symbols appear in doctest examples.

This test ensures that every symbol exported in r2x_core.__all__ has at least
one doctest example in the documentation, with specific exceptions for re-exports
from other packages.

Usage:
    pytest tests/test_docs_coverage.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import r2x_core

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"

# Re-exports that don't require documentation
SKIP_SYMBOLS = frozenset({"Ok", "Err", "Result", "is_ok", "is_err"})

# Patterns for extracting symbols from doctest blocks
IMPORT_PATTERN = r"from\s+r2x_core\s+import\s+([^#\n]+)"
DIRECT_PATTERN = r"r2x_core\.(\w+)"


def extract_doctest_content(text: str) -> str:
    """Extract all doctest blocks from markdown text."""
    lines = text.split("\n")
    blocks = []
    in_block = False
    block_lines = []

    for line in lines:
        if re.match(r"^(```|~~~)\s*python\s+doctest", line):
            in_block = True
            block_lines = []
        elif in_block and re.match(r"^(```|~~~)", line):
            in_block = False
            blocks.append("\n".join(block_lines))
        elif in_block:
            block_lines.append(line)

    return "\n".join(blocks)


def extract_symbols_from_doctest(doctest_text: str) -> set[str]:
    """Extract r2x_core symbols from doctest content."""
    symbols = set()

    # Extract from imports: from r2x_core import X, Y
    for match in re.finditer(IMPORT_PATTERN, doctest_text):
        imports = match.group(1).split(",")
        for imp in imports:
            name = imp.split(" as ")[0].strip()
            if name and name.isidentifier():
                symbols.add(name)

    # Extract from direct access: r2x_core.Symbol
    for match in re.finditer(DIRECT_PATTERN, doctest_text):
        symbols.add(match.group(1))

    return symbols


def scan_docs_for_symbols() -> set[str]:
    """Scan all documentation files for symbols used in doctests."""
    documented = set()

    if not DOCS_ROOT.exists():
        return documented

    for md_file in DOCS_ROOT.glob("**/*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            doctest_content = extract_doctest_content(content)
            documented.update(extract_symbols_from_doctest(doctest_content))
        except Exception:
            pass

    return documented


@pytest.mark.doc_coverage
def test_public_symbols_documented() -> None:
    """Verify every public API symbol appears in a doctest.

    Raises
    ------
    AssertionError
        If any required symbol is missing from documentation.
    """
    public_symbols = set(r2x_core.__all__)
    documented_symbols = scan_docs_for_symbols()

    required = public_symbols - SKIP_SYMBOLS
    missing = sorted(required - documented_symbols)

    if missing:
        pytest.fail(
            f"Missing documentation for {len(missing)} public symbol(s):\n\n"
            + "\n".join(f"  - {sym}" for sym in missing)
            + "\n\nAdd doctest examples to docs/**/*.md files."
        )


@pytest.mark.doc_coverage
def test_skip_list_contains_valid_symbols() -> None:
    """Ensure skip list only contains actual public symbols."""
    public_symbols = set(r2x_core.__all__)
    unknown = sorted(SKIP_SYMBOLS - public_symbols)

    if unknown:
        pytest.fail(f"SKIP_SYMBOLS contains invalid symbols: {unknown}")
