"""Compatibility factory behavior for plugin-configured data stores."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from r2x_core import DataStore, PluginConfig, PluginContext

pytestmark = pytest.mark.system


class StoreConfig(PluginConfig):
    """Plugin configuration used by DataStore factory tests."""


def test_from_plugin_config_returns_empty_store_when_mapping_is_missing(tmp_path: Path) -> None:
    """Treat an absent optional file mapping as an empty store."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config = StoreConfig(config_path_override=config_dir)

    store = DataStore.from_plugin_config(config, path=data_dir)

    assert store.folder == data_dir.resolve()
    assert store.list_data() == []
    assert store.upgrade_coordinator.plugin_config is config


def test_from_plugin_config_loads_mapping_with_the_new_store_api(tmp_path: Path) -> None:
    """Load mapped inputs rooted at the configured data directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "input.csv").write_text("value\n1\n", encoding="utf-8")
    (config_dir / "file_mapping.json").write_text(
        '[{"name":"input","relative_fpath":"input.csv"}]', encoding="utf-8"
    )
    config = StoreConfig(config_path_override=config_dir)

    store = DataStore.from_plugin_config(config, path=data_dir)

    assert store.list_data() == ["input"]
    assert store["input"].relative_fpath == Path("input.csv")


def test_from_plugin_config_runs_upgrade_and_retries_missing_required_file(tmp_path: Path) -> None:
    """Retry loading after the configured handler restores a required file."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    missing_file = data_dir / "input.csv"
    (config_dir / "file_mapping.json").write_text(
        json.dumps([{"name": "input", "relative_fpath": "input.csv"}]), encoding="utf-8"
    )
    calls = 0

    def upgrade_handler(*, store: DataStore, ctx: PluginContext[StoreConfig]) -> None:
        nonlocal calls
        calls += 1
        assert store.list_data() == []
        assert ctx.store is store
        missing_file.write_text("value\n1\n", encoding="utf-8")

    config = StoreConfig(config_path_override=config_dir, upgrade_handler=upgrade_handler)

    store = DataStore.from_plugin_config(config, path=data_dir)

    assert calls == 1
    assert store.list_data() == ["input"]
    assert store.upgrade_coordinator.ran


def test_from_plugin_config_does_not_run_upgrade_for_invalid_mapping(tmp_path: Path) -> None:
    """Do not treat unrelated mapping validation errors as upgrade requests."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (config_dir / "file_mapping.json").write_text("{}", encoding="utf-8")
    calls = 0

    def upgrade_handler(*, store: DataStore, ctx: PluginContext[StoreConfig]) -> None:
        nonlocal calls
        calls += 1

    config = StoreConfig(config_path_override=config_dir, upgrade_handler=upgrade_handler)

    with pytest.raises(ValidationError):
        DataStore.from_plugin_config(config, path=data_dir)

    assert calls == 0


def test_from_plugin_config_retries_once_if_upgrade_does_not_restore_missing_file(
    tmp_path: Path,
) -> None:
    """Fail after one retry when the configured handler leaves a required input absent."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (config_dir / "file_mapping.json").write_text(
        json.dumps([{"name": "input", "relative_fpath": "input.csv"}]), encoding="utf-8"
    )
    calls = 0

    def upgrade_handler(*, store: DataStore, ctx: PluginContext[StoreConfig]) -> None:
        nonlocal calls
        calls += 1
        assert store.list_data() == []
        assert ctx.store is store

    config = StoreConfig(config_path_override=config_dir, upgrade_handler=upgrade_handler)

    with pytest.raises(ValidationError, match="Missing required file"):
        DataStore.from_plugin_config(config, path=data_dir)

    assert calls == 1


def test_from_plugin_config_does_not_upgrade_optional_template_or_inline_inputs(
    tmp_path: Path,
) -> None:
    """Keep optional, templated, and non-physical inputs out of legacy file checks."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    mapping = [
        {
            "name": "optional",
            "relative_fpath": "optional.csv",
            "info": {"requirement": "optional"},
        },
        {"name": "template", "relative_fpath": "{year}/template.csv"},
        {"name": "inline", "inline_table": {"schema": {"value": "int64"}, "rows": [{"value": 1}]}},
    ]
    (config_dir / "file_mapping.json").write_text(json.dumps(mapping), encoding="utf-8")
    calls = 0

    def upgrade_handler(*, store: DataStore, ctx: PluginContext[StoreConfig]) -> None:
        nonlocal calls
        calls += 1

    config = StoreConfig(config_path_override=config_dir, upgrade_handler=upgrade_handler)

    store = DataStore.from_plugin_config(config, path=data_dir)

    assert store.list_data() == ["inline", "optional", "template"]
    assert calls == 0


def test_from_plugin_config_reports_missing_required_file_without_handler(tmp_path: Path) -> None:
    """Raise a validation error when a required mapped file is absent."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (config_dir / "file_mapping.json").write_text(
        json.dumps([{"name": "input", "relative_fpath": "input.csv"}]), encoding="utf-8"
    )
    config = StoreConfig(config_path_override=config_dir)

    with pytest.raises(ValidationError, match="Missing required file"):
        DataStore.from_plugin_config(config, path=data_dir)
