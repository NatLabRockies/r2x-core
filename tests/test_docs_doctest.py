"""Pytest plugin for running Python doctest blocks in markdown documentation.

This module discovers and executes Python code blocks marked with 'python doctest'
in markdown files. Each code block is executed to ensure documentation examples
remain accurate and functional.

Usage:
    pytest tests/test_docs_doctest.py -v

The plugin scans all markdown files recursively under docs/ and extracts code
blocks formatted as doctests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.doctest_runner import minimum_python, run_block

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"
FENCE_RE = re.compile(r"^(```|~~~)\s*([^\n`]*)?$")
DOCTEST_PROMPT_RE = re.compile(r"^\s*>>> ?")
DOCTEST_CONTINUATION_RE = re.compile(r"^\s*\.\.\. ?")


@dataclass(frozen=True)
class DocBlock:
    """Represents a doctest code block from markdown."""

    path: Path
    start_line: int
    text: str
    minimum_python: tuple[int, int]


def extract_doctest_blocks(path: Path) -> list[DocBlock]:
    """Extract doctest code blocks from markdown file.

    Parameters
    ----------
    path : Path
        Path to markdown file.

    Returns
    -------
    list[DocBlock]
        List of doctest blocks found.
    """
    if not path.exists():
        return []

    blocks: list[DocBlock] = []
    lines = path.read_text(encoding="utf-8").split("\n")
    i = 0

    while i < len(lines):
        match = FENCE_RE.match(lines[i])
        if not match or not is_doctest_marker(match.group(2)):
            i += 1
            continue

        fence_char = match.group(1)
        block_start = i
        i += 1
        block_lines = []

        # Collect block content until closing fence
        while i < len(lines) and not (FENCE_RE.match(lines[i]) and fence_char in lines[i]):
            block_lines.append(lines[i])
            i += 1

        # Extract doctest-formatted lines
        doctest_lines = extract_doctest_lines(block_lines)
        if doctest_lines:
            blocks.append(
                DocBlock(
                    path=path,
                    start_line=block_start + 1,
                    text="\n".join(doctest_lines),
                    minimum_python=minimum_python(match.group(2) or ""),
                )
            )

        i += 1

    return blocks


def is_doctest_marker(lang_info: str | None) -> bool:
    """Check if language info contains both 'python' and 'doctest' markers."""
    if not lang_info:
        return False
    parts = lang_info.split()
    return "python" in parts and "doctest" in parts


def extract_doctest_lines(block_lines: list[str]) -> list[str]:
    """Extract lines that look like doctest (prompts and expected output)."""
    result = []
    has_prompt = False

    for line in block_lines:
        is_prompt = DOCTEST_PROMPT_RE.match(line)
        if is_prompt:
            result.append(line)
            has_prompt = True
        elif has_prompt:
            # Include output lines and blank lines after prompts
            result.append(line)

    return result


def test_comment_prefixed_expectations_are_compared() -> None:
    correct = run_block(">>> 2 + 2\n# 4", name="commented_output", filename=__file__, minimum=(3, 11))
    incorrect = run_block(">>> 2 + 2\n# 5", name="incorrect_output", filename=__file__, minimum=(3, 11))

    assert correct.failed == 0
    assert incorrect.failed == 1


def test_getter_registrations_are_isolated_between_blocks() -> None:
    code = "\n".join(
        (
            ">>> from r2x_core import getter",
            ">>> @getter",
            "... def extract_name(component):",
            "...     return component.name",
            ">>> extract_name.__name__",
            "# 'extract_name'",
        )
    )

    for index in range(2):
        result = run_block(code, name=f"getter_registry_{index}", filename=__file__, minimum=(3, 11))
        assert result.failed == 0


def test_documentation_expectations_are_copyable() -> None:
    violations: list[str] = []
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        for block in extract_doctest_blocks(path):
            for line in block.text.splitlines():
                if not line.strip() or DOCTEST_PROMPT_RE.match(line) or DOCTEST_CONTINUATION_RE.match(line):
                    continue
                if not line.startswith("# "):
                    violations.append(f"{path}:{block.start_line}: {line!r}")

    assert not violations, "Doctest expected output must be prefixed with '# ':\n" + "\n".join(violations)


def run_doctest_block(block: DocBlock, block_index: int) -> tuple[int, int]:
    """Run a single doctest block.

    Returns
    -------
    tuple[int, int]
        (failures, tests) - number of failures and tests run.
    """
    result = run_block(
        block.text,
        name=f"{block.path.name}:block_{block_index}",
        filename=str(block.path),
        minimum=block.minimum_python,
    )
    return result.failed, result.attempted


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Pytest hook to generate doctest parametrized tests."""
    if metafunc.function.__name__ != "test_markdown_doctest":
        return

    if not DOCS_ROOT.exists():
        metafunc.parametrize("doc_path", [])
        return

    # Discover all markdown files with doctests
    doc_paths = sorted(p for p in DOCS_ROOT.glob("**/*.md") if extract_doctest_blocks(p))

    metafunc.parametrize(
        "doc_path",
        doc_paths,
        ids=lambda p: f"{p.parent.name}/{p.name}",
    )


@pytest.mark.doctest
def test_markdown_doctest(doc_path: Path) -> None:
    """Execute all doctests found in a markdown file.

    Parameters
    ----------
    doc_path : Path
        Path to markdown file.
    """
    blocks = extract_doctest_blocks(doc_path)

    if not blocks:
        pytest.skip(f"No doctest blocks in {doc_path.name}")

    total_failures = 0
    total_tests = 0

    for i, block in enumerate(blocks):
        failures, tests = run_doctest_block(block, i)
        total_failures += failures
        total_tests += tests

    if total_failures > 0:
        pytest.fail(f"{total_failures}/{total_tests} doctest(s) failed")
