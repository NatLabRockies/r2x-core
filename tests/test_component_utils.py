import csv
import os
import stat
import subprocess
import sys
import tracemalloc
from pathlib import Path

import pytest
from infrasys import Component
from pydantic import field_serializer
from pydantic_core import PydanticSerializationError

from r2x_core.system import System
from r2x_core.utils import components_to_records, export_components_to_csv


def test_components_to_records_returns_data():
    """Test components_to_records returns list of dictionaries."""
    system = System(name="TestSystem")
    system.add_components(Component(name="comp1"), Component(name="comp2"))

    result = components_to_records(system)
    assert isinstance(result, list)
    assert len(result) == 2


def test_components_to_records_with_filter():
    """Test components_to_records with filter function."""
    system = System(name="FilterTest")
    system.add_components(
        Component(name="keep1"),
        Component(name="skip"),
        Component(name="keep2"),
    )

    result = components_to_records(system, filter_func=lambda c: "keep" in c.name)
    assert len(result) == 2
    assert all("keep" in r["name"] for r in result)


def test_components_to_records_with_fields():
    """Test components_to_records with specific fields."""
    system = System(name="FieldsTest")
    system.add_components(Component(name="test"))

    # Only export name field
    result = components_to_records(system, fields=["name"])
    assert len(result) == 1
    assert "name" in result[0]
    # Should only have the name field
    assert len(result[0]) == 1


def test_components_to_records_with_key_mapping():
    """Test components_to_records with key mapping."""
    system = System(name="MappingTest")
    system.add_components(Component(name="test"))

    result = components_to_records(system, key_mapping={"name": "component_name"})
    assert len(result) == 1
    assert "component_name" in result[0]
    assert result[0]["component_name"] == "test"


def test_export_components_to_csv_to_file(tmp_path):
    """Test export_components_to_csv to file."""
    import csv

    system = System(name="FileTest")
    system.add_components(Component(name="comp1"), Component(name="comp2"))

    output_file = tmp_path / "components.csv"
    export_components_to_csv(system, file_path=output_file)

    assert output_file.exists()

    # Read and verify CSV
    with open(output_file) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["name"] == "comp1"
        assert rows[1]["name"] == "comp2"


def test_export_components_to_csv_empty(tmp_path):
    """Test export_components_to_csv when no components match."""
    system = System(name="EmptyTest")
    system.add_components(Component(name="test"))

    output_file = tmp_path / "empty.csv"
    export_components_to_csv(system, file_path=output_file, filter_func=lambda c: False)

    assert not output_file.exists()


class LargeExportComponent(Component):
    payload: int = 0

    @field_serializer("payload")
    def serialize_payload(self, value: int) -> str:
        return str(value) + "x" * 32768


def test_export_components_to_csv_streams_records(tmp_path: Path) -> None:
    system = System(name="Streaming")
    system.add_components(*(LargeExportComponent(name=f"component-{i}") for i in range(1000)))
    output_file = tmp_path / "streamed.csv"

    tracemalloc.start()
    try:
        export_components_to_csv(system, file_path=output_file, fields=["name", "payload"])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # Eager serialization retains over 32 MB of payloads for this export.
    assert peak < 4_000_000
    with output_file.open(newline="") as stream:
        names = [row["name"] for row in csv.DictReader(stream)]
    assert names == [component.name for component in system.get_components(Component)]


def test_export_components_to_csv_options(tmp_path: Path) -> None:
    system = System(name="Options")
    system.add_components(Component(name="keep2"), Component(name="skip"), Component(name="keep1"))
    output_file = tmp_path / "nested" / "components.csv"
    export_components_to_csv(
        system,
        file_path=output_file,
        fields=["name"],
        key_mapping={"name": "label"},
        filter_func=lambda component: component.name.startswith("keep"),
        delimiter=";",
    )
    with output_file.open(newline="") as stream:
        assert list(csv.DictReader(stream, delimiter=";")) == [{"label": "keep2"}, {"label": "keep1"}]
    assert list(output_file.parent.iterdir()) == [output_file]


def test_export_components_to_csv_empty_preserves_existing_file(tmp_path: Path) -> None:
    system = System(name="Empty")
    output_file = tmp_path / "existing.csv"
    output_file.write_text("original")
    export_components_to_csv(system, file_path=output_file)
    assert output_file.read_text() == "original"


def test_export_components_to_csv_empty_fields_writes_rows(tmp_path: Path) -> None:
    system = System(name="EmptyFields")
    system.add_components(Component(name="first"), Component(name="second"))
    output_file = tmp_path / "empty-fields.csv"
    export_components_to_csv(system, file_path=output_file, fields=[])
    assert output_file.read_bytes() == b"\r\n\r\n\r\n"


class FailingExportComponent(Component):
    payload: int = 0

    @field_serializer("payload")
    def serialize_payload(self, value: int) -> int:
        if value < 0:
            raise ValueError("Cannot serialize negative payload")
        return value


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["serialization", "filter"])
def test_export_components_to_csv_failure_preserves_destination(
    tmp_path: Path, existing: bool, failure: str
) -> None:
    system = System(name="Failure")
    system.add_components(
        FailingExportComponent(name="first", payload=1),
        FailingExportComponent(name="second", payload=-1 if failure == "serialization" else 2),
    )
    output_file = tmp_path / "components.csv"
    if existing:
        output_file.write_bytes(b"original\r\n")

    def filter_component(component: Component) -> bool:
        if failure == "filter" and component.name == "second":
            raise ValueError("Cannot filter second component")
        return True

    expected_error = PydanticSerializationError if failure == "serialization" else ValueError
    with pytest.raises(expected_error):
        export_components_to_csv(system, file_path=output_file, filter_func=filter_component)

    if existing:
        assert output_file.read_bytes() == b"original\r\n"
    else:
        assert not output_file.exists()
    assert list(tmp_path.iterdir()) == ([output_file] if existing else [])


def test_export_components_to_csv_replaces_existing_file(tmp_path: Path) -> None:
    system = System(name="Replacement")
    system.add_components(Component(name="second"), Component(name="first"))
    output_file = tmp_path / "components.csv"
    output_file.write_text("original")

    export_components_to_csv(system, file_path=output_file, fields=["name"])

    with output_file.open(newline="") as stream:
        assert list(csv.DictReader(stream)) == [{"name": "second"}, {"name": "first"}]
    assert list(tmp_path.iterdir()) == [output_file]


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permission semantics")
def test_export_components_to_csv_preserves_existing_permissions(tmp_path: Path) -> None:
    system = System(name="Permissions")
    system.add_components(Component(name="first"))
    output_file = tmp_path / "components.csv"
    output_file.write_text("original")
    output_file.chmod(0o640)

    export_components_to_csv(system, file_path=output_file, fields=["name"])

    assert stat.S_IMODE(output_file.stat().st_mode) == 0o640


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permission semantics")
def test_export_components_to_csv_respects_umask(tmp_path: Path) -> None:
    output_file = tmp_path / "components.csv"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys; from infrasys import Component; "
            "from r2x_core import System, export_components_to_csv; "
            "os.umask(0o022); system = System(name='Permissions'); "
            "system.add_components(Component(name='first')); "
            "export_components_to_csv(system, file_path=sys.argv[1], fields=['name'])",
            str(output_file),
        ],
        check=True,
    )
    assert stat.S_IMODE(output_file.stat().st_mode) == 0o644


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permission semantics")
def test_export_components_to_csv_stages_with_restricted_permissions(tmp_path: Path) -> None:
    system = System(name="Restricted")
    system.add_components(Component(name="first"), Component(name="second"))
    output_file = tmp_path / "components.csv"
    output_file.write_text("original")
    output_file.chmod(0o600)
    observed_modes: list[int] = []

    def inspect_staging(component: Component) -> bool:
        if component.name == "second":
            staging_files = [path for path in tmp_path.iterdir() if path != output_file]
            assert len(staging_files) == 1
            observed_modes.append(stat.S_IMODE(staging_files[0].stat().st_mode))
        return True

    export_components_to_csv(system, file_path=output_file, filter_func=inspect_staging)

    assert observed_modes == [0o600]
    assert list(tmp_path.iterdir()) == [output_file]


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink semantics")
def test_export_components_to_csv_preserves_symlink(tmp_path: Path) -> None:
    system = System(name="Symlink")
    system.add_components(Component(name="first"))
    target = tmp_path / "target" / "components.csv"
    target.parent.mkdir()
    target.write_text("original")
    link = tmp_path / "linked.csv"
    link.symlink_to(target.relative_to(tmp_path))

    export_components_to_csv(system, file_path=link, fields=["name"])

    assert link.is_symlink()
    assert link.read_bytes() == target.read_bytes() == b"name\r\nfirst\r\n"
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.skipif(os.name != "posix", reason="POSIX filename length semantics")
def test_export_components_to_csv_supports_long_filenames(tmp_path: Path) -> None:
    system = System(name="LongFilename")
    system.add_components(Component(name="first"))
    output_file = tmp_path / ("x" * 236 + ".csv")

    export_components_to_csv(system, file_path=output_file, fields=["name"])

    assert output_file.read_bytes() == b"name\r\nfirst\r\n"
    assert list(tmp_path.iterdir()) == [output_file]


@pytest.mark.skipif(os.name != "posix", reason="POSIX file permission semantics")
def test_export_components_to_csv_preserves_read_only_destination(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("Root can write read-only files")
    system = System(name="ReadOnly")
    system.add_components(Component(name="first"))
    output_file = tmp_path / "components.csv"
    output_file.write_bytes(b"original")
    output_file.chmod(0o444)
    try:
        with pytest.raises(PermissionError):
            export_components_to_csv(system, file_path=output_file)
        assert output_file.read_bytes() == b"original"
        assert stat.S_IMODE(output_file.stat().st_mode) == 0o444
        assert list(tmp_path.iterdir()) == [output_file]
    finally:
        output_file.chmod(0o600)
