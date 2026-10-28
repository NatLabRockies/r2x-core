"""Exercise the illustrative RAW reader through configured construction."""

import importlib
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from r2x_core import InputColumn, PluginConfig, ReaderConfig, build_system

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


@pytest.mark.polars
def test_multisource_reader_rejects_ambiguous_native_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject one input schema when the reader emits distinct table schemas."""
    monkeypatch.syspath_prepend(str(EXAMPLE))
    reader_module: ModuleType = importlib.import_module("psse_reader")

    with pytest.raises(ValueError, match=r"multiple sources.*shared column schema"):
        reader_module.DummyPSSEReader().read_file(
            "dummy_raw",
            file_path=EXAMPLE / "inputs" / "case.raw",
            reader_config=ReaderConfig(columns=(InputColumn(name="bus_number", dtype="int64"),)),
        )
