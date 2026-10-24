"""Exercise the illustrative RAW reader through configured construction."""

import importlib
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from r2x_core import PluginConfig, build_system

EXAMPLE = Path(__file__).parents[1] / "docs" / "examples" / "psse-raw"


@pytest.mark.polars
def test_empty_illustrative_raw_builds_empty_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep declared table schemas when a valid custom input has no records."""
    monkeypatch.syspath_prepend(str(EXAMPLE))
    models: ModuleType = importlib.import_module("psse_models")
    reader_module: ModuleType = importlib.import_module("psse_reader")

    config_dir = tmp_path / "config"
    input_dir = tmp_path / "inputs"
    config_dir.mkdir()
    input_dir.mkdir()
    (input_dir / "case.raw").write_text("# No BUS or GEN records\n", encoding="utf-8")
    for name in ("file_mapping.json", "parser_rules.json"):
        shutil.copyfile(EXAMPLE / "config" / name, config_dir / name)

    config = PluginConfig(models=("psse_models",), config_path_override=config_dir)
    system = build_system(
        config,
        name="empty-illustrative-case",
        input_folder=tmp_path,
        readers={"dummy_raw": reader_module.DummyPSSEReader()},
    )

    assert tuple(system.get_components(models.PSSEBus)) == ()
    assert tuple(system.get_components(models.PSSEGenerator)) == ()
