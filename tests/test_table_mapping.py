"""Public table assembly and ingestion behavior."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import cast

import polars as pl
import pytest
from fixtures.ingestion_models import NestedValuesComponent, PSSEBus, PSSEGenerator
from pydantic import ValidationError

import r2x_core
from r2x_core import DataFile, DataReader, PluginConfig, SourceAvailability, TabularSource, build_system
from r2x_core.polars_adapter import PolarsTabularBackend
from r2x_core.tabular_backend import TableDateTimePart

pytestmark = [pytest.mark.processing, pytest.mark.table_mapping, pytest.mark.polars]


def write_pipeline_files(tmp_path: Path) -> tuple[Path, Path]:
    """Write real CSV inputs and the three configuration files for the slice."""
    config_dir = tmp_path / "config"
    input_dir = tmp_path / "inputs"
    config_dir.mkdir()
    input_dir.mkdir()
    (input_dir / "buses.csv").write_text(
        "name,number,base_kv\nNorth,1,230.0\nSouth,2,115.0\n", encoding="utf-8"
    )
    (input_dir / "generators.csv").write_text(
        "name,bus_name,capacity_mw,available\nG-North,North,100.0,true\nG-South,South,80.0,true\n",
        encoding="utf-8",
    )
    (input_dir / "reserve_factors.csv").write_text(
        "bus_name,fraction\nSouth,0.25\nNorth,0.1\n", encoding="utf-8"
    )
    (config_dir / "file_mapping.json").write_text(
        json.dumps(
            [
                {"name": "buses", "relative_fpath": "buses.csv", "reader": {"format": "csv"}},
                {
                    "name": "generators",
                    "relative_fpath": "generators.csv",
                    "reader": {"format": "csv"},
                },
                {
                    "name": "reserve_factors",
                    "relative_fpath": "reserve_factors.csv",
                    "reader": {"format": "csv"},
                },
                {
                    "name": "empty_generators",
                    "inline_table": {
                        "schema": {
                            "available": "bool",
                            "bus_name": "string",
                            "name": "string",
                            "reserve_mw": "float64",
                        },
                        "rows": [],
                    },
                },
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "table_mapping.json").write_text(
        json.dumps(
            [
                {
                    "name": "reserve_requirement_rows",
                    "source": "generators",
                    "operations": [
                        {
                            "operation": "join",
                            "source": "reserve_factors",
                            "how": "inner",
                            "on": ["bus_name"],
                            "columns": ["fraction"],
                        },
                        {
                            "operation": "multiply",
                            "columns": ["capacity_mw", "fraction"],
                            "output": "reserve_mw",
                        },
                    ],
                    "columns": {
                        "name": "name",
                        "bus_name": "bus_name",
                        "reserve_mw": "reserve_mw",
                        "available": "available",
                        "record_type": {"value": "reserve requirement"},
                    },
                },
                {
                    "name": "empty_reserve_requirement_rows",
                    "source": "empty_generators",
                    "operations": [],
                    "columns": {
                        "name": "name",
                        "bus_name": "bus_name",
                        "reserve_mw": "reserve_mw",
                        "available": "available",
                        "record_type": {"value": "reserve requirement"},
                    },
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
                    "source": "buses",
                    "component_type": "PSSEBus",
                    "fields": {"name": "name", "number": "number", "base_kv": "base_kv"},
                },
                {
                    "kind": "component",
                    "source": "reserve_requirement_rows",
                    "component_type": "PSSEGenerator",
                    "fields": {
                        "name": "name",
                        "active_power_mw": "reserve_mw",
                        "available": "available",
                    },
                    "references": {"bus": {"component_type": "PSSEBus", "name_field": "bus_name"}},
                },
                {
                    "kind": "component",
                    "source": "empty_reserve_requirement_rows",
                    "component_type": "PSSEGenerator",
                    "fields": {
                        "name": "name",
                        "active_power_mw": "reserve_mw",
                        "available": "available",
                    },
                    "references": {"bus": {"component_type": "PSSEBus", "name_field": "bus_name"}},
                },
            ]
        ),
        encoding="utf-8",
    )
    return config_dir, input_dir


def test_public_assembly_returns_exact_parser_rows_and_typed_empty_output(tmp_path: Path) -> None:
    """Join, multiply, and project named inputs, retaining an empty schema."""
    config_dir, input_dir = write_pipeline_files(tmp_path)
    files = [
        DataFile.model_validate(record)
        for record in json.loads((config_dir / "file_mapping.json").read_bytes())
    ]
    sources = DataReader().read_data_files(files, folder_path=input_dir)

    tables = r2x_core.assemble_tables(
        sources,
        mapping_path=config_dir / "table_mapping.json",
        backend=PolarsTabularBackend(),
    )

    assert set(tables) == {"reserve_requirement_rows", "empty_reserve_requirement_rows"}
    assert list(tables["reserve_requirement_rows"].iter_rows()) == [
        {
            "available": True,
            "bus_name": "North",
            "name": "G-North",
            "record_type": "reserve requirement",
            "reserve_mw": 10.0,
        },
        {
            "available": True,
            "bus_name": "South",
            "name": "G-South",
            "record_type": "reserve requirement",
            "reserve_mw": 20.0,
        },
    ]
    empty = tables["empty_reserve_requirement_rows"]
    assert isinstance(empty, TabularSource)
    assert list(empty.iter_rows()) == []
    assert empty.fields() == ["available", "bus_name", "name", "record_type", "reserve_mw"]
    assert isinstance(empty.data, pl.LazyFrame)
    assert empty.data.collect_schema() == pl.Schema(
        {
            "available": pl.Boolean,
            "bus_name": pl.String,
            "name": pl.String,
            "record_type": pl.String,
            "reserve_mw": pl.Float64,
        }
    )


def test_build_system_assembles_csv_inputs_before_parser_rules(tmp_path: Path) -> None:
    """Run file mapping, table mapping, and parser rules through the public loader."""
    config_dir, input_dir = write_pipeline_files(tmp_path)
    config = PluginConfig(
        models=("fixtures.ingestion_models",),
        config_path_override=config_dir,
    )

    system = build_system(
        config,
        name="assembled-reserves",
        input_folder=input_dir,
        table_mapping_path=config_dir / "table_mapping.json",
    )

    buses = {bus.name: bus for bus in system.get_components(PSSEBus)}
    generators = {generator.name: generator for generator in system.get_components(PSSEGenerator)}
    assert set(buses) == {"North", "South"}
    assert set(generators) == {"G-North", "G-South"}
    assert generators["G-North"].active_power_mw == 10.0
    assert generators["G-South"].active_power_mw == 20.0
    assert generators["G-North"].bus is buses["North"]
    assert generators["G-South"].bus is buses["South"]


def source_tables() -> dict[str, TabularSource[pl.LazyFrame]]:
    """Create one present typed empty table for configuration-boundary checks."""
    backend = PolarsTabularBackend()
    frame = pl.DataFrame(schema={"value": pl.Int64}).lazy()
    return {"input": TabularSource(frame, backend)}


def assemble_mapping(tmp_path: Path, contents: str) -> None:
    """Invoke the public JSON loading and assembly boundary on a temporary file."""
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(contents, encoding="utf-8")
    r2x_core.assemble_tables(
        source_tables(),
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
    )


def test_mapping_loader_rejects_malformed_and_unknown_fields(tmp_path: Path) -> None:
    """Reject a non-array mapping and strict-model field typos."""
    with pytest.raises(ValidationError):
        assemble_mapping(tmp_path, '{"tables": []}')
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            '[{"name":"out","source":"input","operations":[],"columns_typo":{}}]',
        )


def test_mapping_loader_rejects_unknown_operations(tmp_path: Path) -> None:
    """Reject operation tags outside the implemented mapping vocabulary."""
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            '[{"name":"out","source":"input","operations":[{"operation":"scale"}]}]',
        )


def test_mapping_loader_rejects_unsupported_int32_rows_schema(tmp_path: Path) -> None:
    """Keep rows constructors within the declared logical scalar vocabulary."""
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            '[{"name":"years","operations":[{"operation":"rows",'
            '"schema":[{"name":"year","dtype":"int32"}],"values":[]}]}]',
        )


def test_mapping_loader_rejects_forward_references_and_unknown_sources(tmp_path: Path) -> None:
    """Require every source to be an input or an earlier table record."""
    with pytest.raises(ValueError, match="before it is declared"):
        assemble_mapping(
            tmp_path,
            '[{"name":"first","source":"later","operations":[]},'
            '{"name":"later","source":"input","operations":[]}]',
        )
    with pytest.raises(ValueError, match="Unknown table source"):
        assemble_mapping(tmp_path, '[{"name":"out","source":"missing","operations":[]}]')


def test_selected_seeded_table_validates_its_declared_source(tmp_path: Path) -> None:
    """A reused seeded output still has a valid declared source contract."""
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"seed","source":"missing","operations":[]},'
        '{"name":"output","source":"seed","operations":[]}]',
        encoding="utf-8",
    )
    seed = source_tables()["input"]

    with pytest.raises(ValueError, match="Unknown table source 'missing'"):
        r2x_core.assemble_tables(
            {},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables={"seed": seed},
            table_names=["output"],
        )


def test_selected_seeded_table_rejects_a_forward_declared_source(tmp_path: Path) -> None:
    """A reused output cannot bypass the table declaration order rule."""
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"output","source":"seed","operations":[]},'
        '{"name":"seed","source":"input","operations":[]}]',
        encoding="utf-8",
    )
    sources = source_tables()
    seed = sources["input"]

    with pytest.raises(ValueError, match="Table source 'seed' is referenced before it is declared"):
        r2x_core.assemble_tables(
            sources,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables={"seed": seed},
            table_names=["output"],
        )


def test_selected_initial_table_must_be_declared_in_mapping(tmp_path: Path) -> None:
    """A preassembled seed cannot invent an output absent from the mapping."""
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="Initial table is not declared by the table mapping"):
        r2x_core.assemble_tables(
            {},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables={"undeclared": source_tables()["input"]},
            table_names=["undeclared"],
        )


@pytest.mark.parametrize(
    ("values", "expected"),
    [([1, 2, 3], [{"kind": "constant"}] * 3), ([], [])],
    ids=["nonempty", "empty"],
)
def test_literal_only_projection_preserves_input_row_count(
    tmp_path: Path, values: list[int], expected: list[dict[str, str]]
) -> None:
    """Broadcast literal projection values without creating or removing rows."""
    backend = PolarsTabularBackend()
    frame = pl.DataFrame({"value": values}, schema={"value": pl.Int64}).lazy()
    source = TabularSource(frame, backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"literal_rows","source":"input","operations":[],"columns":{"kind":{"value":"constant"}}}]',
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source},
        mapping_path=mapping_path,
        backend=backend,
    )

    assert list(tables["literal_rows"].iter_rows()) == expected


@pytest.mark.parametrize(
    ("value", "dtype", "expected", "expected_dtype"),
    [
        pytest.param(True, "bool", True, pl.Boolean, id="bool"),
        pytest.param(7, "int64", 7, pl.Int64, id="int64"),
        pytest.param(1.5, "float64", 1.5, pl.Float64, id="float64"),
        pytest.param(10**100, "float64", float(10**100), pl.Float64, id="large-integer-as-float64"),
        pytest.param("label", "string", "label", pl.String, id="string"),
        pytest.param(
            "2032-01-02T03:04:05",
            "datetime",
            datetime(2032, 1, 2, 3, 4, 5),
            pl.Datetime("us"),
            id="datetime",
        ),
    ],
)
def test_typed_projection_literal_preserves_declared_dtype_and_source_columns(
    tmp_path: Path, value: object, dtype: str, expected: object, expected_dtype: pl.DataType
) -> None:
    """Project typed scalar literals, replacing an explicit field without alias collisions."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "value": ["source value"],
                "__r2x_table_mapping_literal_1__": ["source column"],
            }
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "typed",
                    "source": "input",
                    "operations": [],
                    "columns": {
                        "retained": "__r2x_table_mapping_literal_1__",
                        "value": {"value": value, "dtype": dtype},
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["typed"].iter_rows()) == [{"retained": "source column", "value": expected}]
    assert tables["typed"].data.collect_schema() == pl.Schema(
        {"retained": pl.String, "value": expected_dtype}
    )


@pytest.mark.parametrize(
    ("include_optional_column", "row_count", "availability", "absent_inputs", "expected"),
    [
        pytest.param(
            True, 1, SourceAvailability.PRESENT, frozenset(), [{"factor": 0.25, "id": 1}], id="present-value"
        ),
        pytest.param(
            False,
            1,
            SourceAvailability.PRESENT,
            frozenset(),
            [{"factor": None, "id": 1}],
            id="present-missing-column",
        ),
        pytest.param(False, 0, SourceAvailability.PRESENT, frozenset(), [], id="present-empty"),
        pytest.param(
            False,
            0,
            SourceAvailability.ABSENT,
            frozenset({"optional_input"}),
            [],
            id="absent-input",
        ),
    ],
)
def test_optional_typed_projection_preserves_values_and_types_missing_columns(
    tmp_path: Path,
    include_optional_column: bool,
    row_count: int,
    availability: SourceAvailability,
    absent_inputs: frozenset[str],
    expected: list[dict[str, object]],
) -> None:
    """Optional typed projections preserve present values and type missing nulls."""
    backend = PolarsTabularBackend()
    schema: dict[str, pl.DataType] = {"id": pl.Int64}
    rows: list[dict[str, object]] = [{"id": 1} for _ in range(row_count)]
    if include_optional_column:
        schema["optional_factor"] = pl.Float32
        rows = [{"id": 1, "optional_factor": 0.25}]
    source = TabularSource(
        pl.DataFrame(rows, schema=schema).lazy(),
        backend,
        availability=availability,
        absent_inputs=absent_inputs,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "projected",
                    "source": "input",
                    "operations": [],
                    "columns": {
                        "id": "id",
                        "factor": {"optional_column": "optional_factor", "dtype": "float64"},
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    result = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)[
        "projected"
    ]

    assert list(result.iter_rows()) == expected
    assert result.data.collect_schema()["factor"] == pl.Float64
    assert result.availability is availability
    assert result.absent_inputs == absent_inputs


def test_optional_typed_projection_parses_iso_datetime_values(tmp_path: Path) -> None:
    """Optional datetime projection uses the same ISO parser as table cast."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"timestamp": ["2032-01-02T03:04:05"]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"projected","source":"input","operations":[],"columns":'
        '{"timestamp":{"optional_column":"timestamp","dtype":"datetime"}}}]',
        encoding="utf-8",
    )

    result = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)[
        "projected"
    ]

    assert list(result.iter_rows()) == [{"timestamp": datetime(2032, 1, 2, 3, 4, 5)}]
    assert result.data.collect_schema()["timestamp"] == pl.Datetime("us")


def test_optional_typed_projection_rejects_float_to_integer_truncation(tmp_path: Path) -> None:
    """Optional projection follows the public cast operation's lossy-cast policy."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"value": [1.7]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"projected","source":"input","operations":[],"columns":'
        '{"value":{"optional_column":"value","dtype":"int64"}}}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="floating-point to integer"):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_optional_typed_projection_rejects_integer_overflow(tmp_path: Path) -> None:
    """Optional projection does not wrap values outside the declared integer range."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"value": [2**63]}, schema={"value": pl.UInt64}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"projected","source":"input","operations":[],"columns":'
        '{"value":{"optional_column":"value","dtype":"int64"}}}]',
        encoding="utf-8",
    )
    result = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)[
        "projected"
    ]

    with pytest.raises(pl.exceptions.PolarsError):
        list(result.iter_rows())


def test_typed_null_projection_differs_from_omission_for_empty_and_absent_sources(
    tmp_path: Path,
) -> None:
    """A typed null creates a declared column while omission does not, even without rows."""
    backend = PolarsTabularBackend()
    schema = {"retained": pl.Int64}
    present = TabularSource(pl.DataFrame({"retained": [4]}, schema=schema).lazy(), backend)
    empty = TabularSource(pl.DataFrame(schema=schema).lazy(), backend)
    absent = TabularSource(
        pl.DataFrame(schema=schema).lazy(),
        backend,
        availability=SourceAvailability.ABSENT,
        absent_inputs=frozenset({"missing_resource_input"}),
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": name,
                    "source": source_name,
                    "operations": [],
                    "columns": columns,
                }
                for name, source_name, columns in [
                    (
                        "explicit_null",
                        "present",
                        {"retained": "retained", "capacity": {"value": None, "dtype": "float64"}},
                    ),
                    ("omitted", "present", {"retained": "retained"}),
                    (
                        "empty_null",
                        "empty",
                        {"retained": "retained", "capacity": {"value": None, "dtype": "float64"}},
                    ),
                    (
                        "absent_null",
                        "absent",
                        {"retained": "retained", "capacity": {"value": None, "dtype": "float64"}},
                    ),
                ]
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"present": present, "empty": empty, "absent": absent},
        mapping_path=mapping_path,
        backend=backend,
    )

    assert list(tables["explicit_null"].iter_rows()) == [{"capacity": None, "retained": 4}]
    assert tables["explicit_null"].data.collect_schema() == pl.Schema(
        {"capacity": pl.Float64, "retained": pl.Int64}
    )
    assert tables["omitted"].fields() == ["retained"]
    assert tables["empty_null"].fields() == ["capacity", "retained"]
    assert tables["empty_null"].data.collect_schema() == pl.Schema(
        {"capacity": pl.Float64, "retained": pl.Int64}
    )
    assert list(tables["empty_null"].iter_rows()) == []
    assert tables["absent_null"].availability is SourceAvailability.ABSENT
    assert tables["absent_null"].absent_inputs == frozenset({"missing_resource_input"})
    assert tables["absent_null"].data.collect_schema() == pl.Schema(
        {"capacity": pl.Float64, "retained": pl.Int64}
    )
    assert list(tables["absent_null"].iter_rows()) == []


def test_object_fields_keep_their_text_literal_contract(tmp_path: Path) -> None:
    """Typed table projection literals do not broaden object-field literal semantics."""
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            '[{"name":"bad","source":"input","operations":[{"operation":"object",'
            '"columns":{"field":{"value":1,"dtype":"int64"}},"output":"object"}]}]',
        )


@pytest.mark.parametrize(
    "literal",
    [
        pytest.param({"value": 1, "dtype": "bool"}, id="bool-rejects-integer"),
        pytest.param({"value": 1.0, "dtype": "int64"}, id="integer-rejects-float"),
        pytest.param({"value": 2**63, "dtype": "int64"}, id="integer-overflow"),
        pytest.param({"value": "not-a-datetime", "dtype": "datetime"}, id="malformed-datetime"),
        pytest.param({"value": 1, "dtype": "int32"}, id="unsupported-int32"),
    ],
)
def test_mapping_loader_rejects_incompatible_typed_projection_literals(
    tmp_path: Path, literal: dict[str, object]
) -> None:
    """Validate typed projection literals against the declared scalar vocabulary."""
    contents = json.dumps(
        [
            {
                "name": "bad",
                "source": "input",
                "operations": [],
                "columns": {"value": literal},
            }
        ]
    )

    with pytest.raises(ValidationError):
        assemble_mapping(tmp_path, contents)


@pytest.mark.parametrize(
    "contents",
    [
        '[{"name":"out","source":"input","operations":[{"operation":"join",'
        '"source":"input","how":"cross","on":null}]}]',
        '[{"name":"out","source":"input","operations":[{"operation":"join",'
        '"source":"input","how":"cross","columns":null}]}]',
        '[{"name":"out","source":"input","operations":[],"columns":null}]',
        '[{"name":"out","source":"input","operations":[{"operation":"unpivot",'
        '"index":[],"variable_name":"kind","value_name":"payload","value_type_name":null}]}]',
    ],
    ids=["cross-on-null", "join-columns-null", "projection-null", "unpivot-type-null"],
)
def test_mapping_loader_rejects_explicit_null_optional_fields(tmp_path: Path, contents: str) -> None:
    """TM-07 requires unused optional fields to be omitted, not null."""
    with pytest.raises(ValidationError):
        assemble_mapping(tmp_path, contents)


def test_join_treats_regex_shaped_column_names_as_exact_keys(tmp_path: Path) -> None:
    """Match a literal regex-shaped key name through the public assembly API."""
    backend = PolarsTabularBackend()
    left = TabularSource(pl.DataFrame({"^.*$": [1], "left": ["L"]}).lazy(), backend)
    right = TabularSource(pl.DataFrame({"^.*$": [1], "right": ["R"]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"joined","source":"left","operations":[{"operation":"join",'
        '"source":"right","how":"inner","on":["^.*$"]}]}]',
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"left": left, "right": right},
        mapping_path=mapping_path,
        backend=backend,
    )

    assert list(tables["joined"].iter_rows()) == [{"^.*$": 1, "left": "L", "right": "R"}]


def test_join_preserves_literal_selector_keys_composite_order_and_empty_payload(tmp_path: Path) -> None:
    """Join literal selector-shaped keys without losing row order or key coalescing."""
    backend = PolarsTabularBackend()
    keys = ["ordinary", "*", "^regex$", "^partial", "partial$"]
    left_columns = {
        "ordinary": [1, 1, 1, 2, None],
        "*": ["x", "y", "x", "z", "n"],
        "^regex$": ["r0", "r1", "r2", "r3", "rn"],
        "regex": ["r0", "r1", "r2", "r3", "rn"],
        "^partial": ["p0", "p1", "p2", "p3", "pn"],
        "partial$": ["s0", "s1", "s2", "s3", "sn"],
        "partial": ["p0", "p1", "p2", "p3", "pn"],
        "__r2x_table_mapping_key_0__": [
            "left-zero-0",
            "left-zero-1",
            "left-zero-2",
            "left-zero-3",
            "left-zero-n",
        ],
        "__r2x_table_mapping_key_1__": ["left-one-0", "left-one-1", "left-one-2", "left-one-3", "left-one-n"],
        "__r2x_table_mapping_key_2__": ["left-two-0", "left-two-1", "left-two-2", "left-two-3", "left-two-n"],
        "left": ["L0", "L1", "L2", "L3", "LN"],
    }
    right_columns = {
        "ordinary": [1, 1, 1, 1, 1, 1, None],
        "*": ["x", "y", "y", "x", "x", "x", "n"],
        "^regex$": ["wrong-r0", "r1", "r1", "r2", "r2", "r2", "rn"],
        "regex": ["r0", "r1", "r1", "r2", "r2", "r2", "rn"],
        "^partial": ["p0", "p1", "p1", "wrong-p2", "p2", "p2", "pn"],
        "partial$": ["s0", "s1", "s1", "s2", "wrong-s2", "s2", "sn"],
        "partial": ["p0", "p1", "p1", "p2", "p2", "p2", "pn"],
        "right_payload": ["near-regex", "R1a", "R1b", "near-prefix", "near-suffix", "R2", "Rnull"],
    }
    sources = {
        "left": TabularSource(pl.DataFrame(left_columns).lazy(), backend),
        "right": TabularSource(pl.DataFrame(right_columns).lazy(), backend),
    }
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "joined",
                    "source": "left",
                    "operations": [
                        {
                            "operation": "join",
                            "source": "right",
                            "how": "left",
                            "on": keys,
                            "columns": ["right_payload"],
                        }
                    ],
                },
                {
                    "name": "empty_payload",
                    "source": "left",
                    "operations": [
                        {
                            "operation": "join",
                            "source": "right",
                            "how": "left",
                            "on": keys,
                            "columns": [],
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=backend)

    joined = list(tables["joined"].iter_rows())
    assert [(row["left"], row["right_payload"]) for row in joined] == [
        ("L0", None),
        ("L1", "R1a"),
        ("L1", "R1b"),
        ("L2", "R2"),
        ("L3", None),
        ("LN", None),
    ]
    assert tables["joined"].fields() == [*left_columns, "right_payload"]
    assert joined[3]["__r2x_table_mapping_key_0__"] == "left-zero-2"
    assert joined[3]["__r2x_table_mapping_key_1__"] == "left-one-2"
    assert joined[3]["__r2x_table_mapping_key_2__"] == "left-two-2"

    empty_payload = tables["empty_payload"]
    assert empty_payload.fields() == list(left_columns)
    assert [row["left"] for row in empty_payload.iter_rows()] == ["L0", "L1", "L1", "L2", "L3", "LN"]


def test_join_preserves_duplicate_match_order_and_empty_payload_semantics(tmp_path: Path) -> None:
    """Preserve left order and right-match order even when no right payload is selected."""
    backend = PolarsTabularBackend()
    left = TabularSource(
        pl.DataFrame({"key": [2, 1, 2, 3], "left": ["L0", "L1", "L2", "L3"]}).lazy(), backend
    )
    right = TabularSource(pl.DataFrame({"key": [2, 2, 1], "right": ["R0", "R1", "R2"]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "matches",
                    "source": "left",
                    "operations": [{"operation": "join", "source": "right", "how": "inner", "on": ["key"]}],
                },
                {
                    "name": "empty_payload",
                    "source": "left",
                    "operations": [
                        {
                            "operation": "join",
                            "source": "right",
                            "how": "inner",
                            "on": ["key"],
                            "columns": [],
                        }
                    ],
                },
                {
                    "name": "empty_cross_payload",
                    "source": "left",
                    "operations": [{"operation": "join", "source": "right", "how": "cross", "columns": []}],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"left": left, "right": right}, mapping_path=mapping_path, backend=backend
    )

    expected = [
        {"key": 2, "left": "L0", "right": "R0"},
        {"key": 2, "left": "L0", "right": "R1"},
        {"key": 1, "left": "L1", "right": "R2"},
        {"key": 2, "left": "L2", "right": "R0"},
        {"key": 2, "left": "L2", "right": "R1"},
    ]
    assert list(tables["matches"].iter_rows()) == expected
    assert list(tables["empty_payload"].iter_rows()) == [
        {"key": 2, "left": "L0"},
        {"key": 2, "left": "L0"},
        {"key": 1, "left": "L1"},
        {"key": 2, "left": "L2"},
        {"key": 2, "left": "L2"},
    ]
    assert list(tables["empty_cross_payload"].iter_rows()) == [
        {"key": 2, "left": "L0"},
        {"key": 2, "left": "L0"},
        {"key": 2, "left": "L0"},
        {"key": 1, "left": "L1"},
        {"key": 1, "left": "L1"},
        {"key": 1, "left": "L1"},
        {"key": 2, "left": "L2"},
        {"key": 2, "left": "L2"},
        {"key": 2, "left": "L2"},
        {"key": 3, "left": "L3"},
        {"key": 3, "left": "L3"},
        {"key": 3, "left": "L3"},
    ]


def test_join_null_keys_do_not_match(tmp_path: Path) -> None:
    """Keep null join keys as non-matches while preserving the output schema."""
    backend = PolarsTabularBackend()
    left = TabularSource(
        pl.DataFrame(
            [pl.Series("key", [None], dtype=pl.Int64), pl.Series("left_value", [7], dtype=pl.Int64)]
        ).lazy(),
        backend,
    )
    right = TabularSource(
        pl.DataFrame(
            [pl.Series("key", [None], dtype=pl.Int64), pl.Series("right_value", [9], dtype=pl.Int64)]
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"joined","source":"left","operations":[{"operation":"join",'
        '"source":"right","how":"inner","on":["key"]}]}]',
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"left": left, "right": right},
        mapping_path=mapping_path,
        backend=backend,
    )

    assert list(tables["joined"].iter_rows()) == []
    assert tables["joined"].fields() == ["key", "left_value", "right_value"]


def test_join_rejects_payload_name_collisions(tmp_path: Path) -> None:
    """Fail instead of accepting Polars' automatic right-column suffixes."""
    backend = PolarsTabularBackend()
    left = TabularSource(pl.DataFrame({"key": [1], "payload": [2]}).lazy(), backend)
    right = TabularSource(pl.DataFrame({"key": [1], "payload": [3]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"joined","source":"left","operations":[{"operation":"join",'
        '"source":"right","how":"inner","on":["key"]}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="collide with left table"):
        r2x_core.assemble_tables(
            {"left": left, "right": right},
            mapping_path=mapping_path,
            backend=backend,
        )


def test_mapping_loader_rejects_duplicate_names_and_json_keys(tmp_path: Path) -> None:
    """Reject duplicate output names and duplicate JSON object members."""
    with pytest.raises(ValueError, match="Duplicate table name"):
        assemble_mapping(
            tmp_path,
            '[{"name":"out","source":"input","operations":[]},'
            '{"name":"out","source":"input","operations":[]}]',
        )
    with pytest.raises(ValueError, match="Duplicate JSON key 'name'"):
        assemble_mapping(
            tmp_path,
            '[{"name":"out","name":"out","source":"input","operations":[]}]',
        )


def test_documented_operations_preserve_literal_rows_types_and_order(tmp_path: Path) -> None:
    """Exercise filtering, grouping, unpivot, rows, concat, fill, and sort via JSON."""
    backend = PolarsTabularBackend()
    input_table = TabularSource(
        pl.DataFrame(
            {
                "year": [2032, 2032, 2040, 2032],
                "group": ["a", "a", "b", "b"],
                "amount": [5, None, None, None],
                "low": [1, 2, 3, 4],
                "high": [10.0, 20.0, 30.0, 40.0],
                "ratio": [float("nan"), None, 4.0, None],
                "sort_key": ["b", "b", "a", None],
                "ordinal": [0, 1, 2, 3],
            },
            schema={
                "year": pl.Int64,
                "group": pl.String,
                "amount": pl.Int64,
                "low": pl.Int64,
                "high": pl.Float64,
                "ratio": pl.Float64,
                "sort_key": pl.String,
                "ordinal": pl.Int64,
            },
        ).lazy(),
        backend,
    )
    inputs = {
        "input": input_table,
        "concat_int": TabularSource(
            pl.DataFrame(
                {"name": ["int"], "amount": [2]}, schema={"name": pl.String, "amount": pl.Int64}
            ).lazy(),
            backend,
        ),
        "concat_empty": TabularSource(
            pl.DataFrame(schema={"name": pl.String, "amount": pl.Float64}).lazy(), backend
        ),
        "concat_float": TabularSource(pl.DataFrame({"amount": [3.5], "name": ["float"]}).lazy(), backend),
    }
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "filtered",
                    "source": "input",
                    "operations": [
                        {"operation": "filter", "column": "year", "comparison": "equals", "value": "{year}"}
                    ],
                },
                {
                    "name": "grouped",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "group_by",
                            "columns": ["group"],
                            "aggregate": [
                                {"operation": "sum", "column": "amount", "output": "total"},
                                {"operation": "max", "column": "amount", "output": "largest"},
                            ],
                        }
                    ],
                },
                {
                    "name": "long",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "unpivot",
                            "index": ["ordinal"],
                            "columns": {"low": "low", "high": "high"},
                            "variable_name": "kind",
                            "value_name": "value",
                        }
                    ],
                },
                {
                    "name": "constructed",
                    "operations": [
                        {
                            "operation": "rows",
                            "schema": [{"name": "year", "dtype": "int64"}],
                            "values": "{solve_year_rows}",
                        }
                    ],
                },
                {
                    "name": "combined",
                    "operations": [
                        {"operation": "concat", "sources": ["concat_int", "concat_empty", "concat_float"]}
                    ],
                },
                {
                    "name": "filled",
                    "source": "input",
                    "operations": [
                        {"operation": "fill_null", "columns": ["amount", "ratio"], "value": "{zero}"}
                    ],
                },
                {
                    "name": "products",
                    "source": "input",
                    "operations": [
                        {"operation": "multiply", "columns": ["amount", "high"], "output": "product"}
                    ],
                },
                {
                    "name": "null_row",
                    "operations": [
                        {
                            "operation": "rows",
                            "schema": [{"name": "year", "dtype": "int64"}],
                            "values": [{"year": None}],
                        }
                    ],
                },
                {
                    "name": "sorted",
                    "source": "input",
                    "operations": [{"operation": "sort", "columns": ["sort_key"]}],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        inputs,
        mapping_path=mapping_path,
        backend=backend,
        placeholders={"year": 2032, "solve_year_rows": [{"year": 2032}, {"year": 2040}], "zero": 0},
    )

    filtered_rows = list(tables["filtered"].iter_rows())
    assert [{key: value for key, value in row.items() if key != "ratio"} for row in filtered_rows] == [
        {"amount": 5, "group": "a", "high": 10.0, "low": 1, "ordinal": 0, "sort_key": "b", "year": 2032},
        {"amount": None, "group": "a", "high": 20.0, "low": 2, "ordinal": 1, "sort_key": "b", "year": 2032},
        {"amount": None, "group": "b", "high": 40.0, "low": 4, "ordinal": 3, "sort_key": None, "year": 2032},
    ]
    assert filtered_rows[0]["ratio"] != filtered_rows[0]["ratio"]
    assert [row["ratio"] for row in filtered_rows[1:]] == [None, None]
    assert list(tables["grouped"].iter_rows()) == [
        {"group": "a", "total": 5, "largest": 5},
        {"group": "b", "total": 0, "largest": None},
    ]
    assert list(tables["long"].iter_rows()) == [
        {"ordinal": 0, "kind": "high", "value": 10.0},
        {"ordinal": 1, "kind": "high", "value": 20.0},
        {"ordinal": 2, "kind": "high", "value": 30.0},
        {"ordinal": 3, "kind": "high", "value": 40.0},
        {"ordinal": 0, "kind": "low", "value": 1.0},
        {"ordinal": 1, "kind": "low", "value": 2.0},
        {"ordinal": 2, "kind": "low", "value": 3.0},
        {"ordinal": 3, "kind": "low", "value": 4.0},
    ]
    assert tables["long"].fields() == ["ordinal", "kind", "value"]
    assert list(tables["constructed"].iter_rows()) == [{"year": 2032}, {"year": 2040}]
    assert list(tables["combined"].iter_rows()) == [
        {"name": "int", "amount": 2.0},
        {"name": "float", "amount": 3.5},
    ]
    assert tables["combined"].fields() == ["name", "amount"]
    assert tables["combined"].data.collect_schema() == pl.Schema({"name": pl.String, "amount": pl.Float64})
    filled_rows = list(tables["filled"].iter_rows())
    assert [row["amount"] for row in filled_rows] == [5, 0, 0, 0]
    assert filled_rows[0]["ratio"] != filled_rows[0]["ratio"]
    assert [row["ratio"] for row in filled_rows[1:]] == [0.0, 4.0, 0.0]
    assert tables["filled"].data.collect_schema()["amount"] == pl.Int64
    assert [row["product"] for row in tables["products"].iter_rows()] == [50.0, None, None, None]
    assert list(tables["null_row"].iter_rows()) == [{"year": None}]
    assert tables["null_row"].data.collect_schema() == pl.Schema({"year": pl.Int64})
    assert [row["ordinal"] for row in tables["sorted"].iter_rows()] == [2, 0, 1, 3]


def test_casefold_operation_supports_exact_key_joins_without_changing_display_values(tmp_path: Path) -> None:
    """Normalize Unicode lookup keys while retaining exact, casefolded join semantics."""
    backend = PolarsTabularBackend()
    generators = TabularSource(
        pl.DataFrame(
            {"technology": ["WIND*CCS", "wind_ccs", "Maße", None]},
            schema={"technology": pl.String},
        ).lazy(),
        backend,
    )
    overrides = TabularSource(
        pl.DataFrame(
            {
                "override_technology": ["wind*ccs", "wind", "MASSE"],
                "category": ["special", "prefix-like", "unicode"],
            },
            schema={"override_technology": pl.String, "category": pl.String},
        ).lazy(),
        backend,
    )
    empty_generators = TabularSource(
        pl.DataFrame(schema={"technology": pl.String}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "generator_keys",
                    "source": "generators",
                    "operations": [
                        {"operation": "casefold", "column": "technology", "output": "technology_key"}
                    ],
                },
                {
                    "name": "override_keys",
                    "source": "overrides",
                    "operations": [
                        {
                            "operation": "casefold",
                            "column": "override_technology",
                            "output": "technology_key",
                        }
                    ],
                },
                {
                    "name": "empty_generator_keys",
                    "source": "empty_generators",
                    "operations": [
                        {"operation": "casefold", "column": "technology", "output": "technology_key"}
                    ],
                },
                {
                    "name": "matched",
                    "source": "generator_keys",
                    "operations": [
                        {
                            "operation": "join",
                            "source": "override_keys",
                            "how": "left",
                            "on": ["technology_key"],
                            "columns": ["category"],
                        }
                    ],
                    "columns": {"category": "category", "technology": "technology"},
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"generators": generators, "overrides": overrides, "empty_generators": empty_generators},
        mapping_path=mapping_path,
        backend=backend,
    )

    assert list(tables["matched"].iter_rows()) == [
        {"category": "special", "technology": "WIND*CCS"},
        {"category": None, "technology": "wind_ccs"},
        {"category": "unicode", "technology": "Maße"},
        {"category": None, "technology": None},
    ]
    assert tables["empty_generator_keys"].fields() == ["technology", "technology_key"]
    assert tables["empty_generator_keys"].data.collect_schema() == pl.Schema(
        {"technology": pl.String, "technology_key": pl.String}
    )
    assert list(tables["empty_generator_keys"].iter_rows()) == []


@pytest.mark.parametrize(
    ("schema", "column", "output", "match"),
    [
        ({"technology": pl.Int64}, "technology", "key", "requires a string column"),
        ({"technology": pl.String}, "missing", "key", "missing column"),
        ({"technology": pl.String, "key": pl.String}, "technology", "key", "already exists"),
    ],
    ids=["non-string", "missing-column", "output-collision"],
)
def test_casefold_operation_rejects_invalid_columns(
    tmp_path: Path,
    schema: dict[str, pl.DataType],
    column: str,
    output: str,
    match: str,
) -> None:
    """Reject invalid casefold inputs instead of coercing or overwriting values."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame(schema=schema).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "casefolded",
                    "source": "input",
                    "operations": [{"operation": "casefold", "column": column, "output": output}],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=match):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_absolute_operation_preserves_numeric_dtype_nulls_order_and_empty_schema(tmp_path: Path) -> None:
    """Take absolute values through the public mapping API without changing rows or dtype."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            [
                pl.Series("integer", [-70, 0, None, 70], dtype=pl.Int64),
                pl.Series("floating", [-1.5, 0.0, None, 2.5], dtype=pl.Float64),
            ]
        ).lazy(),
        backend,
    )
    empty = TabularSource(
        pl.DataFrame(schema={"integer": pl.Int64}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "integer_absolute",
                    "source": "input",
                    "operations": [{"operation": "absolute", "column": "integer", "output": "magnitude"}],
                },
                {
                    "name": "float_absolute",
                    "source": "input",
                    "operations": [{"operation": "absolute", "column": "floating", "output": "magnitude"}],
                },
                {
                    "name": "empty_absolute",
                    "source": "empty",
                    "operations": [{"operation": "absolute", "column": "integer", "output": "magnitude"}],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty": empty}, mapping_path=mapping_path, backend=backend
    )

    assert [row["magnitude"] for row in tables["integer_absolute"].iter_rows()] == [70, 0, None, 70]
    assert tables["integer_absolute"].data.collect_schema()["magnitude"] == pl.Int64
    assert [row["magnitude"] for row in tables["float_absolute"].iter_rows()] == [1.5, 0.0, None, 2.5]
    assert tables["float_absolute"].data.collect_schema()["magnitude"] == pl.Float64
    assert list(tables["empty_absolute"].iter_rows()) == []
    assert tables["empty_absolute"].data.collect_schema() == pl.Schema(
        {"integer": pl.Int64, "magnitude": pl.Int64}
    )


@pytest.mark.parametrize(
    ("column", "output", "schema", "values", "match"),
    [
        ("value", "magnitude", {"value": pl.String}, ["-70"], "requires a numeric column"),
        ("missing", "magnitude", {"value": pl.Int64}, [1], "missing column"),
        ("value", "value", {"value": pl.Int64}, [1], "already exists"),
    ],
    ids=["text", "missing-column", "output-collision"],
)
def test_absolute_operation_rejects_invalid_columns(
    tmp_path: Path,
    column: str,
    output: str,
    schema: dict[str, pl.DataType],
    values: list[object],
    match: str,
) -> None:
    """Reject unsupported inputs instead of silently coercing or overwriting them."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"value": values}, schema=schema).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "absolute",
                    "source": "input",
                    "operations": [{"operation": "absolute", "column": column, "output": output}],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=match):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_static_match_patterns_emits_every_matching_group_and_typed_empty_output(tmp_path: Path) -> None:
    """Keep static exact/prefix matching distinct from source-pattern precedence matching."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {"^.*$": ["BATTERY_4", "battery", "CAES", "rtes_solar", "unmatched", None]},
            schema={"^.*$": pl.String},
        ).lazy(),
        backend,
    )
    empty_source = TabularSource(pl.DataFrame(schema={"^.*$": pl.String}).lazy(), backend)
    operation = {
        "operation": "match_patterns",
        "column": "^.*$",
        "label_column": "category",
        "defaults": {"priority": 90},
        "case_sensitive": False,
        "groups": [
            {"label": "broad", "prefixes": ["battery"]},
            {"label": "storage", "prefixes": ["battery_"]},
            {"label": "storage", "exact": ["caes"]},
            {"label": "geothermal", "prefixes": ["rtes"]},
        ],
    }
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {"name": "matches", "source": "input", "operations": [operation]},
                {"name": "empty_matches", "source": "empty", "operations": [operation]},
                {
                    "name": "case_sensitive_matches",
                    "source": "input",
                    "operations": [{**operation, "case_sensitive": True}],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty": empty_source}, mapping_path=mapping_path, backend=backend
    )

    assert list(tables["matches"].iter_rows()) == [
        {"^.*$": "BATTERY_4", "category": "broad", "priority": 90},
        {"^.*$": "battery", "category": "broad", "priority": 90},
        {"^.*$": "BATTERY_4", "category": "storage", "priority": 90},
        {"^.*$": "CAES", "category": "storage", "priority": 90},
        {"^.*$": "rtes_solar", "category": "geothermal", "priority": 90},
    ]
    assert tables["empty_matches"].data.collect_schema() == pl.Schema(
        {"^.*$": pl.String, "category": pl.String, "priority": pl.Int64}
    )
    assert list(tables["empty_matches"].iter_rows()) == []
    assert list(tables["case_sensitive_matches"].iter_rows()) == [
        {"^.*$": "battery", "category": "broad", "priority": 90},
        {"^.*$": "rtes_solar", "category": "geothermal", "priority": 90},
    ]


def test_static_match_patterns_rejects_output_collisions(tmp_path: Path) -> None:
    """Raise on static matcher labels that overwrite source columns."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"name": ["gas"], "category": ["existing"]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "matches",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "match_patterns",
                            "column": "name",
                            "label_column": "category",
                            "groups": [{"label": "thermal", "exact": ["gas"]}],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="already exist"):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


@pytest.mark.parametrize(
    ("duplicate_policy", "exact_label"),
    [("first", "exact-first"), ("last", "exact-last")],
)
def test_match_source_patterns_resolves_precedence_duplicates_and_unmatched_rows(
    tmp_path: Path, duplicate_policy: str, exact_label: str
) -> None:
    """Match exact, numeric range, and delimited prefix with explicit tie and keep policies."""
    backend = PolarsTabularBackend()
    technologies = TabularSource(
        pl.DataFrame(
            {"technology": ["plant_4", "plant_6", "plant_10", "outsider"], "capacity": [40, 60, 100, 5]},
            schema={"technology": pl.String, "capacity": pl.Int64},
        ).lazy(),
        backend,
    )
    patterns = TabularSource(
        pl.DataFrame(
            {
                "pattern": ["plant_1..plant_9", "plant", "plant_4", "plant_4"],
                "label": ["range", "prefix", "exact-first", "exact-last"],
            },
            schema={"pattern": pl.String, "label": pl.String},
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "classified",
                    "source": "technologies",
                    "operations": [
                        {
                            "operation": "match_source_patterns",
                            "column": "technology",
                            "source": "patterns",
                            "pattern_column": "pattern",
                            "range_separator": "..",
                            "prefix_separator": "_",
                            "precedence": ["exact", "range", "prefix"],
                            "prefix_policy": "longest",
                            "duplicate_policy": duplicate_policy,
                            "unmatched": "keep",
                            "case_sensitive": True,
                        }
                    ],
                    "columns": {
                        "capacity": "capacity",
                        "category": "label",
                        "technology": "technology",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"technologies": technologies, "patterns": patterns},
        mapping_path=mapping_path,
        backend=backend,
    )

    assert list(tables["classified"].iter_rows()) == [
        {"capacity": 40, "category": exact_label, "technology": "plant_4"},
        {"capacity": 60, "category": "range", "technology": "plant_6"},
        {"capacity": 100, "category": "prefix", "technology": "plant_10"},
        {"capacity": 5, "category": None, "technology": "outsider"},
    ]


@pytest.mark.parametrize(
    ("left_name", "pattern_name", "payload_name"),
    [
        pytest.param("^technology$", "^pattern$", "^label$", id="regex-shaped-names"),
        pytest.param("*", "pattern", "output", id="wildcard-left-name"),
        pytest.param("technology", "*", "output", id="wildcard-pattern-name"),
        pytest.param("technology", "pattern", "*", id="wildcard-payload-name"),
        pytest.param("*", "*", "output", id="shared-wildcard-name"),
        pytest.param("^technology$", "^technology$", "output", id="shared-regex-shaped-name"),
    ],
)
def test_match_source_patterns_treats_selector_shaped_names_as_literals(
    tmp_path: Path, left_name: str, pattern_name: str, payload_name: str
) -> None:
    """Match and retain exact user columns even when names resemble Polars selectors."""
    backend = PolarsTabularBackend()
    left_columns = {left_name: ["wind", "other"], "left_marker": ["first", "second"]}
    pattern_columns = {pattern_name: ["wind"], payload_name: ["matched"]}
    if left_name == "^technology$":
        left_columns["technology"] = ["wrong", "wrong"]
        pattern_columns["pattern"] = ["pattern-decoy"]
        pattern_columns["label"] = ["label-decoy"]
    sources = {
        "assets": TabularSource(pl.DataFrame(left_columns).lazy(), backend),
        "patterns": TabularSource(pl.DataFrame(pattern_columns).lazy(), backend),
    }
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "matches",
                    "source": "assets",
                    "operations": [
                        {
                            "operation": "match_source_patterns",
                            "column": left_name,
                            "source": "patterns",
                            "pattern_column": pattern_name,
                            "range_separator": "..",
                            "prefix_separator": "_",
                            "precedence": ["exact", "range", "prefix"],
                            "prefix_policy": "longest",
                            "duplicate_policy": "first",
                            "unmatched": "keep",
                            "case_sensitive": True,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=backend)["matches"]

    first = {left_name: "wind", "left_marker": "first", payload_name: "matched"}
    second = {left_name: "other", "left_marker": "second", payload_name: None}
    if left_name == "^technology$":
        first.update({"technology": "wrong", "pattern": "pattern-decoy", "label": "label-decoy"})
        second.update({"technology": "wrong", "pattern": None, "label": None})
    assert result.fields() == [*left_columns, *(name for name in pattern_columns if name != pattern_name)]
    assert list(result.iter_rows()) == [first, second]


def test_match_source_patterns_allows_pattern_name_to_overlap_left_columns(tmp_path: Path) -> None:
    """A pattern-only column is not an output and cannot conflict with left column names."""
    backend = PolarsTabularBackend()
    sources = {
        "assets": TabularSource(
            pl.DataFrame({"technology": ["wind"], "pattern": ["left"], "pattern_right": ["retained"]}).lazy(),
            backend,
        ),
        "patterns": TabularSource(pl.DataFrame({"pattern": ["wind"], "label": ["matched"]}).lazy(), backend),
    }
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "matches",
                    "source": "assets",
                    "operations": [
                        {
                            "operation": "match_source_patterns",
                            "column": "technology",
                            "source": "patterns",
                            "pattern_column": "pattern",
                            "range_separator": "..",
                            "prefix_separator": "_",
                            "precedence": ["exact", "range", "prefix"],
                            "prefix_policy": "longest",
                            "duplicate_policy": "first",
                            "unmatched": "keep",
                            "case_sensitive": True,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=backend)["matches"]

    assert result.fields() == ["technology", "pattern", "pattern_right", "label"]
    assert list(result.iter_rows()) == [
        {"technology": "wind", "pattern": "left", "pattern_right": "retained", "label": "matched"}
    ]


def test_match_source_patterns_uses_unicode_casefold_not_lowercase(tmp_path: Path) -> None:
    """Use Unicode casefold for endpoints and separators without folding dotless i."""
    backend = PolarsTabularBackend()
    technologies = TabularSource(
        pl.DataFrame(
            {"technology": ["stra\u00dfe", "\u0131sparta", "stra\u00dfe2", "ITEM\u0130node"]},
            schema={"technology": pl.String},
        ).lazy(),
        backend,
    )
    patterns = TabularSource(
        pl.DataFrame(
            {
                "pattern": ["STRASSE", "isparta", "stra\u00dfe1..STRASSE3", "item"],
                "policy": ["sharp-s", "dotted-i", "range", "prefix"],
            },
            schema={"pattern": pl.String, "policy": pl.String},
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "classified",
                    "source": "technologies",
                    "operations": [
                        {
                            "operation": "match_source_patterns",
                            "column": "technology",
                            "source": "patterns",
                            "pattern_column": "pattern",
                            "range_separator": "..",
                            "prefix_separator": "İ",
                            "precedence": ["exact", "range", "prefix"],
                            "prefix_policy": "longest",
                            "duplicate_policy": "first",
                            "unmatched": "keep",
                            "case_sensitive": False,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"technologies": technologies, "patterns": patterns}, mapping_path=mapping_path, backend=backend
    )

    assert list(tables["classified"].iter_rows()) == [
        {"technology": "stra\u00dfe", "policy": "sharp-s"},
        {"technology": "\u0131sparta", "policy": None},
        {"technology": "stra\u00dfe2", "policy": "range"},
        {"technology": "ITEM\u0130node", "policy": "prefix"},
    ]


@pytest.mark.parametrize(("case_sensitive", "invalid"), [(False, True), (True, False)])
def test_match_source_patterns_validates_casefolded_delimiters(
    tmp_path: Path, case_sensitive: bool, invalid: bool
) -> None:
    """Only case-insensitive matching rejects delimiters with equal casefold forms."""
    backend = PolarsTabularBackend()
    sources = {
        "assets": TabularSource(
            pl.DataFrame({"asset_id": []}, schema={"asset_id": pl.String}).lazy(), backend
        ),
        "patterns": TabularSource(
            pl.DataFrame(
                {"pattern": [], "policy": []}, schema={"pattern": pl.String, "policy": pl.String}
            ).lazy(),
            backend,
        ),
    }
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "classified",
                    "source": "assets",
                    "operations": [
                        {
                            "operation": "match_source_patterns",
                            "column": "asset_id",
                            "source": "patterns",
                            "pattern_column": "pattern",
                            "range_separator": "ß",
                            "prefix_separator": "ss",
                            "precedence": ["exact", "range", "prefix"],
                            "prefix_policy": "first",
                            "duplicate_policy": "first",
                            "unmatched": "keep",
                            "case_sensitive": case_sensitive,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    if invalid:
        with pytest.raises(ValidationError, match="casefold"):
            r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=backend)
    else:
        result = r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=backend)["classified"]
        assert list(result.iter_rows()) == []
        assert result.fields() == ["asset_id", "policy"]


def test_match_source_patterns_drops_unmatched_and_preserves_empty_schemas(tmp_path: Path) -> None:
    """Apply unmatched-drop and retain typed output fields for empty left or right inputs."""
    backend = PolarsTabularBackend()
    sources = {
        "assets": TabularSource(
            pl.DataFrame({"asset_id": ["rack.2", "other.1"]}, schema={"asset_id": pl.String}).lazy(), backend
        ),
        "empty_assets": TabularSource(
            pl.DataFrame({"asset_id": []}, schema={"asset_id": pl.String}).lazy(), backend
        ),
        "absent_assets": TabularSource(
            pl.DataFrame({"asset_id": []}, schema={"asset_id": pl.String}).lazy(),
            backend,
            availability=SourceAvailability.ABSENT,
            absent_inputs=frozenset({"optional_assets"}),
        ),
        "patterns": TabularSource(
            pl.DataFrame(
                {"pattern": ["rack.1..rack.3"], "policy": ["rack"]},
                schema={"pattern": pl.String, "policy": pl.String},
            ).lazy(),
            backend,
        ),
        "empty_patterns": TabularSource(
            pl.DataFrame(
                {"pattern": [], "policy": []}, schema={"pattern": pl.String, "policy": pl.String}
            ).lazy(),
            backend,
        ),
        "absent_patterns": TabularSource(
            pl.DataFrame(
                {"pattern": [], "policy": []}, schema={"pattern": pl.String, "policy": pl.String}
            ).lazy(),
            backend,
            availability=SourceAvailability.ABSENT,
            absent_inputs=frozenset({"optional_patterns"}),
        ),
    }
    operation = {
        "operation": "match_source_patterns",
        "column": "asset_id",
        "source": "patterns",
        "pattern_column": "pattern",
        "range_separator": "..",
        "prefix_separator": ".",
        "precedence": ["exact", "range", "prefix"],
        "prefix_policy": "longest",
        "duplicate_policy": "last",
        "unmatched": "drop",
    }
    empty_operation = {**operation, "source": "empty_patterns", "unmatched": "keep"}
    absent_keep_operation = {**operation, "source": "absent_patterns", "unmatched": "keep"}
    absent_drop_operation = {**operation, "source": "absent_patterns"}
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {"name": "matched", "source": "assets", "operations": [operation]},
                {"name": "empty_left", "source": "empty_assets", "operations": [empty_operation]},
                {"name": "empty_right", "source": "assets", "operations": [empty_operation]},
                {
                    "name": "empty_right_drop",
                    "source": "assets",
                    "operations": [{**empty_operation, "unmatched": "drop"}],
                },
                {"name": "absent_right_keep", "source": "assets", "operations": [absent_keep_operation]},
                {"name": "absent_right_drop", "source": "assets", "operations": [absent_drop_operation]},
                {
                    "name": "absent_left_and_right",
                    "source": "absent_assets",
                    "operations": [absent_keep_operation],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=backend)

    assert list(tables["matched"].iter_rows()) == [{"asset_id": "rack.2", "policy": "rack"}]
    assert list(tables["empty_left"].iter_rows()) == []
    assert tables["empty_left"].fields() == ["asset_id", "policy"]
    assert tables["empty_left"].data.collect_schema() == pl.Schema(
        {"asset_id": pl.String, "policy": pl.String}
    )
    assert list(tables["empty_right"].iter_rows()) == [
        {"asset_id": "rack.2", "policy": None},
        {"asset_id": "other.1", "policy": None},
    ]
    assert tables["empty_right"].fields() == ["asset_id", "policy"]
    assert tables["empty_right"].data.collect_schema() == pl.Schema(
        {"asset_id": pl.String, "policy": pl.String}
    )
    assert list(tables["empty_right_drop"].iter_rows()) == []
    assert tables["empty_right_drop"].absent_inputs == frozenset()
    for name in ("absent_right_keep", "absent_right_drop"):
        assert tables[name].availability is SourceAvailability.PRESENT
        assert tables[name].absent_inputs == frozenset({"optional_patterns"})
    assert list(tables["absent_right_keep"].iter_rows()) == [
        {"asset_id": "rack.2", "policy": None},
        {"asset_id": "other.1", "policy": None},
    ]
    assert list(tables["absent_right_drop"].iter_rows()) == []
    assert tables["absent_left_and_right"].availability is SourceAvailability.ABSENT
    assert tables["absent_left_and_right"].absent_inputs == frozenset(
        {"optional_assets", "optional_patterns"}
    )
    assert list(tables["absent_left_and_right"].iter_rows()) == []


def test_match_source_patterns_rejects_malformed_ranges_in_table_mapping(tmp_path: Path) -> None:
    """Reject malformed present range declarations through the public assembly API."""
    backend = PolarsTabularBackend()
    sources = {
        "assets": TabularSource(
            pl.DataFrame({"asset_id": []}, schema={"asset_id": pl.String}).lazy(), backend
        ),
        "patterns": TabularSource(
            pl.DataFrame(
                {"pattern": ["rack.1..shelf.4"], "policy": ["invalid"]},
                schema={"pattern": pl.String, "policy": pl.String},
            ).lazy(),
            backend,
        ),
    }
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "classified",
                    "source": "assets",
                    "operations": [
                        {
                            "operation": "match_source_patterns",
                            "column": "asset_id",
                            "source": "patterns",
                            "pattern_column": "pattern",
                            "range_separator": "..",
                            "prefix_separator": ".",
                            "precedence": ["exact", "range", "prefix"],
                            "prefix_policy": "first",
                            "duplicate_policy": "first",
                            "unmatched": "keep",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid numeric range pattern"):
        r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=backend)


def test_unpivot_allows_an_index_column_as_a_value_input(tmp_path: Path) -> None:
    """Retain an identifier while also unpivoting its value under an explicit label."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"region": ["west"]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "long",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "unpivot",
                            "index": ["region"],
                            "columns": {"selected": "region"},
                            "variable_name": "kind",
                            "value_name": "value",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["long"].iter_rows()) == [{"region": "west", "kind": "selected", "value": "west"}]


def test_unpivot_preserves_source_types_with_explicit_labels_and_nulls(tmp_path: Path) -> None:
    """Attach backend-neutral type names while preserving exact labels and source order."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "id": ["a", "b"],
                "a.label": ["yes", "true"],
                "^.*$": [True, None],
            },
            schema={"id": pl.String, "a.label": pl.String, "^.*$": pl.Boolean},
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "long",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "unpivot",
                            "index": ["id"],
                            "columns": {"id": "^.*$", "a.label": "a.label"},
                            "variable_name": "label",
                            "value_name": "value",
                            "value_type_name": "logical_type",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["long"].iter_rows()) == [
        {"id": "a", "label": "a.label", "value": "yes", "logical_type": "string"},
        {"id": "b", "label": "a.label", "value": "true", "logical_type": "string"},
        {"id": "a", "label": "id", "value": "true", "logical_type": "bool"},
        {"id": "b", "label": "id", "value": None, "logical_type": "bool"},
    ]


def test_unpivot_type_metadata_rejects_non_scalar_source_dtypes(tmp_path: Path) -> None:
    """Require every typed-unpivot source column to use a supported logical scalar type."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"values": [[1], [2]]}, schema={"values": pl.List(pl.Int64)}).lazy(), backend
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "long",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "unpivot",
                            "index": [],
                            "columns": {"values": "values"},
                            "variable_name": "field",
                            "value_name": "value",
                            "value_type_name": "field_type",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="supported types are bool, int64, float64, string, and datetime"):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_unpivot_type_metadata_preserves_typed_empty_schema(tmp_path: Path) -> None:
    """Retain declared identifier, value, label, and logical type fields on empty input."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(schema={"region": pl.String, "enabled": pl.Boolean, "name^raw": pl.String}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "empty_long",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "unpivot",
                            "index": ["region"],
                            "columns": {"enabled": "enabled", "name^raw": "name^raw"},
                            "variable_name": "field",
                            "value_name": "raw_value",
                            "value_type_name": "field_type",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    table = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)[
        "empty_long"
    ]

    assert list(table.iter_rows()) == []
    assert table.data.collect_schema() == pl.Schema(
        {
            "region": pl.String,
            "field": pl.String,
            "raw_value": pl.String,
            "field_type": pl.String,
        }
    )


def test_unpivot_uses_all_non_index_columns_when_columns_are_omitted(tmp_path: Path) -> None:
    """Use exact native headers, sorted labels, and preserved row order."""
    from datetime import datetime

    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "datetime": [datetime(2032, 1, 1), datetime(2032, 1, 2), datetime(2032, 1, 3)],
                "solve_year": [2032, 2032, 2040],
                "weather_year": [2012, 2012, 2013],
                "p2": [20, None, 30],
                "p1": [1.5, 2.5, None],
            },
            schema={
                "datetime": pl.Datetime("us"),
                "solve_year": pl.Int64,
                "weather_year": pl.Int64,
                "p2": pl.Int64,
                "p1": pl.Float64,
            },
        ).lazy(),
        backend,
    )
    empty = TabularSource(
        pl.DataFrame(
            schema={
                "datetime": pl.Datetime("us"),
                "solve_year": pl.Int64,
                "weather_year": pl.Int64,
                "p2": pl.Int64,
                "p1": pl.Float64,
            }
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "long",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "unpivot",
                            "index": ["datetime", "solve_year", "weather_year"],
                            "variable_name": "region",
                            "value_name": "load_mw",
                        }
                    ],
                },
                {
                    "name": "long_empty",
                    "source": "empty",
                    "operations": [
                        {
                            "operation": "unpivot",
                            "index": ["datetime", "solve_year", "weather_year"],
                            "variable_name": "region",
                            "value_name": "load_mw",
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty": empty}, mapping_path=mapping_path, backend=backend
    )

    assert list(tables["long"].iter_rows()) == [
        {
            "datetime": datetime(2032, 1, 1),
            "solve_year": 2032,
            "weather_year": 2012,
            "region": "p1",
            "load_mw": 1.5,
        },
        {
            "datetime": datetime(2032, 1, 2),
            "solve_year": 2032,
            "weather_year": 2012,
            "region": "p1",
            "load_mw": 2.5,
        },
        {
            "datetime": datetime(2032, 1, 3),
            "solve_year": 2040,
            "weather_year": 2013,
            "region": "p1",
            "load_mw": None,
        },
        {
            "datetime": datetime(2032, 1, 1),
            "solve_year": 2032,
            "weather_year": 2012,
            "region": "p2",
            "load_mw": 20.0,
        },
        {
            "datetime": datetime(2032, 1, 2),
            "solve_year": 2032,
            "weather_year": 2012,
            "region": "p2",
            "load_mw": None,
        },
        {
            "datetime": datetime(2032, 1, 3),
            "solve_year": 2040,
            "weather_year": 2013,
            "region": "p2",
            "load_mw": 30.0,
        },
    ]
    expected_schema = pl.Schema(
        {
            "datetime": pl.Datetime("us"),
            "solve_year": pl.Int64,
            "weather_year": pl.Int64,
            "region": pl.String,
            "load_mw": pl.Float64,
        }
    )
    assert tables["long"].data.collect_schema() == expected_schema
    assert list(tables["long_empty"].iter_rows()) == []
    assert tables["long_empty"].data.collect_schema() == expected_schema


def test_unpivot_rejects_omitted_columns_when_no_value_columns_exist(tmp_path: Path) -> None:
    """Require at least one dynamically selected value column."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(schema={"datetime": pl.Datetime("us"), "solve_year": pl.Int64}).lazy(), backend
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"long","source":"input","operations":[{"operation":"unpivot",'
        '"index":["datetime","solve_year"],"variable_name":"region","value_name":"load_mw"}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="at least one value column"):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_add_and_divide_preserve_types_nulls_and_rows(tmp_path: Path) -> None:
    """Use explicit operand order and return null for null operands or zero division."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "id": ["normal", "zero", "null"],
                "left_int": [45_000, None, 4],
                "right_int": [1_000, 3, None],
                "left_float": [1.25, 2.0, 2.0],
                "cost": [200.0, 200.0, None],
                "distance": [40.0, 0.0, 5.0],
            },
            schema={
                "id": pl.String,
                "left_int": pl.Int64,
                "right_int": pl.Int64,
                "left_float": pl.Float64,
                "cost": pl.Float64,
                "distance": pl.Float64,
            },
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "integer_addition",
                    "source": "input",
                    "operations": [
                        {"operation": "add", "columns": ["left_int", "right_int"], "output": "total"}
                    ],
                    "columns": {"id": "id", "total": "total"},
                },
                {
                    "name": "mixed_addition",
                    "source": "input",
                    "operations": [
                        {"operation": "add", "columns": ["left_int", "left_float"], "output": "total"}
                    ],
                    "columns": {"id": "id", "total": "total"},
                },
                {
                    "name": "division",
                    "source": "input",
                    "operations": [
                        {"operation": "divide", "columns": ["cost", "distance"], "output": "rate"}
                    ],
                    "columns": {"id": "id", "rate": "rate"},
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["integer_addition"].iter_rows()) == [
        {"id": "normal", "total": 46_000},
        {"id": "zero", "total": None},
        {"id": "null", "total": None},
    ]
    assert tables["integer_addition"].data.collect_schema()["total"] == pl.Int64
    assert list(tables["mixed_addition"].iter_rows()) == [
        {"id": "normal", "total": 45_001.25},
        {"id": "zero", "total": None},
        {"id": "null", "total": 6.0},
    ]
    assert tables["mixed_addition"].data.collect_schema()["total"] == pl.Float64
    assert list(tables["division"].iter_rows()) == [
        {"id": "normal", "rate": 5.0},
        {"id": "zero", "rate": None},
        {"id": "null", "rate": None},
    ]
    assert tables["division"].data.collect_schema()["rate"] == pl.Float64


def test_filter_comparisons_support_columns_and_null_predicates(tmp_path: Path) -> None:
    """Apply literal and exact column comparisons without coercion or null matches."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "id": [0, 1, 2, 3, 4],
                "value": [1, 2, 3, None, 2],
                "other": [2, 2, 2, 2, None],
            },
            schema={"id": pl.Int64, "value": pl.Int64, "other": pl.Int64},
        ).lazy(),
        backend,
    )
    filter_cases = [
        ("greater", "greater_than", {"other_column": "other"}, [2]),
        ("different", "not_equal", {"value": 2}, [0, 2]),
        ("less", "less_than", {"value": 2}, [0]),
        ("at_least", "greater_than_or_equal", {"other_column": "other"}, [1, 2]),
        ("at_most", "less_than_or_equal", {"other_column": "other"}, [0, 1]),
        ("nulls", "is_null", {}, [3]),
        ("non_nulls", "is_not_null", {}, [0, 1, 2, 4]),
    ]
    records = [
        {
            "name": name,
            "source": "input",
            "operations": [
                {
                    "operation": "filter",
                    "column": "value",
                    "comparison": comparison,
                    **operand,
                }
            ],
            "columns": {"id": "id"},
        }
        for name, comparison, operand, _ in filter_cases
    ]
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(json.dumps(records), encoding="utf-8")

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert {name: list(table.iter_rows()) for name, table in tables.items()} == {
        name: [{"id": value} for value in expected] for name, _comparison, _operand, expected in filter_cases
    }


def test_starts_with_filters_and_chooses_literal_or_column_prefixes(tmp_path: Path) -> None:
    """Use literal, case-sensitive string prefixes with explicit null and row semantics."""
    backend = PolarsTabularBackend()
    schema = {"value": pl.String, "prefix": pl.String}
    source = TabularSource(
        pl.DataFrame(
            {
                "value": ["init1", "init-1", "INIT1", "new1", None, "anything", "a.b", "axb", ""],
                "prefix": ["init", "init", "init", "new", "init", None, "a.", "a.", ""],
            },
            schema=schema,
        ).lazy(),
        backend,
    )
    empty = TabularSource(pl.DataFrame(schema=schema).lazy(), backend)
    special = TabularSource(
        pl.DataFrame({"^value$": ["init1"], "value": ["decoy"], "*": ["init"]}).lazy(), backend
    )
    choose = {
        "operation": "choose",
        "column": "value",
        "comparison": "starts_with",
        "other_column": "prefix",
        "then": {"value": True},
        "otherwise": {"value": False},
        "output": "matched",
    }
    records = [
        {"name": "chosen", "source": "input", "operations": [choose]},
        {"name": "empty_result", "source": "empty", "operations": [choose]},
        {
            "name": "special_result",
            "source": "special",
            "operations": [choose | {"column": "^value$", "other_column": "*"}],
        },
        {
            "name": "literal_filter",
            "source": "input",
            "operations": [
                {"operation": "filter", "column": "value", "comparison": "starts_with", "value": "{prefix}"}
            ],
            "columns": {"value": "value"},
        },
        {
            "name": "column_filter",
            "source": "input",
            "operations": [
                {
                    "operation": "filter",
                    "column": "value",
                    "comparison": "starts_with",
                    "other_column": "prefix",
                }
            ],
            "columns": {"value": "value"},
        },
        {
            "name": "null_filter",
            "source": "input",
            "operations": [
                {"operation": "filter", "column": "value", "comparison": "starts_with", "value": None}
            ],
        },
    ]
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(json.dumps(records), encoding="utf-8")

    tables = r2x_core.assemble_tables(
        {"input": source, "empty": empty, "special": special},
        mapping_path=mapping_path,
        backend=backend,
        placeholders={"prefix": "init"},
    )

    assert [row["matched"] for row in tables["chosen"].iter_rows()] == [
        True,
        True,
        False,
        True,
        False,
        False,
        True,
        False,
        True,
    ]
    assert tables["empty_result"].data.collect_schema()["matched"] == pl.Boolean
    assert list(tables["empty_result"].iter_rows()) == []
    assert list(tables["special_result"].iter_rows()) == [
        {"^value$": "init1", "value": "decoy", "*": "init", "matched": True}
    ]
    assert list(tables["literal_filter"].iter_rows()) == [{"value": "init1"}, {"value": "init-1"}]
    assert list(tables["column_filter"].iter_rows()) == [
        {"value": "init1"},
        {"value": "init-1"},
        {"value": "new1"},
        {"value": "a.b"},
        {"value": ""},
    ]
    assert list(tables["null_filter"].iter_rows()) == []


@pytest.mark.parametrize(
    ("values", "operand"),
    [
        pytest.param({"value": [1]}, {"value": 1}, id="numeric-input"),
        pytest.param({"value": [1]}, {"value": None}, id="numeric-input-null-operand"),
        pytest.param({"value": ["abc"]}, {"value": 1}, id="numeric-literal"),
        pytest.param({"value": ["abc"], "prefix": [1]}, {"other_column": "prefix"}, id="numeric-column"),
    ],
)
def test_starts_with_rejects_non_string_operands(
    tmp_path: Path, values: dict[str, list[object]], operand: dict[str, object]
) -> None:
    """A prefix comparison requires string columns and string or null literals."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame(values).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "filtered",
                    "source": "input",
                    "operations": [
                        {"operation": "filter", "column": "value", "comparison": "starts_with", **operand}
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"(?:string|types must match|incompatible)"):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_choose_selects_columns_and_typed_literals_without_changing_rows(tmp_path: Path) -> None:
    """Select explicit branch values while retaining null, empty, and row semantics."""
    backend = PolarsTabularBackend()
    schema = {
        "id": pl.Int64,
        "family": pl.String,
        "heat_rate": pl.Float64,
        "fallback_rate": pl.Float64,
        "capacity": pl.Float64,
        "threshold": pl.Float64,
        "integer_value": pl.Int64,
        "floating_value": pl.Float64,
    }
    source = TabularSource(
        pl.DataFrame(
            {
                "id": [0, 1, 2, 3],
                "family": ["thermal", "wind", None, "thermal"],
                "heat_rate": [None, None, 8.0, None],
                "fallback_rate": [12.0, 13.0, 14.0, 15.0],
                "capacity": [1e-9, 2.0, 0.0, None],
                "threshold": [1e-8, 1e-8, 1e-8, 1e-8],
                "integer_value": [1, 2, 3, 4],
                "floating_value": [1.5, 2.5, 3.5, 4.5],
            },
            schema=schema,
        ).lazy(),
        backend,
    )
    empty = TabularSource(pl.DataFrame(schema=schema).lazy(), backend)
    operations = [
        {
            "operation": "choose",
            "column": "family",
            "comparison": "equals",
            "value": "thermal",
            "then": "fallback_rate",
            "otherwise": "heat_rate",
            "output": "prepared_rate",
        },
        {
            "operation": "choose",
            "column": "capacity",
            "comparison": "less_than_or_equal",
            "other_column": "threshold",
            "then": {"value": 0.0},
            "otherwise": "capacity",
            "output": "prepared_capacity",
        },
        {
            "operation": "choose",
            "column": "heat_rate",
            "comparison": "is_null",
            "then": {"value": None},
            "otherwise": "heat_rate",
            "output": "null_rate",
        },
        {
            "operation": "choose",
            "column": "id",
            "comparison": "equals",
            "value": 0,
            "then": "integer_value",
            "otherwise": "floating_value",
            "output": "mixed_numeric",
        },
    ]
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "prepared",
                    "source": "input",
                    "operations": operations,
                    "columns": {
                        "id": "id",
                        "capacity": "prepared_capacity",
                        "rate": "prepared_rate",
                        "null_rate": "null_rate",
                        "mixed": "mixed_numeric",
                    },
                },
                {
                    "name": "prepared_empty",
                    "source": "empty",
                    "operations": operations,
                    "columns": {
                        "id": "id",
                        "capacity": "prepared_capacity",
                        "rate": "prepared_rate",
                        "null_rate": "null_rate",
                        "mixed": "mixed_numeric",
                    },
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty": empty}, mapping_path=mapping_path, backend=backend
    )

    assert list(tables["prepared"].iter_rows()) == [
        {"capacity": 0.0, "id": 0, "mixed": 1.0, "null_rate": None, "rate": 12.0},
        {"capacity": 2.0, "id": 1, "mixed": 2.5, "null_rate": None, "rate": None},
        {"capacity": 0.0, "id": 2, "mixed": 3.5, "null_rate": 8.0, "rate": 8.0},
        {"capacity": None, "id": 3, "mixed": 4.5, "null_rate": None, "rate": 15.0},
    ]
    expected_schema = pl.Schema(
        {
            "capacity": pl.Float64,
            "id": pl.Int64,
            "mixed": pl.Float64,
            "null_rate": pl.Float64,
            "rate": pl.Float64,
        }
    )
    assert tables["prepared"].data.collect_schema() == expected_schema
    assert list(tables["prepared_empty"].iter_rows()) == []
    assert tables["prepared_empty"].data.collect_schema() == expected_schema


@pytest.mark.parametrize(
    "choose_fields",
    [
        {
            "column": "value",
            "comparison": "equals",
            "then": "value",
            "otherwise": "value",
            "output": "selected",
        },
        {
            "column": "value",
            "comparison": "equals",
            "value": 1,
            "other_column": "value",
            "then": "value",
            "otherwise": "value",
            "output": "selected",
        },
        {
            "column": "value",
            "comparison": "is_null",
            "value": None,
            "then": "value",
            "otherwise": "value",
            "output": "selected",
        },
        {
            "column": "value",
            "comparison": "equals",
            "value": 1,
            "then": {},
            "otherwise": "value",
            "output": "selected",
        },
        {
            "column": "value",
            "comparison": "equals",
            "value": 1,
            "then": {"value": None, "column": "value"},
            "otherwise": "value",
            "output": "selected",
        },
        {
            "column": "value",
            "comparison": "equals",
            "value": 1,
            "then": {"value": None, "ignored": True},
            "otherwise": "value",
            "output": "selected",
        },
    ],
    ids=[
        "missing-predicate-value",
        "both-predicate-values",
        "unary-value",
        "missing-branch",
        "ambiguous-branch",
        "unknown-branch-field",
    ],
)
def test_choose_rejects_malformed_or_ambiguous_fields(
    tmp_path: Path, choose_fields: dict[str, object]
) -> None:
    """Require one flat predicate and one bare-column or scalar-literal branch form."""
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            json.dumps(
                [
                    {
                        "name": "out",
                        "source": "input",
                        "operations": [{"operation": "choose", **choose_fields}],
                    }
                ]
            ),
        )


@pytest.mark.parametrize(
    ("then", "otherwise", "output", "match"),
    [
        ("value", {"value": "text"}, "selected", "branch types are incompatible"),
        ({"value": None}, {"value": None}, "selected", "cannot be inferred"),
        ("missing", "value", "selected", "missing column"),
        ("value", "value", "value", "already exists"),
    ],
    ids=["incompatible-types", "two-null-literals", "missing-branch-column", "output-collision"],
)
def test_choose_rejects_incompatible_or_unknown_outputs(
    tmp_path: Path, then: object, otherwise: object, output: str, match: str
) -> None:
    """Reject branch values that cannot be represented in one typed output."""
    with pytest.raises(ValueError, match=match):
        assemble_mapping(
            tmp_path,
            json.dumps(
                [
                    {
                        "name": "out",
                        "source": "input",
                        "operations": [
                            {
                                "operation": "choose",
                                "column": "value",
                                "comparison": "equals",
                                "value": 1,
                                "then": then,
                                "otherwise": otherwise,
                                "output": output,
                            }
                        ],
                    }
                ]
            ),
        )


@pytest.mark.parametrize(
    "operation",
    [
        {"column": "value", "comparison": "equals"},
        {"column": "value", "comparison": "equals", "value": 1, "other_column": "value"},
        {"column": "value", "comparison": "is_null", "value": None},
        {"column": "value", "comparison": "is_not_null", "other_column": "value"},
        {"column": "value", "comparison": "equals", "other_column": None},
    ],
)
def test_filter_requires_exactly_the_documented_operands(
    tmp_path: Path, operation: dict[str, object]
) -> None:
    """Reject missing, conflicting, and explicitly null comparison columns."""
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            json.dumps(
                [{"name": "out", "source": "input", "operations": [{"operation": "filter", **operation}]}]
            ),
        )


def test_weighted_rate_candidates_keep_unknown_and_nonpositive_groups_null(tmp_path: Path) -> None:
    """Compose multiplication, aggregation, division, and explicit null priorities."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "group": ["A", "A", "B", "B", "C", "C", "D", "E"],
                "capacity": [100.0, 300.0, 100.0, 100.0, -5.0, 0.0, 0.0, 100.0],
                "rate": [20.0, 40.0, None, 20.0, 50.0, 10.0, 10.0, 0.0],
            },
            schema={"group": pl.String, "capacity": pl.Float64, "rate": pl.Float64},
        ).lazy(),
        backend,
    )
    records = [
        {
            "name": "weighted_rows",
            "source": "input",
            "operations": [{"operation": "multiply", "columns": ["capacity", "rate"], "output": "cost"}],
        },
        {
            "name": "weighted_totals",
            "source": "weighted_rows",
            "operations": [
                {
                    "operation": "group_by",
                    "columns": ["group"],
                    "aggregate": [
                        {"operation": "sum", "column": "cost", "output": "weighted_sum"},
                        {"operation": "sum", "column": "capacity", "output": "total_capacity"},
                    ],
                }
            ],
        },
        {
            "name": "positive_totals",
            "source": "weighted_totals",
            "operations": [
                {"operation": "filter", "column": "total_capacity", "comparison": "greater_than", "value": 0}
            ],
        },
        {
            "name": "weighted_candidates",
            "source": "positive_totals",
            "operations": [
                {"operation": "divide", "columns": ["weighted_sum", "total_capacity"], "output": "rate"}
            ],
            "columns": {"group": "group", "priority": {"value": "weighted"}, "rate": "rate"},
        },
        {
            "name": "unknown_rate_groups",
            "source": "input",
            "operations": [
                {"operation": "filter", "column": "capacity", "comparison": "greater_than", "value": 0},
                {"operation": "filter", "column": "rate", "comparison": "is_null"},
                {
                    "operation": "group_by",
                    "columns": ["group"],
                    "aggregate": [{"operation": "first", "column": "rate", "output": "rate"}],
                },
            ],
            "columns": {"group": "group", "priority": {"value": "missing"}, "rate": "rate"},
        },
        {
            "name": "nonpositive_totals",
            "source": "weighted_totals",
            "operations": [
                {
                    "operation": "filter",
                    "column": "total_capacity",
                    "comparison": "less_than_or_equal",
                    "value": 0,
                }
            ],
        },
        {
            "name": "null_rate",
            "operations": [
                {
                    "operation": "rows",
                    "schema": [{"name": "rate", "dtype": "float64"}],
                    "values": [{"rate": None}],
                }
            ],
        },
        {
            "name": "nonpositive_candidates",
            "source": "nonpositive_totals",
            "operations": [{"operation": "join", "source": "null_rate", "how": "cross", "columns": ["rate"]}],
            "columns": {"group": "group", "priority": {"value": "nonpositive"}, "rate": "rate"},
        },
        {
            "name": "all_candidates",
            "operations": [
                {
                    "operation": "concat",
                    "sources": ["unknown_rate_groups", "nonpositive_candidates", "weighted_candidates"],
                }
            ],
        },
        {
            "name": "weighted_rates",
            "source": "all_candidates",
            "operations": [
                {"operation": "sort", "columns": ["priority"]},
                {"operation": "unique", "columns": ["group"], "keep": "first"},
                {"operation": "sort", "columns": ["group"]},
            ],
            "columns": {"group": "group", "rate": "rate"},
        },
    ]
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(json.dumps(records), encoding="utf-8")

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["weighted_rates"].iter_rows()) == [
        {"group": "A", "rate": 35.0},
        {"group": "B", "rate": None},
        {"group": "C", "rate": None},
        {"group": "D", "rate": None},
        {"group": "E", "rate": 0.0},
    ]
    assert tables["weighted_rates"].data.collect_schema() == pl.Schema(
        {"group": pl.String, "rate": pl.Float64}
    )


def test_conditional_candidates_and_priority_selection_keep_complete_rows(tmp_path: Path) -> None:
    """Select configured candidate rows and the last eligible earlier nonzero record."""
    backend = PolarsTabularBackend()
    conditional = TabularSource(
        pl.DataFrame(
            {
                "technology": ["eligible-a", "base-only"],
                "eligible": [True, False],
                "base_rate": [20.0, 20.0],
                "target_rate": [40.0, 40.0],
            }
        ).lazy(),
        backend,
    )
    bins = TabularSource(
        pl.DataFrame(
            {"interface": ["north-south", "north-south"], "bin": [1, 2], "cost": [40.0, 30.0]}
        ).lazy(),
        backend,
    )
    history = TabularSource(
        pl.DataFrame(
            {
                "technology": ["coal", "coal", "coal", "coal"],
                "year": [2020, 2025, 2030, 2035],
                "rate": [66.0, 0.0, 88.0, 55.0],
            }
        ).lazy(),
        backend,
    )
    records = [
        {
            "name": "target_candidates",
            "source": "conditional",
            "operations": [
                {"operation": "filter", "column": "eligible", "comparison": "equals", "value": True}
            ],
            "columns": {
                "technology": "technology",
                "priority": {"value": "1-target"},
                "rate": "target_rate",
            },
        },
        {
            "name": "base_candidates",
            "source": "conditional",
            "operations": [],
            "columns": {
                "technology": "technology",
                "priority": {"value": "2-base"},
                "rate": "base_rate",
            },
        },
        {
            "name": "all_candidates",
            "operations": [{"operation": "concat", "sources": ["target_candidates", "base_candidates"]}],
        },
        {
            "name": "conditional_rates",
            "source": "all_candidates",
            "operations": [
                {"operation": "sort", "columns": ["priority"]},
                {"operation": "unique", "columns": ["technology"], "keep": "first"},
            ],
            "columns": {"rate": "rate", "technology": "technology"},
        },
        {
            "name": "preferred_bin",
            "source": "bins",
            "operations": [
                {"operation": "sort", "columns": ["bin"]},
                {"operation": "unique", "columns": ["interface"], "keep": "first"},
            ],
        },
        {
            "name": "earlier_rate",
            "source": "history",
            "operations": [
                {"operation": "filter", "column": "year", "comparison": "less_than", "value": "{solve_year}"},
                {"operation": "filter", "column": "rate", "comparison": "not_equal", "value": 0},
                {"operation": "sort", "columns": ["year"]},
                {"operation": "unique", "columns": ["technology"], "keep": "last"},
            ],
        },
    ]
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(json.dumps(records), encoding="utf-8")

    tables = r2x_core.assemble_tables(
        {"conditional": conditional, "bins": bins, "history": history},
        mapping_path=mapping_path,
        backend=backend,
        placeholders={"solve_year": 2030},
    )

    assert list(tables["conditional_rates"].iter_rows()) == [
        {"rate": 40.0, "technology": "eligible-a"},
        {"rate": 20.0, "technology": "base-only"},
    ]
    assert list(tables["preferred_bin"].iter_rows()) == [{"interface": "north-south", "bin": 1, "cost": 40.0}]
    assert list(tables["earlier_rate"].iter_rows()) == [{"technology": "coal", "year": 2020, "rate": 66.0}]


def test_group_by_mean_count_first_last_follow_contract(tmp_path: Path) -> None:
    """Use null-aware aggregates and retain first or last values in current row order."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "group": ["a", "a", "b", "b", "c"],
                "measure": [None, 2.0, None, None, 4.0],
                "label": [None, "later", "first", None, "only"],
            },
            schema={"group": pl.String, "measure": pl.Float64, "label": pl.String},
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "summaries",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "group_by",
                            "columns": ["group"],
                            "aggregate": [
                                {"operation": "mean", "column": "measure", "output": "mean"},
                                {"operation": "count", "column": "measure", "output": "count"},
                                {"operation": "first", "column": "measure", "output": "first_measure"},
                                {"operation": "last", "column": "measure", "output": "last_measure"},
                                {"operation": "first", "column": "label", "output": "first_label"},
                                {"operation": "last", "column": "label", "output": "last_label"},
                            ],
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["summaries"].iter_rows()) == [
        {
            "count": 1,
            "first_label": None,
            "first_measure": None,
            "group": "a",
            "last_label": "later",
            "last_measure": 2.0,
            "mean": 2.0,
        },
        {
            "count": 0,
            "first_label": "first",
            "first_measure": None,
            "group": "b",
            "last_label": None,
            "last_measure": None,
            "mean": None,
        },
        {
            "count": 1,
            "first_label": "only",
            "first_measure": 4.0,
            "group": "c",
            "last_label": "only",
            "last_measure": 4.0,
            "mean": 4.0,
        },
    ]
    assert tables["summaries"].data.collect_schema() == pl.Schema(
        {
            "group": pl.String,
            "mean": pl.Float64,
            "count": pl.Int64,
            "first_measure": pl.Float64,
            "last_measure": pl.Float64,
            "first_label": pl.String,
            "last_label": pl.String,
        }
    )


def test_group_by_without_keys_returns_one_global_summary_for_empty_and_present_rows(
    tmp_path: Path,
) -> None:
    """Aggregate all rows into one summary, including a typed empty summary."""
    backend = PolarsTabularBackend()
    present = TabularSource(
        pl.DataFrame({"cost": [4.0, None, 8.0]}, schema={"cost": pl.Float64}).lazy(),
        backend,
    )
    empty = TabularSource(pl.DataFrame(schema={"cost": pl.Float64}).lazy(), backend)
    absent = TabularSource(
        pl.DataFrame(schema={"cost": pl.Float64}).lazy(),
        backend,
        availability=SourceAvailability.ABSENT,
        absent_inputs=frozenset({"optional_costs"}),
    )
    mapping_path = tmp_path / "table_mapping.json"
    operation = {
        "operation": "group_by",
        "columns": [],
        "aggregate": [
            {"operation": "mean", "column": "cost", "output": "mean_cost"},
            {"operation": "count", "column": "cost", "output": "value_count"},
        ],
    }
    mapping_path.write_text(
        json.dumps(
            [
                {"name": "present_summary", "source": "present", "operations": [operation]},
                {"name": "empty_summary", "source": "empty", "operations": [operation]},
                {"name": "absent_summary", "source": "absent", "operations": [operation]},
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"present": present, "empty": empty, "absent": absent},
        mapping_path=mapping_path,
        backend=backend,
    )

    assert list(tables["present_summary"].iter_rows()) == [{"mean_cost": 6.0, "value_count": 2}]
    assert list(tables["empty_summary"].iter_rows()) == [{"mean_cost": None, "value_count": 0}]
    absent_summary = tables["absent_summary"]
    assert absent_summary.availability is SourceAvailability.ABSENT
    assert absent_summary.absent_inputs == frozenset({"optional_costs"})
    assert list(absent_summary.iter_rows()) == []
    expected_schema = pl.Schema({"mean_cost": pl.Float64, "value_count": pl.Int64})
    assert tables["present_summary"].data.collect_schema() == expected_schema
    assert tables["empty_summary"].data.collect_schema() == expected_schema
    assert absent_summary.data.collect_schema() == expected_schema


def test_fill_null_uses_ordered_original_column_values(tmp_path: Path) -> None:
    """Fill each target from its first non-null backup while preserving zero and null."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "id": ["first", "zero", "missing"],
                "primary": [None, 0, None],
                "secondary": [5, None, None],
                "backup_a": [80, 80, None],
                "backup_b": [90, 90, None],
            },
            schema={
                "id": pl.String,
                "primary": pl.Int64,
                "secondary": pl.Int64,
                "backup_a": pl.Int64,
                "backup_b": pl.Int64,
            },
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"filled","source":"input","operations":[{"operation":"fill_null",'
        '"columns":["primary","secondary"],"from_columns":["backup_a","backup_b"]}],'
        '"columns":{"id":"id","primary":"primary","secondary":"secondary"}}]',
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["filled"].iter_rows()) == [
        {"id": "first", "primary": 80, "secondary": 5},
        {"id": "zero", "primary": 0, "secondary": 80},
        {"id": "missing", "primary": None, "secondary": None},
    ]
    assert tables["filled"].data.collect_schema() == pl.Schema(
        {"id": pl.String, "primary": pl.Int64, "secondary": pl.Int64}
    )


def test_fill_null_with_null_literal_preserves_values_and_dtype(tmp_path: Path) -> None:
    """An explicit null fill is a typed no-op, not an invalid Polars fill call."""
    backend = PolarsTabularBackend()
    schema = {"v": pl.Int64}
    source = TabularSource(pl.DataFrame({"v": [None, 2]}, schema=schema).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "unchanged",
                    "source": "input",
                    "operations": [{"operation": "fill_null", "columns": ["v"], "value": None}],
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["unchanged"].iter_rows()) == [{"v": None}, {"v": 2}]
    assert tables["unchanged"].data.collect_schema() == pl.Schema(schema)


def test_fill_null_preserves_an_external_int32_column(tmp_path: Path) -> None:
    """Fill an externally supplied Int32 column without changing its native dtype."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"value": pl.Series("value", [None, 2], dtype=pl.Int32)}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"filled","source":"input","operations":[{"operation":"fill_null",'
        '"columns":["value"],"value":7}]}]',
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["filled"].iter_rows()) == [{"value": 7}, {"value": 2}]
    assert tables["filled"].data.collect_schema() == pl.Schema({"value": pl.Int32})


def test_fill_null_rejects_integer_overflow_for_an_external_int32_column(tmp_path: Path) -> None:
    """Reject an out-of-range replacement instead of widening the input column."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"value": pl.Series("value", [None, 2], dtype=pl.Int32)}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"filled","source":"input","operations":[{"operation":"fill_null",'
        '"columns":["value"],"value":2147483648}]}]',
        encoding="utf-8",
    )

    filled = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)["filled"]

    with pytest.raises(pl.exceptions.PolarsError):
        list(filled.iter_rows())


def test_fill_null_rejects_float_for_an_external_int32_column(tmp_path: Path) -> None:
    """Reject an incompatible scalar rather than widening an external integer field."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"value": pl.Series("value", [None, 2], dtype=pl.Int32)}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"filled","source":"input","operations":[{"operation":"fill_null",'
        '"columns":["value"],"value":1.5}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"Fill value type float is incompatible with column 'value'"):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_fill_null_accepts_typed_list_literals_and_empty_inputs(tmp_path: Path) -> None:
    """Fill missing list values without flattening or changing nested element order."""
    backend = PolarsTabularBackend()
    schema = {"memberships": pl.List(pl.String)}
    source = TabularSource(
        pl.DataFrame(
            {"memberships": [None, ["wind"], ["solar", None]]},
            schema=schema,
        ).lazy(),
        backend,
    )
    empty = TabularSource(pl.DataFrame(schema=schema).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "empty_filled",
                    "source": "input",
                    "operations": [{"operation": "fill_null", "columns": ["memberships"], "value": []}],
                },
                {
                    "name": "default_filled",
                    "source": "input",
                    "operations": [
                        {"operation": "fill_null", "columns": ["memberships"], "value": ["unknown"]}
                    ],
                },
                {
                    "name": "typed_empty",
                    "source": "empty",
                    "operations": [{"operation": "fill_null", "columns": ["memberships"], "value": []}],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty": empty}, mapping_path=mapping_path, backend=backend
    )

    assert list(tables["empty_filled"].iter_rows()) == [
        {"memberships": []},
        {"memberships": ["wind"]},
        {"memberships": ["solar", None]},
    ]
    assert list(tables["default_filled"].iter_rows()) == [
        {"memberships": ["unknown"]},
        {"memberships": ["wind"]},
        {"memberships": ["solar", None]},
    ]
    assert list(tables["typed_empty"].iter_rows()) == []
    for table in tables.values():
        assert table.data.collect_schema() == pl.Schema({"memberships": pl.List(pl.String)})


@pytest.mark.parametrize(
    "operation",
    [
        {"columns": ["value"]},
        {"columns": ["value"], "value": 0, "from_columns": ["value"]},
        {"columns": ["value"], "from_columns": []},
        {"columns": ["value"], "from_columns": ["value", "value"]},
    ],
)
def test_fill_null_requires_one_valid_fill_source(tmp_path: Path, operation: dict[str, object]) -> None:
    """Require one scalar or a nonempty ordered list of unique backup columns."""
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            json.dumps(
                [{"name": "out", "source": "input", "operations": [{"operation": "fill_null", **operation}]}]
            ),
        )


def test_unique_keeps_complete_rows_in_selected_source_order(tmp_path: Path) -> None:
    """Select stable first or last priority rows, grouping duplicate null keys."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "key": ["a", "b", "a", None, None, "a"],
                "priority": [2, 1, 1, 2, 1, 1],
                "row_id": ["a2", "b1", "a1", "null2", "null1", "a1-tie"],
                "cost": [40.0, 30.0, 20.0, 9.0, 8.0, 25.0],
            },
            schema={"key": pl.String, "priority": pl.Int64, "row_id": pl.String, "cost": pl.Float64},
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "first_priority",
                    "source": "input",
                    "operations": [
                        {"operation": "sort", "columns": ["priority"]},
                        {"operation": "unique", "columns": ["key"], "keep": "first"},
                    ],
                },
                {
                    "name": "last_priority",
                    "source": "input",
                    "operations": [
                        {"operation": "sort", "columns": ["priority"]},
                        {"operation": "unique", "columns": ["key"], "keep": "last"},
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["first_priority"].iter_rows()) == [
        {"cost": 30.0, "key": "b", "priority": 1, "row_id": "b1"},
        {"cost": 20.0, "key": "a", "priority": 1, "row_id": "a1"},
        {"cost": 8.0, "key": None, "priority": 1, "row_id": "null1"},
    ]
    assert list(tables["last_priority"].iter_rows()) == [
        {"cost": 30.0, "key": "b", "priority": 1, "row_id": "b1"},
        {"cost": 40.0, "key": "a", "priority": 2, "row_id": "a2"},
        {"cost": 9.0, "key": None, "priority": 2, "row_id": "null2"},
    ]
    assert tables["last_priority"].fields() == ["key", "priority", "row_id", "cost"]


def test_cast_converts_supported_scalar_types_and_fails_strictly(tmp_path: Path) -> None:
    """Cast exact named columns in place, retaining nulls and rejecting invalid values."""
    from datetime import datetime

    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "enabled": [0, 1],
                "count": ["3", "4"],
                "ratio": ["1.25", "2.5"],
                "label": [1, 2],
                "when": ["2032-01-01T00:00:00", None],
            }
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "typed",
                    "source": "input",
                    "operations": [
                        {"operation": "cast", "column": "enabled", "dtype": "bool"},
                        {"operation": "cast", "column": "count", "dtype": "int64"},
                        {"operation": "cast", "column": "ratio", "dtype": "float64"},
                        {"operation": "cast", "column": "label", "dtype": "string"},
                        {"operation": "cast", "column": "when", "dtype": "datetime"},
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["typed"].iter_rows()) == [
        {
            "enabled": False,
            "count": 3,
            "ratio": 1.25,
            "label": "1",
            "when": datetime(2032, 1, 1),
        },
        {
            "enabled": True,
            "count": 4,
            "ratio": 2.5,
            "label": "2",
            "when": None,
        },
    ]
    assert tables["typed"].data.collect_schema() == pl.Schema(
        {
            "enabled": pl.Boolean,
            "count": pl.Int64,
            "ratio": pl.Float64,
            "label": pl.String,
            "when": pl.Datetime("us"),
        }
    )

    invalid_source = TabularSource(pl.DataFrame({"count": ["3.2"]}).lazy(), backend)
    invalid_path = tmp_path / "invalid-table-mapping.json"
    invalid_path.write_text(
        '[{"name":"invalid","source":"input","operations":['
        '{"operation":"cast","column":"count","dtype":"int64"}]}]',
        encoding="utf-8",
    )
    invalid_table = r2x_core.assemble_tables(
        {"input": invalid_source}, mapping_path=invalid_path, backend=backend
    )["invalid"]
    with pytest.raises(pl.exceptions.PolarsError):
        list(invalid_table.iter_rows())


def test_cast_rejects_float_to_integer_without_implicit_truncation(tmp_path: Path) -> None:
    """Reject floating-point values for integer casts instead of truncating them."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"value": pl.Series("value", [1.5, -2.9, None], dtype=pl.Float64)}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"integer_values","source":"input","operations":['
        '{"operation":"cast","column":"value","dtype":"int64"}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"floating-point.*integer"):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_group_by_keeps_first_seen_order_and_combines_null_keys(tmp_path: Path) -> None:
    """Preserve first-seen groups while combining null keys into one group."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            [pl.Series("key", [None, "a", None, "a"], dtype=pl.String), pl.Series("value", [1, 2, 3, 4])]
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"grouped","source":"input","operations":[{"operation":"group_by",'
        '"columns":["key"],"aggregate":[{"operation":"sum","column":"value","output":"total"}]}]}]',
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert list(tables["grouped"].iter_rows()) == [{"key": None, "total": 4}, {"key": "a", "total": 6}]


def test_list_operation_preserves_nested_list_values(tmp_path: Path) -> None:
    """Collect whole list-valued cells, preserving nesting and null positions."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            [
                pl.Series("left", [[1, 2], None], dtype=pl.List(pl.Int64)),
                pl.Series("right", [[3], [4, 5]], dtype=pl.List(pl.Int64)),
            ]
        ).lazy(),
        backend,
    )
    empty_source = TabularSource(
        pl.DataFrame(schema={"left": pl.List(pl.Int64), "right": pl.List(pl.Int64)}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"pairs","source":"input","operations":['
        '{"operation":"list","columns":["left","right"],"output":"pair"}]},'
        '{"name":"empty_pairs","source":"empty_input","operations":['
        '{"operation":"list","columns":["left","right"],"output":"pair"}]}]',
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty_input": empty_source}, mapping_path=mapping_path, backend=backend
    )
    table = tables["pairs"]

    assert list(table.iter_rows()) == [
        {"left": [1, 2], "right": [3], "pair": [[1, 2], [3]]},
        {"left": None, "right": [4, 5], "pair": [None, [4, 5]]},
    ]
    nested_schema = pl.Schema(
        {
            "left": pl.List(pl.Int64),
            "right": pl.List(pl.Int64),
            "pair": pl.List(pl.List(pl.Int64)),
        }
    )
    assert table.data.collect_schema() == nested_schema
    empty_table = tables["empty_pairs"]
    assert list(empty_table.iter_rows()) == []
    assert empty_table.data.collect_schema() == nested_schema


def test_split_selects_literal_separator_parts_and_preserves_empty_schema(tmp_path: Path) -> None:
    """Select one string part without changing row order or typed empty inputs."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {"technology": ["Gas-CC_case", "plain", "wind__2", "wind.2", None]},
            schema={"technology": pl.String},
        ).lazy(),
        backend,
    )
    empty_source = TabularSource(
        pl.DataFrame(schema={"technology": pl.String}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"base_names","source":"input","operations":[{"operation":"split",'
        '"column":"technology","separator":"_","index":0,"output":"part"}]},'
        '{"name":"suffixes","source":"input","operations":[{"operation":"split",'
        '"column":"technology","separator":"_","index":1,"output":"part"}]},'
        '{"name":"dot_suffixes","source":"input","operations":[{"operation":"split",'
        '"column":"technology","separator":".","index":1,"output":"part"}]},'
        '{"name":"empty_parts","source":"empty_input","operations":[{"operation":"split",'
        '"column":"technology","separator":"_","index":1,"output":"part"}]}]',
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty_input": empty_source}, mapping_path=mapping_path, backend=backend
    )

    assert [row["part"] for row in tables["base_names"].iter_rows()] == [
        "Gas-CC",
        "plain",
        "wind",
        "wind.2",
        None,
    ]
    assert [row["part"] for row in tables["suffixes"].iter_rows()] == ["case", None, "", None, None]
    assert [row["part"] for row in tables["dot_suffixes"].iter_rows()] == [None, None, None, "2", None]
    assert list(tables["empty_parts"].iter_rows()) == []
    assert tables["empty_parts"].data.collect_schema() == pl.Schema(
        {"technology": pl.String, "part": pl.String}
    )


@pytest.mark.parametrize(
    "operation",
    [
        {"operation": "split", "column": "technology", "separator": "", "index": 0, "output": "part"},
        {"operation": "split", "column": "technology", "separator": "_", "index": -1, "output": "part"},
        {
            "operation": "split",
            "column": "technology",
            "separator": "_",
            "index": 0,
            "output": "part",
            "regex": True,
        },
    ],
    ids=["empty-separator", "negative-index", "unknown-field"],
)
def test_split_rejects_malformed_operation_fields(tmp_path: Path, operation: dict[str, object]) -> None:
    """Keep split separators, indexes, and operation fields strict at JSON load."""
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps([{"name": "out", "source": "input", "operations": [operation]}]),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        r2x_core.assemble_tables(source_tables(), mapping_path=mapping_path, backend=PolarsTabularBackend())


def test_split_rejects_non_string_columns_and_existing_outputs(tmp_path: Path) -> None:
    """Reject wrong input types and output collisions instead of coercing or replacing."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"value": [1], "part": ["old"]}).lazy(), backend)
    for column, output in [("value", "new_part"), ("part", "part")]:
        mapping_path = tmp_path / f"mapping-{column}-{output}.json"
        mapping_path.write_text(
            json.dumps(
                [
                    {
                        "name": "out",
                        "source": "input",
                        "operations": [
                            {
                                "operation": "split",
                                "column": column,
                                "separator": "_",
                                "index": 0,
                                "output": output,
                            }
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_extended_operations_retain_empty_input_schemas(tmp_path: Path) -> None:
    """Keep declared dtypes through empty arithmetic, aggregation, fill, selection, and casts."""
    backend = PolarsTabularBackend()
    empty = TabularSource(
        pl.DataFrame(
            schema={
                "group": pl.String,
                "left": pl.Int64,
                "right": pl.Float64,
                "label": pl.String,
                "backup": pl.Int64,
            }
        ).lazy(),
        backend,
    )
    records = [
        {
            "name": "added",
            "source": "empty",
            "operations": [{"operation": "add", "columns": ["left", "right"], "output": "sum"}],
        },
        {
            "name": "divided",
            "source": "empty",
            "operations": [{"operation": "divide", "columns": ["left", "right"], "output": "ratio"}],
        },
        {
            "name": "grouped",
            "source": "empty",
            "operations": [
                {
                    "operation": "group_by",
                    "columns": ["group"],
                    "aggregate": [
                        {"operation": "mean", "column": "right", "output": "mean"},
                        {"operation": "count", "column": "label", "output": "count"},
                        {"operation": "first", "column": "label", "output": "first"},
                        {"operation": "last", "column": "label", "output": "last"},
                    ],
                }
            ],
        },
        {
            "name": "filled",
            "source": "empty",
            "operations": [{"operation": "fill_null", "columns": ["left"], "from_columns": ["backup"]}],
        },
        {
            "name": "selected",
            "source": "empty",
            "operations": [{"operation": "unique", "columns": ["group"], "keep": "last"}],
        },
        {
            "name": "casted",
            "source": "empty",
            "operations": [{"operation": "cast", "column": "left", "dtype": "float64"}],
        },
        {
            "name": "object_column",
            "source": "empty",
            "operations": [
                {
                    "operation": "object",
                    "columns": {"group": "group", "label": {"value": "site"}},
                    "output": "payload",
                }
            ],
        },
        {
            "name": "list_column",
            "source": "empty",
            "operations": [{"operation": "list", "columns": ["left", "right"], "output": "items"}],
        },
    ]
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(json.dumps(records), encoding="utf-8")

    tables = r2x_core.assemble_tables({"empty": empty}, mapping_path=mapping_path, backend=backend)

    assert all(list(table.iter_rows()) == [] for table in tables.values())
    assert tables["added"].data.collect_schema() == pl.Schema(
        {
            "group": pl.String,
            "left": pl.Int64,
            "right": pl.Float64,
            "label": pl.String,
            "backup": pl.Int64,
            "sum": pl.Float64,
        }
    )
    assert tables["divided"].data.collect_schema() == pl.Schema(
        {
            "group": pl.String,
            "left": pl.Int64,
            "right": pl.Float64,
            "label": pl.String,
            "backup": pl.Int64,
            "ratio": pl.Float64,
        }
    )
    assert tables["grouped"].data.collect_schema() == pl.Schema(
        {"group": pl.String, "mean": pl.Float64, "count": pl.Int64, "first": pl.String, "last": pl.String}
    )
    assert tables["filled"].data.collect_schema() == pl.Schema(
        {"group": pl.String, "left": pl.Int64, "right": pl.Float64, "label": pl.String, "backup": pl.Int64}
    )
    assert tables["selected"].data.collect_schema() == pl.Schema(
        {"group": pl.String, "left": pl.Int64, "right": pl.Float64, "label": pl.String, "backup": pl.Int64}
    )
    assert tables["casted"].data.collect_schema() == pl.Schema(
        {"group": pl.String, "left": pl.Float64, "right": pl.Float64, "label": pl.String, "backup": pl.Int64}
    )
    assert tables["object_column"].data.collect_schema() == pl.Schema(
        {
            "group": pl.String,
            "left": pl.Int64,
            "right": pl.Float64,
            "label": pl.String,
            "backup": pl.Int64,
            "payload": pl.Struct({"group": pl.String, "label": pl.String}),
        }
    )
    assert tables["list_column"].data.collect_schema() == pl.Schema(
        {
            "group": pl.String,
            "left": pl.Int64,
            "right": pl.Float64,
            "label": pl.String,
            "backup": pl.Int64,
            "items": pl.List(pl.Float64),
        }
    )


def test_sort_direction_preserves_stable_ties_and_nulls_last(tmp_path: Path) -> None:
    """Sort either direction without changing tie order or null placement."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "key": [2, 1, 1, None, 2],
                "ordinal": ["two-first", "one-first", "one-second", "null", "two-second"],
            },
            schema={"key": pl.Int64, "ordinal": pl.String},
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "ascending",
                    "source": "input",
                    "operations": [{"operation": "sort", "columns": ["key"]}],
                },
                {
                    "name": "descending",
                    "source": "input",
                    "operations": [{"operation": "sort", "columns": ["key"], "descending": True}],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert [row["ordinal"] for row in tables["ascending"].iter_rows()] == [
        "one-first",
        "one-second",
        "two-first",
        "two-second",
        "null",
    ]
    assert [row["ordinal"] for row in tables["descending"].iter_rows()] == [
        "two-first",
        "two-second",
        "one-first",
        "one-second",
        "null",
    ]


def test_empty_operations_retain_declared_schemas_and_null_filters_drop_rows(tmp_path: Path) -> None:
    """Keep empty constructors and row operations typed without inventing values."""
    backend = PolarsTabularBackend()
    empty = TabularSource(
        pl.DataFrame(schema={"group": pl.String, "low": pl.Int64, "high": pl.Float64}).lazy(),
        backend,
    )
    source = TabularSource(pl.DataFrame({"value": [None, 1]}, schema={"value": pl.Int64}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "empty_groups",
                    "source": "empty",
                    "operations": [
                        {
                            "operation": "group_by",
                            "columns": ["group"],
                            "aggregate": [{"operation": "sum", "column": "low", "output": "total"}],
                        }
                    ],
                },
                {
                    "name": "empty_unpivot",
                    "source": "empty",
                    "operations": [
                        {
                            "operation": "unpivot",
                            "index": ["group"],
                            "columns": {"low": "low", "high": "high"},
                            "variable_name": "kind",
                            "value_name": "value",
                        }
                    ],
                },
                {
                    "name": "empty_rows",
                    "operations": [
                        {
                            "operation": "rows",
                            "schema": [{"name": "when", "dtype": "datetime"}],
                            "values": [],
                        }
                    ],
                },
                {"name": "empty_concat", "operations": [{"operation": "concat", "sources": ["empty"]}]},
                {
                    "name": "null_filtered",
                    "source": "input",
                    "operations": [
                        {"operation": "filter", "column": "value", "comparison": "equals", "value": None}
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"empty": empty, "input": source}, mapping_path=mapping_path, backend=backend
    )

    assert list(tables["empty_groups"].iter_rows()) == []
    assert tables["empty_groups"].data.collect_schema() == pl.Schema({"group": pl.String, "total": pl.Int64})
    assert list(tables["empty_unpivot"].iter_rows()) == []
    assert tables["empty_unpivot"].data.collect_schema() == pl.Schema(
        {"group": pl.String, "kind": pl.String, "value": pl.Float64}
    )
    assert list(tables["empty_rows"].iter_rows()) == []
    assert tables["empty_rows"].data.collect_schema() == pl.Schema({"when": pl.Datetime("us")})
    assert list(tables["empty_concat"].iter_rows()) == []
    assert tables["empty_concat"].fields() == ["group", "low", "high"]
    assert list(tables["null_filtered"].iter_rows()) == []


@pytest.mark.parametrize(
    "contents",
    [
        '[{"name":"bad","source":"input","operations":[{"operation":"add",'
        '"columns":["value"],"output":"result"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"filter",'
        '"column":"value","comparison":"equals"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"filter",'
        '"column":"value","comparison":"equals","value":1,"other_column":"value"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"filter",'
        '"column":"value","comparison":"is_null","value":null}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"filter",'
        '"column":"value","comparison":"is_not_null","other_column":null}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"fill_null","columns":["value"]}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"fill_null",'
        '"columns":["value"],"value":0,"from_columns":["value"]}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"fill_null",'
        '"columns":["value"],"from_columns":null}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"unique","columns":["value"]}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"unique",'
        '"columns":["value"],"keep":"any"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"cast",'
        '"column":"value","dtype":"float"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"unpivot",'
        '"index":["value"],"columns":null,"variable_name":"kind","value_name":"payload"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"unpivot",'
        '"index":["value"],"columns":{},"variable_name":"kind","value_name":"payload"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"sort",'
        '"columns":["value"],"descending":"true"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"head","n":-1}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"head","n":true}]}]',
    ],
)
def test_mapping_loader_rejects_invalid_extended_operation_shapes(tmp_path: Path, contents: str) -> None:
    """Reject undocumented fields, missing operands, and invalid operation values."""
    with pytest.raises(ValidationError):
        assemble_mapping(tmp_path, contents)


def test_mapping_loader_rejects_invalid_constructors_optional_nulls_and_bindings(tmp_path: Path) -> None:
    """Reject invalid constructor placement, explicit null, and unresolved values."""
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            '[{"name":"bad","source":"input","operations":[{"operation":"rows",'
            '"schema":[{"name":"value","dtype":"int64"}],"values":[]}]}]',
        )
    with pytest.raises(ValidationError):
        assemble_mapping(tmp_path, '[{"name":"bad","source":null,"operations":[]}]')
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            '[{"name":"bad","operations":[{"operation":"rows","row_schema":['
            '{"name":"value","dtype":"int64"}],"values":[{"value":1}]}]}]',
        )
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            '[{"name":"bad","operations":[{"operation":"rows",'
            '"schema":[{"name":"value","dtype":"int64"}],"values":null}]}]',
        )
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            '[{"name":"bad","source":"input","operations":[{"operation":"filter",'
            '"column":"value","comparison":"equals","value":1,"extra":true}]}]',
        )
    with pytest.raises(ValueError, match="Invalid JSON numeric constant"):
        assemble_mapping(
            tmp_path,
            '[{"name":"bad","source":"input","operations":[{"operation":"fill_null",'
            '"columns":["value"],"value":NaN}]}]',
        )
    with pytest.raises(ValueError, match="before it is declared"):
        assemble_mapping(
            tmp_path,
            '[{"name":"first","operations":[{"operation":"concat","sources":["later"]}]},'
            '{"name":"later","operations":[{"operation":"rows",'
            '"schema":[{"name":"value","dtype":"int64"}],"values":[]}]}]',
        )

    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"bad","source":"input","operations":[{"operation":"filter",'
        '"column":"value","comparison":"equals","value":"{missing}"}]}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unresolved"):
        r2x_core.assemble_tables(source_tables(), mapping_path=mapping_path, backend=PolarsTabularBackend())


def test_operations_reject_missing_fields_and_incompatible_values(tmp_path: Path) -> None:
    """Reject invalid fields, comparison types, aggregation values, and reshape schemas."""
    backend = PolarsTabularBackend()
    inputs = {
        "input": TabularSource(
            pl.DataFrame({"value": [1], "text": ["one"], "other_number": [1.0]}).lazy(), backend
        ),
        "other_names": TabularSource(pl.DataFrame({"other": [1]}).lazy(), backend),
        "other_types": TabularSource(
            pl.DataFrame(
                {"value": [2.0], "text": [2], "other_number": [1.0]},
                schema={"value": pl.Float64, "text": pl.Int64, "other_number": pl.Float64},
            ).lazy(),
            backend,
        ),
    }
    cases = [
        (
            '[{"name":"out","source":"input","operations":[{"operation":"filter",'
            '"column":"missing","comparison":"equals","value":1}]}]',
            "missing column",
        ),
        (
            '[{"name":"out","source":"input","operations":[{"operation":"filter",'
            '"column":"text","comparison":"greater_than","value":1}]}]',
            "incompatible",
        ),
        (
            '[{"name":"out","source":"input","operations":[{"operation":"filter",'
            '"column":"value","comparison":"equals","other_column":"other_number"}]}]',
            "types must match",
        ),
        (
            '[{"name":"out","source":"input","operations":[{"operation":"group_by",'
            '"columns":["text"],"aggregate":[{"operation":"sum","column":"text","output":"total"}]}]}]',
            "numeric column",
        ),
        (
            '[{"name":"out","source":"input","operations":[{"operation":"unpivot",'
            '"index":[],"columns":{"number":"value","text":"text"},'
            '"variable_name":"kind","value_name":"payload"}]}]',
            "incompatible types",
        ),
        (
            '[{"name":"out","operations":[{"operation":"concat","sources":["input","other_names"]}]}]',
            "matching column names",
        ),
        (
            '[{"name":"out","operations":[{"operation":"concat","sources":["input","other_types"]}]}]',
            "incompatible types",
        ),
        (
            '[{"name":"out","source":"input","operations":[{"operation":"fill_null",'
            '"columns":["value"],"value":"zero"}]}]',
            "incompatible",
        ),
        (
            '[{"name":"out","source":"input","operations":[{"operation":"fill_null",'
            '"columns":["value"],"from_columns":["other_number"]}]}]',
            "backup types must match",
        ),
    ]
    mapping_path = tmp_path / "table_mapping.json"
    for contents, error in cases:
        mapping_path.write_text(contents, encoding="utf-8")
        with pytest.raises(ValueError, match=error):
            r2x_core.assemble_tables(inputs, mapping_path=mapping_path, backend=backend)


def test_rows_datetime_literals_bindings_and_inline_tables_build_typed_values(tmp_path: Path) -> None:
    """Parse validated ISO datetime values consistently in both row constructors."""
    from datetime import datetime

    backend = PolarsTabularBackend()
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "literal_times",
                    "operations": [
                        {
                            "operation": "rows",
                            "schema": [{"name": "when", "dtype": "datetime"}],
                            "values": [
                                {"when": "2032-01-01T00:00:00"},
                                {"when": None},
                            ],
                        }
                    ],
                },
                {
                    "name": "bound_times",
                    "operations": [
                        {
                            "operation": "rows",
                            "schema": [{"name": "when", "dtype": "datetime"}],
                            "values": "{time_rows}",
                        }
                    ],
                },
                {
                    "name": "empty_times",
                    "operations": [
                        {
                            "operation": "rows",
                            "schema": [{"name": "when", "dtype": "datetime"}],
                            "values": [],
                        }
                    ],
                },
                {
                    "name": "typed_values",
                    "operations": [
                        {
                            "operation": "rows",
                            "schema": [
                                {"name": "enabled", "dtype": "bool"},
                                {"name": "count", "dtype": "int64"},
                                {"name": "ratio", "dtype": "float64"},
                                {"name": "label", "dtype": "string"},
                            ],
                            "values": [{"enabled": True, "count": 2, "ratio": 1.25, "label": "literal"}],
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )
    tables = r2x_core.assemble_tables(
        {},
        mapping_path=mapping_path,
        backend=backend,
        placeholders={"time_rows": [{"when": "2040-02-03T04:05:06"}, {"when": None}]},
    )
    assert list(tables["literal_times"].iter_rows()) == [
        {"when": datetime(2032, 1, 1)},
        {"when": None},
    ]
    assert list(tables["bound_times"].iter_rows()) == [
        {"when": datetime(2040, 2, 3, 4, 5, 6)},
        {"when": None},
    ]
    assert list(tables["empty_times"].iter_rows()) == []
    assert tables["empty_times"].data.collect_schema() == pl.Schema({"when": pl.Datetime("us")})
    assert list(tables["typed_values"].iter_rows()) == [
        {"enabled": True, "count": 2, "ratio": 1.25, "label": "literal"}
    ]
    assert tables["typed_values"].data.collect_schema() == pl.Schema(
        {"enabled": pl.Boolean, "count": pl.Int64, "ratio": pl.Float64, "label": pl.String}
    )

    invalid_path = tmp_path / "invalid-table-mapping.json"
    invalid_path.write_text(
        '[{"name":"invalid_times","operations":[{"operation":"rows",'
        '"schema":[{"name":"when","dtype":"datetime"}],'
        '"values":[{"when":"not-a-datetime"}]}]}]',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        r2x_core.assemble_tables({}, mapping_path=invalid_path, backend=backend)

    inline_file = DataFile(
        name="inline_times",
        inline_table={
            "schema": {"when": "datetime"},
            "rows": [{"when": "2032-01-01T00:00:00"}, {"when": None}],
        },
    )
    inline_source = DataReader().read_data_files([inline_file], folder_path=tmp_path)["inline_times"]
    assert list(inline_source.iter_rows()) == [
        {"when": datetime(2032, 1, 1)},
        {"when": None},
    ]
    with pytest.raises(ValidationError):
        DataFile(
            name="bad_inline_times",
            inline_table={"schema": {"when": "datetime"}, "rows": [{"when": "not-a-datetime"}]},
        )


def test_data_file_column_schema_preserves_optional_absence_and_present_empty(tmp_path: Path) -> None:
    """Use declared native columns to distinguish absent from present-empty inputs."""
    from r2x_core.file_reader import SourceAvailability

    empty_path = tmp_path / "empty.csv"
    empty_path.write_text("native_year,native_value\n", encoding="utf-8")
    optional = DataFile.model_validate(
        {
            "name": "missing",
            "relative_fpath": "missing.csv",
            "info": {"requirement": "optional"},
            "columns": [
                {"name": "native_year", "dtype": "int64", "rename": "year"},
                {"name": "native_value", "dtype": "float64", "rename": "value"},
            ],
        }
    )
    present_empty = DataFile.model_validate(
        {
            "name": "empty",
            "fpath": empty_path,
            "columns": [
                {"name": "native_year", "dtype": "int64", "rename": "year"},
                {"name": "native_value", "dtype": "float64", "rename": "value"},
            ],
        }
    )

    processed_optional = DataFile.model_validate(
        {
            "name": "processed_missing",
            "relative_fpath": "processed-missing.csv",
            "info": {"requirement": "optional"},
            "columns": [{"name": "native_value", "dtype": "float64", "rename": "value"}],
            "proc_spec": {
                "kind": "tabular",
                "steps": [{"op": "rename_columns", "column_mapping": {"value": "load_mw"}}],
            },
        }
    )
    sources = DataReader().read_data_files(
        [optional, present_empty, processed_optional], folder_path=tmp_path
    )

    absent = sources["missing"]
    assert isinstance(absent, TabularSource)
    assert absent.availability is SourceAvailability.ABSENT
    assert absent.absent_inputs == frozenset({"missing"})
    assert absent.fields() == ["year", "value"]
    assert absent.data.collect_schema() == pl.Schema({"year": pl.Int64, "value": pl.Float64})
    assert list(absent.iter_rows()) == []
    empty = sources["empty"]
    assert isinstance(empty, TabularSource)
    assert empty.availability is SourceAvailability.PRESENT
    assert empty.fields() == ["year", "value"]
    assert empty.data.collect_schema() == pl.Schema({"year": pl.Int64, "value": pl.Float64})
    assert list(empty.iter_rows()) == []
    processed_absent = sources["processed_missing"]
    assert processed_absent.availability is SourceAvailability.ABSENT
    assert processed_absent.fields() == ["load_mw"]
    assert processed_absent.data.collect_schema() == pl.Schema({"load_mw": pl.Float64})
    assert list(processed_absent.iter_rows()) == []


def test_native_csv_schema_guides_inference_and_is_part_of_cache_identity(tmp_path: Path) -> None:
    """Decode late fractional values with declared types and separate cache schemas."""
    path = tmp_path / "rates.csv"
    path.write_text("rate\n" + "1\n" * 100 + "1.2861\n", encoding="utf-8")
    as_integer = DataFile(
        name="integer_rate",
        fpath=path,
        columns=[{"name": "rate", "dtype": "int64"}],
    )
    as_float = DataFile(
        name="float_rate",
        fpath=path,
        columns=[{"name": "rate", "dtype": "float64"}],
    )

    sources = DataReader().read_data_files([as_integer, as_float], folder_path=tmp_path)

    float_rates = list(sources["float_rate"].iter_rows())
    assert float_rates[:2] == [{"rate": 1.0}, {"rate": 1.0}]
    assert float_rates[-1] == {"rate": 1.2861}
    assert sources["float_rate"].data.collect_schema() == pl.Schema({"rate": pl.Float64})


@pytest.mark.parametrize("required", ["false", 0, None])
def test_native_column_required_is_a_strict_boolean(tmp_path: Path, required: object) -> None:
    """Reject non-boolean required declarations and default omitted values to required."""
    defaulted = DataFile.model_validate(
        {"name": "defaulted", "fpath": "input.csv", "columns": [{"name": "value", "dtype": "float64"}]}
    )
    assert defaulted.columns is not None
    assert defaulted.columns[0].required is True
    with pytest.raises(ValidationError):
        DataFile.model_validate(
            {
                "name": "invalid",
                "fpath": "input.csv",
                "columns": [{"name": "value", "dtype": "float64", "required": required}],
            }
        )


def test_optional_native_column_materializes_typed_nulls_for_present_files(tmp_path: Path) -> None:
    """Materialize only a missing optional column and retain rows and undeclared fields."""
    populated_path = tmp_path / "populated.csv"
    populated_path.write_text("id,payload\n1,a\n2,b\n", encoding="utf-8")
    empty_path = tmp_path / "empty.csv"
    empty_path.write_text("id,payload\n", encoding="utf-8")
    records = [
        {
            "name": name,
            "fpath": path,
            "columns": [
                {"name": "id", "dtype": "int64"},
                {"name": "quantity", "dtype": "float64", "required": False},
            ],
        }
        for name, path in (("populated", populated_path), ("empty", empty_path))
    ]

    sources = DataReader().read_data_files(
        [DataFile.model_validate(record) for record in records], folder_path=tmp_path
    )

    populated = sources["populated"]
    assert populated.fields() == ["id", "payload", "quantity"]
    assert populated.data.collect_schema() == pl.Schema(
        {"id": pl.Int64, "payload": pl.String, "quantity": pl.Float64}
    )
    assert list(populated.iter_rows()) == [
        {"id": 1, "payload": "a", "quantity": None},
        {"id": 2, "payload": "b", "quantity": None},
    ]
    empty = sources["empty"]
    assert list(empty.iter_rows()) == []
    assert empty.data.collect_schema() == populated.data.collect_schema()


def test_optional_native_column_is_strictly_cast_and_renamed_when_present(tmp_path: Path) -> None:
    """Normalize a present optional column with the same strict native schema."""
    path = tmp_path / "optional-present.csv"
    path.write_text("id,native_quantity\n1,2.5\n2,\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "native",
            "fpath": path,
            "columns": [
                {"name": "id", "dtype": "int64"},
                {
                    "name": "native_quantity",
                    "dtype": "float64",
                    "rename": "quantity",
                    "required": False,
                },
            ],
        }
    )

    source = DataReader().read_data_files([data_file], folder_path=tmp_path)["native"]

    assert source.data.collect_schema() == pl.Schema({"id": pl.Int64, "quantity": pl.Float64})
    assert list(source.iter_rows()) == [{"id": 1, "quantity": 2.5}, {"id": 2, "quantity": None}]


def test_optional_native_column_does_not_hide_malformed_present_values(tmp_path: Path) -> None:
    """Keep malformed values as errors when an optional column is present."""
    path = tmp_path / "optional-invalid.csv"
    path.write_text("id,quantity\n1,not-a-number\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "native",
            "fpath": path,
            "columns": [
                {"name": "id", "dtype": "int64"},
                {"name": "quantity", "dtype": "float64", "required": False},
            ],
        }
    )

    source = DataReader().read_data_files([data_file], folder_path=tmp_path)["native"]
    with pytest.raises(pl.exceptions.PolarsError):
        list(source.iter_rows())


def test_optional_native_column_rename_cannot_overwrite_an_actual_column(tmp_path: Path) -> None:
    """Reject optional schema renames that collide with undeclared native fields."""
    from r2x_core.exceptions import ReaderError

    path = tmp_path / "optional-collision.csv"
    path.write_text("id,quantity\n1,3.0\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "native",
            "fpath": path,
            "columns": [
                {"name": "id", "dtype": "int64"},
                {"name": "not_in_file", "dtype": "float64", "rename": "quantity", "required": False},
            ],
        }
    )

    with pytest.raises(ReaderError, match="duplicate column names"):
        DataReader().read_data_files([data_file], folder_path=tmp_path)


def test_native_hdf5_schema_rejects_fractional_float_to_integer_casts(tmp_path: Path) -> None:
    """Reject HDF5 float columns declared as integers instead of truncating values."""
    import h5py
    import numpy as np

    from r2x_core.exceptions import ReaderError

    path = tmp_path / "counts.h5"
    with h5py.File(path, "w") as output:
        output.create_dataset("columns", data=np.asarray(["value"], dtype="S"))
        output.create_dataset("data", data=np.asarray([[1.5], [-2.9]]))
    data_file = DataFile.model_validate(
        {
            "name": "counts",
            "relative_fpath": "counts.h5",
            "reader": {"options": {"data_key": "data", "columns_key": "columns"}},
            "columns": [{"name": "value", "dtype": "int64"}],
        }
    )

    with pytest.raises(ReaderError, match="floating-point to integer is unsupported"):
        DataReader().read_data_files([data_file], folder_path=tmp_path)


def test_native_blank_header_is_exactly_renamed_at_file_boundary(tmp_path: Path) -> None:
    """Allow a blank physical header only when it receives a usable output name."""
    path = tmp_path / "blank-header.csv"
    path.write_text(",value\n2032,1.5\n", encoding="utf-8")
    data_file = DataFile(
        name="blank_header",
        fpath=path,
        columns=[{"name": "", "dtype": "int64", "rename": "year"}, {"name": "value", "dtype": "float64"}],
    )

    source = DataReader().read_data_files([data_file], folder_path=tmp_path)["blank_header"]

    assert isinstance(source, TabularSource)
    assert source.fields() == ["year", "value"]
    assert list(source.iter_rows()) == [{"year": 2032, "value": 1.5}]
    with pytest.raises(ValidationError):
        DataFile.model_validate({"name": "bad", "fpath": path, "columns": [{"name": "", "dtype": "int64"}]})


def test_optional_input_without_schema_stays_unknown_to_table_assembly(tmp_path: Path) -> None:
    """Do not infer absence semantics for an optional input without declared columns."""
    from r2x_core import FileRequirement

    optional = DataFile(
        name="unknown_optional",
        relative_fpath="missing.csv",
        info={"requirement": FileRequirement.OPTIONAL},
    )
    sources = DataReader().read_data_files([optional], folder_path=tmp_path)
    assert "unknown_optional" not in sources
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"out","source":"unknown_optional","operations":[]}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unknown table source"):
        r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=PolarsTabularBackend())


def test_declared_native_columns_reject_missing_and_invalid_present_values(tmp_path: Path) -> None:
    """Fail on present inputs that violate their declared native shape or types."""
    from r2x_core.exceptions import ReaderError

    missing_column = tmp_path / "missing-column.csv"
    missing_column.write_text("year\n2032\n", encoding="utf-8")
    invalid_cast = tmp_path / "invalid-cast.csv"
    invalid_cast.write_text("year,value\nnot-an-integer,1.0\n", encoding="utf-8")
    declarations = [
        DataFile(
            name="native",
            fpath=path,
            columns=[{"name": "year", "dtype": "int64"}, {"name": "value", "dtype": "float64"}],
        )
        for path in (missing_column, invalid_cast)
    ]

    with pytest.raises(ReaderError):
        DataReader().read_data_files([declarations[0]], folder_path=tmp_path)
    source = DataReader().read_data_files([declarations[1]], folder_path=tmp_path)["native"]
    assert isinstance(source, TabularSource)
    assert source.availability.value == "present"
    with pytest.raises(pl.exceptions.PolarsError):
        list(source.iter_rows())


def test_absent_optional_source_is_not_an_unknown_or_present_table(tmp_path: Path) -> None:
    """Propagate declared absence through assembly and reject parser consumption."""
    from r2x_core import FileRequirement
    from r2x_core.file_reader import SourceAvailability
    from r2x_core.ingestion import build_system_from_sources
    from r2x_core.models import ComponentInstruction

    optional = DataFile(
        name="missing",
        relative_fpath="missing.csv",
        info={"requirement": FileRequirement.OPTIONAL},
        columns=[{"name": "key", "dtype": "int64"}, {"name": "value", "dtype": "int64"}],
    )
    base = DataFile(
        name="base",
        inline_table={
            "schema": {"key": "int64", "payload": "string"},
            "rows": [{"key": 1, "payload": "A"}, {"key": 2, "payload": "B"}],
        },
    )
    independent = DataFile(
        name="independent",
        inline_table={"schema": {"name": "string"}, "rows": [{"name": "kept"}]},
    )
    sources = DataReader().read_data_files([optional, base, independent], folder_path=tmp_path)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "still_missing",
                    "source": "missing",
                    "operations": [],
                    "columns": {"value": "value"},
                },
                {
                    "name": "inner_join",
                    "source": "base",
                    "operations": [
                        {
                            "operation": "join",
                            "source": "missing",
                            "how": "inner",
                            "on": ["key"],
                            "columns": ["value"],
                        }
                    ],
                },
                {
                    "name": "left_join",
                    "source": "base",
                    "operations": [
                        {
                            "operation": "join",
                            "source": "missing",
                            "how": "left",
                            "on": ["key"],
                            "columns": ["value"],
                        }
                    ],
                },
                {
                    "name": "cross_join",
                    "source": "base",
                    "operations": [
                        {"operation": "join", "source": "missing", "how": "cross", "columns": ["value"]}
                    ],
                },
                {"name": "absent_concat", "operations": [{"operation": "concat", "sources": ["missing"]}]},
                {
                    "name": "concat_skips_incompatible_absent",
                    "operations": [{"operation": "concat", "sources": ["missing", "independent"]}],
                },
            ]
        ),
        encoding="utf-8",
    )
    tables = r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=PolarsTabularBackend())
    result = tables["still_missing"]
    assert result.availability is SourceAvailability.ABSENT
    assert result.absent_inputs == frozenset({"missing"})
    assert result.data.collect_schema() == pl.Schema({"value": pl.Int64})
    assert list(tables["inner_join"].iter_rows()) == []
    assert tables["inner_join"].fields() == ["key", "payload", "value"]
    assert tables["inner_join"].availability is SourceAvailability.PRESENT
    assert tables["inner_join"].absent_inputs == frozenset({"missing"})
    assert list(tables["left_join"].iter_rows()) == [
        {"key": 1, "payload": "A", "value": None},
        {"key": 2, "payload": "B", "value": None},
    ]
    assert list(tables["cross_join"].iter_rows()) == []
    assert tables["absent_concat"].availability is SourceAvailability.PRESENT
    assert tables["absent_concat"].absent_inputs == frozenset({"missing"})
    assert tables["absent_concat"].fields() == ["key", "value"]
    assert list(tables["absent_concat"].iter_rows()) == []
    assert tables["concat_skips_incompatible_absent"].fields() == ["name"]
    assert list(tables["concat_skips_incompatible_absent"].iter_rows()) == [{"name": "kept"}]
    assert tables["concat_skips_incompatible_absent"].absent_inputs == frozenset({"missing"})

    config = PluginConfig(models=("fixtures.ingestion_models",), config_path_override=tmp_path / "unused")
    instruction = ComponentInstruction(
        kind="component", source="still_missing", component_type="PSSEBus", fields={"name": "value"}
    )
    with pytest.raises(ValueError, match="absent"):
        build_system_from_sources(
            {**sources, **tables}, config=config, instructions=[instruction], name="absent"
        )


def test_first_present_constructor_returns_the_first_present_source_unchanged(tmp_path: Path) -> None:
    """Present-empty candidates win in declared order and retain source metadata."""
    backend = PolarsTabularBackend()
    missing = TabularSource(
        pl.DataFrame(schema={"value": pl.Int64}).lazy(),
        backend,
        availability=SourceAvailability.ABSENT,
        absent_inputs=frozenset({"missing"}),
    )
    present_empty = TabularSource(
        pl.DataFrame(schema={"value": pl.Int64}).lazy(),
        backend,
        absent_inputs=frozenset({"earlier-missing"}),
    )
    later = TabularSource(pl.DataFrame({"value": [4]}, schema={"value": pl.Int64}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
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
                        {
                            "operation": "first_present",
                            "sources": ["missing", "present_empty", "later", "empty_fallback"],
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"missing": missing, "present_empty": present_empty, "later": later},
        mapping_path=mapping_path,
        backend=backend,
    )

    assert tables["selected"] is present_empty
    assert tables["selected"].availability is SourceAvailability.PRESENT
    assert tables["selected"].absent_inputs == frozenset({"earlier-missing"})
    assert tables["selected"].fields() == ["value"]
    assert list(tables["selected"].iter_rows()) == []


def test_first_present_uses_a_declared_typed_empty_fallback(tmp_path: Path) -> None:
    """An explicit final rows candidate supplies the typed empty result when sources are absent."""
    backend = PolarsTabularBackend()
    missing = TabularSource(
        pl.DataFrame(schema={"value": pl.Int64}).lazy(),
        backend,
        availability=SourceAvailability.ABSENT,
        absent_inputs=frozenset({"missing"}),
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "empty_fallback",
                    "operations": [
                        {"operation": "rows", "schema": [{"name": "value", "dtype": "int64"}], "values": []}
                    ],
                },
                {
                    "name": "selected",
                    "operations": [{"operation": "first_present", "sources": ["missing", "empty_fallback"]}],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"missing": missing}, mapping_path=mapping_path, backend=backend)

    assert tables["selected"] is tables["empty_fallback"]
    assert tables["selected"].availability is SourceAvailability.PRESENT
    assert tables["selected"].absent_inputs == frozenset()
    assert tables["selected"].fields() == ["value"]
    assert list(tables["selected"].iter_rows()) == []


@pytest.mark.parametrize(
    "availability",
    [SourceAvailability.ABSENT, SourceAvailability.PRESENT],
    ids=["absent", "present-empty"],
)
def test_first_nonempty_uses_typed_fallback_for_absent_or_empty_sources(
    tmp_path: Path, availability: SourceAvailability
) -> None:
    """An absent or empty source selects the declared typed fallback unchanged."""
    backend = PolarsTabularBackend()
    candidate = TabularSource(
        pl.DataFrame(schema={"value": pl.Int64}).lazy(),
        backend,
        availability=availability,
        absent_inputs=frozenset({"input"}) if availability is SourceAvailability.ABSENT else frozenset(),
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
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
                        {
                            "operation": "first_nonempty",
                            "sources": ["candidate"],
                            "fallback": "empty_fallback",
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"candidate": candidate}, mapping_path=mapping_path, backend=backend)

    assert tables["selected"] is tables["empty_fallback"]
    assert tables["selected"].availability is SourceAvailability.PRESENT
    assert tables["selected"].absent_inputs == frozenset()
    assert tables["selected"].fields() == ["value"]
    assert list(tables["selected"].iter_rows()) == []


def test_first_nonempty_returns_first_nonempty_source_unchanged(tmp_path: Path) -> None:
    """Skip empty sources in priority order and preserve the selected source metadata."""
    backend = PolarsTabularBackend()
    empty = TabularSource(pl.DataFrame(schema={"value": pl.Int64}).lazy(), backend)
    selected = TabularSource(
        pl.DataFrame({"value": [4]}, schema={"value": pl.Int64}).lazy(),
        backend,
        absent_inputs=frozenset({"previously-absent"}),
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "fallback",
                    "operations": [
                        {"operation": "rows", "schema": [{"name": "value", "dtype": "int64"}], "values": []}
                    ],
                },
                {
                    "name": "selected",
                    "operations": [
                        {
                            "operation": "first_nonempty",
                            "sources": ["empty", "nonempty_source"],
                            "fallback": "fallback",
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"empty": empty, "nonempty_source": selected},
        mapping_path=mapping_path,
        backend=backend,
    )

    assert tables["selected"] is selected
    assert tables["selected"].availability is SourceAvailability.PRESENT
    assert tables["selected"].absent_inputs == frozenset({"previously-absent"})
    assert list(tables["selected"].iter_rows()) == [{"value": 4}]


def test_first_nonempty_propagates_an_absent_fallback_unchanged(tmp_path: Path) -> None:
    """An explicitly selected absent fallback retains its missing-source provenance."""
    backend = PolarsTabularBackend()
    candidate = TabularSource(pl.DataFrame(schema={"value": pl.Int64}).lazy(), backend)
    fallback = TabularSource(
        pl.DataFrame(schema={"value": pl.Int64}).lazy(),
        backend,
        availability=SourceAvailability.ABSENT,
        absent_inputs=frozenset({"fallback_input"}),
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
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
                        {
                            "operation": "first_nonempty",
                            "sources": ["candidate"],
                            "fallback": "empty_fallback",
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"candidate": candidate},
        mapping_path=mapping_path,
        backend=backend,
        initial_tables={"empty_fallback": fallback},
    )

    assert tables["selected"] is fallback
    assert tables["selected"].availability is SourceAvailability.ABSENT
    assert tables["selected"].absent_inputs == frozenset({"fallback_input"})
    assert tables["selected"].fields() == ["value"]
    assert list(tables["selected"].iter_rows()) == []


def test_first_nonempty_rejects_all_empty_candidates_without_fallback(tmp_path: Path) -> None:
    """All-empty first-nonempty inputs require a declared fallback."""
    backend = PolarsTabularBackend()
    empty = TabularSource(pl.DataFrame(schema={"value": pl.Int64}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"selected","operations":[{"operation":"first_nonempty","sources":["left"]}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="No nonempty source"):
        r2x_core.assemble_tables({"left": empty}, mapping_path=mapping_path, backend=backend)


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        pytest.param(
            {"operation": "first_nonempty", "sources": ["input", "input"]},
            "sources must be unique",
            id="duplicate-candidates",
        ),
        pytest.param(
            {"operation": "first_nonempty", "sources": ["input"], "fallback": "input"},
            "must not repeat a candidate",
            id="fallback-collision",
        ),
        pytest.param(
            {"operation": "first_nonempty", "sources": ["input"], "fallback": None},
            "must be omitted when unused, not null",
            id="explicit-null-fallback",
        ),
    ],
)
def test_first_nonempty_rejects_ambiguous_constructor_declarations(
    tmp_path: Path, operation: dict[str, object], message: str
) -> None:
    """Candidate order and optional fallback syntax remain unambiguous."""
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(json.dumps([{"name": "selected", "operations": [operation]}]), encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        r2x_core.assemble_tables({}, mapping_path=mapping_path, backend=PolarsTabularBackend())


def test_first_nonempty_rejects_an_unknown_fallback_source(tmp_path: Path) -> None:
    """A nonempty selector cannot mask an undeclared fallback source."""
    candidate = TabularSource(pl.DataFrame({"value": [1]}).lazy(), PolarsTabularBackend())
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"selected","operations":[{"operation":"first_nonempty","sources":["candidate"],"fallback":"unknown"}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown table source 'unknown'"):
        r2x_core.assemble_tables(
            {"candidate": candidate}, mapping_path=mapping_path, backend=PolarsTabularBackend()
        )


def test_first_present_rejects_all_absent_candidates_without_fallback(tmp_path: Path) -> None:
    """All-absent first-present inputs require an explicitly declared fallback."""
    backend = PolarsTabularBackend()
    absent = TabularSource(
        pl.DataFrame(schema={"value": pl.Int64}).lazy(),
        backend,
        availability=SourceAvailability.ABSENT,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"selected","operations":[{"operation":"first_present","sources":["left","right"]}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="No present source"):
        r2x_core.assemble_tables(
            {"left": absent, "right": absent}, mapping_path=mapping_path, backend=backend
        )


def test_first_present_rejects_unknown_candidates_before_assembly(tmp_path: Path) -> None:
    """A fallback cannot hide an undeclared first-present source name."""
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        '[{"name":"selected","operations":[{"operation":"first_present","sources":["unknown"]}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown table source"):
        r2x_core.assemble_tables({}, mapping_path=mapping_path, backend=PolarsTabularBackend())


def test_canonical_reserve_mapping_runs_through_csv_ingestion_and_parser(tmp_path: Path) -> None:
    """Execute the checked-in nine-table mapping through the real public build path."""
    from datetime import datetime

    from r2x_core.file_reader import SourceAvailability

    config_dir = tmp_path / "config"
    input_dir = tmp_path / "inputs"
    config_dir.mkdir()
    input_dir.mkdir()
    records = {
        "reserve_hierarchy": (
            "region,transmission_region\np1,controlled\n",
            {"region": "string", "transmission_region": "string"},
        ),
        "load_profile_rows": (
            "region,solve_year,datetime,weather_year,value\n"
            "p1,2032,2012-01-01T00:00:00,2012,10.0\n"
            "p1,2032,2012-01-01T01:00:00,2012,10.0\n",
            {
                "region": "string",
                "solve_year": "int64",
                "datetime": "datetime",
                "weather_year": "int64",
                "value": "float64",
            },
        ),
        "renewable_values": (
            "region,solve_year,datetime,category,value,capacity_factor\n"
            "p1,2032,2012-01-01T00:00:00,wind,20.0,0.2\n"
            "p1,2032,2012-01-01T01:00:00,wind,0.0,0.0\n"
            "p1,2032,2012-01-01T00:00:00,solar,0.0,0.0\n"
            "p1,2032,2012-01-01T01:00:00,solar,100.0,0.5\n",
            {
                "region": "string",
                "solve_year": "int64",
                "datetime": "datetime",
                "category": "string",
                "value": "float64",
                "capacity_factor": "float64",
            },
        ),
        "generator_owners": (
            "region,solve_year,category,capacity\n"
            "p1,2032,wind,100.0\np1,2032,solar,200.0\np1,2032,solar,300.0\n",
            {"region": "string", "solve_year": "int64", "category": "string", "capacity": "float64"},
        ),
        "reserve_products": (
            "reserve_type,load_fraction,wind_fraction,solar_fraction\nSPINNING,0.3,0.1,0.2\n",
            {
                "reserve_type": "string",
                "load_fraction": "float64",
                "wind_fraction": "float64",
                "solar_fraction": "float64",
            },
        ),
        "reserve_component_rows": (
            "name,transmission_region,reserve_type,number,base_kv\n"
            "controlled_SPINNING,controlled,SPINNING,1,230.0\n",
            {
                "name": "string",
                "transmission_region": "string",
                "reserve_type": "string",
                "number": "int64",
                "base_kv": "float64",
            },
        ),
        "calendar": (
            "datetime\n2012-01-01T00:00:00\n2012-01-01T01:00:00\n2012-01-01T02:00:00\n",
            {"datetime": "datetime"},
        ),
    }
    file_records = []
    for name, (csv, schema) in records.items():
        path = input_dir / f"{name}.csv"
        path.write_text(csv, encoding="utf-8")
        file_records.append(
            {
                "name": name,
                "relative_fpath": path.name,
                "reader": {"format": "csv"},
                "columns": [{"name": column, "dtype": dtype} for column, dtype in schema.items()],
            }
        )
    (config_dir / "file_mapping.json").write_text(json.dumps(file_records), encoding="utf-8")
    parser_rules = [
        {
            "kind": "component",
            "source": "reserve_component_rows",
            "component_type": "PSSEBus",
            "fields": {"name": "name", "number": "number", "base_kv": "base_kv"},
        },
        {
            "kind": "time_series",
            "source": "reserve_requirement_rows",
            "name": "requirement",
            "values": "requirement",
            "time_axis": {"kind": "column", "column": "datetime", "resolution_seconds": 3600},
            "metadata": {"weather_year": "{primary_weather_year}"},
            "metadata_columns": {"solve_year": "solve_year"},
            "skip_if_empty": True,
            "owners": [{"component_type": "PSSEBus", "name_field": "name"}],
        },
    ]
    (config_dir / "parser_rules.json").write_text(json.dumps(parser_rules), encoding="utf-8")
    table_mapping_path = Path(__file__).parent / "fixtures/reserve_table_mapping.json"
    config = PluginConfig(models=("fixtures.ingestion_models",), config_path_override=config_dir)
    placeholders = {
        "primary_weather_year": 2012,
        "solve_year_rows": [{"solve_year": 2032}, {"solve_year": 2040}],
    }
    input_sources = DataReader().read_data_files(
        [DataFile.model_validate(record) for record in file_records],
        folder_path=input_dir,
    )
    assembled = r2x_core.assemble_tables(
        input_sources,
        mapping_path=table_mapping_path,
        backend=PolarsTabularBackend(),
        placeholders=placeholders,
    )
    expected = [
        {
            "datetime": datetime(2012, 1, 1, 0),
            "name": "controlled_SPINNING",
            "requirement": 5.0,
            "solve_year": 2032,
        },
        {
            "datetime": datetime(2012, 1, 1, 1),
            "name": "controlled_SPINNING",
            "requirement": 103.0,
            "solve_year": 2032,
        },
        {
            "datetime": datetime(2012, 1, 1, 2),
            "name": "controlled_SPINNING",
            "requirement": 0.0,
            "solve_year": 2032,
        },
        {
            "datetime": datetime(2012, 1, 1, 0),
            "name": "controlled_SPINNING",
            "requirement": 0.0,
            "solve_year": 2040,
        },
        {
            "datetime": datetime(2012, 1, 1, 1),
            "name": "controlled_SPINNING",
            "requirement": 0.0,
            "solve_year": 2040,
        },
        {
            "datetime": datetime(2012, 1, 1, 2),
            "name": "controlled_SPINNING",
            "requirement": 0.0,
            "solve_year": 2040,
        },
    ]
    assert list(assembled["reserve_requirement_rows"].iter_rows()) == expected
    assert assembled["reserve_requirement_rows"].availability is SourceAvailability.PRESENT

    system = build_system(
        config,
        name="canonical-reserve",
        input_folder=input_dir,
        table_mapping_path=table_mapping_path,
        placeholders=placeholders,
    )
    owner = system.get_component(PSSEBus, "controlled_SPINNING")
    series_2032 = system.get_time_series(owner, name="requirement", solve_year=2032)
    series_2040 = system.get_time_series(owner, name="requirement", solve_year=2040)
    assert series_2032.data_array.tolist() == [5.0, 103.0, 0.0]
    assert series_2040.data_array.tolist() == [0.0, 0.0, 0.0]
    assert system.list_time_series_metadata(owner, name="requirement")[0].features == {
        "solve_year": 2032,
        "weather_year": 2012,
    }


def test_object_and_list_assembly_reaches_pydantic_component_fields(tmp_path: Path) -> None:
    """Build nested Pydantic component data from real CSV and JSON mappings."""
    config_dir = tmp_path / "config"
    input_dir = tmp_path / "inputs"
    config_dir.mkdir()
    input_dir.mkdir()
    (input_dir / "nested.csv").write_text(
        "name,forward_capacity,reverse_capacity,longitude,latitude,member_a,member_b\n"
        "N-1,12.5,10.0,30,45.5,3,\n"
        "N-2,9.0,8.0,,46.5,,4\n",
        encoding="utf-8",
    )
    columns = [
        {"name": "name", "dtype": "string"},
        {"name": "forward_capacity", "dtype": "float64"},
        {"name": "reverse_capacity", "dtype": "float64"},
        {"name": "longitude", "dtype": "int64"},
        {"name": "latitude", "dtype": "float64"},
        {"name": "member_a", "dtype": "int64"},
        {"name": "member_b", "dtype": "int64"},
    ]
    (config_dir / "file_mapping.json").write_text(
        json.dumps([{"name": "native", "relative_fpath": "nested.csv", "columns": columns}]),
        encoding="utf-8",
    )
    (config_dir / "table_mapping.json").write_text(
        json.dumps(
            [
                {
                    "name": "nested_component_rows",
                    "source": "native",
                    "operations": [
                        {"operation": "list", "columns": ["longitude", "latitude"], "output": "coordinates"},
                        {"operation": "list", "columns": ["member_a", "member_b"], "output": "members"},
                        {
                            "operation": "object",
                            "columns": {
                                "from_to": "forward_capacity",
                                "to_from": "reverse_capacity",
                            },
                            "output": "max_active_power",
                        },
                        {
                            "operation": "object",
                            "columns": {
                                "coordinates": "coordinates",
                                "name": "name",
                                "site_type": {"value": "substation"},
                            },
                            "output": "geographic_info",
                        },
                    ],
                    "columns": {
                        "name": "name",
                        "max_active_power": "max_active_power",
                        "coordinates": "coordinates",
                        "members": "members",
                        "geographic_info": "geographic_info",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "parser_rules.json").write_text(
        json.dumps(
            [
                {
                    "kind": "component",
                    "source": "nested_component_rows",
                    "component_type": "NestedValuesComponent",
                    "fields": {
                        "name": "name",
                        "max_active_power": "max_active_power",
                        "coordinates": "coordinates",
                        "members": "members",
                        "geographic_info": "geographic_info",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    system = build_system(
        PluginConfig(models=("fixtures.ingestion_models",), config_path_override=config_dir),
        name="nested-table-values",
        input_folder=input_dir,
        table_mapping_path=config_dir / "table_mapping.json",
    )

    first = system.get_component(NestedValuesComponent, "N-1")
    second = system.get_component(NestedValuesComponent, "N-2")
    assert first.max_active_power == {"from_to": 12.5, "to_from": 10.0}
    assert first.coordinates == [30.0, 45.5]
    assert first.members == [3, None]
    assert first.geographic_info == {
        "coordinates": [30.0, 45.5],
        "name": "N-1",
        "site_type": "substation",
    }
    assert second.max_active_power == {"from_to": 9.0, "to_from": 8.0}
    assert second.coordinates == [None, 46.5]
    assert second.members == [None, 4]


def test_group_by_list_preserves_order_nulls_and_empty_element_schema(tmp_path: Path) -> None:
    """Collect group values in current row order and keep typed empty results."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {"group": ["b", "a", "b", "c"], "value": [1, None, None, None]},
            schema={"group": pl.String, "value": pl.Int64},
        ).lazy(),
        backend,
    )
    empty = TabularSource(
        pl.DataFrame(schema={"group": pl.String, "value": pl.Int64}).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "grouped",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "group_by",
                            "columns": ["group"],
                            "aggregate": [{"operation": "list", "column": "value", "output": "values"}],
                        }
                    ],
                },
                {
                    "name": "empty_grouped",
                    "source": "empty",
                    "operations": [
                        {
                            "operation": "group_by",
                            "columns": ["group"],
                            "aggregate": [{"operation": "list", "column": "value", "output": "values"}],
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty": empty}, mapping_path=mapping_path, backend=backend
    )

    assert list(tables["grouped"].iter_rows()) == [
        {"group": "b", "values": [1, None]},
        {"group": "a", "values": [None]},
        {"group": "c", "values": [None]},
    ]
    assert tables["grouped"].data.collect_schema() == pl.Schema(
        {"group": pl.String, "values": pl.List(pl.Int64)}
    )
    assert list(tables["empty_grouped"].iter_rows()) == []
    assert tables["empty_grouped"].data.collect_schema() == pl.Schema(
        {"group": pl.String, "values": pl.List(pl.Int64)}
    )


def test_object_and_list_operations_reject_invalid_shapes_and_types(tmp_path: Path) -> None:
    """Reject undocumented values, missing inputs, output collisions, and incompatible lists."""
    backend = PolarsTabularBackend()
    inputs = {
        "input": TabularSource(
            pl.DataFrame({"left": [1], "right": [2.0], "text": ["value"], "existing": [3]}).lazy(),
            backend,
        )
    }
    invalid_shapes = [
        '[{"name":"bad","source":"input","operations":[{"operation":"object",'
        '"columns":{},"output":"payload"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"object",'
        '"columns":{"item":"missing"},"output":"payload"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"object",'
        '"columns":{"item":"left","extra":true},"output":"payload"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"object",'
        '"columns":{"item":"left"},"output":"existing"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"list","columns":[],"output":"items"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"list",'
        '"columns":["left","missing"],"output":"items"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"list",'
        '"columns":["left","text"],"output":"items"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"list",'
        '"columns":["left"],"output":"existing"}]}]',
        '[{"name":"bad","source":"input","operations":[{"operation":"list",'
        '"columns":["left"],"output":"items","unknown":true}]}]',
    ]
    mapping_path = tmp_path / "table_mapping.json"
    invalid_json_shapes = [invalid_shapes[0], invalid_shapes[2], invalid_shapes[4], invalid_shapes[8]]
    invalid_references = [invalid_shapes[1], invalid_shapes[3], *invalid_shapes[5:8]]
    for contents in invalid_json_shapes:
        mapping_path.write_text(contents, encoding="utf-8")
        with pytest.raises(ValidationError):
            r2x_core.assemble_tables(inputs, mapping_path=mapping_path, backend=backend)
    for contents in invalid_references:
        mapping_path.write_text(contents, encoding="utf-8")
        with pytest.raises(ValueError):
            r2x_core.assemble_tables(inputs, mapping_path=mapping_path, backend=backend)


def test_concat_strings_builds_ordered_parser_names_and_preserves_empty_schema(tmp_path: Path) -> None:
    backend = PolarsTabularBackend()
    source_schema = {"region": pl.String, "solve_year": pl.Int64}
    source = TabularSource(
        pl.DataFrame(
            {"region": ["p1", "p2", None], "solve_year": [2030, 2032, 2034]},
            schema=source_schema,
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "load_owner_rows",
                    "source": "load_profiles",
                    "operations": [
                        {
                            "operation": "concat_strings",
                            "columns": ["region", "solve_year"],
                            "separator": "_load_",
                            "output": "owner_name",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    rows = r2x_core.assemble_tables({"load_profiles": source}, mapping_path=mapping_path, backend=backend)[
        "load_owner_rows"
    ]

    assert rows.values("owner_name") == ["p1_load_2030", "p2_load_2032", None]
    assert rows.fields() == ["region", "solve_year", "owner_name"]
    assert rows.data.collect_schema()["owner_name"] == pl.String
    empty = TabularSource(pl.DataFrame(schema=source_schema).lazy(), backend)
    empty_rows = r2x_core.assemble_tables(
        {"load_profiles": empty}, mapping_path=mapping_path, backend=backend
    )["load_owner_rows"]
    assert empty_rows.is_empty()
    assert empty_rows.data.collect_schema()["owner_name"] == pl.String


def test_datetime_part_operation_preserves_rows_nulls_and_typed_empty_sources(tmp_path: Path) -> None:
    """Extract datetime parts as int64 without changing row order or source availability."""
    backend = PolarsTabularBackend()
    schema = {"timestamp": pl.Datetime("us")}
    source = TabularSource(
        pl.DataFrame(
            {"timestamp": [datetime(2012, 12, 31, 23, 58, 57), None]},
            schema=schema,
        ).lazy(),
        backend,
    )
    empty = TabularSource(pl.DataFrame(schema=schema).lazy(), backend)
    absent = TabularSource(
        pl.DataFrame(schema=schema).lazy(),
        backend,
        availability=SourceAvailability.ABSENT,
        absent_inputs=frozenset({"optional_timestamp"}),
    )
    operations = [
        {"operation": "datetime_part", "column": "timestamp", "part": part, "output": part}
        for part in ("year", "month", "day", "hour", "minute", "second")
    ]
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {"name": "parts", "source": "input", "operations": operations},
                {
                    "name": "empty_parts",
                    "source": "empty",
                    "operations": [operations[0]],
                },
                {
                    "name": "absent_parts",
                    "source": "absent",
                    "operations": [operations[0]],
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty": empty, "absent": absent}, mapping_path=mapping_path, backend=backend
    )

    assert list(tables["parts"].iter_rows()) == [
        {
            "timestamp": datetime(2012, 12, 31, 23, 58, 57),
            "year": 2012,
            "month": 12,
            "day": 31,
            "hour": 23,
            "minute": 58,
            "second": 57,
        },
        {
            "timestamp": None,
            "year": None,
            "month": None,
            "day": None,
            "hour": None,
            "minute": None,
            "second": None,
        },
    ]
    assert all(
        tables["parts"].data.collect_schema()[part] == pl.Int64
        for part in ("year", "month", "day", "hour", "minute", "second")
    )
    assert tables["empty_parts"].data.collect_schema() == pl.Schema(
        {"timestamp": pl.Datetime("us"), "year": pl.Int64}
    )
    assert list(tables["empty_parts"].iter_rows()) == []
    assert tables["absent_parts"].availability is SourceAvailability.ABSENT
    assert tables["absent_parts"].absent_inputs == frozenset({"optional_timestamp"})
    assert tables["absent_parts"].data.collect_schema() == pl.Schema(
        {"timestamp": pl.Datetime("us"), "year": pl.Int64}
    )


def test_datetime_part_rejects_non_datetime_columns(tmp_path: Path) -> None:
    """Require a typed datetime input rather than casting arbitrary values."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"timestamp": ["2012-12-31"]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "years",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "datetime_part",
                            "column": "timestamp",
                            "part": "year",
                            "output": "year",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="datetime_part requires a datetime column"):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_datetime_part_backend_rejects_unsupported_direct_part() -> None:
    """Reject a runtime-invalid part even when called without the mapping model."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"timestamp": [datetime(2012, 12, 31)]}, schema={"timestamp": pl.Datetime("us")}).lazy(),
        backend,
    )

    with pytest.raises(ValueError, match="Unsupported datetime_part component 'week'"):
        backend.datetime_part(source, column="timestamp", part=cast(TableDateTimePart, "week"), output="week")


def test_datetime_part_rejects_output_name_collisions(tmp_path: Path) -> None:
    """Require a new output field instead of silently overwriting the input table."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {"timestamp": [datetime(2012, 12, 31)], "year": [2000]},
            schema={"timestamp": pl.Datetime("us"), "year": pl.Int64},
        ).lazy(),
        backend,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "years",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "datetime_part",
                            "column": "timestamp",
                            "part": "year",
                            "output": "year",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="datetime_part output column 'year' already exists"):
        r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_head_operation_keeps_first_rows_and_typed_empty_outputs(tmp_path: Path) -> None:
    """Select a source-order prefix without changing schemas or availability."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"ordinal": [3, 1, 2], "name": ["third", "first", "second"]}).lazy(),
        backend,
    )
    schema = {"ordinal": pl.Int64, "name": pl.String}
    empty = TabularSource(pl.DataFrame(schema=schema).lazy(), backend)
    absent = TabularSource(
        pl.DataFrame(schema=schema).lazy(),
        backend,
        availability=SourceAvailability.ABSENT,
        absent_inputs=frozenset({"optional_input"}),
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {"name": "prefix", "source": "input", "operations": [{"operation": "head", "n": 2}]},
                {"name": "zero", "source": "input", "operations": [{"operation": "head", "n": 0}]},
                {"name": "empty_prefix", "source": "empty", "operations": [{"operation": "head", "n": 2}]},
                {"name": "absent_prefix", "source": "absent", "operations": [{"operation": "head", "n": 2}]},
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source, "empty": empty, "absent": absent}, mapping_path=mapping_path, backend=backend
    )

    assert list(tables["prefix"].iter_rows()) == [
        {"name": "third", "ordinal": 3},
        {"name": "first", "ordinal": 1},
    ]
    assert tables["zero"].fields() == ["ordinal", "name"]
    assert tables["zero"].data.collect_schema() == pl.Schema(schema)
    assert list(tables["zero"].iter_rows()) == []
    assert tables["empty_prefix"].fields() == ["ordinal", "name"]
    assert tables["empty_prefix"].data.collect_schema() == pl.Schema(schema)
    assert list(tables["empty_prefix"].iter_rows()) == []
    assert tables["absent_prefix"].availability is SourceAvailability.ABSENT
    assert tables["absent_prefix"].absent_inputs == frozenset({"optional_input"})
    assert list(tables["absent_prefix"].iter_rows()) == []
    assert tables["absent_prefix"].data.collect_schema() == pl.Schema(schema)


def test_materialized_record_snapshots_projected_rows_for_downstream_tables(tmp_path: Path) -> None:
    """Keep the projected table snapshot for multiple downstream reads."""
    input_path = tmp_path / "input.csv"
    input_path.write_text("key,value,ignored\nB,2,drop\nA,,drop\nB,2,drop\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "input",
            "relative_fpath": input_path.name,
            "reader": {"format": "csv"},
        }
    )
    sources = DataReader().read_data_files([data_file], folder_path=tmp_path)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "snapshot",
                    "source": "input",
                    "operations": [],
                    "columns": {"key": "key", "value": "value"},
                    "materialize": True,
                },
                {
                    "name": "only_b",
                    "source": "snapshot",
                    "operations": [
                        {"operation": "filter", "column": "key", "comparison": "equals", "value": "B"}
                    ],
                    "columns": {"key": "key", "value": "value"},
                },
                {
                    "name": "values_above_one",
                    "source": "snapshot",
                    "operations": [
                        {
                            "operation": "filter",
                            "column": "value",
                            "comparison": "greater_than",
                            "value": 1,
                        }
                    ],
                    "columns": {"key": "key", "value": "value"},
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(sources, mapping_path=mapping_path, backend=PolarsTabularBackend())
    input_path.write_text("key,value,ignored\nZ,99,changed\n", encoding="utf-8")

    expected_snapshot = [
        {"key": "B", "value": 2},
        {"key": "A", "value": None},
        {"key": "B", "value": 2},
    ]
    assert tables["snapshot"].data.collect_schema() == pl.Schema({"key": pl.String, "value": pl.Int64})
    assert list(tables["snapshot"].iter_rows()) == expected_snapshot
    assert list(tables["snapshot"].iter_rows()) == expected_snapshot
    assert list(tables["only_b"].iter_rows()) == [expected_snapshot[0], expected_snapshot[2]]
    assert list(tables["values_above_one"].iter_rows()) == [expected_snapshot[0], expected_snapshot[2]]


def test_materialization_occurs_after_final_column_projection(tmp_path: Path) -> None:
    """Do not evaluate a failing operation column removed by the final projection."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"discarded": ["not-an-integer"], "kept": [7]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "projected",
                    "source": "input",
                    "operations": [{"operation": "cast", "column": "discarded", "dtype": "int64"}],
                    "columns": {"value": "kept"},
                    "materialize": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert tables["projected"].fields() == ["value"]
    assert tables["projected"].data.collect_schema() == pl.Schema({"value": pl.Int64})
    assert list(tables["projected"].iter_rows()) == [{"value": 7}]


@pytest.mark.parametrize("materialize", [False, True], ids=["lazy-by-default", "error-at-boundary"])
def test_materialization_controls_when_deferred_polars_errors_surface(
    tmp_path: Path, materialize: bool
) -> None:
    """Keep lazy errors deferred by default and raise them at opted-in boundaries."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"value": ["1", "bad"]}).lazy(), backend)
    record: dict[str, object] = {
        "name": "cast_values",
        "source": "input",
        "operations": [{"operation": "cast", "column": "value", "dtype": "int64"}],
        "columns": {"value": "value"},
    }
    if materialize:
        record["materialize"] = True
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(json.dumps([record]), encoding="utf-8")

    if materialize:
        with pytest.raises(pl.exceptions.InvalidOperationError):
            r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)
    else:
        tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)
        with pytest.raises(pl.exceptions.InvalidOperationError):
            list(tables["cast_values"].iter_rows())


@pytest.mark.parametrize(
    ("availability", "absent_inputs"),
    [
        pytest.param(
            SourceAvailability.PRESENT, frozenset({"upstream_optional"}), id="present-empty-with-provenance"
        ),
        pytest.param(SourceAvailability.ABSENT, frozenset({"optional_input"}), id="absent"),
    ],
)
def test_materialization_preserves_empty_and_absent_source_metadata(
    tmp_path: Path, availability: SourceAvailability, absent_inputs: frozenset[str]
) -> None:
    """Retain the availability and missing-input facts when snapshotting empty schemas."""
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(schema={"value": pl.Int64}).lazy(),
        backend,
        availability=availability,
        absent_inputs=absent_inputs,
    )
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "snapshot",
                    "source": "input",
                    "operations": [],
                    "columns": {"renamed": "value"},
                    "materialize": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)

    assert tables["snapshot"].availability is availability
    assert tables["snapshot"].absent_inputs == absent_inputs
    assert tables["snapshot"].fields() == ["renamed"]
    assert tables["snapshot"].data.collect_schema() == pl.Schema({"renamed": pl.Int64})
    assert list(tables["snapshot"].iter_rows()) == []


def test_initial_table_remains_the_seeded_materialized_record(tmp_path: Path) -> None:
    """Reuse preassembled records without evaluating operations or materialization."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"value": [1]}).lazy(), backend)
    seeded = TabularSource(pl.DataFrame({"value": [2, 2]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {
                    "name": "output",
                    "source": "input",
                    "operations": [
                        {"operation": "filter", "column": "value", "comparison": "equals", "value": 99}
                    ],
                    "columns": {"value": "value"},
                    "materialize": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source}, mapping_path=mapping_path, backend=backend, initial_tables={"output": seeded}
    )

    assert tables["output"] is seeded
    assert list(tables["output"].iter_rows()) == [{"value": 2}, {"value": 2}]


def test_unselected_materialized_records_remain_unevaluated(tmp_path: Path) -> None:
    """Apply opt-in materialization only to records included in the selected closure."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"label": ["selected"], "value": ["not-an-int"]}).lazy(), backend)
    mapping_path = tmp_path / "table_mapping.json"
    mapping_path.write_text(
        json.dumps(
            [
                {"name": "selected", "source": "input", "operations": [], "columns": {"label": "label"}},
                {
                    "name": "not_selected",
                    "source": "input",
                    "operations": [{"operation": "cast", "column": "value", "dtype": "int64"}],
                    "columns": {"value": "value"},
                    "materialize": True,
                },
            ]
        ),
        encoding="utf-8",
    )

    tables = r2x_core.assemble_tables(
        {"input": source}, mapping_path=mapping_path, backend=backend, table_names=["selected"]
    )

    assert set(tables) == {"selected"}
    assert list(tables["selected"].iter_rows()) == [{"label": "selected"}]


@pytest.mark.parametrize("value", [1, "true", None], ids=["integer", "text", "null"])
def test_materialize_mapping_field_requires_a_strict_boolean(tmp_path: Path, value: object) -> None:
    """Reject coerced and explicit-null materialize declarations at the public boundary."""
    with pytest.raises(ValidationError):
        assemble_mapping(
            tmp_path,
            json.dumps(
                [
                    {
                        "name": "output",
                        "source": "input",
                        "operations": [],
                        "materialize": value,
                    }
                ]
            ),
        )
