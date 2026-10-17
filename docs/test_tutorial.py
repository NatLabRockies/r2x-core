"""Exercise the shipped CSV workflow and its validation boundary in fresh processes."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FIXTURE = Path(__file__).parent / "examples/csv-system"


class CsvTutorialTest(unittest.TestCase):
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
