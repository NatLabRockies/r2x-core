"""Fresh-process checks for the lazy public API."""

import os
import subprocess
import sys
from pathlib import Path


def test_reader_interfaces_are_public() -> None:
    import r2x_core
    from r2x_core import FileReader, H5PyFileReader, H5Reader, TabularBackend
    from r2x_core.json_adapter import JSONFileReader, JSONProcessingBackend
    from r2x_core.polars_adapter import PolarsTabularBackend, PolarsTabularFileReader

    assert callable(JSONProcessingBackend)
    assert issubclass(H5Reader, FileReader)
    assert issubclass(H5PyFileReader, H5Reader)
    assert issubclass(JSONFileReader, FileReader)
    assert issubclass(PolarsTabularBackend, TabularBackend)
    assert issubclass(PolarsTabularFileReader, FileReader)
    assert not {
        "JSONFileReader",
        "JSONProcessingBackend",
        "TabularTransformResult",
        "h5_adapter",
    } & set(r2x_core.__all__)


def test_polars_is_a_runtime_dependency_for_no_dev_installs() -> None:
    import tomllib

    from packaging.requirements import Requirement

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    metadata = tomllib.loads(pyproject.read_text())
    project = metadata["project"]
    dependencies = project["dependencies"]
    lock = tomllib.loads((pyproject.parent / "uv.lock").read_text())
    package = next(package for package in lock["package"] if package["name"] == "r2x-core")

    assert "polars" in {Requirement(dependency).name for dependency in dependencies}
    assert "polars" not in project.get("optional-dependencies", {})
    assert any(dependency["name"] == "polars" for dependency in package["dependencies"])


def test_config_imports_do_not_load_translation_or_frame_engines() -> None:
    code = """
import sys
from r2x_core import DataFile, DataStore, ReaderConfig, TabularProcessing
import r2x_core.datafile
import r2x_core.store

assert DataFile and DataStore and ReaderConfig and TabularProcessing
assert 'infrasys' not in sys.modules
assert 'pandas' not in sys.modules
assert 'polars' not in sys.modules
"""
    env = os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30, env=env)


def test_h5_reader_classes_are_lazy_root_exports() -> None:
    code = """
import sys
import r2x_core

assert 'r2x_core.h5_adapter' not in sys.modules
assert 'h5py' not in sys.modules
from r2x_core import H5PyFileReader, H5Reader
assert issubclass(H5PyFileReader, H5Reader)
assert 'r2x_core.h5_adapter' in sys.modules
assert 'h5py' in sys.modules
assert 'h5_adapter' not in r2x_core.__all__
"""
    env = os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30, env=env)
