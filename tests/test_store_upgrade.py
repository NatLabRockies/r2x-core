"""Tests for DataStore upgrade handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, TypedDict

from polars import LazyFrame
from pydantic import Field

from r2x_core import DataStore, PluginConfig, PluginContext


class FileMappingRecord(TypedDict):
    """Typed record for file mapping JSON entries."""

    name: str
    fpath: str


class UpgradeConfig(PluginConfig):
    """PluginConfig for upgrade tests."""

    config_path_override: Annotated[Path, Field(description="Override config path")]


def test_store_runs_upgrade_handler_when_mapping_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    old_path = run_dir / "old.csv"
    old_path.write_text("col\n1\n", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    mapping: list[FileMappingRecord] = [
        {
            "name": "test",
            "fpath": "new.csv",
        }
    ]
    (config_dir / "file_mapping.json").write_text(json.dumps(mapping), encoding="utf-8")

    calls = {"count": 0}

    def upgrade_handler(*, store: DataStore, ctx: PluginContext[Any]) -> None:
        calls["count"] += 1
        (store.folder / "old.csv").rename(store.folder / "new.csv")

    config = UpgradeConfig(config_path_override=config_dir, upgrade_handler=upgrade_handler)
    store = DataStore.from_plugin_config(config, path=run_dir)

    assert calls["count"] == 1

    data = store.read_data("test")
    assert isinstance(data, LazyFrame)
