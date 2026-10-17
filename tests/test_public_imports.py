"""Fresh-process checks for the lazy public API."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("access", ["from r2x_core import h5_readers", "h5_readers = r2x_core.h5_readers"])
def test_h5_readers_is_lazy_and_public(access: str) -> None:
    code = f"""
import importlib
import sys
import r2x_core

assert 'r2x_core.h5_readers' not in sys.modules
assert 'h5py' not in sys.modules
{access}
assert h5_readers is importlib.import_module('r2x_core.h5_readers')
assert r2x_core.h5_readers is h5_readers
assert 'h5py' in sys.modules
assert 'h5_readers' in r2x_core.__all__
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)
