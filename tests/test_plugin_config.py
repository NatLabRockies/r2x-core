"""Tests for :class:`r2x_core.plugin_config.PluginConfig` helpers."""

import json
from pathlib import Path
from typing import Any

import pytest

from r2x_core import DataStore, PluginContext
from r2x_core.plugin_config import PluginConfig
from r2x_core.utils import merge_with_overrides

FILE_MAPPING = "file_mapping.json"
DEFAULTS = "defaults.json"
EXPORTER_RULES = "exporter_rules.json"
PARSER_RULES = "parser_rules.json"
TRANSLATION_RULES = "translation_rules.json"


class SampleConfig(PluginConfig):
    """Minimal PluginConfig subclass for testing."""

    param1: str
    param2: int = 42


def write_assets(tmp_path: Path, payloads: dict[str, object]) -> None:
    for asset, payload in payloads.items():
        (tmp_path / asset).write_text(json.dumps(payload))


def test_models_defaults_to_empty_tuple():
    config = SampleConfig(param1="test")
    assert config.models == ()
    assert PluginConfig(models=None).models == ()


def test_models_normalize_and_reject_registration_values() -> None:
    """Accept symbolic model module names and reject non-iterable registrations."""
    assert PluginConfig(models="package.models").models == ("package.models",)
    assert PluginConfig(models=["package.one", "package.two"]).models == (
        "package.one",
        "package.two",
    )
    with pytest.raises(TypeError, match="models must be a string or iterable"):
        PluginConfig(models=42)


def test_active_versions_is_instance_data():
    first = PluginConfig()
    second = PluginConfig()

    first.active_versions["BusComponent"] = 2

    assert second.active_versions == {}


def test_upgrade_handler_is_excluded_from_json_serialization():
    def handler(*, store: DataStore, ctx: PluginContext[Any]) -> None:
        return None

    config = PluginConfig(upgrade_handler=handler)

    assert config.upgrade_handler is handler
    assert "upgrade_handler" not in config.model_dump()
    assert "upgrade_handler" not in config.model_dump_json()
    assert "upgrade_handler" not in config.model_json_schema()["properties"]


def test_models_accept_string():
    config = SampleConfig(param1="test", models=("r2x_sienna.models",))
    assert config.models == ("r2x_sienna.models",)


def test_models_accept_iterable():
    config = SampleConfig(param1="test", models=("mod.a", "mod.b"))
    assert config.models == ("mod.a", "mod.b")


def test_config_path_override(tmp_path):
    override = tmp_path / "custom"
    override.mkdir()
    config = SampleConfig(param1="test", config_path_override=override)
    assert config.config_path == override


def test_config_path_warns_for_missing_override(tmp_path: Path) -> None:
    """Expose a missing app config directory without changing configured paths."""
    missing = tmp_path / "missing-config"
    assert PluginConfig(config_path_override=missing).config_path == missing


@pytest.mark.parametrize(
    "prop, asset",
    (
        ("fmap_path", FILE_MAPPING),
        ("defaults_path", DEFAULTS),
        ("exporter_rules_path", EXPORTER_RULES),
        ("parser_rules_path", PARSER_RULES),
        ("translation_rules_path", TRANSLATION_RULES),
    ),
)
def test_asset_paths_follow_config_path(prop, asset, tmp_path):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config = SampleConfig(param1="test", config_path_override=config_dir)
    expected = config_dir / asset
    assert getattr(config, prop) == expected


def test_config_path_uses_existing_config_directory(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    module_file = config_dir / "module.py"
    module_file.write_text("# dummy")

    monkeypatch.setattr(
        "r2x_core.plugin_config.inspect.getfile",
        lambda cls: module_file,
    )

    config = SampleConfig(param1="test")
    assert config.config_path == config_dir


def test_config_path_appends_config_directory_when_missing(monkeypatch, tmp_path):
    module_dir = tmp_path / "module"
    module_dir.mkdir()
    module_file = module_dir / "module.py"
    module_file.write_text("# dummy")

    monkeypatch.setattr(
        "r2x_core.plugin_config.inspect.getfile",
        lambda cls: module_file,
    )

    expected = module_dir / "config"
    expected.mkdir()
    config = SampleConfig(param1="test")
    assert config.config_path == expected


def test_load_config_reads_all_assets(tmp_path):
    payloads = {
        FILE_MAPPING: [{"name": "data", "fpath": "file.csv"}],
        DEFAULTS: {"value": 1},
        EXPORTER_RULES: [{"step": "export"}],
        PARSER_RULES: [{"step": "parse"}],
        TRANSLATION_RULES: [{"rule": "map"}],
    }
    write_assets(tmp_path, payloads)

    config = SampleConfig(param1="test")
    result = config.load_config(config_path=tmp_path)

    assert result == {Path(asset).stem: payload for asset, payload in payloads.items()}


def test_load_config_respects_overrides(tmp_path):
    payloads = {
        FILE_MAPPING: [{"name": "data", "fpath": "file.csv"}],
        DEFAULTS: {"value": 1, "items": ["a", "b"]},
        EXPORTER_RULES: [],
        PARSER_RULES: [],
        TRANSLATION_RULES: [],
    }
    write_assets(tmp_path, payloads)

    overrides = {
        "defaults": {"value": 2, "items": ["c"]},
        "file_mapping": [{"name": "data", "fpath": "override.csv"}],
    }

    result = SampleConfig(param1="test").load_config(config_path=tmp_path, overrides=overrides)
    assert result["defaults"]["value"] == 2
    assert result["defaults"]["items"][0] == "c"
    assert result["file_mapping"][0]["fpath"] == "override.csv"


def test_load_config_missing_asset_raises(tmp_path):
    (tmp_path / FILE_MAPPING).write_text(json.dumps([]))
    with pytest.raises(FileNotFoundError):
        SampleConfig(param1="test").load_config(config_path=tmp_path)


def test_merge_with_overrides_merges_scalars():
    base = {"a": 1, "b": 2}
    overrides = {"a": 10}
    result = merge_with_overrides(base, overrides=overrides)
    assert result["a"] == 10
    assert result["b"] == 2


def test_merge_with_overrides_merges_lists():
    base = {"items": ["a", "b", "c"]}
    overrides = {"items": ["x", "y"]}
    result = merge_with_overrides(base, overrides=overrides)
    assert result["items"][0] == "x"
    assert result["items"][1] == "y"
    assert result["items"][2:] == ["c"]


def test_merge_with_overrides_merges_nested_dicts():
    base = {"nested": {"value": 1, "extra": 2}}
    overrides = {"nested": {"value": 10, "new": 5}}
    result = merge_with_overrides(base, overrides=overrides)
    assert result["nested"]["value"] == 10
    assert result["nested"]["extra"] == 2
    assert result["nested"]["new"] == 5
