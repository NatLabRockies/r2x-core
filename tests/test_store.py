"""Tests for file-mapping configuration storage."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from r2x_core import DataFile, DataStore

pytestmark = pytest.mark.system


def test_store_requires_directory_and_resolves_it(tmp_path: Path) -> None:
    """Keep execution paths separate from the mapping configuration object."""
    folder = tmp_path / "inputs"
    folder.mkdir()
    store = DataStore(folder)
    assert store.folder == folder.resolve()
    with pytest.raises(NotADirectoryError):
        DataStore(tmp_path / "missing")
    mapping = tmp_path / "file_mapping.json"
    mapping.write_text("[]", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        DataStore(mapping)


def test_mapping_store_crud_and_serialization(tmp_path: Path) -> None:
    """Manage validated mappings without reading the configured physical inputs."""
    input_path = tmp_path / "input.csv"
    item = DataFile(name="input", relative_fpath="input.csv")
    store = DataStore(tmp_path)
    store.add_data([item])

    assert store.list_data() == ["input"]
    assert store["input"] is item
    assert "input" in store
    with pytest.raises(KeyError, match="missing"):
        _ = store["missing"]
    with pytest.raises(KeyError, match="input"):
        store.add_data([item])
    store.add_data([item], overwrite=True)
    with pytest.raises(KeyError, match="missing"):
        store.remove_data("missing")
    store.remove_data("input")
    assert store.list_data() == []

    store.add_data([item])
    serialized = tmp_path / "mapping.json"
    store.to_json(serialized, exclude_none=True)
    loaded = DataStore(tmp_path)
    loaded.load_file_mapping(serialized)
    assert loaded["input"].relative_fpath == Path("input.csv")
    assert not input_path.exists()


def test_mapping_validation_rejects_invalid_records(tmp_path: Path) -> None:
    """Reject malformed JSON mappings at their configuration boundary."""
    mapping = tmp_path / "invalid.json"
    mapping.write_text('[{"name": 5, "relative_fpath": "input.csv"}]', encoding="utf-8")
    with pytest.raises(ValidationError):
        DataStore(tmp_path).load_file_mapping(mapping)

    mapping.write_text('{"name":"not-an-array"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        DataStore(tmp_path).load_file_mapping(mapping)


def test_mapping_store_rejects_duplicate_names_within_one_batch(tmp_path: Path) -> None:
    """Keep each configured physical or derived source uniquely addressable."""
    store = DataStore(tmp_path)
    with pytest.raises(TypeError, match="only DataFile instances"):
        store.add_data([object()])  # type: ignore[list-item]
    records = [{"name": name, "relative_fpath": f"{name}.csv"} for name in ("duplicate", "duplicate")]
    with pytest.raises(KeyError, match="duplicate"):
        store.add_data([DataFile.model_validate(record) for record in records])
    assert store.list_data() == []
