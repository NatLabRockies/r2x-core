"""Check the release configuration against the project lockfiles."""

import json
import tomllib
from pathlib import Path

import pytest


@pytest.mark.parametrize("lockfile", ["uv.lock", "scripts/generate_api.py.lock"])
def test_release_updates_the_project_version_in_each_lockfile(lockfile: str) -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / ".release-please-config.json").read_text(encoding="utf-8"))
    entries = config["packages"]["."]["extra-files"]
    assert {
        "type": "toml",
        "path": lockfile,
        "jsonpath": "$.package[?(@.name.value=='r2x-core')].version",
    } in entries

    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads((root / lockfile).read_text(encoding="utf-8"))
    packages = [package for package in lock["package"] if package["name"] == project["name"]]
    assert len(packages) == 1
    assert packages[0]["version"] == project["version"]


def test_documentation_script_lock_tracks_project_dependency_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    metadata: list[object] = []
    for lockfile in ("uv.lock", "scripts/generate_api.py.lock"):
        lock = tomllib.loads((root / lockfile).read_text(encoding="utf-8"))
        package = next(package for package in lock["package"] if package["name"] == "r2x-core")
        metadata.append(package["metadata"])

    assert metadata[0] == metadata[1]
