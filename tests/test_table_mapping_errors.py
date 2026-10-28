"""Public table-mapping validation for ambiguous operations and bindings."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import polars as pl
import pytest
from pydantic import ValidationError

from r2x_core import DocumentSource, TableMappingRecord, TabularSource, assemble_tables
from r2x_core.polars_adapter import PolarsTabularBackend

pytestmark = pytest.mark.table_mapping


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        pytest.param(
            {"operation": "join", "source": "other", "how": "cross", "on": ["id"]},
            "cross joins must omit 'on'",
            id="cross-join-with-keys",
        ),
        pytest.param(
            {"operation": "join", "source": "other", "how": "left", "on": []},
            "left joins require non-empty 'on' keys",
            id="left-join-without-keys",
        ),
        pytest.param(
            {"operation": "join", "source": "other", "how": "inner", "on": ["id", "id"]},
            "join keys must be unique",
            id="duplicate-join-keys",
        ),
        pytest.param(
            {"operation": "join", "source": "other", "how": "left", "on": ["id"], "columns": ["v", "v"]},
            "join payload columns must be unique",
            id="duplicate-join-payload",
        ),
        pytest.param(
            {
                "operation": "choose",
                "column": "id",
                "comparison": "equals",
                "other_column": None,
                "then": "id",
                "otherwise": "id",
                "output": "result",
            },
            "choose 'other_column' must be omitted when unused, not null",
            id="choose-null-column",
        ),
        pytest.param(
            {
                "operation": "group_by",
                "columns": ["id", "id"],
                "aggregate": [{"operation": "sum", "column": "id", "output": "total"}],
            },
            "group_by columns must be unique",
            id="duplicate-group-keys",
        ),
        pytest.param(
            {
                "operation": "group_by",
                "columns": ["id"],
                "aggregate": [
                    {"operation": "sum", "column": "id", "output": "total"},
                    {"operation": "max", "column": "id", "output": "total"},
                ],
            },
            "group_by aggregate outputs must be unique",
            id="duplicate-aggregate-outputs",
        ),
        pytest.param(
            {
                "operation": "group_by",
                "columns": ["id"],
                "aggregate": [{"operation": "sum", "column": "id", "output": "id"}],
            },
            "group_by aggregate outputs cannot overlap key columns",
            id="aggregate-output-overlaps-key",
        ),
        pytest.param(
            {"operation": "unpivot", "index": ["id", "id"], "variable_name": "kind", "value_name": "value"},
            "unpivot index columns must be unique",
            id="duplicate-unpivot-index",
        ),
        pytest.param(
            {"operation": "unpivot", "index": ["id"], "variable_name": "id", "value_name": "value"},
            "unpivot output names must be distinct",
            id="unpivot-output-overlaps-index",
        ),
        pytest.param(
            {
                "operation": "unpivot",
                "index": [],
                "columns": {"first": "id", "second": "id"},
                "variable_name": "kind",
                "value_name": "value",
            },
            "unpivot value columns must be unique",
            id="duplicate-unpivot-input",
        ),
        pytest.param(
            {"operation": "fill_null", "columns": ["id", "id"], "value": 0},
            "fill_null columns must be unique",
            id="duplicate-fill-targets",
        ),
        pytest.param(
            {"operation": "fill_null", "columns": ["id"], "from_columns": ["other", "other"]},
            "fill_null from_columns must be unique",
            id="duplicate-fill-backups",
        ),
        pytest.param(
            {"operation": "sort", "columns": ["id", "id"]},
            "sort columns must be unique",
            id="duplicate-sort-keys",
        ),
        pytest.param(
            {"operation": "unique", "columns": ["id", "id"], "keep": "first"},
            "unique columns must be unique",
            id="duplicate-unique-keys",
        ),
        pytest.param(
            {"operation": "list", "columns": ["id", "id"], "output": "result"},
            "list columns must be unique",
            id="duplicate-list-inputs",
        ),
        pytest.param(
            {"operation": "concat_strings", "columns": ["id", "id"], "output": "result"},
            "concat_strings columns must be unique",
            id="duplicate-string-inputs",
        ),
        pytest.param(
            {"operation": "concat", "sources": ["input", "input"]},
            "concat sources must be unique",
            id="duplicate-concat-sources",
        ),
        pytest.param(
            {
                "operation": "rows",
                "schema": [{"name": "id", "dtype": "int64"}] * 2,
                "values": [],
            },
            "rows schema names must be unique",
            id="duplicate-rows-schema",
        ),
    ],
)
def test_rejects_ambiguous_operation_configuration(
    tmp_path: Path, operation: dict[str, object], message: str
) -> None:
    """Reject conflicting declarations before executing any operations."""
    record: dict[str, object] = {"name": "out", "operations": [operation]}
    if operation["operation"] not in {"rows", "concat"}:
        record["source"] = "input"
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(json.dumps([record]), encoding="utf-8")

    with pytest.raises(ValidationError, match=re.escape(message)):
        assemble_tables({}, mapping_path=mapping, backend=PolarsTabularBackend())


@pytest.mark.parametrize(
    ("value", "message"),
    [
        pytest.param([1], "must resolve to a scalar", id="list-is-not-a-scalar"),
        pytest.param({"value": 1}, "must resolve to a scalar", id="object-is-not-a-scalar"),
        pytest.param(float("inf"), "must resolve to a finite number", id="nonfinite-scalar"),
    ],
)
def test_filter_binding_rejects_nonscalar_or_nonfinite_values(
    tmp_path: Path, value: object, message: str
) -> None:
    """A binary filter binding cannot be a structured or nonfinite value."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"id": [1]}).lazy(), backend)
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [
                        {"operation": "filter", "column": "id", "comparison": "equals", "value": "{selected}"}
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        assemble_tables(
            {"input": source}, mapping_path=mapping, backend=backend, placeholders={"selected": value}
        )


@pytest.mark.parametrize(
    ("mapping_record", "source_frame", "message"),
    [
        pytest.param(
            '{"name":"out","source":"input","operations":[{"operation":"filter","column":"id","comparison":"equals","value":1e400}]}',
            pl.DataFrame({"id": [1.0]}),
            "must resolve to a finite number",
            id="filter-number-overflow",
        ),
        pytest.param(
            '{"name":"out","source":"input","operations":[{"operation":"fill_null","columns":["id"],"value":1e400}]}',
            pl.DataFrame({"id": [None]}, schema={"id": pl.Float64}),
            "must be a finite number",
            id="fill-number-overflow",
        ),
        pytest.param(
            '{"name":"out","source":"input","operations":[{"operation":"fill_null","columns":["ids"],"value":[1e400]}]}',
            pl.DataFrame({"ids": [None]}, schema={"ids": pl.List(pl.Float64)}),
            "must contain finite numbers",
            id="fill-list-number-overflow",
        ),
    ],
)
def test_mapping_rejects_overflowing_nonfinite_numeric_literals(
    tmp_path: Path, mapping_record: str, source_frame: pl.DataFrame, message: str
) -> None:
    """JSON exponents that overflow float are rejected just like nonfinite bindings."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(f"[{mapping_record}]", encoding="utf-8")
    backend = PolarsTabularBackend()
    source = TabularSource(source_frame.lazy(), backend)

    with pytest.raises(ValueError, match=message):
        assemble_tables({"input": source}, mapping_path=mapping, backend=backend)


@pytest.mark.parametrize("value", [42, [1, 2], {"id": 1}], ids=["scalar", "scalar-list", "object"])
def test_rows_binding_requires_a_list_of_records(tmp_path: Path, value: object) -> None:
    """A rows constructor cannot turn another binding shape into records."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "operations": [
                        {
                            "operation": "rows",
                            "schema": [{"name": "id", "dtype": "int64"}],
                            "values": "{rows}",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="rows values must resolve to a list of records"):
        assemble_tables(
            {}, mapping_path=mapping, backend=PolarsTabularBackend(), placeholders={"rows": value}
        )


@pytest.mark.parametrize(
    "records",
    [
        pytest.param([{"name": "out", "source": "document", "operations": []}], id="primary-source"),
        pytest.param(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [{"operation": "join", "source": "document", "how": "left", "on": ["id"]}],
                }
            ],
            id="join-source",
        ),
        pytest.param(
            [{"name": "out", "operations": [{"operation": "concat", "sources": ["document"]}]}],
            id="concat-source",
        ),
    ],
)
def test_table_mapping_rejects_non_tabular_sources(tmp_path: Path, records: list[dict[str, object]]) -> None:
    """A JSON document is not implicitly converted to a primary, joined or appended table."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(json.dumps(records), encoding="utf-8")
    backend = PolarsTabularBackend()
    sources = {
        "document": DocumentSource(data={"id": 1}, processor=None),
        "input": TabularSource(pl.DataFrame({"id": [1]}).lazy(), backend),
    }

    with pytest.raises(TypeError, match="source 'document' must be tabular"):
        assemble_tables(sources, mapping_path=mapping, backend=backend)


@pytest.mark.parametrize(
    ("binding", "message"),
    [
        pytest.param([1, float("inf")], "must contain finite numbers", id="nonfinite-list-item"),
        pytest.param({"item": 1}, "must resolve to a scalar", id="structured-fill"),
    ],
)
def test_list_fill_binding_rejects_invalid_values(tmp_path: Path, binding: object, message: str) -> None:
    """List fills reject nonfinite elements and structured non-list values."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [{"operation": "fill_null", "columns": ["values"], "value": "{fill}"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"values": [None]}, schema={"values": pl.List(pl.Int64)}).lazy(), backend
    )

    with pytest.raises(ValueError, match=message):
        assemble_tables(
            {"input": source}, mapping_path=mapping, backend=backend, placeholders={"fill": binding}
        )


def test_fill_binding_requires_a_whole_resolved_placeholder(tmp_path: Path) -> None:
    """Reject partial string interpolation and an unresolved whole-value binding."""
    mapping = tmp_path / "table_mapping.json"
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"value": [None]}, schema={"value": pl.String}).lazy(), backend)
    for value, message in [
        ("prefix_{suffix}", "Partial table-mapping placeholder"),
        ("{missing}", "unresolved"),
    ]:
        mapping.write_text(
            json.dumps(
                [
                    {
                        "name": "out",
                        "source": "input",
                        "operations": [{"operation": "fill_null", "columns": ["value"], "value": value}],
                    }
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=message):
            assemble_tables({"input": source}, mapping_path=mapping, backend=backend)


@pytest.mark.parametrize(
    ("dtype", "replacement", "expected"),
    [
        pytest.param(pl.String, ["wind", None], ["wind", None], id="string-elements"),
        pytest.param(pl.Boolean, [True, None], [True, None], id="boolean-elements"),
        pytest.param(pl.Int64, [1, None], [1, None], id="integer-elements"),
        pytest.param(pl.Float64, [1, 2.5], [1.0, 2.5], id="float-elements"),
        pytest.param(
            pl.Datetime, ["2032-01-02T03:04:05"], [datetime(2032, 1, 2, 3, 4, 5)], id="datetime-elements"
        ),
    ],
)
def test_fill_null_preserves_declared_list_element_types(
    tmp_path: Path, dtype: pl.DataType | type[pl.DataType], replacement: list[object], expected: list[object]
) -> None:
    """Fill a null list with compatible values using the column's element dtype."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [{"operation": "fill_null", "columns": ["values"], "value": replacement}],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"values": [None]}, schema={"values": pl.List(dtype)}).lazy(), backend
    )

    output = assemble_tables({"input": source}, mapping_path=mapping, backend=backend)["out"]

    assert list(output.iter_rows()) == [{"values": expected}]


@pytest.mark.parametrize(
    ("dtype", "replacement", "message"),
    [
        pytest.param(pl.Int64, [1], "list values require a list column", id="list-to-scalar-column"),
        pytest.param(
            pl.List(pl.Int64), [True], "list value type bool is incompatible", id="boolean-to-integer-list"
        ),
        pytest.param(
            pl.List(pl.String), [1], "list value type int is incompatible", id="integer-to-string-list"
        ),
        pytest.param(pl.List(pl.Datetime), ["not-a-date"], "not an ISO datetime", id="invalid-datetime-list"),
        pytest.param(pl.Boolean, 1, "Fill value type int is incompatible", id="integer-to-boolean-column"),
        pytest.param(pl.Datetime, "not-a-date", "not an ISO datetime", id="invalid-datetime-scalar"),
        pytest.param(
            pl.List(pl.String), "text", "Fill value type str is incompatible", id="scalar-to-list-column"
        ),
    ],
)
def test_fill_null_rejects_incompatible_replacement_types(
    tmp_path: Path, dtype: pl.DataType | type[pl.DataType], replacement: object, message: str
) -> None:
    """Never coerce an incompatible scalar or list replacement into the target column."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [{"operation": "fill_null", "columns": ["values"], "value": replacement}],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"values": [None]}, schema={"values": dtype}).lazy(), backend)

    with pytest.raises(ValueError, match=message):
        assemble_tables({"input": source}, mapping_path=mapping, backend=backend)


@pytest.mark.parametrize(
    ("operation", "columns", "output", "message"),
    [
        pytest.param(
            "multiply", ["number", "text"], "result", "multiply requires numeric columns", id="multiply-text"
        ),
        pytest.param(
            "multiply", ["number", "number"], "number", "multiply output column", id="multiply-overwrite"
        ),
        pytest.param("add", ["number", "text"], "result", "add requires numeric columns", id="add-text"),
        pytest.param("add", ["number", "number"], "number", "add output column", id="add-overwrite"),
        pytest.param(
            "divide", ["number", "text"], "result", "divide requires numeric columns", id="divide-text"
        ),
        pytest.param("divide", ["number", "number"], "number", "divide output column", id="divide-overwrite"),
        pytest.param(
            "concat_strings", ["text", "ratio"], "result", "requires string or integer", id="concat-float"
        ),
        pytest.param(
            "concat_strings", ["text"], "text", "concat_strings output column", id="concat-overwrite"
        ),
    ],
)
def test_computed_columns_reject_incompatible_inputs_and_overwrites(
    tmp_path: Path, operation: str, columns: list[str], output: str, message: str
) -> None:
    """New computed columns must use compatible inputs and cannot replace existing fields."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [{"operation": operation, "columns": columns, "output": output}],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"number": [2], "text": ["a"], "ratio": [0.5]}).lazy(), backend)

    with pytest.raises(ValueError, match=message):
        assemble_tables({"input": source}, mapping_path=mapping, backend=backend)


@pytest.mark.parametrize(
    ("dtype", "value", "expected"),
    [
        pytest.param(pl.Boolean, True, [True], id="boolean"),
        pytest.param(pl.Datetime, "2032-01-02T03:04:05", [datetime(2032, 1, 2, 3, 4, 5)], id="datetime"),
    ],
)
def test_filter_accepts_boolean_and_iso_datetime_literals(
    tmp_path: Path, dtype: pl.DataType | type[pl.DataType], value: object, expected: list[object]
) -> None:
    """Literal comparisons respect the target column's boolean or datetime type."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [
                        {"operation": "filter", "column": "value", "comparison": "equals", "value": value}
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame({"value": [*expected, None]}, schema={"value": dtype}).lazy(), backend
    )

    output = assemble_tables({"input": source}, mapping_path=mapping, backend=backend)["out"]

    assert [row["value"] for row in output.iter_rows()] == expected


def test_filter_rejects_a_non_iso_datetime_literal(tmp_path: Path) -> None:
    """Datetime comparison literals must use the documented ISO form."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "filter",
                            "column": "when",
                            "comparison": "equals",
                            "value": "next Tuesday",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"when": [None]}, schema={"when": pl.Datetime}).lazy(), backend)

    with pytest.raises(ValueError, match="not an ISO datetime"):
        assemble_tables({"input": source}, mapping_path=mapping, backend=backend)


@pytest.mark.parametrize(
    ("right_key", "payload", "message"),
    [
        pytest.param("1", None, "Join key types must match exactly", id="mismatched-key-types"),
        pytest.param(1, ["id"], "Join payload columns cannot include matching keys", id="key-as-payload"),
    ],
)
def test_join_rejects_incompatible_keys_and_key_payloads(
    tmp_path: Path, right_key: str | int, payload: list[str] | None, message: str
) -> None:
    """Join keys have matching types and are never duplicated as right-side payload."""
    operation: dict[str, object] = {"operation": "join", "source": "right", "how": "left", "on": ["id"]}
    if payload is not None:
        operation["columns"] = payload
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps([{"name": "out", "source": "left", "operations": [operation]}]), encoding="utf-8"
    )
    backend = PolarsTabularBackend()
    sources = {
        "left": TabularSource(pl.DataFrame({"id": [1]}).lazy(), backend),
        "right": TabularSource(pl.DataFrame({"id": [right_key]}).lazy(), backend),
    }

    with pytest.raises(ValueError, match=message):
        assemble_tables(sources, mapping_path=mapping, backend=backend)


@pytest.mark.parametrize(
    ("method", "columns", "message"),
    [
        pytest.param("create_list_column", [], "list requires at least one input column", id="empty-list"),
        pytest.param("create_list_column", ["id", "id"], "list columns must be unique", id="duplicate-list"),
        pytest.param(
            "concat_strings", [], "concat_strings requires at least one input column", id="empty-strings"
        ),
        pytest.param(
            "concat_strings", ["id", "id"], "concat_strings columns must be unique", id="duplicate-strings"
        ),
    ],
)
def test_backend_rejects_empty_or_repeated_column_sequences(
    method: Literal["create_list_column", "concat_strings"], columns: list[str], message: str
) -> None:
    """The public backend enforces column constraints when used without the JSON model."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"id": [1]}).lazy(), backend)

    with pytest.raises(ValueError, match=message):
        if method == "create_list_column":
            backend.create_list_column(source, columns=columns, output="result")
        else:
            backend.concat_strings(source, columns=columns, output="result", separator="_")


def test_backend_rejects_duplicate_unpivot_inputs() -> None:
    """Direct backend users cannot assign one input column to multiple unpivot labels."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"id": [1], "value": [2]}).lazy(), backend)

    with pytest.raises(ValueError, match="unpivot value columns must be unique"):
        backend.unpivot(
            source,
            index=["id"],
            columns={"first": "value", "second": "value"},
            variable_name="kind",
            value_name="amount",
        )


def test_backend_rejects_empty_object_and_concat_sources() -> None:
    """Direct backend calls cannot construct objects or concatenations from no inputs."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"id": [1]}).lazy(), backend)

    with pytest.raises(ValueError, match="object requires at least one field"):
        backend.create_object_column(source, columns={}, output="result")
    with pytest.raises(ValueError, match="concat requires at least one source"):
        backend.concat_tables([])


@pytest.mark.parametrize(
    ("how", "on", "message"),
    [
        pytest.param("cross", ["id"], "cross joins must omit join keys", id="cross-with-key"),
        pytest.param("left", None, "left joins require explicit keys", id="left-without-key"),
    ],
)
def test_backend_rejects_invalid_direct_join_modes(
    how: Literal["cross", "left"], on: list[str] | None, message: str
) -> None:
    """The backend validates join-key shape even when called directly."""
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"id": [1]}).lazy(), backend)

    with pytest.raises(ValueError, match=message):
        backend.join_tables(source, source, how=how, on=on, columns=[])


def test_backend_rejects_missing_regex_literal_key_despite_matching_decoy() -> None:
    """Require the literal anchored key on both sources before Polars selector parsing."""
    backend = PolarsTabularBackend()
    left = TabularSource(pl.DataFrame({"technology": ["wind"]}).lazy(), backend)
    right = TabularSource(pl.DataFrame({"technology": ["wind"], "value": [1]}).lazy(), backend)

    with pytest.raises(ValueError, match="join references missing column"):
        backend.join_tables(left, right, how="left", on=["^technology$"], columns=[])


def test_backend_checks_exact_regex_shaped_join_key_dtypes() -> None:
    """Validate the literal regex-shaped key's dtype, not the matching decoy column."""
    backend = PolarsTabularBackend()
    left = TabularSource(
        pl.DataFrame(
            {
                "^id$": pl.Series("^id$", [1], dtype=pl.Int64),
                "id": pl.Series("id", ["left"], dtype=pl.String),
            }
        ).lazy(),
        backend,
    )
    right = TabularSource(
        pl.DataFrame(
            {
                "^id$": pl.Series("^id$", ["1"], dtype=pl.String),
                "id": pl.Series("id", ["right"], dtype=pl.String),
            }
        ).lazy(),
        backend,
    )

    with pytest.raises(ValueError, match="Join key types must match exactly"):
        backend.join_tables(left, right, how="inner", on=["^id$"], columns=[])


def test_backend_rejects_eager_frames_for_table_operations() -> None:
    """The Polars backend requires its declared lazy-frame representation."""
    backend = PolarsTabularBackend()
    eager = TabularSource(pl.DataFrame({"id": [1]}), backend)
    lazy = TabularSource(pl.DataFrame({"id": [1]}).lazy(), backend)

    with pytest.raises(TypeError, match="requires Polars LazyFrame sources"):
        backend.join_tables(eager, lazy, how="left", on=["id"], columns=[])
    with pytest.raises(TypeError, match="requires Polars LazyFrame sources"):
        backend.multiply_columns(eager, columns=["id", "id"], output="result")
    with pytest.raises(TypeError, match="requires Polars LazyFrame sources"):
        backend.project_columns(eager, columns={"id": ("column", "id")})


def test_projection_literal_does_not_overwrite_a_temporary_shaped_input_name(tmp_path: Path) -> None:
    """Exact input names remain usable even when they resemble internal literal names."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [],
                    "columns": {"label": {"value": "MW"}, "number": "__r2x_table_mapping_literal_0__"},
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"__r2x_table_mapping_literal_0__": [4]}).lazy(), backend)

    output = assemble_tables({"input": source}, mapping_path=mapping, backend=backend)["out"]

    assert list(output.iter_rows()) == [{"label": "MW", "number": 4}]


@pytest.mark.parametrize(
    ("then_value", "otherwise_value", "dtype", "expected"),
    [
        pytest.param(True, False, pl.Boolean, [True, False, False], id="boolean-literals"),
        pytest.param(3, -2, pl.Int64, [3, -2, -2], id="integer-literals"),
        pytest.param("wind", "thermal", pl.String, ["wind", "thermal", "thermal"], id="text-literals"),
        pytest.param(None, 7, pl.Int64, [None, 7, 7], id="null-and-integer"),
        pytest.param(1, 2.5, pl.Float64, [1.0, 2.5, 2.5], id="numeric-widening"),
    ],
)
def test_choose_scalar_branches_keep_their_declared_types(
    tmp_path: Path,
    then_value: object,
    otherwise_value: object,
    dtype: pl.DataType | type[pl.DataType],
    expected: list[object],
) -> None:
    """A null predicate takes the otherwise branch without changing the selected dtype."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [
                        {
                            "operation": "choose",
                            "column": "id",
                            "comparison": "equals",
                            "value": 0,
                            "then": {"value": then_value},
                            "otherwise": {"value": otherwise_value},
                            "output": "selected",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    source = TabularSource(pl.DataFrame({"id": [0, 1, None]}, schema={"id": pl.Int64}).lazy(), backend)

    output = assemble_tables({"input": source}, mapping_path=mapping, backend=backend)["out"]

    assert isinstance(output, TabularSource)
    assert isinstance(output.data, pl.LazyFrame)
    assert output.data.collect_schema()["selected"] == dtype
    assert [row["selected"] for row in output.iter_rows()] == expected


def test_join_preserves_columns_named_like_temporary_keys(tmp_path: Path) -> None:
    """A real input field must not be replaced by the backend's join-key aliases."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "left",
                    "operations": [{"operation": "join", "source": "right", "how": "left", "on": ["id"]}],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    sources = {
        "left": TabularSource(
            pl.DataFrame({"id": [1], "__r2x_table_mapping_key_0__": ["kept"]}).lazy(), backend
        ),
        "right": TabularSource(pl.DataFrame({"id": [1], "value": [5]}).lazy(), backend),
    }

    output = assemble_tables(sources, mapping_path=mapping, backend=backend)["out"]

    assert list(output.iter_rows()) == [{"id": 1, "__r2x_table_mapping_key_0__": "kept", "value": 5}]


def test_unique_preserves_columns_named_like_its_temporary_fields(tmp_path: Path) -> None:
    """Stable uniqueness does not overwrite similarly named input columns."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "input",
                    "operations": [{"operation": "unique", "columns": ["id"], "keep": "last"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    source = TabularSource(
        pl.DataFrame(
            {
                "id": [1, 1, 2],
                "__r2x_table_mapping_unique_order__": ["first", "second", "third"],
                "__r2x_table_mapping_unique_key_0__": ["a", "b", "c"],
            }
        ).lazy(),
        backend,
    )

    output = assemble_tables({"input": source}, mapping_path=mapping, backend=backend)["out"]

    assert list(output.iter_rows()) == [
        {"id": 1, "__r2x_table_mapping_unique_order__": "second", "__r2x_table_mapping_unique_key_0__": "b"},
        {"id": 2, "__r2x_table_mapping_unique_order__": "third", "__r2x_table_mapping_unique_key_0__": "c"},
    ]


def test_cross_join_with_no_payload_preserves_internal_shaped_columns(tmp_path: Path) -> None:
    """An empty cross-join payload still expands rows without overwriting input names."""
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(
        json.dumps(
            [
                {
                    "name": "out",
                    "source": "left",
                    "operations": [{"operation": "join", "source": "right", "how": "cross", "columns": []}],
                }
            ]
        ),
        encoding="utf-8",
    )
    backend = PolarsTabularBackend()
    sources = {
        "left": TabularSource(pl.DataFrame({"__r2x_table_mapping_right_row__": ["kept"]}).lazy(), backend),
        "right": TabularSource(pl.DataFrame({"item": [1, 2]}).lazy(), backend),
    }

    output = assemble_tables(sources, mapping_path=mapping, backend=backend)["out"]

    assert list(output.iter_rows()) == [
        {"__r2x_table_mapping_right_row__": "kept"},
        {"__r2x_table_mapping_right_row__": "kept"},
    ]


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(
            {
                "name": "rows",
                "operations": [
                    {"operation": "rows", "schema": [{"name": "id", "dtype": "int64"}], "values": []}
                ],
            },
            id="rows-constructor",
        ),
        pytest.param(
            {"name": "concat", "operations": [{"operation": "concat", "sources": ["source"]}]},
            id="concat-constructor",
        ),
        pytest.param(
            {
                "name": "present",
                "operations": [{"operation": "first_present", "sources": ["source"]}],
            },
            id="first-present-constructor",
        ),
        pytest.param(
            {
                "name": "nonempty",
                "operations": [{"operation": "first_nonempty", "sources": ["source"]}],
            },
            id="first-nonempty-constructor-without-fallback",
        ),
        pytest.param(
            {
                "name": "nonempty-fallback",
                "operations": [{"operation": "first_nonempty", "sources": ["source"], "fallback": "empty"}],
            },
            id="first-nonempty-constructor-with-fallback",
        ),
        pytest.param(
            {
                "name": "join",
                "source": "left",
                "operations": [{"operation": "join", "source": "right", "how": "left", "on": ["id"]}],
            },
            id="join",
        ),
        pytest.param(
            {
                "name": "filter",
                "source": "input",
                "operations": [{"operation": "filter", "column": "value", "comparison": "is_null"}],
            },
            id="filter-omitted-operands",
        ),
        pytest.param(
            {
                "name": "filter-null",
                "source": "input",
                "operations": [
                    {"operation": "filter", "column": "value", "comparison": "equals", "value": None}
                ],
            },
            id="filter-explicit-null",
        ),
        pytest.param(
            {
                "name": "choose-null",
                "source": "input",
                "operations": [
                    {
                        "operation": "choose",
                        "column": "value",
                        "comparison": "equals",
                        "value": None,
                        "then": {"value": None},
                        "otherwise": {"value": "fallback"},
                        "output": "result",
                    }
                ],
            },
            id="choose-explicit-null",
        ),
        pytest.param(
            {
                "name": "unpivot",
                "source": "input",
                "operations": [
                    {"operation": "unpivot", "index": ["id"], "variable_name": "kind", "value_name": "value"}
                ],
            },
            id="unpivot-omitted-optional-fields",
        ),
        pytest.param(
            {
                "name": "fill-null",
                "source": "input",
                "operations": [{"operation": "fill_null", "columns": ["value"], "value": None}],
            },
            id="fill-null-explicit-null",
        ),
        pytest.param(
            {
                "name": "fill-backup",
                "source": "input",
                "operations": [{"operation": "fill_null", "columns": ["value"], "from_columns": ["backup"]}],
            },
            id="fill-null-from-columns",
        ),
    ],
)
@pytest.mark.parametrize("by_alias", [False, True], ids=["field-names", "aliases"])
def test_table_mapping_record_dump_roundtrips_omitted_and_null_fields(
    record: dict[str, object], by_alias: bool
) -> None:
    """Model dumps retain valid table records without turning defaults into explicit nulls."""
    parsed = TableMappingRecord.model_validate(record)

    restored = TableMappingRecord.model_validate(parsed.model_dump(mode="json", by_alias=by_alias))

    assert restored == parsed


def test_table_mapping_dump_preserves_explicit_null_operands() -> None:
    """A valid explicit null remains distinct from an omitted comparison operand."""
    record = TableMappingRecord.model_validate(
        {
            "name": "out",
            "source": "input",
            "operations": [
                {"operation": "filter", "column": "value", "comparison": "equals", "value": None},
                {
                    "operation": "choose",
                    "column": "value",
                    "comparison": "equals",
                    "value": None,
                    "then": {"value": None},
                    "otherwise": {"value": "fallback"},
                    "output": "result",
                },
                {"operation": "fill_null", "columns": ["value"], "value": None},
            ],
        }
    )

    dumped = record.model_dump(mode="json")
    restored = TableMappingRecord.model_validate(dumped)

    for operation in dumped["operations"]:
        assert operation["value"] is None
    assert all("value" in operation.model_fields_set for operation in restored.operations)


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(
            {
                "name": "out",
                "source": None,
                "operations": [
                    {"operation": "rows", "schema": [{"name": "id", "dtype": "int64"}], "values": []}
                ],
            },
            id="record-source-null",
        ),
        pytest.param(
            {"name": "out", "source": "input", "operations": [], "columns": None},
            id="record-projection-null",
        ),
        pytest.param(
            {
                "name": "out",
                "source": "input",
                "operations": [{"operation": "join", "source": "right", "how": "left", "on": None}],
            },
            id="join-key-explicit-null",
        ),
        pytest.param(
            {
                "name": "out",
                "source": "input",
                "operations": [
                    {"operation": "filter", "column": "value", "comparison": "is_null", "value": None}
                ],
            },
            id="unary-filter-explicit-null",
        ),
        pytest.param(
            {
                "name": "out",
                "source": "input",
                "operations": [
                    {
                        "operation": "unpivot",
                        "index": [],
                        "variable_name": "kind",
                        "value_name": "value",
                        "value_type_name": None,
                    }
                ],
            },
            id="unpivot-type-explicit-null",
        ),
        pytest.param(
            {
                "name": "out",
                "operations": [{"operation": "first_nonempty", "sources": ["source"], "fallback": None}],
            },
            id="first-nonempty-fallback-explicit-null",
        ),
        pytest.param(
            {
                "name": "out",
                "source": "input",
                "operations": [{"operation": "fill_null", "columns": ["value"], "from_columns": None}],
            },
            id="fill-null-backup-explicit-null",
        ),
    ],
)
def test_table_mapping_record_rejects_explicit_null_for_omitted_only_fields(
    record: dict[str, object],
) -> None:
    """Serialization support does not loosen strict external null validation."""
    with pytest.raises(ValidationError):
        TableMappingRecord.model_validate(record)


def test_rows_record_json_dump_loads_through_public_assembly_api(tmp_path: Path) -> None:
    """Default record JSON uses the schema alias accepted by the mapping loader."""
    record = TableMappingRecord.model_validate(
        {
            "name": "rows",
            "operations": [
                {
                    "operation": "rows",
                    "schema": [{"name": "id", "dtype": "int64"}],
                    "values": [{"id": 7}],
                }
            ],
        }
    )
    serialized = record.model_dump_json()
    mapping = tmp_path / "table_mapping.json"
    mapping.write_text(f"[{serialized}]", encoding="utf-8")

    output = assemble_tables({}, mapping_path=mapping, backend=PolarsTabularBackend())["rows"]

    assert json.loads(serialized)["operations"][0]["schema"] == [{"name": "id", "dtype": "int64"}]
    assert list(output.iter_rows()) == [{"id": 7}]
    unaliased = json.loads(record.model_dump_json(by_alias=False))
    assert unaliased["operations"][0]["row_schema"] == [{"name": "id", "dtype": "int64"}]
