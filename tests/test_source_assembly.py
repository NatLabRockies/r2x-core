"""Public tests for scheduling file inputs and table mappings together."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import h5py
import polars as pl
import pytest

from r2x_core import (
    DataFile,
    DataReader,
    DecodedSource,
    DecodedSources,
    InputColumn,
    ReaderConfig,
    SourceAvailability,
    TabularSource,
    assemble_tables,
)
from r2x_core.exceptions import ReaderError
from r2x_core.models import StrictConfigModel
from r2x_core.polars_adapter import PolarsTabularBackend, PolarsTabularFileReader


def make_data_files(*, needs_fuel: bool, fuel_path: str = "custom/fuel.csv") -> list[DataFile]:
    """Build one conditional input graph without relying on application code."""
    return [
        DataFile.model_validate(
            {
                "name": "capacity",
                "inline_table": {
                    "schema": {"needs_fuel": "bool"},
                    "rows": [{"needs_fuel": needs_fuel}],
                },
            }
        ),
        DataFile.model_validate(
            {
                "name": "fuel_map",
                "relative_fpath": fuel_path,
                "info": {"requirement": "optional"},
                "columns": [{"name": "fuel_type", "dtype": "string"}],
                "required_when": {"source": "fuel_gate", "predicate": "required"},
            }
        ),
        DataFile.model_validate(
            {
                "name": "selected_fuel",
                "source_selection": {
                    "mode": "first_present",
                    "sources": ["fuel_map"],
                    "empty_fallback": {
                        "schema": {"fuel_type": "string"},
                        "rows": [{"fuel_type": "fallback"}],
                    },
                },
            }
        ),
    ]


def write_table_mapping(tmp_path: Path, records: list[dict[str, object]] | None = None) -> Path:
    """Write a compact table gate used by the file requirement predicate."""
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            records
            if records is not None
            else [
                {
                    "name": "fuel_gate",
                    "source": "capacity",
                    "operations": [
                        {
                            "operation": "filter",
                            "column": "needs_fuel",
                            "comparison": "equals",
                            "value": True,
                        }
                    ],
                    "columns": {"required": "needs_fuel"},
                }
            ]
        ),
        encoding="utf-8",
    )
    return mapping_path


def assemble_sources(
    data_files: list[DataFile],
    *,
    folder_path: Path,
    mapping_path: Path,
    initial_sources: Mapping[str, DecodedSource] | None = None,
    initial_tables: Mapping[str, TabularSource] | None = None,
    reader: DataReader | None = None,
) -> DecodedSources:
    """Call the public reader/table integration through its shared backend."""
    data_reader = DataReader() if reader is None else reader
    return data_reader.read_and_assemble_sources(
        data_files,
        folder_path=folder_path,
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
        initial_sources=initial_sources,
        initial_tables=initial_tables,
    )


def test_table_gate_schedules_required_input_at_its_configured_custom_path(tmp_path: Path) -> None:
    """A table output gates the real file read without duplicating its policy."""
    custom_path = tmp_path / "custom" / "fuel.csv"
    custom_path.parent.mkdir()
    custom_path.write_text("fuel_type\ngas\n", encoding="utf-8")
    mapping_path = write_table_mapping(tmp_path)

    sources = assemble_sources(
        make_data_files(needs_fuel=True), folder_path=tmp_path, mapping_path=mapping_path
    )

    assert list(sources["selected_fuel"].iter_rows()) == [{"fuel_type": "gas"}]
    assert list(sources) == ["capacity", "fuel_gate", "fuel_map", "selected_fuel"]


@pytest.mark.parametrize("file_exists", [False, True], ids=["absent", "present-empty"])
def test_optional_input_keeps_absent_and_present_empty_distinct(tmp_path: Path, file_exists: bool) -> None:
    """An absent optional file uses the fallback while a present-empty file wins selection."""
    if file_exists:
        custom_path = tmp_path / "custom" / "fuel.csv"
        custom_path.parent.mkdir()
        custom_path.write_text("fuel_type\n", encoding="utf-8")
    mapping_path = write_table_mapping(tmp_path)

    sources = assemble_sources(
        make_data_files(needs_fuel=False), folder_path=tmp_path, mapping_path=mapping_path
    )

    fuel_map = sources["fuel_map"]
    assert isinstance(fuel_map, TabularSource)
    assert fuel_map.availability is (SourceAvailability.PRESENT if file_exists else SourceAvailability.ABSENT)
    assert list(sources["selected_fuel"].iter_rows()) == ([] if file_exists else [{"fuel_type": "fallback"}])


def test_first_present_skips_declared_missing_source_and_selects_present_empty_file(tmp_path: Path) -> None:
    """Skip an omitted but declared optional file and preserve present-empty precedence."""
    empty_path = tmp_path / "empty.csv"
    empty_path.write_text("value\n", encoding="utf-8")
    data_files = [
        DataFile.model_validate(
            {
                "name": "missing",
                "relative_fpath": "missing.csv",
                "info": {"requirement": "optional"},
            }
        ),
        DataFile.model_validate(
            {
                "name": "empty",
                "relative_fpath": "empty.csv",
                "reader": {"format": "csv"},
                "columns": [{"name": "value", "dtype": "int64"}],
            }
        ),
    ]
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {
                "name": "empty_fallback",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "value", "dtype": "int64"}], "values": []}
                ],
            },
            {
                "name": "selected",
                "operations": [
                    {"operation": "first_present", "sources": ["missing", "empty", "empty_fallback"]}
                ],
            },
        ],
    )

    sources = assemble_sources(data_files, folder_path=tmp_path, mapping_path=mapping_path)

    assert "missing" not in sources
    assert sources["empty"].availability is SourceAvailability.PRESENT
    assert sources["selected"] is sources["empty"]
    assert sources["selected"].fields() == ["value"]
    assert list(sources["selected"].iter_rows()) == []


def test_first_present_skips_missing_optional_hdf_group_without_native_schema(tmp_path: Path) -> None:
    """A missing HDF group is skippable only when the configured group is truly absent."""
    with h5py.File(tmp_path / "inputs.h5", "w") as handle:
        handle.create_group("other")
    data_file = DataFile.model_validate(
        {
            "name": "fuel_group",
            "relative_fpath": "inputs.h5",
            "info": {"requirement": "optional"},
            "reader": {
                "format": "hdf5",
                "options": {
                    "group_key": "fuel",
                    "columns_key": "columns",
                    "columns_as_datasets": True,
                },
            },
        }
    )
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {
                "name": "fallback",
                "operations": [
                    {
                        "operation": "rows",
                        "schema": [{"name": "id", "dtype": "int64"}],
                        "values": [{"id": 99}],
                    }
                ],
            },
            {
                "name": "selected",
                "operations": [{"operation": "first_present", "sources": ["fuel_group", "fallback"]}],
            },
        ],
    )

    sources = DataReader().read_and_assemble_sources(
        [data_file],
        folder_path=tmp_path,
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
    )

    assert "fuel_group" not in sources
    assert sources["selected"] is sources["fallback"]
    assert list(sources["selected"].iter_rows()) == [{"id": 99}]


def test_first_present_does_not_hide_a_malformed_existing_hdf_group(tmp_path: Path) -> None:
    """A present but incomplete HDF group is an input error, not an absent candidate."""
    with h5py.File(tmp_path / "inputs.h5", "w") as handle:
        group = handle.create_group("fuel")
        group.create_dataset("columns", data=[b"id"])
    data_file = DataFile.model_validate(
        {
            "name": "fuel_group",
            "relative_fpath": "inputs.h5",
            "info": {"requirement": "optional"},
            "reader": {
                "format": "hdf5",
                "options": {
                    "group_key": "fuel",
                    "columns_key": "columns",
                    "columns_as_datasets": True,
                },
            },
        }
    )
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {
                "name": "fallback",
                "operations": [
                    {
                        "operation": "rows",
                        "schema": [{"name": "id", "dtype": "int64"}],
                        "values": [{"id": 99}],
                    }
                ],
            },
            {
                "name": "selected",
                "operations": [{"operation": "first_present", "sources": ["fuel_group", "fallback"]}],
            },
        ],
    )

    with pytest.raises(KeyError, match="HDF5 column dataset 'id' not found"):
        DataReader().read_and_assemble_sources(
            [data_file],
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
        )


@pytest.mark.parametrize(
    "source_state",
    ["omitted", "absent-schema", "present-empty"],
    ids=["declared-but-omitted", "schema-bearing-absent", "present-empty"],
)
def test_first_nonempty_skips_missing_and_empty_declared_inputs(tmp_path: Path, source_state: str) -> None:
    """A nonempty selector skips optional missing and empty inputs to its typed fallback."""
    present = source_state == "present-empty"
    if present:
        (tmp_path / "candidate.csv").write_text("value\n", encoding="utf-8")
    candidate_record: dict[str, object] = {
        "name": "candidate",
        "relative_fpath": "candidate.csv",
        "reader": {"format": "csv"},
        "info": {"requirement": "optional"},
    }
    if source_state != "omitted":
        candidate_record["columns"] = [{"name": "value", "dtype": "string"}]
    candidate = DataFile.model_validate(candidate_record)
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {
                "name": "empty_fallback",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "value", "dtype": "string"}], "values": []}
                ],
            },
            {
                "name": "selected",
                "operations": [
                    {"operation": "first_nonempty", "sources": ["candidate"], "fallback": "empty_fallback"}
                ],
            },
        ],
    )

    sources = assemble_sources([candidate], folder_path=tmp_path, mapping_path=mapping_path)

    assert ("candidate" in sources) is (source_state != "omitted")
    assert sources["selected"] is sources["empty_fallback"]
    assert sources["selected"].availability is SourceAvailability.PRESENT
    assert sources["selected"].fields() == ["value"]
    assert list(sources["selected"].iter_rows()) == []


def test_first_nonempty_fallback_is_an_ordered_table_dependency(tmp_path: Path) -> None:
    """The typed fallback must be declared before the source-free constructor."""
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {
                "name": "selected",
                "operations": [
                    {"operation": "first_nonempty", "sources": ["candidate"], "fallback": "later_empty"}
                ],
            },
            {
                "name": "later_empty",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "value", "dtype": "string"}], "values": []}
                ],
            },
        ],
    )

    candidate = DataFile.model_validate(
        {"name": "candidate", "inline_table": {"schema": {"value": "string"}, "rows": [{"value": "ready"}]}}
    )

    with pytest.raises(ValueError, match="referenced before it is declared"):
        assemble_sources([candidate], folder_path=tmp_path, mapping_path=mapping_path)


def test_first_present_does_not_hide_a_malformed_present_input(tmp_path: Path) -> None:
    """A present source decode error is not replaced by a later empty candidate."""
    bad_path = tmp_path / "bad.csv"
    bad_path.write_text("value\nnot-an-integer\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "bad",
            "relative_fpath": "bad.csv",
            "reader": {"format": "csv"},
            "info": {"requirement": "optional"},
            "columns": [{"name": "value", "dtype": "int64"}],
        }
    )
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {
                "name": "empty_fallback",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "value", "dtype": "int64"}], "values": []}
                ],
            },
            {
                "name": "selected",
                "operations": [{"operation": "first_present", "sources": ["bad", "empty_fallback"]}],
            },
        ],
    )

    with pytest.raises((ReaderError, pl.exceptions.PolarsError)):
        sources = assemble_sources([data_file], folder_path=tmp_path, mapping_path=mapping_path)
        list(sources["selected"].iter_rows())


def test_first_present_unknown_reference_fails_before_physical_input_io(tmp_path: Path) -> None:
    """Preflight rejects an unknown candidate before opening an unrelated required file."""
    required = DataFile.model_validate(
        {"name": "required", "relative_fpath": "missing.csv", "reader": {"format": "csv"}}
    )
    mapping_path = write_table_mapping(
        tmp_path,
        [{"name": "selected", "operations": [{"operation": "first_present", "sources": ["unknown"]}]}],
    )

    with pytest.raises(ValueError, match="Unknown source 'unknown'"):
        assemble_sources([required], folder_path=tmp_path, mapping_path=mapping_path)


def test_first_present_candidate_cycle_is_rejected_before_file_io(tmp_path: Path) -> None:
    """A selected table cannot also gate the optional file it chooses."""
    candidate = DataFile.model_validate(
        {
            "name": "candidate",
            "relative_fpath": "missing.csv",
            "info": {"requirement": "optional"},
            "columns": [{"name": "value", "dtype": "string"}],
            "required_when": {"source": "selected", "predicate": "required"},
        }
    )
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {
                "name": "fallback",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "value", "dtype": "string"}], "values": []}
                ],
            },
            {
                "name": "selected",
                "operations": [{"operation": "first_present", "sources": ["candidate", "fallback"]}],
            },
        ],
    )

    with pytest.raises(ValueError, match="dependency cycle"):
        assemble_sources([candidate], folder_path=tmp_path, mapping_path=mapping_path)


def test_first_present_rejects_forward_table_candidates(tmp_path: Path) -> None:
    """A first-present constructor may reference only earlier table records."""
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {"name": "selected", "operations": [{"operation": "first_present", "sources": ["later"]}]},
            {
                "name": "later",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "value", "dtype": "int64"}], "values": []}
                ],
            },
        ],
    )

    with pytest.raises(ValueError, match="referenced before it is declared"):
        assemble_sources([], folder_path=tmp_path, mapping_path=mapping_path)


def test_table_gate_still_requires_missing_conditional_input(tmp_path: Path) -> None:
    """A required_when match preserves the configured missing-file error."""
    mapping_path = write_table_mapping(tmp_path)

    with pytest.raises(FileNotFoundError, match=r"custom/fuel\.csv"):
        assemble_sources(make_data_files(needs_fuel=True), folder_path=tmp_path, mapping_path=mapping_path)


def test_malformed_present_conditional_input_is_not_treated_as_absent(tmp_path: Path) -> None:
    """A declared native conversion error propagates for a present required input."""
    custom_path = tmp_path / "custom" / "fuel.csv"
    custom_path.parent.mkdir()
    custom_path.write_text("fuel_type\nnot-an-integer\n", encoding="utf-8")
    files = make_data_files(needs_fuel=True)
    files[1] = files[1].model_copy(update={"columns": [InputColumn(name="fuel_type", dtype="int64")]})
    mapping_path = write_table_mapping(tmp_path)

    with pytest.raises((ReaderError, pl.exceptions.PolarsError)):
        sources = assemble_sources(files, folder_path=tmp_path, mapping_path=mapping_path)
        list(sources["fuel_map"].iter_rows())


def test_initial_assembled_output_is_reused_for_file_requirements(tmp_path: Path) -> None:
    """A supplied table result satisfies the graph node instead of rerunning its mapping."""
    mapping_path = write_table_mapping(tmp_path)
    backend = PolarsTabularBackend()
    preassembled_gate = TabularSource(
        pl.DataFrame(schema={"required": pl.Boolean}).lazy(),
        backend,
    )

    sources = assemble_sources(
        make_data_files(needs_fuel=True),
        folder_path=tmp_path,
        mapping_path=mapping_path,
        initial_tables={"fuel_gate": preassembled_gate},
    )

    assert sources["fuel_gate"] is preassembled_gate
    assert list(sources["selected_fuel"].iter_rows()) == [{"fuel_type": "fallback"}]


class CountingTabularReader(PolarsTabularFileReader):
    """Count calls while delegating every decode to the production Polars reader."""

    def __init__(self) -> None:
        super().__init__()
        self.read_count = 0

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        self.read_count += 1
        return super().read_file(format_name, file_path=file_path, reader_config=reader_config)


def test_file_decode_is_reused_across_a_table_dependency_boundary(tmp_path: Path) -> None:
    """Repeated declarations of one real file share the reader's execution cache."""
    shared_path = tmp_path / "shared.csv"
    shared_path.write_text("requires\ntrue\n", encoding="utf-8")
    data_files = [
        DataFile.model_validate(
            {
                "name": "first",
                "relative_fpath": "shared.csv",
                "columns": [{"name": "requires", "dtype": "bool"}],
            }
        ),
        DataFile.model_validate(
            {
                "name": "second",
                "relative_fpath": "shared.csv",
                "info": {"requirement": "optional"},
                "columns": [{"name": "requires", "dtype": "bool"}],
                "required_when": {
                    "source": "gate",
                    "predicate": {"eq": ["needs_second", True]},
                },
            }
        ),
    ]
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {
                "name": "gate",
                "source": "first",
                "operations": [],
                "columns": {"needs_second": "requires"},
            }
        ],
    )
    file_reader = CountingTabularReader()
    reader = DataReader(file_readers={"csv": file_reader})

    sources = assemble_sources(
        data_files,
        folder_path=tmp_path,
        mapping_path=mapping_path,
        reader=reader,
    )

    assert list(sources["second"].iter_rows()) == [{"requires": True}]
    assert file_reader.read_count == 1


def test_optional_input_without_declared_schema_still_supports_source_selection(tmp_path: Path) -> None:
    """A missing optional file remains a declared candidate without fabricating a source."""
    data_files = [
        DataFile.model_validate(
            {
                "name": "optional_input",
                "relative_fpath": "missing/optional.csv",
                "info": {"requirement": "optional"},
            }
        ),
        DataFile.model_validate(
            {
                "name": "selected_input",
                "source_selection": {
                    "mode": "first_present",
                    "sources": ["optional_input"],
                    "empty_fallback": {"schema": {"value": "string"}, "rows": [{"value": "fallback"}]},
                },
            }
        ),
    ]
    mapping_path = write_table_mapping(tmp_path, [])

    sources = assemble_sources(data_files, folder_path=tmp_path, mapping_path=mapping_path)

    assert "optional_input" not in sources
    assert list(sources["selected_input"].iter_rows()) == [{"value": "fallback"}]


class RemoveMappingOptions(StrictConfigModel):
    """Accept no options for the temporary mapping-removal test handler."""


class RemoveMappingHandler:
    """Remove one real mapping file while leaving the input frame unchanged."""

    def __init__(self, mapping_path: Path) -> None:
        self.mapping_path = mapping_path

    @property
    def options_model(self) -> type[RemoveMappingOptions]:
        return RemoveMappingOptions

    @property
    def input_type(self) -> type[pl.LazyFrame]:
        return pl.LazyFrame

    @property
    def output_type(self) -> type[pl.LazyFrame]:
        return pl.LazyFrame

    def apply(self, value: pl.LazyFrame, *, options: RemoveMappingOptions) -> pl.LazyFrame:
        self.mapping_path.unlink()
        return value


def test_mapping_snapshot_is_reused_after_a_handler_removes_its_file(tmp_path: Path) -> None:
    """All scheduled table batches execute the records validated before input work."""
    mapping_path = write_table_mapping(
        tmp_path,
        [
            {"name": "first_gate", "source": "capacity", "operations": []},
            {"name": "final_rows", "source": "later_file", "operations": []},
        ],
    )
    later_path = tmp_path / "later.csv"
    later_path.write_text("requires\ntrue\n", encoding="utf-8")
    capacity = DataFile.model_validate(
        {
            "name": "capacity",
            "inline_table": {"schema": {"requires": "bool"}, "rows": [{"requires": True}]},
            "proc_spec": {"kind": "tabular", "steps": [{"op": "custom", "handler": "remove_mapping"}]},
        }
    )
    later_file = DataFile.model_validate(
        {
            "name": "later_file",
            "relative_fpath": "later.csv",
            "info": {"requirement": "optional"},
            "columns": [{"name": "requires", "dtype": "bool"}],
            "required_when": {"source": "first_gate", "predicate": {"eq": ["requires", True]}},
        }
    )
    reader = DataReader(step_handlers={"remove_mapping": RemoveMappingHandler(mapping_path)})

    sources = assemble_sources(
        [capacity, later_file],
        folder_path=tmp_path,
        mapping_path=mapping_path,
        reader=reader,
    )

    assert not mapping_path.exists()
    assert list(sources["final_rows"].iter_rows()) == [{"requires": True}]


def test_assemble_tables_validates_a_seeded_output_declaration(tmp_path: Path) -> None:
    """Reusing a table result does not hide its declared unknown source."""
    mapping_path = write_table_mapping(
        tmp_path,
        [{"name": "seed", "source": "missing", "operations": []}],
    )
    seeded = TabularSource(pl.DataFrame(schema={"id": pl.Int64}).lazy(), PolarsTabularBackend())

    with pytest.raises(ValueError, match=r"(?i)unknown"):
        assemble_tables(
            {},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables={"seed": seeded},
        )


def test_preassembled_table_does_not_mask_unknown_dependencies(tmp_path: Path) -> None:
    """An initial output can replace a table calculation, not invalid declarations."""
    mapping_path = write_table_mapping(
        tmp_path,
        [{"name": "fuel_gate", "source": "missing_table_source", "operations": []}],
    )
    preassembled_gate = TabularSource(
        pl.DataFrame(schema={"required": pl.Boolean}).lazy(),
        PolarsTabularBackend(),
    )

    with pytest.raises(ValueError, match=r"(?i)unknown"):
        assemble_sources(
            make_data_files(needs_fuel=True, fuel_path="missing/never-read.csv"),
            folder_path=tmp_path,
            mapping_path=mapping_path,
            initial_tables={"fuel_gate": preassembled_gate},
        )


def test_undeclared_initial_table_is_rejected_before_reading_files(tmp_path: Path) -> None:
    """Reject an unknown seed before attempting an unrelated missing physical input."""
    mapping_path = write_table_mapping(tmp_path, [])
    missing_file = DataFile.model_validate({"name": "missing_input", "relative_fpath": "missing.csv"})
    initial_table = TabularSource(
        pl.DataFrame({"value": [1]}, schema={"value": pl.Int64}).lazy(),
        PolarsTabularBackend(),
    )

    with pytest.raises(ValueError, match="Initial tables are not declared in table mapping"):
        assemble_sources(
            [missing_file],
            folder_path=tmp_path,
            mapping_path=mapping_path,
            initial_tables={"undeclared": initial_table},
        )


@pytest.mark.parametrize("cycle", [False, True], ids=["unknown-reference", "cycle"])
def test_invalid_cross_references_are_rejected_before_reading_files(tmp_path: Path, cycle: bool) -> None:
    """Unknown dependencies and true cross-boundary cycles fail before input I/O."""
    files = make_data_files(needs_fuel=True, fuel_path="missing/never-read.csv")
    if cycle:
        mapping_records = [
            {
                "name": "fuel_gate",
                "source": "fuel_map",
                "operations": [],
            }
        ]
    else:
        mapping_records = [
            {
                "name": "fuel_gate",
                "source": "missing_table_source",
                "operations": [],
            }
        ]
    mapping_path = write_table_mapping(tmp_path, mapping_records)

    expected = "cycle" if cycle else "(?i)unknown"
    with pytest.raises(ValueError, match=expected):
        assemble_sources(files, folder_path=tmp_path, mapping_path=mapping_path)
