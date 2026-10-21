"""Exercise the shipped CSV workflow and its validation boundary in fresh processes."""

from __future__ import annotations

import doctest
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from doctest_runner import minimum_python, run_block

FIXTURE = Path(__file__).parent / "examples/csv-system"


class CsvTutorialTest(unittest.TestCase):
    def test_marked_examples_have_checked_expectations(self) -> None:
        content = Path(__file__).parent / "src/content/docs"
        checked = 0
        for page in content.rglob("*.md"):
            if "references" in page.relative_to(content).parts:
                continue
            text = page.read_text(encoding="utf-8")
            for index, block in enumerate(re.finditer(r"^```python([^\n]*)\n(.*?)^```", text, re.M | re.S)):
                marker, code = block.groups()
                if ">>>" not in code:
                    continue
                self.assertIn("doctest", marker.split(), f"{page}: Python prompts need a doctest fence")
                example = doctest.DocTestParser().get_doctest(code, {}, f"{page.name}:{index}", str(page), 0)
                self.assertTrue(
                    any(item.want or re.search(r"\bassert\s", item.source) for item in example.examples),
                    f"{page}: doctest must check output or assert a value",
                )
                result = run_block(
                    code, name=example.name, filename=str(page), minimum=minimum_python(marker)
                )
                self.assertEqual(result.failed, 0, str(page))
                checked += result.attempted
        self.assertGreater(checked, 0)

    def test_declared_syntax_and_expectations(self) -> None:
        page = Path(__file__).parent / "src/content/docs/tutorials/plugin-discovery.md"
        blocks = list(
            re.finditer(r"^```python([^\n]*)\n(.*?)^```", page.read_text(encoding="utf-8"), re.M | re.S)
        )
        generic = next(block for block in blocks if "def generic_transform[" in block[2])
        self.assertEqual(minimum_python(generic[1]), (3, 12))
        ordinary = next(block for block in blocks if "class BuildDemo(" in block[2])
        self.assertEqual(minimum_python(ordinary[1]), (3, 11))
        code = ">>> def identity[T](value: T) -> T:\n...     return value\n>>> identity(7)\n7\n"
        result = run_block(code, name="generic", filename=__file__, minimum=(3, 12))
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.attempted, 2)
        with redirect_stdout(io.StringIO()) as diagnostics:
            incorrect = run_block(
                code.replace("\n7\n", "\n8\n"), name="incorrect", filename=__file__, minimum=(3, 12)
            )
        self.assertEqual(incorrect.failed, 1)
        self.assertIn("Expected:", diagnostics.getvalue())
        self.assertEqual(minimum_python(" doctest requires-python=3.12"), (3, 12))

    def test_export_reload_and_invalid_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for scenario in ("valid", "invalid"):
                destination = root / scenario
                shutil.copytree(FIXTURE, destination, ignore=shutil.ignore_patterns("output", "__pycache__"))
            valid = root / "valid"
            build = subprocess.run(
                [sys.executable, "build_system.py"], cwd=valid, capture_output=True, text=True, check=True
            )
            self.assertIn("2 active generators", build.stdout)
            self.assertIn("165.0 MW after scaling", build.stdout)
            self.assertTrue((valid / "output/system.json").is_file())
            inspect = subprocess.run(
                [sys.executable, "inspect_system.py"], cwd=valid, capture_output=True, text=True, check=True
            )
            self.assertIn("Alpha: 110.0 MW", inspect.stdout)
            self.assertIn("Bravo: 55.0 MW", inspect.stdout)
            invalid = root / "invalid"
            source = invalid / "inputs/generators.csv"
            source.write_text(
                source.read_text(encoding="utf-8").replace("Alpha,100,active", "Alpha,-1,active"),
                encoding="utf-8",
            )
            failure = subprocess.run(
                [sys.executable, "build_system.py"], cwd=invalid, capture_output=True, text=True, check=False
            )
            self.assertNotEqual(failure.returncode, 0)
            self.assertIn("capacity_mw", failure.stderr)
            self.assertFalse((invalid / "output/system.json").exists())


if __name__ == "__main__":
    unittest.main()
