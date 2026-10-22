"""End-to-end configured construction from multiple input representations."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

import h5py
import numpy as np
import polars as pl
import pytest
from fixtures.ingestion_models import PSSEBus, PSSEGenerator
from infrasys import Component, SupplementalAttribute
from pydantic import ValidationError
from rust_ok import Err, Ok, Result

from r2x_core import (
    ArraySource,
    DecodedSource,
    DecodedSources,
    DocumentSource,
    FileReader,
    PluginConfig,
    ReaderConfig,
    TabularProcessing,
    TabularSource,
    build_system,
)
from r2x_core.datafile import DataFile
from r2x_core.exceptions import ReaderError
from r2x_core.file_reader import SourceProcessor
from r2x_core.ingestion import (
    attach_time_series,
    build_components,
    build_supplemental_attributes,
    get_component,
    parse_timestamp,
    resolve_model_type,
    resolve_owners,
    resolve_time_axis,
)
from r2x_core.json_adapter.processing import JSONProcessingBackend
from r2x_core.models import (
    ColumnTimeAxis,
    ComponentInstruction,
    ComponentOwner,
    ComponentReference,
    JSONProcessing,
    RegularTimeAxis,
    StrictConfigModel,
    SupplementalAttributeInstruction,
    TimeSeriesInstruction,
)
from r2x_core.polars_adapter import PolarsTabularBackend
from r2x_core.reader import DataReader
from r2x_core.system import System
from r2x_core.types import FileProcessing, JSONValue


class DummyRawOptions(StrictConfigModel):
    """Validate options owned by the illustrative decoder."""

    encoding: str = "utf-8"


class DummyRawReader(FileReader):
    """Decode the illustrative RAW records into named tables."""

    def read_file(
        self,
        file_format: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        if file_format != "dummy_raw":
            msg = f"Unsupported format {file_format!r}"
            raise ValueError(msg)
        options = DummyRawOptions.model_validate(reader_config.options)
        rows: dict[str, list[dict[str, JSONValue]]] = {"buses": [], "generators": []}
        with file_path.open(encoding=options.encoding, newline="") as file:
            for record in csv.reader(file, skipinitialspace=True):
                if not record or record[0].startswith("#"):
                    continue
                match record:
                    case ["BUS", number, name, base_kv]:
                        rows["buses"].append(
                            {"bus_number": int(number), "bus_name": name, "base_kv": float(base_kv)}
                        )
                    case ["GEN", number, machine_id, power, status]:
                        rows["generators"].append(
                            {
                                "bus_number": int(number),
                                "machine_id": machine_id,
                                "p_mw": float(power),
                                "status": int(status),
                            }
                        )
                    case _:
                        msg = f"Invalid illustrative RAW record: {record}"
                        raise ValueError(msg)
        backend = PolarsTabularBackend()
        return {name: TabularSource(pl.DataFrame(records).lazy(), backend) for name, records in rows.items()}


class JSONOptions(StrictConfigModel):
    """Reader options with strict validation for a registered custom format."""

    encoding: str = "utf-8"


class DocumentProcessor(SourceProcessor[JSONValue]):
    """App-defined processing paired with a non-tabular document payload."""

    def __init__(self) -> None:
        self.calls = 0

    def process(
        self,
        data: JSONValue,
        /,
        *,
        processing: FileProcessing,
        sources: Mapping[str, DecodedSource],
        data_file: DataFile,
    ) -> Result[JSONValue, ValueError]:
        self.calls += 1
        if not isinstance(processing, JSONProcessing):
            return Err(ValueError("DocumentProcessor requires JSONProcessing"))
        return JSONProcessingBackend().process(data, processing=processing, sources={}, data_file=data_file)


class ConcreteDocumentSource(DecodedSource):
    """Implement the public source contract without ProcessingSource wrappers."""

    def __init__(self) -> None:
        self.calls = 0

    def fields(self) -> list[str]:
        return ["value"]

    def iter_rows(self) -> list[Mapping[str, object]]:
        return [{"value": 3}]

    def values(self, field: str, /) -> list[object]:
        if field != "value":
            msg = f"Unknown field {field!r}"
            raise ValueError(msg)
        return [3]

    def process(
        self,
        processing: FileProcessing,
        *,
        sources: Mapping[str, DecodedSource],
        data_file: DataFile,
    ) -> Result[DecodedSource, ValueError]:
        self.calls += 1
        return Ok(self)


class CustomDocumentReader(FileReader):
    """Read a new extension and pair documents with an application processor."""

    def __init__(self) -> None:
        self.processor = DocumentProcessor()
        self.reads = 0
        self.paths: list[Path] = []

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        if format_name != "custom_document":
            msg = f"Unsupported format {format_name!r}"
            raise ValueError(msg)
        self.reads += 1
        self.paths.append(file_path)
        options = JSONOptions.model_validate(reader_config.options)
        with file_path.open(encoding=options.encoding) as file:
            return {"data": DocumentSource(json.load(file), self.processor)}


class CustomTableReader(FileReader):
    """Read registered custom extensions into independent Polars backends."""

    def __init__(self) -> None:
        self.backend = PolarsTabularBackend()

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        return {"data": TabularSource(pl.scan_csv(file_path), self.backend)}


def test_build_system_reads_and_attaches_components_attributes_and_time_series(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    input_dir = tmp_path / "inputs"
    config_dir.mkdir()
    input_dir.mkdir()
    (input_dir / "case.raw").write_text(
        "BUS,101,NORTH,230\nBUS,102,SOUTH,115\nGEN,101,1,100,1\nGEN,102,1,0,1\nGEN,101,2,25,0\n",
        encoding="utf-8",
    )
    (input_dir / "geography.json").write_text(
        json.dumps(
            [
                {"bus_name": "NORTH", "region": "north"},
                {"bus_name": "SOUTH", "region": "south"},
            ]
        ),
        encoding="utf-8",
    )
    with h5py.File(input_dir / "loads.h5", "w") as h5_file:
        h5_file.create_dataset("samples", data=np.array([0.0, 4.0, 8.0]))

    (config_dir / "file_mapping.json").write_text(
        json.dumps(
            [
                {
                    "name": "case",
                    "relative_fpath": "../inputs/case.raw",
                    "reader": {"format": "dummy_raw", "options": {"encoding": "utf-8"}},
                },
                {
                    "name": "bus_names",
                    "source": "case.buses",
                    "proc_spec": {
                        "kind": "tabular",
                        "steps": [
                            {
                                "op": "select_columns",
                                "select_columns": ["bus_number", "bus_name"],
                            }
                        ],
                    },
                },
                {
                    "name": "generators",
                    "source": "case.generators",
                    "proc_spec": {
                        "kind": "tabular",
                        "steps": [
                            {
                                "op": "filter",
                                "predicate": {
                                    "op": "eq",
                                    "args": [{"column": "status"}, {"literal": 1}],
                                },
                            },
                            {"op": "join", "source": "bus_names", "how": "left", "on": ["bus_number"]},
                            {
                                "op": "with_columns",
                                "columns": {
                                    "name": {
                                        "op": "concat_str",
                                        "args": [
                                            {"column": "bus_name"},
                                            {"literal": "_"},
                                            {"column": "machine_id"},
                                        ],
                                    }
                                },
                            },
                        ],
                    },
                },
                {"name": "geography", "relative_fpath": "../inputs/geography.json"},
                {
                    "name": "loads",
                    "relative_fpath": "../inputs/loads.h5",
                    "reader": {"format": "hdf5_array", "options": {"data_key": "samples"}},
                },
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "parser_rules.json").write_text(
        json.dumps(
            [
                {
                    "kind": "component",
                    "source": "case.buses",
                    "component_type": "PSSEBus",
                    "fields": {"name": "bus_name", "number": "bus_number", "base_kv": "base_kv"},
                },
                {
                    "kind": "component",
                    "source": "generators",
                    "component_type": "PSSEGenerator",
                    "fields": {"name": "name", "active_power_mw": "p_mw", "available": "status"},
                    "references": {"bus": {"component_type": "PSSEBus", "name_field": "bus_name"}},
                },
                {
                    "kind": "time_series",
                    "source": "loads",
                    "name": "load_mw",
                    "values": "samples",
                    "time_axis": {
                        "kind": "regular",
                        "initial_timestamp": "2024-01-01T00:00:00",
                        "resolution_seconds": 3600,
                    },
                    "units": "MW",
                    "metadata": {"scenario": "base", "enabled": False},
                    "owners": [{"component_type": "PSSEBus", "name": "NORTH"}],
                },
                {
                    "kind": "supplemental_attribute",
                    "source": "geography",
                    "attribute_type": "BusGeo",
                    "fields": {"region": "region"},
                    "owners": [{"component_type": "PSSEBus", "name_field": "bus_name"}],
                },
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "config.json").write_text('{"name":"dummy-psse"}', encoding="utf-8")
    config = PluginConfig(
        models=("fixtures.ingestion_models",),
        config_path_override=config_dir,
    )

    system = build_system(
        config,
        name="dummy-psse",
        readers={"dummy_raw": DummyRawReader()},
    )

    buses = {bus.name: bus for bus in system.get_components(PSSEBus)}
    generators = {generator.name: generator for generator in system.get_components(PSSEGenerator)}
    assert system.name == "dummy-psse"
    assert set(buses) == {"NORTH", "SOUTH"}
    assert generators["NORTH_1"].bus is buses["NORTH"]
    assert generators["SOUTH_1"].bus is buses["SOUTH"]
    assert generators["NORTH_1"].active_power_mw == 100.0
    assert generators["SOUTH_1"].active_power_mw == 0.0
    assert generators["NORTH_1"].available is True
    assert len(tuple(system.get_components(PSSEGenerator))) == 2
    assert [item.region for item in system.get_supplemental_attributes_with_component(buses["NORTH"])] == [
        "north"
    ]
    assert [item.region for item in system.get_supplemental_attributes_with_component(buses["SOUTH"])] == [
        "south"
    ]
    series = system.get_time_series(buses["NORTH"], name="load_mw")
    np.testing.assert_array_equal(series.data_array, np.array([0.0, 4.0, 8.0]))
    metadata = system.list_time_series_metadata(buses["NORTH"], name="load_mw")
    assert metadata[0].units.units == "megawatt"
    assert metadata[0].features == {"enabled": False, "scenario": "base"}


def test_custom_document_processor_and_reader_options(tmp_path: Path) -> None:
    """Use a registered processor with a non-Polars document and validate its options."""
    path = tmp_path / "payload.r2doc"
    path.write_text('{"old_name":"North","enabled":false}', encoding="utf-8")
    reader = CustomDocumentReader()
    data_reader = DataReader(file_readers={"custom_document": reader})
    data_file = DataFile(
        name="payload",
        fpath=path,
        reader=ReaderConfig(format="custom_document", options={"encoding": "utf-8"}),
        proc_spec=JSONProcessing(steps=[{"op": "rename_keys", "mapping": {"old_name": "name"}}]),
    )

    sources = data_reader.read_data_files([data_file], folder_path=tmp_path)

    assert isinstance(sources["payload"], DocumentSource)
    assert sources["payload"].data == {"name": "North", "enabled": False}
    assert reader.processor.calls == 1
    invalid = data_file.model_copy(
        update={
            "reader": ReaderConfig(
                format="custom_document", options={"encoding": "utf-8", "unexpected": True}
            )
        }
    )
    with pytest.raises(ValueError, match="unexpected"):
        data_reader.read_data_files([invalid], folder_path=tmp_path)


def test_reader_rejects_missing_processor_and_unsupported_processing() -> None:
    """Requested operations fail explicitly when the source has no compatible processor."""
    missing = DocumentSource({"value": 1}, None)
    json_file = DataFile(
        name="missing",
        source="origin",
        proc_spec=JSONProcessing(steps=[{"op": "rename_keys", "mapping": {"value": "renamed"}}]),
    )
    with pytest.raises(ReaderError, match="No processor registered"):
        DataReader.process_source(missing, data_file=json_file, sources={"origin": missing})

    reader = CustomDocumentReader()
    document = DocumentSource({"value": 1}, reader.processor)
    tabular_file = DataFile(
        name="unsupported",
        source="origin",
        proc_spec=TabularProcessing(steps=[{"op": "drop_columns", "drop_columns": ["value"]}]),
    )
    with pytest.raises(ReaderError, match="requires JSONProcessing"):
        DataReader.process_source(document, data_file=tabular_file, sources={"origin": document})
    tabular = TabularSource(pl.DataFrame({"value": [1]}).lazy(), PolarsTabularBackend())
    with pytest.raises(ReaderError, match="requires TabularProcessing"):
        DataReader.process_source(tabular, data_file=json_file, sources={"origin": tabular})
    assert (
        DataReader.process_source(
            document, data_file=DataFile(name="passthrough", source="origin"), sources={"origin": document}
        )
        is document
    )


def test_document_time_series_rejects_missing_cells_without_dropping_alignment(tmp_path: Path) -> None:
    """Fail on absent document cells, while keeping explicitly present null values."""
    config = PluginConfig(models=("fixtures.ingestion_models",), config_path_override=tmp_path)
    system = System(name="document-series")
    owner = PSSEBus(name="NORTH", number=101, base_kv=230.0)
    system.add_component(owner)
    instruction = TimeSeriesInstruction(
        kind="time_series",
        source="samples",
        name="load",
        values="load",
        time_axis=ColumnTimeAxis(kind="column", column="timestamp", resolution_seconds=3600),
        owners=[ComponentOwner(component_type="PSSEBus", name="NORTH")],
    )
    complementary = DocumentSource(
        [
            {"timestamp": "2024-01-01T00:00:00", "load": 1.0},
            {"timestamp": "2024-01-01T01:00:00"},
            {"load": 3.0},
        ],
        None,
    )

    with pytest.raises(ValueError, match="missing field 'load'"):
        attach_time_series(system, instruction, source=complementary, config=config)

    explicit_null = DocumentSource(
        [
            {"timestamp": "2024-01-01T00:00:00", "load": None},
            {"timestamp": "2024-01-01T01:00:00", "load": 1.0},
        ],
        None,
    )
    assert explicit_null.values("load") == [None, 1.0]
    attach_time_series(system, instruction, source=explicit_null, config=config)
    series = system.get_time_series(owner, name="load")
    assert len(series.data_array) == len(explicit_null.values("timestamp")) == 2
    assert np.isnan(series.data_array[0])
    assert series.data_array[1] == 1.0


def test_custom_decoded_source_uses_its_processing_contract_directly() -> None:
    """Invoke an app-defined source without requiring the built-in paired wrapper."""
    source = ConcreteDocumentSource()
    data_file = DataFile(
        name="custom",
        source="origin",
        proc_spec=JSONProcessing(steps=[{"op": "rename_keys", "mapping": {"value": "renamed"}}]),
    )

    result = DataReader.process_source(source, data_file=data_file, sources={"origin": source})

    assert result is source
    assert source.calls == 1


def test_tabular_source_selects_regex_shaped_field_exactly() -> None:
    """Select literal field names without Polars' regex column expansion."""
    source = TabularSource(pl.LazyFrame({"load": [10.0], "^load$": [99.0]}), PolarsTabularBackend())

    assert source.values("^load$") == [99.0]
    with pytest.raises(ValueError, match="Table has no field 'missing'"):
        source.values("missing")


def test_named_join_uses_separately_decoded_registered_sources(tmp_path: Path) -> None:
    """Join custom tables decoded by distinct reader/backend instances."""
    left = tmp_path / "left.r2left"
    right = tmp_path / "right.r2right"
    left.write_text("id,label\n1,north\n2,south\n", encoding="utf-8")
    right.write_text("id,value\n1,10\n2,20\n", encoding="utf-8")
    files = [
        DataFile.model_validate(record)
        for record in [
            {"name": "left", "fpath": left, "reader": {"format": "left_table"}},
            {"name": "right", "fpath": right, "reader": {"format": "right_table"}},
            {
                "name": "joined",
                "source": "right",
                "proc_spec": {
                    "kind": "tabular",
                    "steps": [{"op": "join", "source": "left", "how": "left", "on": ["id"]}],
                },
            },
        ]
    ]
    sources = DataReader(
        file_readers={"left_table": CustomTableReader(), "right_table": CustomTableReader()}
    ).read_data_files(files, folder_path=tmp_path)

    assert sources["joined"].values("label") == ["north", "south"]
    assert sources["joined"].values("value") == [10, 20]


def test_decoded_qualified_names_cannot_be_replaced_by_derived_sources(tmp_path: Path) -> None:
    """Reject derived names that collide with one of a reader's named outputs."""
    path = tmp_path / "case.raw"
    path.write_text("BUS,1,NORTH,230\nGEN,1,1,10,1\n", encoding="utf-8")
    files = [
        DataFile.model_validate(record)
        for record in [
            {"name": "case", "fpath": path, "reader": {"format": "dummy_raw"}},
            {"name": "case.buses", "source": "case.generators"},
        ]
    ]

    with pytest.raises(ValueError, match=r"Duplicate named source 'case\.buses'"):
        DataReader(file_readers={"dummy_raw": DummyRawReader()}).read_data_files(files, folder_path=tmp_path)


def test_decoded_sources_cannot_overwrite_an_existing_derived_name(tmp_path: Path) -> None:
    """Reject a later decoder output that collides with an earlier composed source."""
    json_path = tmp_path / "bus.json"
    json_path.write_text('{"name":"existing"}', encoding="utf-8")
    raw_path = tmp_path / "case.raw"
    raw_path.write_text("BUS,1,NORTH,230\nGEN,1,1,10,1\n", encoding="utf-8")
    files = [
        DataFile(name="case.buses", fpath=json_path),
        DataFile(name="case", fpath=raw_path, reader=ReaderConfig(format="dummy_raw")),
    ]

    with pytest.raises(ValueError, match=r"Duplicate named source 'case\.buses'"):
        DataReader(file_readers={"dummy_raw": DummyRawReader()}).read_data_files(files, folder_path=tmp_path)


def test_decode_cache_is_execution_local_and_parameter_sensitive(tmp_path: Path) -> None:
    """Reuse identical decodes within one run, but not across parameterized runs."""
    path = tmp_path / "same.r2doc"
    path.write_text('{"value":"plain"}', encoding="utf-8")
    reader = CustomDocumentReader()
    data_reader = DataReader(file_readers={"custom_document": reader})
    files = [
        DataFile(
            name="first",
            fpath=path,
            reader=ReaderConfig(format="custom_document", options={"encoding": "{encoding}"}),
        ),
        DataFile(
            name="second",
            relative_fpath="./same.r2doc",
            reader=ReaderConfig(format="custom_document", options={"encoding": "{encoding}"}),
        ),
    ]

    data_reader.read_data_files(files, folder_path=tmp_path, placeholders={"encoding": "utf-8"})
    assert reader.reads == 1
    assert reader.paths == [path.resolve()]
    data_reader.read_data_files(files, folder_path=tmp_path, placeholders={"encoding": "latin-1"})
    assert reader.reads == 2
    assert reader.paths == [path.resolve(), path.resolve()]


def test_processing_placeholder_preserves_boolean_replacement_key() -> None:
    """Substitute typed processing options without JSON-stringifying mapping keys."""
    data_file = DataFile(
        name="values",
        fpath=Path("values.csv"),
        proc_spec=TabularProcessing(
            steps=[
                {"op": "replace_values", "replace_values": {True: False}},
                {"op": "scale_columns", "scale": {"value": "{factor}"}},
            ]
        ),
    )

    resolved = DataReader.resolve_placeholders(data_file, placeholders={"factor": 2.0})

    assert isinstance(resolved.proc_spec, TabularProcessing)
    replacement = resolved.proc_spec.steps[0].replace_values
    assert list(replacement) == [True]
    assert type(next(iter(replacement))) is bool
    assert replacement[True] is False
    assert resolved.proc_spec.steps[1].scale["value"] == 2.0


def test_parser_rules_are_resolved_before_reading_inputs(tmp_path: Path) -> None:
    """Invalid parser placeholders fail before any registered reader executes."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    input_path = tmp_path / "input.r2doc"
    input_path.write_text("{}", encoding="utf-8")
    (config_dir / "file_mapping.json").write_text(
        json.dumps([{"name": "input", "fpath": str(input_path), "reader": {"format": "custom_document"}}]),
        encoding="utf-8",
    )
    (config_dir / "parser_rules.json").write_text(
        json.dumps(
            [
                {
                    "kind": "component",
                    "source": "{missing_source}",
                    "component_type": "PSSEBus",
                    "fields": {"name": "name"},
                }
            ]
        ),
        encoding="utf-8",
    )
    reader = CustomDocumentReader()

    with pytest.raises(ValueError, match="missing_source"):
        build_system(
            PluginConfig(models=("fixtures.ingestion_models",), config_path_override=config_dir),
            name="invalid",
            readers={"custom_document": reader},
        )

    assert reader.reads == 0


def test_csv_column_axis_creates_owner_specific_and_explicitly_shared_series(tmp_path: Path) -> None:
    """Read column axes once and group long-form samples by dynamic owner names."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (tmp_path / "buses.csv").write_text(
        "name,number,base_kv\nNORTH,101,230\nSOUTH,102,115\n", encoding="utf-8"
    )
    (tmp_path / "long.csv").write_text(
        "bus_name,timestamp,load\n"
        "NORTH,2024-01-01T00:00:00,1\nNORTH,2024-01-01T01:00:00,2\n"
        "SOUTH,2024-01-01T00:00:00,9\nSOUTH,2024-01-01T01:00:00,10\n",
        encoding="utf-8",
    )
    (tmp_path / "shared.csv").write_text(
        "timestamp,load\n2024-01-01T00:00:00,100\n2024-01-01T01:00:00,200\n",
        encoding="utf-8",
    )
    (config_dir / "file_mapping.json").write_text(
        json.dumps(
            [
                {"name": "buses", "relative_fpath": "../buses.csv"},
                {"name": "long", "relative_fpath": "../long.csv"},
                {"name": "shared", "relative_fpath": "../shared.csv"},
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "parser_rules.json").write_text(
        json.dumps(
            [
                {
                    "kind": "component",
                    "source": "buses",
                    "component_type": "PSSEBus",
                    "fields": {"name": "name", "number": "number", "base_kv": "base_kv"},
                },
                {
                    "kind": "time_series",
                    "source": "long",
                    "name": "owner_load",
                    "values": "load",
                    "time_axis": {"kind": "column", "column": "timestamp"},
                    "owners": [{"component_type": "PSSEBus", "name_field": "bus_name"}],
                },
                {
                    "kind": "time_series",
                    "source": "shared",
                    "name": "shared_load",
                    "values": "load",
                    "time_axis": {"kind": "column", "column": "timestamp"},
                    "owners": [{"component_type": "PSSEBus", "names": ["NORTH", "SOUTH"]}],
                },
            ]
        ),
        encoding="utf-8",
    )

    system = build_system(
        PluginConfig(models=("fixtures.ingestion_models",), config_path_override=config_dir),
        name="csv-series",
    )
    buses = {bus.name: bus for bus in system.get_components(PSSEBus)}

    np.testing.assert_array_equal(system.get_time_series(buses["NORTH"], name="owner_load").data, [1, 2])
    np.testing.assert_array_equal(system.get_time_series(buses["SOUTH"], name="owner_load").data, [9, 10])
    for bus in buses.values():
        np.testing.assert_array_equal(system.get_time_series(bus, name="shared_load").data, [100, 200])


def test_component_name_matching_override_and_cross_type_identity(tmp_path: Path) -> None:
    """Use explicit mappings over same-name fields and allow cross-type name reuse."""
    config = PluginConfig(models=("fixtures.ingestion_models",), config_path_override=tmp_path)
    system = System(name="names")
    identities: set[tuple[type[Component], str]] = set()
    backend = PolarsTabularBackend()
    buses = TabularSource(pl.DataFrame([{"name": "SHARED", "number": 1, "base_kv": 100.0}]).lazy(), backend)
    build_components(
        system,
        ComponentInstruction(
            kind="component",
            source="buses",
            component_type="PSSEBus",
            fields={"number": "number", "base_kv": "base_kv"},
        ),
        source=buses,
        component_type=PSSEBus,
        identities=identities,
        config=config,
    )
    generator_type = PSSEGenerator
    generators = TabularSource(
        pl.DataFrame(
            [
                {
                    "name": "wrong-name",
                    "alias": "SHARED",
                    "bus_name": "SHARED",
                    "power": 0.0,
                }
            ]
        ).lazy(),
        backend,
    )
    build_components(
        system,
        ComponentInstruction(
            kind="component",
            source="generators",
            component_type="PSSEGenerator",
            fields={"name": "alias", "active_power_mw": "power"},
            references={"bus": ComponentReference(component_type="PSSEBus", name_field="bus_name")},
        ),
        source=generators,
        component_type=generator_type,
        identities=identities,
        config=config,
    )

    assert system.get_component(PSSEBus, "SHARED").name == "SHARED"
    generator = next(iter(system.get_components(PSSEGenerator)))
    assert generator.name == "SHARED"
    assert generator.active_power_mw == 0.0


def test_component_builder_rejects_empty_duplicate_and_missing_names(tmp_path: Path) -> None:
    """Reject unaddressable names and report duplicate or missing references."""
    config = PluginConfig(models=("fixtures.ingestion_models",), config_path_override=tmp_path)
    backend = PolarsTabularBackend()

    empty_system = System(name="empty-name")
    with pytest.raises(ValueError, match="empty name"):
        build_components(
            empty_system,
            ComponentInstruction(
                kind="component",
                source="buses",
                component_type="PSSEBus",
                fields={"name": "name", "number": "number", "base_kv": "base_kv"},
            ),
            source=TabularSource(
                pl.DataFrame([{"name": "  ", "number": 1, "base_kv": 100.0}]).lazy(), backend
            ),
            component_type=PSSEBus,
            identities=set(),
            config=config,
        )

    with pytest.raises(ValueError, match="Missing reference"):
        get_component(System(name="missing"), PSSEBus, "UNKNOWN", label="reference")

    ambiguous = System(name="ambiguous")
    ambiguous.add_component(PSSEBus(name="DUP", number=1, base_kv=100.0))
    ambiguous.add_component(PSSEBus(name="DUP", number=2, base_kv=100.0))
    with pytest.raises(ValueError, match="Ambiguous reference"):
        get_component(ambiguous, PSSEBus, "DUP", label="reference")


def test_document_and_array_sources_keep_their_native_access_contracts() -> None:
    """Read named fields from JSON objects and arrays without reshaping them."""
    document = DocumentSource({"samples": [0, None], "enabled": False}, None)
    assert document.fields() == ["samples", "enabled"]
    assert list(document.iter_rows()) == [{"samples": [0, None], "enabled": False}]
    assert document.values("samples") == [0, None]
    assert document.values("enabled") == [False]
    with pytest.raises(ValueError, match="no field"):
        document.values("missing")
    with pytest.raises(TypeError, match="explicit reader conversion"):
        DocumentSource("not a record document", None).fields()

    arrays = ArraySource({"load": np.array([1.0, 2.0]), "ready": np.array([False, True])}, None)
    assert arrays.fields() == ["load", "ready"]
    assert arrays.values("load") == [1.0, 2.0]
    assert list(arrays.iter_rows()) == [
        {"load": 1.0, "ready": False},
        {"load": 2.0, "ready": True},
    ]
    assert ArraySource(np.array([3, 4]), None).values("data") == [3, 4]
    with pytest.raises(ValueError, match="no values named"):
        arrays.values("missing")
    with pytest.raises(ValueError, match="equal lengths"):
        ArraySource({"left": np.array([1]), "right": np.array([1, 2])}, None).iter_rows()
    with pytest.raises(ValueError, match="one-dimensional"):
        ArraySource({"matrix": np.array([[1, 2]])}, None).iter_rows()
    with pytest.raises(TypeError, match="field names must be strings"):
        ArraySource({1: np.array([1])}, None).fields()
    with pytest.raises(ValueError, match="one-dimensional"):
        ArraySource(np.array([[1, 2]]), None).fields()
    with pytest.raises(ValueError, match="one-dimensional"):
        ArraySource({"matrix": np.array([[1, 2]])}, None).values("matrix")


def test_component_builder_preserves_defaults_false_and_explicit_null() -> None:
    """Model validation distinguishes absent defaults from explicit null values."""
    config = PluginConfig(models=("fixtures.ingestion_models",), config_path_override=Path.cwd())
    system = System(name="component-values")
    bus = PSSEBus(name="NORTH", number=101, base_kv=230.0)
    system.add_component(bus)
    instruction = ComponentInstruction(
        kind="component",
        source="generators",
        component_type="PSSEGenerator",
        fields={"name": "name", "active_power_mw": "power"},
        references={"bus": ComponentReference(component_type="PSSEBus", name_field="bus_name")},
    )
    rows = DocumentSource(
        [
            {"name": "NORTH_1", "power": 1.0, "bus_name": "NORTH"},
            {"name": "NORTH_2", "power": 0.0, "available": False, "bus_name": "NORTH"},
        ],
        None,
    )
    build_components(
        system,
        instruction,
        source=rows,
        component_type=PSSEGenerator,
        identities={(PSSEBus, "NORTH")},
        config=config,
    )
    generators = {generator.name: generator for generator in system.get_components(PSSEGenerator)}
    assert generators["NORTH_1"].available is True
    assert generators["NORTH_2"].available is False
    assert generators["NORTH_2"].active_power_mw == 0.0

    null_system = System(name="null-component")
    null_system.add_component(PSSEBus(name="NORTH", number=101, base_kv=230.0))
    with pytest.raises(ValidationError):
        build_components(
            null_system,
            instruction,
            source=DocumentSource(
                [{"name": "NORTH_3", "power": 1.0, "available": None, "bus_name": "NORTH"}], None
            ),
            component_type=PSSEGenerator,
            identities=set(),
            config=config,
        )


def test_component_builder_validates_fields_models_and_duplicate_names() -> None:
    """Fail on missing source fields, invalid components, and repeated type/name pairs."""
    config = PluginConfig(models=("fixtures.ingestion_models",), config_path_override=Path.cwd())
    instruction = ComponentInstruction(
        kind="component",
        source="buses",
        component_type="PSSEBus",
        fields={"name": "name", "number": "number", "base_kv": "base_kv"},
    )
    with pytest.raises(ValueError, match="Source has no field"):
        build_components(
            System(name="missing-fields"),
            instruction,
            source=DocumentSource([{"name": "NORTH"}], None),
            component_type=PSSEBus,
            identities=set(),
            config=config,
        )

    invalid = DocumentSource([{"name": "NORTH", "number": 1, "base_kv": 0.0}], None)
    with pytest.raises(ValidationError):
        build_components(
            System(name="invalid-model"),
            instruction,
            source=invalid,
            component_type=PSSEBus,
            identities=set(),
            config=config,
        )

    duplicate = DocumentSource(
        [
            {"name": "NORTH", "number": 1, "base_kv": 230.0},
            {"name": "NORTH", "number": 2, "base_kv": 115.0},
        ],
        None,
    )
    with pytest.raises(ValueError, match="Duplicate component"):
        build_components(
            System(name="duplicate"),
            instruction,
            source=duplicate,
            component_type=PSSEBus,
            identities=set(),
            config=config,
        )
    with pytest.raises(ValueError, match="not a Component"):
        resolve_model_type("BusGeo", config=config, expected=Component)


def test_supplemental_builder_validates_attributes_and_shares_to_selected_owners() -> None:
    """Validate one supplemental model before attaching it to explicit owners."""
    config = PluginConfig(models=("fixtures.ingestion_models",), config_path_override=Path.cwd())
    system = System(name="supplemental")
    north = PSSEBus(name="NORTH", number=101, base_kv=230.0)
    south = PSSEBus(name="SOUTH", number=102, base_kv=115.0)
    system.add_component(north)
    system.add_component(south)
    instruction = SupplementalAttributeInstruction(
        kind="supplemental_attribute",
        source="regions",
        attribute_type="BusGeo",
        fields={"region": "region"},
        owners=[ComponentOwner(component_type="PSSEBus", names=["NORTH", "SOUTH"])],
    )
    build_supplemental_attributes(
        system,
        instruction,
        source=DocumentSource([{"region": "west"}], None),
        attribute_type=resolve_model_type("BusGeo", config=config, expected=SupplementalAttribute),
        config=config,
    )
    for owner in (north, south):
        attributes = system.get_supplemental_attributes_with_component(owner)
        assert [attribute.region for attribute in attributes] == ["west"]

    with pytest.raises(ValidationError):
        build_supplemental_attributes(
            system,
            instruction,
            source=DocumentSource([{"region": None}], None),
            attribute_type=resolve_model_type("BusGeo", config=config, expected=SupplementalAttribute),
            config=config,
        )


@pytest.mark.parametrize(
    ("timestamps", "sample_count", "resolution_seconds", "message"),
    [
        (None, 2, None, "has 0 values"),
        (["2024-01-01T00:00:00"], 2, None, "has 1 values"),
        (["2024-01-01T00:00:00", "2024-01-01T00:00:00"], 2, None, "strictly increasing"),
        (
            ["2024-01-01T00:00:00", "2024-01-01T01:00:00", "2024-01-01T03:00:00"],
            3,
            None,
            "regular time axis",
        ),
        (["2024-01-01T00:00:00", "2024-01-01T01:00:00"], 2, 1800, "does not match"),
        (["2024-01-01T00:00:00"], 1, None, "one-sample"),
        (["not-a-timestamp"], 1, 3600, "Invalid ISO"),
        ([1], 1, 3600, "Unsupported time-axis"),
    ],
)
def test_column_time_axis_rejects_invalid_samples(
    timestamps: list[object] | None,
    sample_count: int,
    resolution_seconds: float | None,
    message: str,
) -> None:
    """Reject absent, irregular, unsupported, or incompatible timestamp columns."""
    axis = ColumnTimeAxis(kind="column", column="timestamp", resolution_seconds=resolution_seconds)
    with pytest.raises((TypeError, ValueError), match=message):
        resolve_time_axis(axis, timestamps, sample_count)


def test_time_axis_accepts_datetime_values_and_regular_configuration() -> None:
    """Interpret supported datetime values and fixed regular axes explicitly."""
    start = datetime(2024, 1, 1)
    assert parse_timestamp(start) == start
    times = [np.datetime64("2024-01-01T00:00:00"), np.datetime64("2024-01-01T01:00:00")]
    initial, resolution = resolve_time_axis(ColumnTimeAxis(kind="column", column="time"), times, 2)
    assert initial == start
    assert resolution == timedelta(hours=1)
    configured = RegularTimeAxis(kind="regular", initial_timestamp=start, resolution_seconds=900)
    assert resolve_time_axis(configured, None, 4) == (start, timedelta(minutes=15))


@pytest.mark.parametrize(
    "selection",
    [{}, {"name": "NORTH", "names": ["SOUTH"]}, {"names": []}],
)
def test_component_owner_requires_one_nonempty_selection(selection: dict[str, object]) -> None:
    """Reject missing, conflicting, or empty component owner selections."""
    with pytest.raises(ValidationError, match="owner"):
        ComponentOwner(component_type="PSSEBus", **selection)


def test_output_instruction_models_reject_conflicting_or_reserved_fields() -> None:
    """Keep tagged output configuration unambiguous and metadata-safe."""
    with pytest.raises(ValidationError, match="both mapped and referenced"):
        ComponentInstruction(
            kind="component",
            source="generators",
            component_type="PSSEGenerator",
            fields={"bus": "bus_name"},
            references={"bus": {"component_type": "PSSEBus", "name_field": "bus_name"}},
        )
    with pytest.raises(ValidationError, match="reserved infrasys 'context'"):
        TimeSeriesInstruction(
            kind="time_series",
            source="loads",
            name="load",
            values="value",
            time_axis={"kind": "regular", "initial_timestamp": "2024-01-01", "resolution_seconds": 3600},
            owners=[{"component_type": "PSSEBus", "name": "NORTH"}],
            metadata={"context": "not-a-feature"},
        )


def test_build_system_fails_explicitly_for_missing_input_or_output_source(tmp_path: Path) -> None:
    """Report absent required files and output source names at the build boundary."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "file_mapping.json").write_text(
        '[{"name":"missing","relative_fpath":"missing.csv"}]', encoding="utf-8"
    )
    (config_dir / "parser_rules.json").write_text("[]", encoding="utf-8")
    config = PluginConfig(config_path_override=config_dir)
    with pytest.raises(FileNotFoundError):
        build_system(config, name="missing-input")

    (config_dir / "file_mapping.json").write_text("[]", encoding="utf-8")
    (config_dir / "parser_rules.json").write_text(
        '[{"kind":"component","source":"not-loaded","component_type":"PSSEBus"}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Output source 'not-loaded' is not available"):
        build_system(config, name="missing-source")


def test_builders_reject_unknown_mappings_and_empty_owner_groups(tmp_path: Path) -> None:
    """Reject unsupported output fields and time series with no selected owners or samples."""
    config = PluginConfig(models=("fixtures.ingestion_models",), config_path_override=tmp_path)
    system = System(name="invalid-output")
    component_instruction = ComponentInstruction(
        kind="component",
        source="buses",
        component_type="PSSEBus",
        fields={"not_a_field": "name"},
    )
    with pytest.raises(ValueError, match="Unknown fields for PSSEBus"):
        build_components(
            system,
            component_instruction,
            source=DocumentSource([{"name": "NORTH"}], None),
            component_type=PSSEBus,
            identities=set(),
            config=config,
        )

    bus = PSSEBus(name="NORTH", number=101, base_kv=230.0)
    system.add_component(bus)
    supplemental_instruction = SupplementalAttributeInstruction(
        kind="supplemental_attribute",
        source="regions",
        attribute_type="BusGeo",
        fields={"not_a_field": "region"},
        owners=[ComponentOwner(component_type="PSSEBus", name="NORTH")],
    )
    with pytest.raises(ValueError, match="Unknown fields for BusGeo"):
        build_supplemental_attributes(
            system,
            supplemental_instruction,
            source=DocumentSource([{"region": "west"}], None),
            attribute_type=resolve_model_type("BusGeo", config=config, expected=SupplementalAttribute),
            config=config,
        )

    with pytest.raises(ValueError, match="no component owners"):
        resolve_owners(system, [], config=config, rows=())
    with pytest.raises(ValueError, match="non-empty string"):
        resolve_owners(
            system,
            [ComponentOwner(component_type="PSSEBus", name_field="name")],
            config=config,
            rows=({"name": None},),
        )

    empty_columns = pl.DataFrame(
        schema={"name": pl.String, "timestamp": pl.String, "load": pl.Float64}
    ).lazy()
    empty_series = TimeSeriesInstruction(
        kind="time_series",
        source="loads",
        name="load",
        values="load",
        time_axis=ColumnTimeAxis(kind="column", column="timestamp"),
        owners=[ComponentOwner(component_type="PSSEBus", name_field="name")],
    )
    with pytest.raises(ValueError, match="no samples"):
        attach_time_series(
            system,
            empty_series,
            source=TabularSource(empty_columns, PolarsTabularBackend()),
            config=config,
        )

    empty_values = TimeSeriesInstruction(
        kind="time_series",
        source="loads",
        name="empty",
        values="load",
        time_axis={"kind": "regular", "initial_timestamp": "2024-01-01", "resolution_seconds": 3600},
        owners=[ComponentOwner(component_type="PSSEBus", name="NORTH")],
    )
    with pytest.raises(ValueError, match="cannot be empty"):
        attach_time_series(
            system,
            empty_values,
            source=ArraySource({"load": np.array([])}, None),
            config=config,
        )
