"""Execute every block on an interpreter that supports its declared syntax."""

from __future__ import annotations

import doctest
import io
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def minimum_python(marker: str) -> tuple[int, int]:
    match = re.search(r"\brequires-python=(\d+)\.(\d+)\b", marker)
    return (int(match[1]), int(match[2])) if match else (3, 11)


def run_block(code: str, *, name: str, filename: str, minimum: tuple[int, int]) -> doctest.TestResults:
    """Run actual example text, using an isolated newer environment when required."""
    if sys.version_info[:2] < minimum:
        version = ".".join(map(str, minimum))
        process = subprocess.run(
            [
                "uv",
                "run",
                "--isolated",
                "--python",
                version,
                "--locked",
                "--no-dev",
                "--group",
                "docs",
                "python",
                str(Path(__file__).resolve()),
            ],
            cwd=ROOT,
            input=json.dumps({"code": code, "name": name, "filename": filename}),
            capture_output=True,
            text=True,
            check=True,
            timeout=180,
        )
        result = json.loads(process.stdout)
        if result["diagnostics"]:
            print(result["diagnostics"], end="")
        return doctest.TestResults(result["failed"], result["attempted"])
    result, diagnostics = _execute(code, name=name, filename=filename)
    if diagnostics:
        print(diagnostics, end="")
    return result


def _execute(code: str, *, name: str, filename: str) -> tuple[doctest.TestResults, str]:
    from r2x_core.getters import GETTER_REGISTRY

    code = re.sub(r"(?m)^# (.*)$", r"\1", code)
    original_getters = GETTER_REGISTRY.copy()
    GETTER_REGISTRY.clear()
    try:
        test = doctest.DocTestParser().get_doctest(code, {}, name, filename, 0)
        output = io.StringIO()
        result = doctest.DocTestRunner(verbose=False).run(test, out=output.write)
        return result, output.getvalue()
    finally:
        GETTER_REGISTRY.clear()
        GETTER_REGISTRY.update(original_getters)


if __name__ == "__main__":
    payload = json.load(sys.stdin)
    result, diagnostics = _execute(**payload)
    print(json.dumps({"failed": result.failed, "attempted": result.attempted, "diagnostics": diagnostics}))
