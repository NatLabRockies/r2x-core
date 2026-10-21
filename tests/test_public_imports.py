"""Fresh-process checks for the lazy public API."""

import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


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


def test_missing_polars_errors_name_the_install_or_adapter_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import r2x_core
    from r2x_core import DataFile, DataReader, TabularProcessing
    from r2x_core.processors import apply_processing
    from r2x_core.types import TableFormat

    class MissingPolarsAdapter(ModuleType):
        def __getattr__(self, name: str) -> object:
            raise ModuleNotFoundError("No module named 'polars'", name="polars")

    adapter = MissingPolarsAdapter("r2x_core.polars_adapter")
    monkeypatch.setitem(sys.modules, "r2x_core.polars_adapter", adapter)
    monkeypatch.setattr(r2x_core, "polars_adapter", adapter, raising=False)

    with pytest.raises(ImportError, match=r"r2x-core\[polars\].*FileReader"):
        DataReader().select_file_reader(TableFormat())

    data_file = DataFile(name="missing-polars", relative_fpath="input.csv")
    with pytest.raises(ImportError, match=r"r2x-core\[polars\].*TabularBackend"):
        apply_processing([], data_file=data_file, proc_spec=TabularProcessing())


def test_unrelated_missing_dependencies_are_propagated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import r2x_core
    from r2x_core import DataFile, DataReader, TabularProcessing
    from r2x_core.processors import apply_processing
    from r2x_core.types import TableFormat

    class MissingAdapterDependency(ModuleType):
        def __getattr__(self, name: str) -> object:
            raise ModuleNotFoundError("No module named 'adapter_dependency'", name="adapter_dependency")

    adapter = MissingAdapterDependency("r2x_core.polars_adapter")
    monkeypatch.setitem(sys.modules, "r2x_core.polars_adapter", adapter)
    monkeypatch.setattr(r2x_core, "polars_adapter", adapter, raising=False)

    with pytest.raises(ModuleNotFoundError, match="adapter_dependency"):
        DataReader().select_file_reader(TableFormat())

    data_file = DataFile(name="missing-adapter", relative_fpath="input.csv")
    with pytest.raises(ModuleNotFoundError, match="adapter_dependency"):
        apply_processing([], data_file=data_file, proc_spec=TabularProcessing())


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
