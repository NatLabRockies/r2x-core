"""Ensure configured system construction retains input upgrades."""

from pathlib import Path

import pytest
from fixtures.ingestion_models import PSSEBus

from r2x_core import DataStore, PluginConfig, PluginContext, build_system


class UpgradeConfig(PluginConfig):
    """Configuration model used by the upgrade integration test."""


@pytest.mark.polars
def test_missing_table_mapping_does_not_run_input_upgrade_handler(tmp_path: Path) -> None:
    """A missing assembly configuration is not treated as a missing input file."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "buses.csv").write_text("name,number,base_kv\nNORTH,1,230\n", encoding="utf-8")
    (config_dir / "file_mapping.json").write_text(
        '[{"name":"buses","relative_fpath":"buses.csv"}]', encoding="utf-8"
    )
    (config_dir / "parser_rules.json").write_text(
        '[{"kind":"component","source":"buses","component_type":"PSSEBus",'
        '"fields":{"name":"name","number":"number"}}]',
        encoding="utf-8",
    )
    marker = tmp_path / "upgrade-ran"

    def upgrade_handler(*, store: DataStore, ctx: PluginContext[UpgradeConfig]) -> None:
        marker.write_text("ran", encoding="utf-8")

    config = UpgradeConfig(
        models=("fixtures.ingestion_models",),
        config_path_override=config_dir,
        upgrade_handler=upgrade_handler,
    )

    with pytest.raises(FileNotFoundError, match=r"table_mapping\.json"):
        build_system(
            config,
            name="missing-table-mapping",
            input_folder=config_dir,
            table_mapping_path=config_dir / "table_mapping.json",
        )

    assert not marker.exists()


def test_build_system_with_table_mapping_runs_upgrade_for_missing_physical_input_once(
    tmp_path: Path,
) -> None:
    """A real missing input still triggers one upgrade and retries the same mapping snapshot."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "file_mapping.json").write_text(
        '[{"name":"buses","relative_fpath":"new.csv"}]', encoding="utf-8"
    )
    (config_dir / "table_mapping.json").write_text(
        '[{"name":"mapped_buses","source":"buses","operations":[]}]', encoding="utf-8"
    )
    (config_dir / "parser_rules.json").write_text(
        '[{"kind":"component","source":"mapped_buses","component_type":"PSSEBus",'
        '"fields":{"name":"name","number":"number"}}]',
        encoding="utf-8",
    )
    marker = tmp_path / "upgrade-ran"
    calls = 0

    def upgrade_handler(*, store: DataStore, ctx: PluginContext[UpgradeConfig]) -> None:
        nonlocal calls
        calls += 1
        marker.write_text("ran", encoding="utf-8")
        (store.folder / "new.csv").write_text("name,number,base_kv\nNORTH,1,230\n", encoding="utf-8")

    config = UpgradeConfig(
        models=("fixtures.ingestion_models",),
        config_path_override=config_dir,
        upgrade_handler=upgrade_handler,
    )

    system = build_system(
        config,
        name="upgraded-with-mapping",
        input_folder=config_dir,
        table_mapping_path=config_dir / "table_mapping.json",
    )

    assert calls == 1
    assert marker.read_text(encoding="utf-8") == "ran"
    assert [bus.name for bus in system.get_components(PSSEBus)] == ["NORTH"]


def test_build_system_runs_upgrade_handler_when_input_is_missing(tmp_path: Path) -> None:
    """Retry configured reads after the handler updates the input directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "old.csv").write_text("name,number,base_kv\nNORTH,1,230\n", encoding="utf-8")
    (config_dir / "file_mapping.json").write_text(
        '[{"name":"buses","relative_fpath":"new.csv"}]', encoding="utf-8"
    )
    (config_dir / "parser_rules.json").write_text(
        '[{"kind":"component","source":"buses","component_type":"PSSEBus",'
        '"fields":{"name":"name","number":"number"}}]',
        encoding="utf-8",
    )
    calls = 0

    def upgrade_handler(*, store: DataStore, ctx: PluginContext[UpgradeConfig]) -> None:
        nonlocal calls
        calls += 1
        (store.folder / "old.csv").rename(store.folder / "new.csv")

    config = UpgradeConfig(
        models=("fixtures.ingestion_models",),
        config_path_override=config_dir,
        upgrade_handler=upgrade_handler,
    )
    system = build_system(config, name="upgraded", input_folder=config_dir)

    assert calls == 1
    assert [bus.name for bus in system.get_components(PSSEBus)] == ["NORTH"]
