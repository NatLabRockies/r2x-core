"""Public preflight contracts for interleaved file and table assembly."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from pydantic import TypeAdapter, ValidationError
from rust_ok import Err

from r2x_core import (
    DataFile,
    DataReader,
    DecodedSources,
    DocumentSource,
    PluginConfig,
    ReaderConfig,
    TabularSource,
    assemble_tables,
    build_system,
    build_system_from_sources,
)
from r2x_core.models import ComponentInstruction, MappingStep
from r2x_core.polars_adapter import PolarsTabularBackend, PolarsTabularFileReader
from r2x_core.tabular_backend import apply_mapping_steps


def write_mapping(folder: Path, records: list[dict[str, object]]) -> Path:
    """Write a real table mapping for a public assembly call."""
    path = folder / "mapping.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def seed_table() -> TabularSource:
    """Create a typed, nonempty source for validation-only cases."""
    backend = PolarsTabularBackend()
    return TabularSource(pl.DataFrame({"id": [1]}).lazy(), backend)


pytestmark = pytest.mark.ingestion


@pytest.mark.parametrize(
    ("files", "records", "expected"),
    [
        pytest.param(
            [DataFile(name="same", relative_fpath="missing.csv")] * 2,
            [],
            "Duplicate named source",
            id="duplicate-files",
        ),
        pytest.param(
            [DataFile(name="input", relative_fpath="missing.csv")],
            [
                {"name": "same", "source": "input", "operations": []},
                {"name": "same", "source": "input", "operations": []},
            ],
            "Duplicate table name",
            id="duplicate-tables",
        ),
        pytest.param(
            [DataFile(name="same", relative_fpath="missing.csv")],
            [{"name": "same", "source": "missing", "operations": []}],
            "File and table mappings declare the same name",
            id="file-table-collision",
        ),
        pytest.param(
            [DataFile(name="first", source="second"), DataFile(name="second", relative_fpath="missing.csv")],
            [],
            "before it is declared",
            id="forward-file-reference",
        ),
        pytest.param(
            [DataFile(name="input", relative_fpath="missing.csv")],
            [
                {"name": "first", "source": "second", "operations": []},
                {"name": "second", "source": "input", "operations": []},
            ],
            "before it is declared",
            id="forward-table-reference",
        ),
        pytest.param(
            [DataFile(name="first", source="first")],
            [],
            "before it is declared",
            id="file-self-reference",
        ),
    ],
)
def test_assembly_rejects_ambiguous_or_forward_declarations_before_input_io(
    tmp_path: Path, files: list[DataFile], records: list[dict[str, object]], expected: str
) -> None:
    """Invalid graph declarations win over the missing physical input error."""
    mapping_path = write_mapping(tmp_path, records)

    with pytest.raises(ValueError, match=expected):
        DataReader().read_and_assemble_sources(
            files, folder_path=tmp_path, mapping_path=mapping_path, backend=PolarsTabularBackend()
        )


@pytest.mark.parametrize(
    ("source_name", "table_names", "expected"),
    [
        pytest.param("input", [], "Initial source collides with a configured file", id="input-source"),
        pytest.param("output", [], "Initial source collides with a table output", id="output-source"),
        pytest.param("output", ["output"], "Initial source and table names collide", id="seed-collision"),
    ],
)
def test_assembly_rejects_seeded_source_collisions_before_input_io(
    tmp_path: Path, source_name: str, table_names: list[str], expected: str
) -> None:
    """Explicit sources cannot shadow configured files or table output names."""
    mapping_path = write_mapping(tmp_path, [{"name": "output", "source": "input", "operations": []}])
    seed = seed_table()

    with pytest.raises(ValueError, match=expected):
        DataReader().read_and_assemble_sources(
            [DataFile(name="input", relative_fpath="missing.csv")],
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_sources={source_name: seed},
            initial_tables=dict.fromkeys(table_names, seed),
        )


def test_assembly_rejects_an_initial_table_not_declared_in_the_mapping(tmp_path: Path) -> None:
    """An initial table cannot add an undeclared graph output."""
    mapping_path = write_mapping(tmp_path, [])

    with pytest.raises(ValueError, match="Initial tables are not declared"):
        DataReader().read_and_assemble_sources(
            [DataFile(name="input", relative_fpath="missing.csv")],
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables={"undeclared": seed_table()},
        )


def test_assembly_rejects_an_empty_initial_table_name(tmp_path: Path) -> None:
    """Initial output names must be nonempty, even without file dependencies."""
    mapping_path = write_mapping(tmp_path, [])

    with pytest.raises(TypeError, match="Initial tables must be named"):
        DataReader().read_and_assemble_sources(
            [],
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables={"": seed_table()},
        )


@pytest.mark.parametrize(
    ("operations", "message"),
    [
        pytest.param(
            [],
            "must start with a rows, concat, first_present, or first_nonempty constructor",
            id="missing-constructor",
        ),
        pytest.param(
            [
                {"operation": "rows", "schema": [{"name": "id", "dtype": "int64"}], "values": []},
                {"operation": "rows", "schema": [{"name": "id", "dtype": "int64"}], "values": []},
            ],
            "may contain only one constructor",
            id="two-constructors",
        ),
        pytest.param(
            [{"operation": "first_present", "sources": ["input", "input"]}],
            "first_present sources must be unique",
            id="duplicate-first-present-candidate",
        ),
    ],
)
def test_source_free_table_requires_one_constructor(
    tmp_path: Path, operations: list[dict[str, object]], message: str
) -> None:
    """Source-free tables need exactly one first-position constructor."""
    mapping_path = write_mapping(tmp_path, [{"name": "output", "operations": operations}])

    with pytest.raises(ValidationError, match=message):
        assemble_tables({}, mapping_path=mapping_path, backend=PolarsTabularBackend())


def test_declared_table_source_names_must_not_be_empty(tmp_path: Path) -> None:
    """A scheduler cannot declare an empty source name for mapping validation."""
    mapping_path = write_mapping(tmp_path, [])

    with pytest.raises(ValueError, match="Declared source names must be non-empty"):
        assemble_tables(
            {}, mapping_path=mapping_path, backend=PolarsTabularBackend(), declared_source_names=[""]
        )


def test_absent_source_names_must_be_nonempty(tmp_path: Path) -> None:
    """Explicit omission metadata requires exact, non-empty source names."""
    mapping_path = write_mapping(tmp_path, [])

    with pytest.raises(ValueError, match="Absent source names must be non-empty strings"):
        assemble_tables(
            {},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            absent_source_names=[""],
        )


def test_present_source_cannot_also_be_declared_absent(tmp_path: Path) -> None:
    """The omission metadata cannot contradict a decoded present source."""
    mapping_path = write_mapping(tmp_path, [{"name": "output", "source": "input", "operations": []}])

    with pytest.raises(ValueError, match="Absent source names cannot also identify decoded values"):
        assemble_tables(
            {"input": seed_table()},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            absent_source_names=["input"],
        )


@pytest.mark.parametrize("operation", ["first_present", "first_nonempty"])
def test_selection_rejects_null_decoded_candidate_without_using_fallback(
    tmp_path: Path, operation: str
) -> None:
    """An invalid decoded value is not equivalent to an omitted source."""
    if operation == "first_present":
        selection = {"operation": operation, "sources": ["candidate", "fallback"]}
    else:
        selection = {"operation": operation, "sources": ["candidate"], "fallback": "fallback"}
    mapping_path = write_mapping(
        tmp_path,
        [{"name": "selected", "operations": [selection]}],
    )

    with pytest.raises(ValueError, match="source 'candidate' is not available"):
        assemble_tables(
            {"candidate": None, "fallback": seed_table()},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
        )


def test_absent_source_name_cannot_collide_with_a_table_output(tmp_path: Path) -> None:
    """A physical omission name cannot also identify an output constructed by this mapping."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "candidate",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "id", "dtype": "int64"}], "values": []}
                ],
            },
            {
                "name": "selected",
                "operations": [{"operation": "first_present", "sources": ["candidate"]}],
            },
        ],
    )

    with pytest.raises(
        ValueError, match="Absent source names cannot also identify decoded values or table outputs"
    ):
        assemble_tables(
            {},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            absent_source_names=["candidate"],
        )


def test_preassembled_tables_require_nonempty_names(tmp_path: Path) -> None:
    """The table-only API rejects an unnamed preassembled value."""
    mapping_path = write_mapping(tmp_path, [])

    with pytest.raises(TypeError, match="Initial tables must use non-empty string names"):
        assemble_tables(
            {}, mapping_path=mapping_path, backend=PolarsTabularBackend(), initial_tables={"": seed_table()}
        )


@pytest.mark.parametrize(
    ("table_names", "expected"),
    [
        pytest.param([], "one or more non-empty names", id="empty-selection"),
        pytest.param([""], "one or more non-empty names", id="empty-name"),
        pytest.param(["output", "output"], "table_names must be unique", id="duplicate-selection"),
        pytest.param(["missing"], "Unknown table output", id="unknown-output"),
    ],
)
def test_selected_table_names_are_validated(tmp_path: Path, table_names: list[str], expected: str) -> None:
    """A selection identifies distinct, declared outputs rather than a silent empty result."""
    mapping_path = write_mapping(tmp_path, [{"name": "output", "source": "input", "operations": []}])

    with pytest.raises(ValueError, match=expected):
        assemble_tables(
            {"input": seed_table()},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            table_names=table_names,
        )


@pytest.mark.parametrize(
    ("initial_sources", "initial_tables", "expected"),
    [
        pytest.param(["output"], [], "Table name collides with an input source", id="input-table"),
        pytest.param(["output"], ["output"], "Initial table collides with an input source", id="input-seed"),
    ],
)
def test_table_assembly_rejects_output_name_collisions(
    tmp_path: Path, initial_sources: list[str], initial_tables: list[str], expected: str
) -> None:
    """Table assembly cannot overwrite an input or an explicitly supplied table."""
    mapping_path = write_mapping(tmp_path, [{"name": "output", "source": "input", "operations": []}])
    seed = seed_table()

    with pytest.raises(ValueError, match=expected):
        assemble_tables(
            dict.fromkeys(["input", *initial_sources], seed),
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables=dict.fromkeys(initial_tables, seed),
        )


@pytest.mark.parametrize("upstream_is_table", [False, True], ids=["input-source", "upstream-table"])
def test_selected_preassembled_table_is_reused_without_computing_its_dependencies(
    tmp_path: Path, upstream_is_table: bool
) -> None:
    """A declared seeded table supplies its rows directly, even when its mapping filters them out."""
    records: list[dict[str, object]] = []
    if upstream_is_table:
        records.append({"name": "upstream", "source": "input", "operations": []})
    records.append(
        {
            "name": "seeded",
            "source": "upstream" if upstream_is_table else "input",
            "operations": [{"operation": "filter", "column": "id", "comparison": "equals", "value": 99}],
        }
    )
    mapping_path = write_mapping(tmp_path, records)
    seeded = seed_table()

    sources = assemble_tables(
        {"input": seed_table()},
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
        initial_tables={"seeded": seeded},
        table_names=["seeded"],
    )

    assert list(sources) == ["seeded"]
    assert sources["seeded"] is seeded
    assert list(sources["seeded"].iter_rows()) == [{"id": 1}]


def test_seeded_table_accepts_a_declared_but_not_yet_decoded_dependency(tmp_path: Path) -> None:
    """A seed can reuse its output before another declared file source is decoded."""
    mapping_path = write_mapping(tmp_path, [{"name": "seeded", "source": "later_file", "operations": []}])
    seeded = seed_table()

    sources = assemble_tables(
        {},
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
        initial_tables={"seeded": seeded},
        declared_source_names=["later_file"],
    )

    assert sources["seeded"] is seeded
    assert list(sources["seeded"].iter_rows()) == [{"id": 1}]


def test_seeded_table_feeds_a_later_table_without_recomputation(tmp_path: Path) -> None:
    """A declared seed satisfies a later table dependency without a scheduler cycle."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {"name": "seeded", "source": "input", "operations": []},
            {"name": "output", "source": "seeded", "operations": []},
        ],
    )
    seed = seed_table()
    preassembled = seed_table()

    sources = DataReader().read_and_assemble_sources(
        [],
        folder_path=tmp_path,
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
        initial_sources={"input": seed},
        initial_tables={"seeded": preassembled},
    )

    assert sources["seeded"] is preassembled
    assert list(sources["output"].iter_rows()) == [{"id": 1}]


def test_seeded_table_does_not_allow_forward_reference_in_scheduler(tmp_path: Path) -> None:
    """The scheduler validates declaration order even when a table output is seeded."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {"name": "seeded", "source": "later", "operations": []},
            {"name": "later", "source": "input", "operations": []},
        ],
    )

    with pytest.raises(ValueError, match="before it is declared"):
        DataReader().read_and_assemble_sources(
            [],
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_sources={"input": seed_table()},
            initial_tables={"seeded": seed_table()},
        )


@pytest.mark.parametrize(
    ("binding", "fallback"),
    [
        pytest.param(None, "fallback", id="null"),
        pytest.param(True, False, id="boolean"),
        pytest.param(1.5, 2.5, id="float"),
        pytest.param("chosen", "fallback", id="string"),
    ],
)
def test_choose_resolves_typed_scalar_bindings(
    tmp_path: Path, binding: str | float | bool | None, fallback: str | float | bool
) -> None:
    """Whole-value bindings preserve their native scalar type and null semantics."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [
                    {
                        "operation": "choose",
                        "column": "id",
                        "comparison": "equals",
                        "value": 1,
                        "then": {"value": "{chosen}"},
                        "otherwise": {"value": fallback},
                        "output": "result",
                    }
                ],
            }
        ],
    )
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"id": [1, 2]}).lazy(), backend)

    result = assemble_tables(
        {"input": source}, mapping_path=mapping_path, backend=backend, placeholders={"chosen": binding}
    )["output"]

    assert list(result.iter_rows()) == [{"id": 1, "result": binding}, {"id": 2, "result": fallback}]


def test_choose_rejects_partial_scalar_placeholder_interpolation(tmp_path: Path) -> None:
    """A scalar binding names a whole value, not a template embedded in text."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [
                    {
                        "operation": "choose",
                        "column": "id",
                        "comparison": "equals",
                        "value": 1,
                        "then": {"value": "prefix-{chosen}"},
                        "otherwise": {"value": "fallback"},
                        "output": "result",
                    }
                ],
            }
        ],
    )

    with pytest.raises(ValueError, match="Partial table-mapping placeholder interpolation"):
        assemble_tables(
            {"input": seed_table()},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            placeholders={"chosen": "value"},
        )


def test_rows_constructor_rejects_an_unresolved_placeholder(tmp_path: Path) -> None:
    """A rows binding must be supplied before the table can be constructed."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "id", "dtype": "int64"}], "values": "{rows}"}
                ],
            }
        ],
    )

    with pytest.raises(ValueError, match="placeholder 'rows' is unresolved"):
        assemble_tables({}, mapping_path=mapping_path, backend=PolarsTabularBackend())


def test_fill_null_resolves_a_list_binding_as_one_typed_value(tmp_path: Path) -> None:
    """A list binding fills missing list-valued cells without flattening rows."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [{"operation": "fill_null", "columns": ["values"], "value": "{defaults}"}],
            }
        ],
    )
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"values": [None, [3]]}, schema={"values": pl.List(pl.Int64)}).lazy(), backend
    )

    result = assemble_tables(
        {"input": source}, mapping_path=mapping_path, backend=backend, placeholders={"defaults": [1, 2]}
    )["output"]

    assert list(result.iter_rows()) == [{"values": [1, 2]}, {"values": [3]}]


def test_table_backend_rejects_a_nonstring_column_operand() -> None:
    """Direct backend calls cannot supply a scalar where a column name is required."""
    backend = PolarsTabularBackend()

    with pytest.raises(TypeError, match="choose column operand must name a string column"):
        backend.choose_column(
            seed_table(),
            column="id",
            comparison="equals",
            value=1,
            other_column=None,
            then=("column", 2),
            otherwise=("value", 0),
            output="result",
        )


def test_table_backend_rejects_a_nonlazy_polars_source(tmp_path: Path) -> None:
    """A table mapping reports a representation mismatch rather than silently converting it."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [{"operation": "sort", "columns": ["id"]}],
            }
        ],
    )
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"id": [1]}), backend)

    with pytest.raises(TypeError, match="requires Polars LazyFrame sources"):
        assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_filter_rejects_a_scalar_comparison_against_a_list_column(tmp_path: Path) -> None:
    """A list-valued field is not implicitly coerced into a scalar filter value."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [
                    {"operation": "filter", "column": "items", "comparison": "equals", "value": 1}
                ],
            }
        ],
    )
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"items": [[1]]}).lazy(), backend)

    with pytest.raises(ValueError, match="incompatible with column"):
        assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)


def test_fill_null_preserves_existing_strings(tmp_path: Path) -> None:
    """A string default only fills missing string values."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [{"operation": "fill_null", "columns": ["name"], "value": "fallback"}],
            }
        ],
    )
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"name": [None, "existing"]}, schema={"name": pl.String}).lazy(), backend
    )

    result = assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)["output"]

    assert list(result.iter_rows()) == [{"name": "fallback"}, {"name": "existing"}]


@pytest.mark.parametrize(
    ("step", "message"),
    [
        pytest.param(
            {"op": "concat", "sources": ["missing"]}, "concat sources were not provided", id="concat"
        ),
        pytest.param(
            {
                "op": "match_source_patterns",
                "column": "name",
                "source": "missing",
                "pattern_column": "pattern",
                "range_separator": "*",
                "prefix_separator": "_",
                "precedence": ["exact", "range", "prefix"],
                "prefix_policy": "longest",
                "duplicate_policy": "first",
                "unmatched": "keep",
            },
            "match_source_patterns source 'missing' was not provided",
            id="match-source-patterns",
        ),
    ],
)
def test_mapping_step_backend_reports_a_missing_named_source(step: dict[str, object], message: str) -> None:
    """A direct mapping-step caller receives an error value for missing source frames."""
    steps = TypeAdapter(list[MappingStep]).validate_python([step])

    result = apply_mapping_steps(pl.LazyFrame({"name": ["wind"]}), steps, backend=PolarsTabularBackend())

    assert isinstance(result, Err)
    assert message in str(result.err())


def test_mapping_step_join_without_keys_reports_a_backend_error() -> None:
    """The direct step API preserves the backend's missing-key diagnostic."""
    steps = TypeAdapter(list[MappingStep]).validate_python(
        [{"op": "join", "source": "other", "how": "inner"}]
    )
    frame = pl.LazyFrame({"id": [1]})

    result = apply_mapping_steps(frame, steps, backend=PolarsTabularBackend(), source_frames={"other": frame})

    assert isinstance(result, Err)
    assert "must specify `on`" in str(result.err())


def test_unpivot_rejects_a_table_with_no_value_columns(tmp_path: Path) -> None:
    """Omitting the value map still requires a column outside the index."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [
                    {"operation": "unpivot", "index": ["id"], "variable_name": "kind", "value_name": "value"}
                ],
            }
        ],
    )

    with pytest.raises(ValueError, match="unpivot requires at least one value column"):
        assemble_tables({"input": seed_table()}, mapping_path=mapping_path, backend=PolarsTabularBackend())


def test_unpivot_preserves_a_user_column_named_like_its_temporary_field(tmp_path: Path) -> None:
    """Internal-looking user fields remain literal input columns during unpivot."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [
                    {
                        "operation": "unpivot",
                        "index": ["id", "__r2x_unpivot_source_name__"],
                        "columns": {"chosen": "value"},
                        "variable_name": "kind",
                        "value_name": "amount",
                    }
                ],
            }
        ],
    )
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"id": [1], "__r2x_unpivot_source_name__": ["kept"], "value": [5]}).lazy(), backend
    )

    result = assemble_tables({"input": source}, mapping_path=mapping_path, backend=backend)["output"]

    assert list(result.iter_rows()) == [
        {"id": 1, "__r2x_unpivot_source_name__": "kept", "kind": "chosen", "amount": 5}
    ]


@pytest.mark.parametrize("invalid_side", ["input", "patterns"])
def test_pattern_matching_requires_string_keys(tmp_path: Path, invalid_side: str) -> None:
    """Numeric match keys do not undergo implicit text coercion."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [
                    {
                        "operation": "match_source_patterns",
                        "column": "technology",
                        "source": "patterns",
                        "pattern_column": "pattern",
                        "range_separator": "*",
                        "prefix_separator": "_",
                        "precedence": ["exact", "range", "prefix"],
                        "prefix_policy": "longest",
                        "duplicate_policy": "first",
                        "unmatched": "keep",
                    }
                ],
            }
        ],
    )
    backend = PolarsTabularBackend()
    input_value: int | str = 1 if invalid_side == "input" else "wind"
    pattern_value: int | str = 1 if invalid_side == "patterns" else "wind"
    sources = {
        "input": TabularSource(pl.DataFrame({"technology": [input_value]}).lazy(), backend),
        "patterns": TabularSource(pl.DataFrame({"pattern": [pattern_value], "flag": [True]}).lazy(), backend),
    }

    with pytest.raises(ValueError, match="must have a string dtype"):
        assemble_tables(sources, mapping_path=mapping_path, backend=backend)


def test_pattern_match_preserves_a_user_column_named_like_a_temporary_field(tmp_path: Path) -> None:
    """A literal input name resembling an internal match index is never overwritten."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [
                    {
                        "operation": "match_source_patterns",
                        "column": "technology",
                        "source": "patterns",
                        "pattern_column": "pattern",
                        "range_separator": "*",
                        "prefix_separator": "_",
                        "precedence": ["exact", "range", "prefix"],
                        "prefix_policy": "longest",
                        "duplicate_policy": "first",
                        "unmatched": "keep",
                    }
                ],
            }
        ],
    )
    backend = PolarsTabularBackend()
    sources = {
        "input": TabularSource(
            pl.DataFrame({"technology": ["wind"], "__r2x_match_patterns_left_index__": ["kept"]}).lazy(),
            backend,
        ),
        "patterns": TabularSource(pl.DataFrame({"pattern": ["wind"], "flag": [True]}).lazy(), backend),
    }

    result = assemble_tables(sources, mapping_path=mapping_path, backend=backend)["output"]

    assert list(result.iter_rows()) == [
        {"technology": "wind", "__r2x_match_patterns_left_index__": "kept", "flag": True}
    ]


def test_selected_table_assembly_returns_its_dependency_closure(tmp_path: Path) -> None:
    """Selecting a downstream output includes its earlier dependencies, not unrelated tables."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {"name": "first", "source": "input", "operations": []},
            {"name": "second", "source": "first", "operations": []},
            {"name": "unrelated", "source": "input", "operations": []},
        ],
    )

    sources = assemble_tables(
        {"input": seed_table()},
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
        table_names=["second"],
    )

    assert list(sources) == ["first", "second"]
    assert list(sources["second"].iter_rows()) == [{"id": 1}]


def test_assembly_uses_an_initial_source_for_a_derived_file(tmp_path: Path) -> None:
    """A seeded input can feed a derived file and then a named table."""
    mapping_path = write_mapping(tmp_path, [{"name": "output", "source": "derived", "operations": []}])
    seed = seed_table()

    sources = DataReader().read_and_assemble_sources(
        [DataFile(name="derived", source="seed")],
        folder_path=tmp_path,
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
        initial_sources={"seed": seed},
    )

    assert list(sources["output"].iter_rows()) == [{"id": 1}]


class NamespacedCSVReader(PolarsTabularFileReader):
    """Expose a real decoded CSV table under a named reader output."""

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        decoded = super().read_file(format_name, file_path=file_path, reader_config=reader_config)
        return {"item": decoded["data"]}


def test_component_construction_rejects_a_missing_field_in_one_document_row() -> None:
    """A field present in another row does not excuse a missing required row value."""
    source = DocumentSource(
        [{"name": "first", "number": 1, "base_kv": 230.0}, {"name": "second", "base_kv": 115.0}],
        None,
    )
    instruction = ComponentInstruction(
        kind="component",
        source="buses",
        component_type="PSSEBus",
        fields={"name": "name", "number": "number", "base_kv": "base_kv"},
    )

    with pytest.raises(ValueError, match="Source record has no field 'number'"):
        build_system_from_sources(
            {"buses": source},
            config=PluginConfig(models=("fixtures.ingestion_models",)),
            instructions=[instruction],
            name="test",
        )


def test_build_system_rejects_a_table_backend_without_a_mapping(tmp_path: Path) -> None:
    """A table backend is only meaningful when table assembly was explicitly configured."""
    with pytest.raises(ValueError, match="table_mapping_backend requires table_mapping_path"):
        build_system(
            PluginConfig(config_path_override=tmp_path),
            name="test",
            input_folder=tmp_path,
            table_mapping_backend=PolarsTabularBackend(),
        )


def test_build_system_accepts_an_explicit_table_backend(tmp_path: Path) -> None:
    """The public builder can execute an empty mapping with a supplied backend."""
    (tmp_path / "file_mapping.json").write_text("[]", encoding="utf-8")
    (tmp_path / "parser_rules.json").write_text("[]", encoding="utf-8")
    mapping_path = write_mapping(tmp_path, [])

    system = build_system(
        PluginConfig(config_path_override=tmp_path),
        name="test",
        input_folder=tmp_path,
        table_mapping_path=mapping_path,
        table_mapping_backend=PolarsTabularBackend(),
    )

    assert system.name == "test"


def test_initial_sources_are_not_treated_as_qualified_reader_namespaces(tmp_path: Path) -> None:
    """Reject unknown dotted seed references before opening unrelated physical files."""
    mapping_path = write_mapping(tmp_path, [])
    files = [
        DataFile(name="missing_input", relative_fpath="missing.csv"),
        DataFile(name="derived", source="seed.nonexistent"),
    ]

    with pytest.raises(ValueError, match=r"Unknown source 'seed\.nonexistent'"):
        DataReader().read_and_assemble_sources(
            files,
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_sources={"seed": seed_table()},
        )


class TwoTableCSVReader(PolarsTabularFileReader):
    """Expose two named tables from one real CSV decode."""

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        decoded = super().read_file(format_name, file_path=file_path, reader_config=reader_config)
        return {"first": decoded["data"], "second": decoded["data"]}


def test_native_column_declarations_require_one_reader_output(tmp_path: Path) -> None:
    """A single physical schema cannot ambiguously describe multiple named tables."""
    (tmp_path / "catalog.csv").write_text("id\n7\n", encoding="utf-8")
    data_file = DataFile.model_validate(
        {
            "name": "catalog",
            "relative_fpath": "catalog.csv",
            "columns": [{"name": "id", "dtype": "int64"}],
        }
    )

    with pytest.raises(ValueError, match="column declarations require one tabular source"):
        DataReader(file_readers={"csv": TwoTableCSVReader()}).read_data_files(
            [data_file], folder_path=tmp_path
        )


@pytest.mark.parametrize("operation", ["first_present", "first_nonempty"])
@pytest.mark.parametrize(
    ("candidate_name", "expected_error"),
    [
        pytest.param(
            "catalog.missing", r"Unknown table source 'catalog\.missing'", id="missing-qualified-output"
        ),
        pytest.param("catalog", "Unknown table source 'catalog'", id="present-file-missing-exact-output"),
    ],
)
def test_table_selectors_reject_missing_outputs_from_a_present_namespaced_file(
    tmp_path: Path, operation: str, candidate_name: str, expected_error: str
) -> None:
    """Only a missing optional file, not a present reader with different outputs, is skippable."""
    (tmp_path / "catalog.csv").write_text("id\n7\n", encoding="utf-8")
    fallback = {
        "name": "fallback",
        "operations": [
            {"operation": "rows", "schema": [{"name": "id", "dtype": "int64"}], "values": [{"id": 99}]}
        ],
    }
    selection = {"operation": operation, "sources": [candidate_name]}
    if operation == "first_present":
        selection["sources"].append("fallback")
    else:
        selection["fallback"] = "fallback"
    selected = {"name": "selected", "operations": [selection]}
    mapping_path = write_mapping(tmp_path, [fallback, selected])

    with pytest.raises(ValueError, match=expected_error):
        DataReader(file_readers={"csv": NamespacedCSVReader()}).read_and_assemble_sources(
            [DataFile(name="catalog", relative_fpath="catalog.csv")],
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
        )


@pytest.mark.parametrize("operation", ["first_present", "first_nonempty"])
def test_selection_accepts_an_actual_qualified_reader_output(tmp_path: Path, operation: str) -> None:
    """Selection accepts the exact table name emitted by a namespaced reader."""
    (tmp_path / "catalog.csv").write_text("id\n7\n", encoding="utf-8")
    if operation == "first_present":
        selection: dict[str, object] = {
            "operation": operation,
            "sources": ["catalog.item", "fallback"],
        }
    else:
        selection = {"operation": operation, "sources": ["catalog.item"], "fallback": "fallback"}
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "fallback",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "id", "dtype": "int64"}], "values": []}
                ],
            },
            {"name": "selected", "operations": [selection]},
        ],
    )

    sources = DataReader(file_readers={"csv": NamespacedCSVReader()}).read_and_assemble_sources(
        [DataFile(name="catalog", relative_fpath="catalog.csv")],
        folder_path=tmp_path,
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
    )

    assert sources["selected"] is sources["catalog.item"]
    assert list(sources["selected"].iter_rows()) == [{"id": 7}]


@pytest.mark.parametrize("mode", ["first_present", "first_nonempty"])
def test_namespaced_reader_declaration_is_not_an_exact_selector_after_a_table_batch(
    tmp_path: Path, mode: str
) -> None:
    """A present multi-output reader does not declare its unqualified file name as a source."""
    (tmp_path / "catalog.csv").write_text("id\n7\n", encoding="utf-8")
    mapping_path = write_mapping(
        tmp_path,
        [{"name": "gate", "source": "catalog.item", "operations": []}],
    )
    selected = DataFile.model_validate(
        {
            "name": "selected",
            "source_selection": {
                "mode": mode,
                "sources": ["catalog", "gate"],
                "empty_fallback": {"schema": {"id": "int64"}, "rows": []},
            },
        }
    )

    with pytest.raises(ValueError, match=r"references source 'catalog' before it is declared"):
        DataReader(file_readers={"csv": NamespacedCSVReader()}).read_and_assemble_sources(
            [DataFile(name="catalog", relative_fpath="catalog.csv"), selected],
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
        )


def test_table_dependency_can_reference_a_qualified_reader_output(tmp_path: Path) -> None:
    """A named output from a real file is available to a later table record."""
    (tmp_path / "catalog.csv").write_text("id\n7\n", encoding="utf-8")
    mapping_path = write_mapping(tmp_path, [{"name": "output", "source": "catalog.item", "operations": []}])

    sources = DataReader(file_readers={"csv": NamespacedCSVReader()}).read_and_assemble_sources(
        [DataFile(name="catalog", relative_fpath="catalog.csv")],
        folder_path=tmp_path,
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
    )

    assert list(sources["output"].iter_rows()) == [{"id": 7}]


def test_derived_file_can_reference_a_qualified_reader_output(tmp_path: Path) -> None:
    """A physical multi-output reader may feed a later file through its qualified name."""
    (tmp_path / "catalog.csv").write_text("id\n7\n", encoding="utf-8")
    mapping_path = write_mapping(tmp_path, [])
    files = [
        DataFile(name="catalog", relative_fpath="catalog.csv"),
        DataFile(name="copy", source="catalog.item"),
    ]

    sources = DataReader(file_readers={"csv": NamespacedCSVReader()}).read_and_assemble_sources(
        files,
        folder_path=tmp_path,
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
    )

    assert list(sources["copy"].iter_rows()) == [{"id": 7}]


def test_source_selection_rejects_a_missing_qualified_reader_output(tmp_path: Path) -> None:
    """A reader namespace prefix does not make an undeclared output selectable."""
    (tmp_path / "catalog.csv").write_text("id\n7\n", encoding="utf-8")
    mapping_path = write_mapping(tmp_path, [])
    files = [
        DataFile(name="catalog", relative_fpath="catalog.csv"),
        DataFile.model_validate(
            {
                "name": "selected",
                "source_selection": {
                    "mode": "first_present",
                    "sources": ["catalog.missing"],
                    "empty_fallback": {"schema": {"id": "int64"}, "rows": []},
                },
            }
        ),
    ]

    with pytest.raises(ValueError, match=r"Source selection candidates must be declared.*catalog\.missing"):
        DataReader(file_readers={"csv": NamespacedCSVReader()}).read_and_assemble_sources(
            files,
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
        )


def test_qualified_reader_outputs_cannot_shadow_table_outputs(tmp_path: Path) -> None:
    """The scheduler rejects collisions discovered only after decoding a real input."""
    (tmp_path / "catalog.csv").write_text("id\n7\n", encoding="utf-8")
    mapping_path = write_mapping(tmp_path, [{"name": "catalog.item", "source": "catalog", "operations": []}])

    with pytest.raises(ValueError, match="File source collides with a table output"):
        DataReader(file_readers={"csv": NamespacedCSVReader()}).read_and_assemble_sources(
            [DataFile(name="catalog", relative_fpath="catalog.csv")],
            folder_path=tmp_path,
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
        )


@pytest.mark.parametrize("operation", ["first_present", "first_nonempty"])
def test_seeded_selector_accepts_an_explicitly_absent_optional_candidate(
    tmp_path: Path, operation: str
) -> None:
    """An absent optional candidate remains skippable when a selector output is seeded."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "selected",
                "operations": [{"operation": operation, "sources": ["missing", "input"]}],
            }
        ],
    )
    seeded = seed_table()

    outputs = assemble_tables(
        {"input": seeded},
        mapping_path=mapping_path,
        backend=PolarsTabularBackend(),
        initial_tables={"selected": seeded},
        declared_source_names=["missing"],
        absent_source_names=["missing"],
        table_names=["selected"],
    )

    assert outputs["selected"] is seeded


@pytest.mark.parametrize("operation", ["first_present", "first_nonempty"])
def test_seeded_selector_keeps_a_later_ordinary_absent_reference_required(
    tmp_path: Path, operation: str
) -> None:
    """A candidate reused by an ordinary operation remains a required dependency."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "selected",
                "operations": [
                    {"operation": operation, "sources": ["missing", "input"]},
                    {"operation": "join", "source": "missing", "how": "cross"},
                ],
            }
        ],
    )
    seeded = seed_table()

    with pytest.raises(ValueError, match="Unknown table source 'missing'"):
        assemble_tables(
            {"input": seeded},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables={"selected": seeded},
            declared_source_names=["missing"],
            absent_source_names=["missing"],
            table_names=["selected"],
        )


def test_seeded_table_still_rejects_a_forward_table_reference(tmp_path: Path) -> None:
    """Precomputed values do not excuse a declaration that references a later table."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {"name": "first", "source": "later", "operations": []},
            {"name": "later", "source": "input", "operations": []},
        ],
    )

    with pytest.raises(ValueError, match="before it is declared"):
        assemble_tables(
            {"input": seed_table()},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables={"first": seed_table()},
        )


@pytest.mark.parametrize(
    ("value", "dtype", "message"),
    [
        pytest.param(10**309, "float64", "incompatible with dtype", id="float-overflow"),
        pytest.param("2032-01-02T03:04:05+05:30", "datetime", "timezone-naive", id="timezone-aware"),
        pytest.param(False, "datetime", "incompatible with dtype", id="datetime-requires-text"),
    ],
)
def test_typed_projection_rejects_values_outside_its_scalar_contract(
    tmp_path: Path, value: object, dtype: str, message: str
) -> None:
    """Reject values that cannot safely inhabit the declared projection dtype."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {
                "name": "output",
                "source": "input",
                "operations": [],
                "columns": {"projected": {"value": value, "dtype": dtype}},
            }
        ],
    )

    with pytest.raises(ValidationError, match=message):
        assemble_tables({"input": seed_table()}, mapping_path=mapping_path, backend=PolarsTabularBackend())


def test_selected_seeded_table_validates_the_entire_seeded_dependency_chain(tmp_path: Path) -> None:
    """Reusing multiple outputs cannot hide an unknown dependency in an earlier seed."""
    mapping_path = write_mapping(
        tmp_path,
        [
            {"name": "first", "source": "missing", "operations": []},
            {"name": "second", "source": "first", "operations": []},
        ],
    )

    with pytest.raises(ValueError, match="Unknown table source 'missing'"):
        assemble_tables(
            {},
            mapping_path=mapping_path,
            backend=PolarsTabularBackend(),
            initial_tables={"first": seed_table(), "second": seed_table()},
            table_names=["second"],
        )
