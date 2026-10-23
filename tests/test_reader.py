"""Integration tests for configured named-source reader behavior."""

import os
import subprocess
import sys
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import h5py
import numpy as np
import polars as pl
import pytest

from r2x_core import (
    ArraySource,
    DataFile,
    DataReader,
    DecodedSources,
    DocumentSource,
    InlineTable,
    TabularSource,
)
from r2x_core.datafile import FileInfo, ReaderConfig
from r2x_core.exceptions import ConfiguredGroupNotFoundError, ReaderError
from r2x_core.models import TabularProcessing
from r2x_core.polars_adapter import PolarsTabularBackend
from r2x_core.types import FileRequirement

pytestmark = pytest.mark.polars


def read_one(
    reader: DataReader,
    item: DataFile,
    folder: Path,
    *,
    placeholders: dict[str, object] | None = None,
) -> object | None:
    """Load one configured name through source orchestration."""
    return reader.read_data_files([item], folder_path=folder, placeholders=placeholders).get(item.name)


def table_data(source: object) -> pl.LazyFrame:
    """Require a Polars-backed source in tests of the built-in tabular reader."""
    assert isinstance(source, TabularSource)
    assert isinstance(source.data, pl.LazyFrame)
    return source.data


def test_parquet_input_uses_configured_format(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    pl.DataFrame({"value": [1, 2]}).write_parquet(path)

    source = read_one(DataReader(), DataFile(name="parquet", fpath=path), tmp_path)

    assert table_data(source).collect().to_dicts() == [{"value": 1}, {"value": 2}]


def test_processing_error_names_datafile_and_preserves_cause(tmp_path: Path) -> None:
    item = DataFile(
        name="reserve_costs_default",
        inline_table={"schema": {"id": "int64"}, "rows": [{"id": 1}]},
        proc_spec={
            "kind": "tabular",
            "steps": [{"op": "rename_columns", "column_mapping": {"missing": "value"}}],
        },
    )

    with pytest.raises(ReaderError, match="reserve_costs_default") as captured:
        DataReader().read_data_files([item], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, ValueError)


def test_parquet_reader_applies_validated_json_options(tmp_path: Path) -> None:
    path = tmp_path / "data.parquet"
    pl.DataFrame({"value": [1, 2]}).write_parquet(path)
    item = DataFile(
        name="limited_parquet",
        fpath=path,
        reader=ReaderConfig(format="parquet", options={"n_rows": 1}),
    )

    source = read_one(DataReader(), item, tmp_path)

    assert table_data(source).collect().to_dicts() == [{"value": 1}]


@pytest.mark.parametrize("options", [{"n_rows": "1"}, {"unsupported": True}])
def test_parquet_reader_rejects_invalid_json_options(tmp_path: Path, options: dict[str, object]) -> None:
    path = tmp_path / "data.parquet"
    pl.DataFrame({"value": [1]}).write_parquet(path)
    item = DataFile(
        name="invalid_parquet_options",
        fpath=path,
        reader=ReaderConfig(format="parquet", options=options),
    )

    with pytest.raises(ValueError, match="Invalid Parquet reader options"):
        read_one(DataReader(), item, tmp_path)


def test_optional_and_required_missing_inputs(tmp_path: Path) -> None:
    optional = DataFile(
        name="optional",
        fpath=tmp_path / "absent.csv",
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
    )
    assert read_one(DataReader(), optional, tmp_path) is None
    required = DataFile(name="required", fpath=tmp_path / "absent.csv")
    with pytest.raises(FileNotFoundError, match="Missing required file"):
        read_one(DataReader(), required, tmp_path)


def test_conditional_required_input_preserves_missing_file_error(tmp_path: Path) -> None:
    files = [
        DataFile(
            name="policy",
            inline_table={"schema": {"enabled": "bool"}, "rows": [{"enabled": True}]},
        ),
        DataFile(
            name="water_upgrades",
            fpath=tmp_path / "water.csv",
            info=FileInfo(requirement=FileRequirement.OPTIONAL),
            required_when={"source": "policy", "predicate": "enabled"},
        ),
    ]

    with pytest.raises(FileNotFoundError, match="Missing required file"):
        DataReader().read_data_files(files, folder_path=tmp_path)


def test_conditional_required_input_allows_absence_when_predicate_is_false(tmp_path: Path) -> None:
    files = [
        DataFile(
            name="policy",
            inline_table={"schema": {"enabled": "bool"}, "rows": [{"enabled": False}]},
        ),
        DataFile(
            name="water_upgrades",
            fpath=tmp_path / "water.csv",
            info=FileInfo(requirement=FileRequirement.OPTIONAL),
            required_when={"source": "policy", "predicate": "enabled"},
        ),
    ]

    sources = DataReader().read_data_files(files, folder_path=tmp_path)

    assert "water_upgrades" not in sources


def test_conditional_required_hdf_group_preserves_configured_group_error(tmp_path: Path) -> None:
    path = tmp_path / "outputs.h5"
    with h5py.File(path, "w"):
        pass
    files = [
        DataFile(
            name="policy",
            inline_table={"schema": {"enabled": "bool"}, "rows": [{"enabled": True}]},
        ),
        DataFile(
            name="water_upgrades",
            fpath=path,
            info=FileInfo(requirement=FileRequirement.OPTIONAL),
            reader=ReaderConfig(format="hdf5", options={"group_key": "water_upgrades"}),
            required_when={"source": "policy", "predicate": "enabled"},
        ),
    ]

    with pytest.raises(ConfiguredGroupNotFoundError, match="water_upgrades"):
        DataReader().read_data_files(files, folder_path=tmp_path)


def test_conditional_required_source_reads_a_present_input(tmp_path: Path) -> None:
    path = tmp_path / "water.csv"
    path.write_text("technology\nhydro\n", encoding="utf-8")
    files = [
        DataFile(
            name="policy",
            inline_table={"schema": {"enabled": "bool"}, "rows": [{"enabled": True}]},
        ),
        DataFile(
            name="water_upgrades",
            fpath=path,
            info=FileInfo(requirement=FileRequirement.OPTIONAL),
            required_when={"source": "policy", "predicate": "enabled"},
        ),
    ]

    sources = DataReader().read_data_files(files, folder_path=tmp_path)

    assert list(sources["water_upgrades"].iter_rows()) == [{"technology": "hydro"}]


def test_conditional_requiredness_does_not_hide_malformed_present_input(tmp_path: Path) -> None:
    path = tmp_path / "water.json"
    path.write_text("{not json", encoding="utf-8")
    files = [
        DataFile(
            name="policy",
            inline_table={"schema": {"enabled": "bool"}, "rows": [{"enabled": True}]},
        ),
        DataFile(
            name="water_upgrades",
            fpath=path,
            info=FileInfo(requirement=FileRequirement.OPTIONAL),
            reader=ReaderConfig(format="json"),
            required_when={"source": "policy", "predicate": "enabled"},
        ),
    ]

    with pytest.raises(JSONDecodeError):
        DataReader().read_data_files(files, folder_path=tmp_path)


def test_literal_expression_placeholder_resolves_to_its_native_scalar(tmp_path: Path) -> None:
    data_file = DataFile(
        name="years",
        inline_table={"schema": {"year": "int64"}, "rows": [{"year": 2032}, {"year": 2035}]},
        proc_spec={
            "kind": "tabular",
            "steps": [{"op": "filter", "predicate": {"eq": ["year", {"literal": "{requested_year}"}]}}],
        },
    )

    sources = DataReader().read_data_files(
        [data_file], folder_path=tmp_path, placeholders={"requested_year": 2032}
    )

    assert table_data(sources["years"]).collect().to_dicts() == [{"year": 2032}]


@pytest.mark.parametrize("enabled_value", [True, False], ids=["required", "optional"])
def test_conditional_requiredness_resolves_source_and_predicate_placeholders(
    tmp_path: Path, enabled_value: bool
) -> None:
    policy_path = tmp_path / "policy.csv"
    policy_path.write_text("enabled\ntrue\n", encoding="utf-8")
    files = [
        DataFile(name="policy", fpath=policy_path),
        DataFile(
            name="water",
            fpath=tmp_path / "water.csv",
            info=FileInfo(requirement=FileRequirement.OPTIONAL),
            required_when={
                "source": "{policy_source}",
                "predicate": {"eq": ["enabled", {"literal": "{enabled_value}"}]},
            },
        ),
    ]
    placeholders = {"policy_source": "policy", "enabled_value": enabled_value}

    if enabled_value:
        with pytest.raises(FileNotFoundError, match="Missing required file"):
            DataReader().read_data_files(files, folder_path=tmp_path, placeholders=placeholders)
    else:
        sources = DataReader().read_data_files(files, folder_path=tmp_path, placeholders=placeholders)
        assert "water" not in sources


def test_conditional_requiredness_requires_an_available_tabular_predicate() -> None:
    optional_policy = DataFile(
        name="policy",
        fpath="absent.csv",
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
    )
    water = DataFile(
        name="water",
        fpath="water.csv",
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
        required_when={"source": "policy", "predicate": True},
    )

    with pytest.raises(ValueError, match="required_when source 'policy' is not available"):
        DataReader().read_data_files([optional_policy, water], folder_path=Path("."))


def test_conditional_requiredness_preserves_predicate_processing_error(tmp_path: Path) -> None:
    source = DataFile(
        name="policy",
        inline_table={"schema": {"enabled": "int64"}, "rows": [{"enabled": 1}]},
    )
    water = DataFile(
        name="water",
        fpath=tmp_path / "water.csv",
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
        required_when={"source": "policy", "predicate": "enabled"},
    )

    from r2x_core.exceptions import ReaderError

    with pytest.raises(ReaderError, match="filter predicate must be of type") as captured:
        DataReader().read_data_files([source, water], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, pl.exceptions.PolarsError)


def test_conditional_requiredness_preserves_mapping_validation_error(tmp_path: Path) -> None:
    source = DataFile(
        name="policy",
        inline_table={"schema": {"enabled": "bool"}, "rows": [{"enabled": True}]},
    )
    water = DataFile(
        name="water",
        fpath=tmp_path / "water.csv",
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
        required_when={"source": "policy", "predicate": "missing"},
    )

    from r2x_core.exceptions import ReaderError

    with pytest.raises(ReaderError, match="not found in current frame") as captured:
        DataReader().read_data_files([source, water], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, ValueError)


def test_conditional_requiredness_rejects_non_tabular_predicate_sources(tmp_path: Path) -> None:
    water = DataFile(
        name="water",
        fpath=tmp_path / "water.csv",
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
        required_when={"source": "policy", "predicate": True},
    )

    with pytest.raises(TypeError, match="must be tabular"):
        DataReader().read_data_files(
            [water],
            folder_path=tmp_path,
            initial_sources={"policy": DocumentSource({"enabled": True}, None)},
        )


def test_conditional_requiredness_is_limited_to_optional_physical_inputs() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="only to optional physical inputs"):
        DataFile(
            name="derived",
            source="policy",
            required_when={"source": "policy", "predicate": True},
        )
    with pytest.raises(ValidationError, match="only to optional physical inputs"):
        DataFile(
            name="required",
            fpath="required.csv",
            required_when={"source": "policy", "predicate": True},
        )


def test_builtin_readers_are_cached_per_datareader_instance() -> None:
    first = DataReader()
    second = DataReader()
    selected = first.select_file_reader("csv")

    assert first.select_file_reader("csv") is selected
    assert second.select_file_reader("csv") is not selected


def test_declared_cross_join_combines_prior_sources() -> None:
    sources = DataReader().read_data_files(
        [
            DataFile(name="left", inline_table={"schema": {"left": "int64"}, "rows": [{"left": 1}]}),
            DataFile(
                name="right",
                inline_table={"schema": {"right": "string"}, "rows": [{"right": "a"}, {"right": "b"}]},
            ),
            DataFile(
                name="joined",
                source="left",
                proc_spec={"kind": "tabular", "steps": [{"op": "join", "source": "right", "how": "cross"}]},
            ),
        ],
        folder_path=Path("."),
    )

    assert list(sources["joined"].iter_rows()) == [
        {"left": 1, "right": "a"},
        {"left": 1, "right": "b"},
    ]


def test_cross_join_projection_preserves_rows_after_scalar_reduction() -> None:
    sources = DataReader().read_data_files(
        [
            DataFile(
                name="values",
                inline_table={
                    "schema": {"symbol": "string", "value": "float64"},
                    "rows": [
                        {"symbol": "A", "value": 1.0},
                        {"symbol": "B", "value": 2.0},
                        {"symbol": "C", "value": 3.0},
                    ],
                },
            ),
            DataFile(
                name="median",
                source="values",
                proc_spec={
                    "kind": "tabular",
                    "steps": [{"op": "aggregate", "aggregate_on": {"value": "median"}}],
                },
            ),
            DataFile(
                name="projected",
                source="values",
                proc_spec={
                    "kind": "tabular",
                    "steps": [
                        {"op": "join", "source": "median", "how": "cross"},
                        {"op": "select_columns", "select_columns": ["symbol"]},
                    ],
                },
            ),
        ],
        folder_path=Path("."),
    )

    assert list(sources["projected"].iter_rows()) == [
        {"symbol": "A"},
        {"symbol": "B"},
        {"symbol": "C"},
    ]


def test_declared_concat_combines_prior_sources_with_same_schema() -> None:
    sources = DataReader().read_data_files(
        [
            DataFile(
                name="first",
                inline_table={
                    "schema": {"technology": "string", "id": "int64"},
                    "rows": [{"technology": "upv", "id": 1}],
                },
            ),
            DataFile(
                name="second",
                inline_table={
                    "schema": {"technology": "string", "id": "int64"},
                    "rows": [{"technology": "wind-ons", "id": 2}],
                },
            ),
            DataFile(
                name="combined",
                source="first",
                proc_spec={"kind": "tabular", "steps": [{"op": "concat", "sources": ["second"]}]},
            ),
        ],
        folder_path=Path("."),
    )

    assert list(sources["combined"].iter_rows()) == [
        {"technology": "upv", "id": 1},
        {"technology": "wind-ons", "id": 2},
    ]


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        (True, [True]),
        (False, [False]),
        ([True], [True]),
        ([False], [False]),
        ([True, False], [True, False]),
    ],
)
def test_filter_columns_matches_typed_boolean_values(
    selected: bool | list[bool], expected: list[bool]
) -> None:
    sources = DataReader().read_data_files(
        [
            DataFile(
                name="flags",
                inline_table={
                    "schema": {"enabled": "bool"},
                    "rows": [{"enabled": True}, {"enabled": False}],
                },
                proc_spec={
                    "kind": "tabular",
                    "steps": [{"op": "filter_columns", "filter_by": {"enabled": selected}}],
                },
            )
        ],
        folder_path=Path("."),
    )

    assert [row["enabled"] for row in sources["flags"].iter_rows()] == expected


def test_declared_repeat_by_and_explode_expand_monthly_rows() -> None:
    sources = DataReader().read_data_files(
        [
            DataFile(
                name="monthly",
                inline_table={
                    "schema": {"month": "string", "hours": "int64", "factor": "float64"},
                    "rows": [
                        {"month": "feb", "hours": 2, "factor": 0.1},
                        {"month": "mar", "hours": 3, "factor": 0.2},
                    ],
                },
                proc_spec={
                    "kind": "tabular",
                    "steps": [
                        {
                            "op": "with_columns",
                            "columns": {"sample": {"repeat_by": ["factor", "hours"]}},
                        },
                        {"op": "explode", "columns": ["sample"]},
                    ],
                },
            )
        ],
        folder_path=Path("."),
    )

    assert [row["sample"] for row in sources["monthly"].iter_rows()] == [0.1, 0.1, 0.2, 0.2, 0.2]


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, []), (None, [{"value": 7, "count": None, "sample": None}])],
    ids=["zero-repetitions", "null-count-preserves-null"],
)
def test_repeat_by_explode_has_stable_empty_and_null_semantics(
    tmp_path: Path, count: int | None, expected: list[dict[str, object]]
) -> None:
    source = DataFile(
        name="monthly",
        inline_table={
            "schema": {"value": "int64", "count": "int64"},
            "rows": [{"value": 7, "count": count}],
        },
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "with_columns",
                    "columns": {"sample": {"repeat_by": ["value", "count"]}},
                },
                {"op": "explode", "columns": ["sample"]},
            ],
        },
    )

    sources = DataReader().read_data_files([source], folder_path=tmp_path)

    assert list(sources["monthly"].iter_rows()) == expected


def test_repeat_by_rejects_negative_repetition_count(tmp_path: Path) -> None:
    source = DataFile(
        name="monthly",
        inline_table={"schema": {"value": "int64", "count": "int64"}, "rows": [{"value": 7, "count": -1}]},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "with_columns",
                    "columns": {"sample": {"repeat_by": ["value", "count"]}},
                },
                {"op": "explode", "columns": ["sample"]},
            ],
        },
    )

    sources = DataReader().read_data_files([source], folder_path=tmp_path)

    with pytest.raises(pl.exceptions.InvalidOperationError):
        list(sources["monthly"].iter_rows())


def test_datetime_range_expands_each_seed_to_a_regular_axis(tmp_path: Path) -> None:
    source = DataFile(
        name="calendar",
        inline_table={
            "schema": {"owner": "string", "start": "string"},
            "rows": [
                {"owner": "north", "start": "2012-01-01T00:00:00"},
                {"owner": "south", "start": "2012-02-01T00:00:00"},
            ],
        },
        proc_spec={
            "kind": "tabular",
            "steps": [
                {"op": "cast_columns", "column_schema": {"start": "datetime"}},
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 3,
                    "resolution_seconds": 3600,
                },
            ],
        },
    )

    sources = DataReader().read_data_files([source], folder_path=tmp_path)

    assert list(sources["calendar"].iter_rows()) == [
        {"owner": "north", "start": datetime(2012, 1, 1), "datetime": datetime(2012, 1, 1)},
        {
            "owner": "north",
            "start": datetime(2012, 1, 1),
            "datetime": datetime(2012, 1, 1, 1),
        },
        {
            "owner": "north",
            "start": datetime(2012, 1, 1),
            "datetime": datetime(2012, 1, 1, 2),
        },
        {"owner": "south", "start": datetime(2012, 2, 1), "datetime": datetime(2012, 2, 1)},
        {
            "owner": "south",
            "start": datetime(2012, 2, 1),
            "datetime": datetime(2012, 2, 1, 1),
        },
        {
            "owner": "south",
            "start": datetime(2012, 2, 1),
            "datetime": datetime(2012, 2, 1, 2),
        },
    ]


def test_datetime_range_preserves_nanosecond_start_precision(tmp_path: Path) -> None:
    start_nanoseconds = 1_577_836_800_000_000_001
    path = tmp_path / "nanosecond-start.parquet"
    pl.DataFrame(
        {"start": pl.Series("start", [start_nanoseconds], dtype=pl.Int64).cast(pl.Datetime("ns"))}
    ).write_parquet(path)
    source = DataFile(
        name="calendar",
        fpath=path,
        reader=ReaderConfig(format="parquet"),
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 2,
                    "resolution_seconds": 1,
                }
            ],
        },
    )

    result = DataReader().read_data_files([source], folder_path=tmp_path)["calendar"]
    frame = result.data.collect()

    assert frame.schema["datetime"] == pl.Datetime("ns")
    assert frame["datetime"].cast(pl.Int64).to_list() == [
        start_nanoseconds,
        start_nanoseconds + 1_000_000_000,
    ]


def test_datetime_range_uses_fixed_elapsed_spacing_across_dst(tmp_path: Path) -> None:
    path = tmp_path / "dst-start.parquet"
    pl.DataFrame(
        {
            "start": pl.Series(
                "start",
                [datetime(2020, 3, 7, 12, tzinfo=ZoneInfo("America/New_York"))],
                dtype=pl.Datetime("us", "America/New_York"),
            )
        }
    ).write_parquet(path)
    source = DataFile(
        name="calendar",
        fpath=path,
        reader=ReaderConfig(format="parquet"),
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 3,
                    "resolution_seconds": 86400,
                }
            ],
        },
    )

    result = DataReader().read_data_files([source], folder_path=tmp_path)["calendar"]
    frame = result.data.collect()
    timestamps = frame["datetime"].cast(pl.Int64).to_list()

    assert frame.schema["datetime"] == pl.Datetime("us", "America/New_York")
    assert len(timestamps) == 3
    assert [timestamps[1] - timestamps[0], timestamps[2] - timestamps[1]] == [
        86_400_000_000,
        86_400_000_000,
    ]


def test_datetime_range_preserves_submicrosecond_spacing(tmp_path: Path) -> None:
    path = tmp_path / "microsecond-start.parquet"
    start_microseconds = 1_577_836_800_000_000
    pl.DataFrame(
        {"start": pl.Series("start", [start_microseconds], dtype=pl.Int64).cast(pl.Datetime("us"))}
    ).write_parquet(path)
    source = DataFile(
        name="calendar",
        fpath=path,
        reader=ReaderConfig(format="parquet"),
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 3,
                    "resolution_seconds": 0.0000006,
                }
            ],
        },
    )

    result = DataReader().read_data_files([source], folder_path=tmp_path)["calendar"]
    frame = result.data.collect()

    assert frame.schema["datetime"] == pl.Datetime("ns")
    assert frame["datetime"].cast(pl.Int64).to_list() == [
        start_microseconds * 1_000,
        start_microseconds * 1_000 + 600,
        start_microseconds * 1_000 + 1_200,
    ]


def test_datetime_range_promotes_millisecond_start_for_submillisecond_spacing(tmp_path: Path) -> None:
    path = tmp_path / "millisecond-start.parquet"
    start_milliseconds = 1_577_836_800_000
    pl.DataFrame(
        {"start": pl.Series("start", [start_milliseconds], dtype=pl.Int64).cast(pl.Datetime("ms"))}
    ).write_parquet(path)
    source = DataFile(
        name="calendar",
        fpath=path,
        reader=ReaderConfig(format="parquet"),
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 3,
                    "resolution_seconds": 0.0001,
                }
            ],
        },
    )

    result = DataReader().read_data_files([source], folder_path=tmp_path)["calendar"]
    frame = result.data.collect()

    assert frame.schema["datetime"] == pl.Datetime("us")
    assert frame["datetime"].cast(pl.Int64).to_list() == [
        start_milliseconds * 1_000,
        start_milliseconds * 1_000 + 100,
        start_milliseconds * 1_000 + 200,
    ]


@pytest.mark.parametrize(
    ("periods", "resolution_seconds"),
    [(0, 3600), (-1, 3600), (1, 0), (1, -1), (1, float("inf")), (1, float("nan"))],
    ids=["zero-periods", "negative-periods", "zero-resolution", "negative-resolution", "infinite", "nan"],
)
def test_datetime_range_rejects_nonpositive_or_nonfinite_parameters(
    periods: int, resolution_seconds: float
) -> None:
    with pytest.raises(ValueError):
        DataFile(
            name="calendar",
            inline_table={"schema": {"start": "string"}, "rows": [{"start": "2012-01-01T00:00:00"}]},
            proc_spec={
                "kind": "tabular",
                "steps": [
                    {"op": "cast_columns", "column_schema": {"start": "datetime"}},
                    {
                        "op": "datetime_range",
                        "start": "start",
                        "column": "datetime",
                        "periods": periods,
                        "resolution_seconds": resolution_seconds,
                    },
                ],
            },
        )


@pytest.mark.parametrize(
    "resolution_seconds",
    [0.0000000001, 0.0000000006],
    ids=["below-nanosecond", "nonintegral-nanosecond"],
)
def test_datetime_range_rejects_unrepresentable_resolution(tmp_path: Path, resolution_seconds: float) -> None:
    source = DataFile(
        name="calendar",
        inline_table={"schema": {"start": "string"}, "rows": [{"start": "2012-01-01T00:00:00"}]},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {"op": "cast_columns", "column_schema": {"start": "datetime"}},
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 2,
                    "resolution_seconds": resolution_seconds,
                },
            ],
        },
    )

    with pytest.raises(ReaderError, match="representable in nanoseconds") as captured:
        DataReader().read_data_files([source], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, ValueError)


def test_datetime_range_rejects_existing_output_column(tmp_path: Path) -> None:
    source = DataFile(
        name="calendar",
        inline_table={
            "schema": {"start": "string", "datetime": "string"},
            "rows": [{"start": "2012-01-01T00:00:00", "datetime": "existing"}],
        },
        proc_spec={
            "kind": "tabular",
            "steps": [
                {"op": "cast_columns", "column_schema": {"start": "datetime"}},
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 2,
                    "resolution_seconds": 3600,
                },
            ],
        },
    )

    with pytest.raises(ReaderError, match="output column 'datetime' already exists") as captured:
        DataReader().read_data_files([source], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, ValueError)


def test_datetime_range_rejects_start_column_as_output() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="cannot replace its start column"):
        DataFile(
            name="calendar",
            inline_table={"schema": {"start": "string"}, "rows": [{"start": "2012-01-01T00:00:00"}]},
            proc_spec={
                "kind": "tabular",
                "steps": [
                    {
                        "op": "datetime_range",
                        "start": "start",
                        "column": "start",
                        "periods": 2,
                        "resolution_seconds": 3600,
                    }
                ],
            },
        )


def test_datetime_range_rejects_excessive_span(tmp_path: Path) -> None:
    source = DataFile(
        name="calendar",
        inline_table={"schema": {"start": "string"}, "rows": [{"start": "2012-01-01T00:00:00"}]},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {"op": "cast_columns", "column_schema": {"start": "datetime"}},
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 2,
                    "resolution_seconds": 1e20,
                },
            ],
        },
    )

    with pytest.raises(ReaderError, match="span exceeds the supported datetime range") as captured:
        DataReader().read_data_files([source], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, ValueError)


@pytest.mark.parametrize(
    ("schema", "rows", "steps"),
    [
        ({"owner": "string"}, [{"owner": "north"}], []),
        (
            {"owner": "string", "start": "string"},
            [{"owner": "north", "start": "2012-01-01T00:00:00"}],
            [],
        ),
        (
            {"owner": "string", "start": "string"},
            [{"owner": "north", "start": None}],
            [{"op": "cast_columns", "column_schema": {"start": "datetime"}}],
        ),
    ],
    ids=["absent-start", "wrong-start-type", "null-start"],
)
def test_datetime_range_rejects_invalid_start_columns(
    tmp_path: Path,
    schema: dict[str, str],
    rows: list[dict[str, object]],
    steps: list[dict[str, object]],
) -> None:
    source = DataFile(
        name="calendar",
        inline_table={"schema": schema, "rows": rows},
        proc_spec={
            "kind": "tabular",
            "steps": [
                *steps,
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 3,
                    "resolution_seconds": 3600,
                },
            ],
        },
    )

    with pytest.raises(ReaderError) as captured:
        DataReader().read_data_files([source], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, ValueError)


def test_datetime_range_preserves_empty_seed_tables(tmp_path: Path) -> None:
    source = DataFile(
        name="calendar",
        inline_table={"schema": {"start": "string"}, "rows": []},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {"op": "cast_columns", "column_schema": {"start": "datetime"}},
                {
                    "op": "datetime_range",
                    "start": "start",
                    "column": "datetime",
                    "periods": 3,
                    "resolution_seconds": 3600,
                },
            ],
        },
    )

    sources = DataReader().read_data_files([source], folder_path=tmp_path)

    assert list(sources["calendar"].iter_rows()) == []


@pytest.mark.parametrize(
    ("count", "expected"),
    [(2, [{"value": 3}, {"value": 1}]), (0, [])],
    ids=["keep-first-rows", "empty-prefix"],
)
def test_head_keeps_the_requested_source_prefix(
    tmp_path: Path, count: int, expected: list[dict[str, int]]
) -> None:
    source = DataFile(
        name="samples",
        inline_table={"schema": {"value": "int64"}, "rows": [{"value": 3}, {"value": 1}, {"value": 2}]},
        proc_spec={"kind": "tabular", "steps": [{"op": "head", "n": count}]},
    )

    sources = DataReader().read_data_files([source], folder_path=tmp_path)

    assert list(sources["samples"].iter_rows()) == expected


def test_head_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        DataFile(
            name="samples",
            inline_table={"schema": {"value": "int64"}, "rows": []},
            proc_spec={"kind": "tabular", "steps": [{"op": "head", "n": -1}]},
        )


def test_declared_concat_rejects_schema_mismatch() -> None:
    files = [
        DataFile(name="first", inline_table={"schema": {"id": "int64"}, "rows": [{"id": 1}]}),
        DataFile(name="second", inline_table={"schema": {"other": "string"}, "rows": [{"other": "x"}]}),
        DataFile(
            name="combined",
            source="first",
            proc_spec={"kind": "tabular", "steps": [{"op": "concat", "sources": ["second"]}]},
        ),
    ]

    with pytest.raises(ReaderError, match="concat sources must have identical schemas") as captured:
        DataReader().read_data_files(files, folder_path=Path("."))

    assert isinstance(captured.value.__cause__, ValueError)


def test_concat_rejects_duplicate_source_names() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Concat sources must be unique"):
        DataFile(
            name="combined",
            source="first",
            proc_spec={"kind": "tabular", "steps": [{"op": "concat", "sources": ["second", "second"]}]},
        )


def test_explode_rejects_duplicate_column_names() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Explode columns must be unique"):
        DataFile(
            name="expanded",
            inline_table={"schema": {"samples": "int64"}, "rows": [{"samples": 1}]},
            proc_spec={"kind": "tabular", "steps": [{"op": "explode", "columns": ["samples", "samples"]}]},
        )


@pytest.mark.parametrize("options", [{"on": ["id"]}, {"validate": "1:1"}])
def test_cross_join_rejects_keyed_or_cardinality_validation(options: dict[str, object]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="cross joins cannot define keys or non-m:m validation"):
        DataFile(
            name="joined",
            source="left",
            proc_spec={
                "kind": "tabular",
                "steps": [{"op": "join", "source": "right", "how": "cross", **options}],
            },
        )


def test_assert_step_reports_its_declared_message(tmp_path: Path) -> None:
    data_file = DataFile(
        name="checked",
        inline_table={"schema": {"value": "int64"}, "rows": [{"value": 0}]},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "assert",
                    "predicate": {"gt": ["value", 0]},
                    "message": "Duplicate switch values are not allowed",
                }
            ],
        },
    )

    with pytest.raises(ReaderError, match="Duplicate switch values") as captured:
        DataReader().read_data_files([data_file], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, ValueError)


def test_membership_requires_a_typed_list_operand() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="is_in requires a typed list literal"):
        DataFile(
            name="invalid_membership",
            inline_table={"schema": {"technology": "string"}, "rows": []},
            proc_spec={
                "kind": "tabular",
                "steps": [
                    {
                        "op": "with_columns",
                        "columns": {"included": {"is_in": ["technology", "other"]}},
                    }
                ],
            },
        )


def test_tabular_mapping_builds_nested_geojson_with_named_columns() -> None:
    sources = DataReader().read_data_files(
        [
            DataFile(
                name="resource",
                inline_table={
                    "schema": {
                        "name": "string",
                        "region": "string",
                        "latitude": "float64",
                        "longitude": "float64",
                    },
                    "rows": [
                        {
                            "name": "site-1",
                            "region": "p1",
                            "latitude": 40.0,
                            "longitude": -105.0,
                        }
                    ],
                },
            ),
            DataFile(
                name="features",
                source="resource",
                proc_spec={
                    "kind": "tabular",
                    "steps": [
                        {
                            "op": "with_columns",
                            "columns": {
                                "type": {"literal": "Point"},
                                "coordinates": {"concat_list": ["longitude", "latitude"]},
                            },
                        },
                        {
                            "op": "with_columns",
                            "columns": {
                                "geometry": {"struct": ["type", "coordinates"]},
                                "properties": {"struct": ["name", "region"]},
                            },
                        },
                        {"op": "with_columns", "columns": {"type": {"literal": "Feature"}}},
                        {
                            "op": "with_columns",
                            "columns": {"geo_json": {"struct": ["type", "geometry", "properties"]}},
                        },
                    ],
                },
            ),
        ],
        folder_path=Path("."),
    )

    rows = list(sources["features"].iter_rows())
    assert len(rows) == 1
    assert rows[0]["geo_json"] == {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-105.0, 40.0]},
        "properties": {"name": "site-1", "region": "p1"},
    }


def test_membership_backend_rejects_an_unresolved_list_placeholder() -> None:
    data_file = DataFile(
        name="unresolved_membership",
        inline_table={"schema": {"technology": "string"}, "rows": []},
    )
    processing = TabularProcessing.model_validate(
        {
            "kind": "tabular",
            "steps": [
                {
                    "op": "with_columns",
                    "columns": {"included": {"is_in": ["technology", {"values": "{technologies}"}]}},
                }
            ],
        }
    )

    result = PolarsTabularBackend().process(
        pl.DataFrame({"technology": ["wind"]}).lazy(),
        processing=processing,
        sources={},
        data_file=data_file,
    )

    assert result.is_err()
    assert "Membership list placeholder must be resolved" in str(result.err())


def test_json_processing_does_not_import_polars(tmp_path: Path) -> None:
    code = """
import sys
from pathlib import Path
from r2x_core import DataFile, JSONProcessing
from r2x_core.reader import DataReader
path = Path(sys.argv[1])
path.write_text('{\"old\":\"value\"}', encoding='utf-8')
item = DataFile(name='lazy-json', fpath=path,
    proc_spec=JSONProcessing(steps=[{'op':'rename_keys','mapping':{'old':'new'}}]))
assert DataReader().read_data_files([item], folder_path=path.parent)['lazy-json'].data == {'new':'value'}
assert 'polars' not in sys.modules
"""
    env = os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "lazy.json")],
        check=True,
        timeout=30,
        env=env,
    )


def test_placeholders_resolve_each_supported_path_mode_before_reading(tmp_path: Path) -> None:
    path = tmp_path / "scenario_2030_profile.csv"
    path.write_text("value\n42\n", encoding="utf-8")
    files = [
        DataFile(name="absolute", fpath=tmp_path / "scenario_{year}_profile.csv"),
        DataFile(name="relative", relative_fpath="scenario_{year}_profile.csv"),
        DataFile(name="glob", glob="scenario_{year}_*.csv"),
    ]

    result = DataReader().read_data_files(files, folder_path=tmp_path, placeholders={"year": 2030})

    assert all(table_data(result[name]).collect().to_dicts() == [{"value": 42}] for name in result)


def test_hdf5_missing_group_obeys_requiredness(tmp_path: Path) -> None:
    path = tmp_path / "outputs.h5"
    with h5py.File(path, "w"):
        pass
    reader = DataReader()
    options = {"group_key": "fuel_price"}
    optional = DataFile(
        name="optional",
        fpath=path,
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
        reader=ReaderConfig(format="hdf5", options=options),
    )
    assert read_one(reader, optional, tmp_path) is None
    required = DataFile(name="required", fpath=path, reader=ReaderConfig(format="hdf5", options=options))
    with pytest.raises(ConfiguredGroupNotFoundError, match="fuel_price"):
        read_one(reader, required, tmp_path)


def test_hdf5_columnar_group_is_read_as_table(tmp_path: Path) -> None:
    path = tmp_path / "outputs.h5"
    with h5py.File(path, "w") as output:
        group = output.create_group("fuel_price")
        group.create_dataset("columns", data=np.array([b"i", b"Value"]))
        group.create_dataset("i", data=np.array([b"gas"]))
        group.create_dataset("Value", data=np.array([3.0]))
    item = DataFile(
        name="fuel_price",
        fpath=path,
        reader=ReaderConfig(
            format="hdf5",
            options={
                "group_key": "fuel_price",
                "columns_key": "columns",
                "columns_as_datasets": True,
            },
        ),
    )

    frame = table_data(read_one(DataReader(), item, tmp_path)).collect()

    assert frame.to_dict(as_series=False) == {"i": ["gas"], "Value": [3.0]}


def test_processing_errors_are_explicit_reader_errors(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    item = DataFile(
        name="invalid",
        fpath=path,
        proc_spec={"kind": "tabular", "steps": [{"op": "cast_columns", "column_schema": {"a": "invalid"}}]},
    )
    from r2x_core.exceptions import ReaderError

    with pytest.raises(ReaderError):
        read_one(DataReader(), item, tmp_path)


def test_initial_sources_compose_with_ordered_processing_and_placeholders(tmp_path: Path) -> None:
    capacity = TabularSource(
        pl.DataFrame(
            {
                "year": [2030, 2040, 2030],
                "technology": ["gas", "gas", "wind"],
                "capacity": [10.0, 11.0, 20.0],
            }
        ).lazy(),
        PolarsTabularBackend(),
    )
    fuels = TabularSource(
        pl.DataFrame({"technology": ["gas", "wind"], "fuel_type": ["natural gas", "wind"]}).lazy(),
        PolarsTabularBackend(),
    )
    initial_sources = {"capacity": capacity, "fuels": fuels}
    files = [
        DataFile(
            name="selected_capacity",
            source="capacity",
            proc_spec={
                "kind": "tabular",
                "steps": [{"op": "filter_columns", "filter_by": {"year": "{solve_year}"}}],
            },
        ),
        DataFile(
            name="generator_inputs",
            source="selected_capacity",
            proc_spec={
                "kind": "tabular",
                "steps": [
                    {"op": "join", "source": "fuels", "how": "left", "on": ["technology"]},
                    {
                        "op": "with_columns",
                        "columns": {"double_capacity": {"multiply": ["capacity", 2]}},
                    },
                ],
            },
        ),
    ]

    sources = DataReader().read_data_files(
        files,
        folder_path=tmp_path,
        placeholders={"solve_year": 2030},
        initial_sources=initial_sources,
    )

    assert set(sources) == {"capacity", "fuels", "selected_capacity", "generator_inputs"}
    assert list(initial_sources) == ["capacity", "fuels"]
    assert initial_sources["capacity"] is capacity
    assert initial_sources["fuels"] is fuels
    assert sources["generator_inputs"].data.collect().sort("technology").to_dicts() == [
        {
            "year": 2030,
            "technology": "gas",
            "capacity": 10.0,
            "fuel_type": "natural gas",
            "double_capacity": 20.0,
        },
        {
            "year": 2030,
            "technology": "wind",
            "capacity": 20.0,
            "fuel_type": "wind",
            "double_capacity": 40.0,
        },
    ]


def test_initial_sources_reject_invalid_names_and_values(tmp_path: Path) -> None:
    source = TabularSource(pl.DataFrame({"value": [1]}).lazy(), PolarsTabularBackend())

    with pytest.raises(ValueError, match="non-empty strings"):
        DataReader().read_data_files([], folder_path=tmp_path, initial_sources={"": source})

    invalid_sources = cast(DecodedSources, {"invalid": object()})
    with pytest.raises(TypeError, match="must be a DecodedSource"):
        DataReader().read_data_files([], folder_path=tmp_path, initial_sources=invalid_sources)


def test_initial_sources_reject_physical_output_name_collision(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("value\n1\n", encoding="utf-8")
    initial_sources = {"existing": TabularSource(pl.DataFrame({"value": [2]}).lazy(), PolarsTabularBackend())}

    with pytest.raises(ValueError, match="Duplicate named source 'existing'"):
        DataReader().read_data_files(
            [DataFile(name="existing", fpath=path)],
            folder_path=tmp_path,
            initial_sources=initial_sources,
        )

    assert initial_sources["existing"].data.collect().to_dicts() == [{"value": 2}]


def test_initial_sources_reject_duplicate_configured_names(tmp_path: Path) -> None:
    initial_sources = {"existing": TabularSource(pl.DataFrame({"value": [1]}).lazy(), PolarsTabularBackend())}

    with pytest.raises(ValueError, match="Duplicate named source 'existing'"):
        DataReader().read_data_files(
            [DataFile(name="existing", source="existing")],
            folder_path=tmp_path,
            initial_sources=initial_sources,
        )

    assert list(initial_sources) == ["existing"]


def test_source_selection_rejects_undeclared_candidate_even_with_fallback(tmp_path: Path) -> None:
    files = [
        DataFile(
            name="actual",
            inline_table={"schema": {"id": "int64"}, "rows": [{"id": 1}]},
        ),
        DataFile(
            name="selected",
            source_selection={
                "mode": "first_present",
                "sources": ["actaul"],
                "empty_fallback": {"schema": {"id": "int64"}, "rows": []},
            },
        ),
    ]

    with pytest.raises(ValueError, match="must be declared before 'selected'"):
        DataReader().read_data_files(files, folder_path=tmp_path)


def test_source_selection_rejects_forward_candidate_even_with_fallback(tmp_path: Path) -> None:
    files = [
        DataFile(
            name="selected",
            source_selection={
                "mode": "first_present",
                "sources": ["later"],
                "empty_fallback": {"schema": {"id": "int64"}, "rows": []},
            },
        ),
        DataFile(name="later", inline_table={"schema": {"id": "int64"}, "rows": [{"id": 1}]}),
    ]

    with pytest.raises(ValueError, match="must be declared before 'selected'"):
        DataReader().read_data_files(files, folder_path=tmp_path)


def test_source_selection_rejects_duplicate_candidate_names() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="candidates must be unique"):
        DataFile(
            name="selected",
            source_selection={"mode": "first_present", "sources": ["actual", "actual"]},
        )


def test_reader_rejects_duplicate_declared_names_even_when_optional_sources_are_absent(
    tmp_path: Path,
) -> None:
    optional = DataFile(
        name="optional",
        fpath=tmp_path / "absent.csv",
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
    )

    with pytest.raises(ValueError, match="Duplicate named source 'optional'"):
        DataReader().read_data_files([optional, optional], folder_path=tmp_path)


def test_first_nonempty_document_selection_matches_record_contract(tmp_path: Path) -> None:
    initial_sources = {
        "empty_object": DocumentSource({}, None),
        "empty_array": DocumentSource([], None),
    }
    files = [
        DataFile(
            name="object_record",
            source_selection={
                "mode": "first_nonempty",
                "sources": ["empty_object"],
                "empty_fallback": {"schema": {"id": "int64"}, "rows": []},
            },
        ),
        DataFile(
            name="array_fallback",
            source_selection={
                "mode": "first_nonempty",
                "sources": ["empty_array"],
                "empty_fallback": {"schema": {"id": "int64"}, "rows": []},
            },
        ),
    ]

    result = DataReader().read_data_files(files, folder_path=tmp_path, initial_sources=initial_sources)

    assert result["object_record"].is_empty() is False
    assert list(result["object_record"].iter_rows()) == [{}]
    assert result["array_fallback"].is_empty() is True
    assert result["array_fallback"].fields() == ["id"]


def test_first_nonempty_array_selection_uses_array_record_count(tmp_path: Path) -> None:
    initial_sources = {"empty_array": ArraySource({"value": np.array([])}, None)}
    item = DataFile(
        name="selected_array",
        source_selection={
            "mode": "first_nonempty",
            "sources": ["empty_array"],
            "empty_fallback": {"schema": {"value": "int64"}, "rows": []},
        },
    )

    result = DataReader().read_data_files([item], folder_path=tmp_path, initial_sources=initial_sources)

    assert initial_sources["empty_array"].is_empty() is True
    assert result["selected_array"].fields() == ["value"]
    assert result["selected_array"].is_empty() is True


def test_source_selection_without_matching_source_or_fallback_fails(tmp_path: Path) -> None:
    optional = DataFile(
        name="optional_costs",
        fpath=tmp_path / "absent.csv",
        info=FileInfo(requirement=FileRequirement.OPTIONAL),
    )
    selection = DataFile(
        name="costs",
        source_selection={"mode": "first_present", "sources": ["optional_costs"]},
    )

    with pytest.raises(ValueError, match="No source matched 'first_present'"):
        DataReader().read_data_files([optional, selection], folder_path=tmp_path)


def test_first_present_selects_market_when_default_file_is_absent(tmp_path: Path) -> None:
    market_path = tmp_path / "market.csv"
    market_path.write_text("technology,cost\ngas,3\n", encoding="utf-8")
    files = [
        DataFile(
            name="default_costs",
            fpath=tmp_path / "default.csv",
            info=FileInfo(requirement=FileRequirement.OPTIONAL),
        ),
        DataFile(name="market_costs", fpath=market_path),
        DataFile(
            name="reserve_costs",
            source_selection={"mode": "first_present", "sources": ["default_costs", "market_costs"]},
        ),
    ]

    result = DataReader().read_data_files(files, folder_path=tmp_path)

    assert list(result["reserve_costs"].iter_rows()) == [{"technology": "gas", "cost": 3}]


def test_first_present_preserves_present_empty_default_source(tmp_path: Path) -> None:
    default_path = tmp_path / "default.csv"
    default_path.write_text("technology,cost\n", encoding="utf-8")
    market_path = tmp_path / "market.csv"
    market_path.write_text("technology,cost\ngas,3\n", encoding="utf-8")
    files = [
        DataFile(name="default_costs", fpath=default_path),
        DataFile(name="market_costs", fpath=market_path),
        DataFile(
            name="reserve_costs",
            source_selection={"mode": "first_present", "sources": ["default_costs", "market_costs"]},
        ),
    ]

    result = DataReader().read_data_files(files, folder_path=tmp_path)

    assert list(result["reserve_costs"].iter_rows()) == []
    assert result["reserve_costs"].fields() == ["technology", "cost"]


def test_source_selection_skips_empty_sources_and_uses_typed_empty_fallback(tmp_path: Path) -> None:
    empty_path = tmp_path / "empty.csv"
    empty_path.write_text("technology,cost\n", encoding="utf-8")
    value_path = tmp_path / "candidate.csv"
    value_path.write_text("technology,cost\nwind,4\n", encoding="utf-8")
    files = [
        DataFile(name="primary", fpath=empty_path),
        DataFile(name="candidate", fpath=value_path),
        DataFile(
            name="selected",
            source_selection={
                "mode": "first_nonempty",
                "sources": ["primary", "candidate"],
                "empty_fallback": {
                    "schema": {"technology": "string", "cost": "float64"},
                    "rows": [],
                },
            },
        ),
        DataFile(
            name="missing_one",
            fpath=tmp_path / "missing-one.csv",
            info=FileInfo(requirement=FileRequirement.OPTIONAL),
        ),
        DataFile(
            name="missing_two",
            fpath=tmp_path / "missing-two.csv",
            info=FileInfo(requirement=FileRequirement.OPTIONAL),
        ),
        DataFile(
            name="all_absent",
            source_selection={
                "mode": "first_nonempty",
                "sources": ["missing_one", "missing_two"],
                "empty_fallback": {
                    "schema": {"technology": "string", "cost": "float64"},
                    "rows": [],
                },
            },
        ),
    ]

    result = DataReader().read_data_files(files, folder_path=tmp_path)

    assert list(result["selected"].iter_rows()) == [{"technology": "wind", "cost": 4.0}]
    assert list(result["all_absent"].iter_rows()) == []
    assert result["all_absent"].fields() == ["technology", "cost"]


def test_first_nonempty_primary_ownership_excludes_candidate_only_rows(tmp_path: Path) -> None:
    primary_path = tmp_path / "primary.csv"
    primary_path.write_text("id,capacity\n1,10\n", encoding="utf-8")
    candidate_path = tmp_path / "candidate.csv"
    candidate_path.write_text("id,latitude\n1,40\n2,50\n", encoding="utf-8")
    files = [
        DataFile(name="primary", fpath=primary_path),
        DataFile(name="candidate", fpath=candidate_path),
        DataFile(
            name="resource_base",
            source_selection={"mode": "first_nonempty", "sources": ["primary", "candidate"]},
        ),
        DataFile(
            name="resource_sites",
            source="resource_base",
            proc_spec={
                "kind": "tabular",
                "steps": [{"op": "join", "source": "candidate", "how": "left", "on": ["id"]}],
            },
        ),
    ]

    result = DataReader().read_data_files(files, folder_path=tmp_path)

    assert result["resource_sites"].data.collect().to_dicts() == [{"id": 1, "capacity": 10, "latitude": 40}]


def test_malformed_present_optional_source_is_not_replaced_by_selection(tmp_path: Path) -> None:
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{not json", encoding="utf-8")
    fallback_path = tmp_path / "market.csv"
    fallback_path.write_text("technology,cost\ngas,3\n", encoding="utf-8")

    with pytest.raises(JSONDecodeError):
        DataReader().read_data_files(
            [
                DataFile(
                    name="default_costs",
                    fpath=malformed_path,
                    info=FileInfo(requirement=FileRequirement.OPTIONAL),
                    reader=ReaderConfig(format="json"),
                ),
                DataFile(name="market_costs", fpath=fallback_path),
                DataFile(
                    name="reserve_costs",
                    source_selection={
                        "mode": "first_present",
                        "sources": ["default_costs", "market_costs"],
                    },
                ),
            ],
            folder_path=tmp_path,
        )


def test_inline_table_validates_raw_rows_resolves_placeholders_then_processes(tmp_path: Path) -> None:
    item = DataFile(
        name="years",
        inline_table={
            "schema": {"year": "string", "amount": "float64"},
            "rows": "{rows}",
        },
        proc_spec={
            "kind": "tabular",
            "steps": [{"op": "cast_columns", "column_schema": {"year": "int64"}}],
        },
    )

    sources = DataReader().read_data_files(
        [item],
        folder_path=tmp_path,
        placeholders={"rows": [{"year": "2030", "amount": 2.5}]},
    )
    frame = table_data(sources["years"])

    assert frame.collect().to_dicts() == [{"year": 2030, "amount": 2.5}]
    assert frame.collect_schema()["year"] == pl.Int64


@pytest.mark.parametrize(
    "row",
    [
        pytest.param({"name": "gas", "extra": 1}, id="extra-field"),
        pytest.param({}, id="missing-field"),
        pytest.param({"name": 3}, id="wrong-type"),
    ],
)
def test_inline_table_rejects_rows_that_do_not_match_its_schema(row: dict[str, object]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DataFile(
            name="strict_rows",
            inline_table={"schema": {"name": "string"}, "rows": [row]},
        )


@pytest.mark.parametrize(
    ("column_type", "value"),
    [
        pytest.param("int64", 2**63, id="int64-overflow"),
        pytest.param("int64", -(2**63) - 1, id="int64-underflow"),
        pytest.param("float64", 10**400, id="float-overflow"),
        pytest.param("float64", float("inf"), id="infinity"),
        pytest.param("float64", float("nan"), id="nan"),
    ],
)
def test_inline_table_rejects_values_outside_declared_scalar_range(column_type: str, value: object) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DataFile(
            name="out_of_range",
            inline_table={"schema": {"value": column_type}, "rows": [{"value": value}]},
        )


def test_inline_table_accepts_int64_boundary_values(tmp_path: Path) -> None:
    item = DataFile(
        name="int64_boundaries",
        inline_table={
            "schema": {"value": "int64"},
            "rows": [{"value": -(2**63)}, {"value": 2**63 - 1}],
        },
    )

    source = DataReader().read_data_files([item], folder_path=tmp_path)["int64_boundaries"]

    assert source.values("value") == [-(2**63), 2**63 - 1]


@pytest.mark.parametrize(
    ("schema", "row", "expected"),
    [
        ({"technology": "string"}, {"technology": "gas-cc"}, {"technology": "gas-cc", "fuel_type": None}),
        (
            {"technology": "string", "fuel_type": "string"},
            {"technology": "gas-cc", "fuel_type": "gas"},
            {"technology": "gas-cc", "fuel_type": "gas"},
        ),
    ],
)
def test_optional_column_expression_preserves_present_values_and_nulls_absent_values(
    tmp_path: Path,
    schema: dict[str, str],
    row: dict[str, str],
    expected: dict[str, str | None],
) -> None:
    item = DataFile(
        name="generator",
        inline_table={"schema": schema, "rows": [row]},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "with_columns",
                    "columns": {"normalized_fuel_type": {"optional_column": "fuel_type"}},
                }
            ],
        },
    )

    source = table_data(DataReader().read_data_files([item], folder_path=tmp_path)["generator"])

    assert source.collect().to_dicts() == [{**row, "normalized_fuel_type": expected["fuel_type"]}]


@pytest.mark.parametrize(
    ("excluded", "expected"),
    [
        (["can-imports"], [{"technology": "upv"}]),
        ([], [{"technology": "can-imports"}, {"technology": "upv"}]),
    ],
)
def test_mapping_expression_excludes_configured_values_without_matching_nulls(
    tmp_path: Path, excluded: list[str], expected: list[dict[str, str]]
) -> None:
    item = DataFile(
        name="generators",
        inline_table={
            "schema": {"technology": "string"},
            "rows": [{"technology": "can-imports"}, {"technology": "upv"}, {"technology": None}],
        },
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "filter",
                    "predicate": {"eq": [{"is_in": ["technology", {"values": excluded}]}, False]},
                }
            ],
        },
    )

    source = table_data(DataReader().read_data_files([item], folder_path=tmp_path)["generators"])

    assert source.collect().to_dicts() == expected


@pytest.mark.parametrize(
    ("values", "placeholder"),
    [([1, "gas"], False), ([True, 1], False), ([1, 1.5], False), ([1, "gas"], True)],
)
def test_mapping_expression_rejects_mixed_membership_values(
    tmp_path: Path, values: list[object], placeholder: bool
) -> None:
    configured_values: object = "{members}" if placeholder else values
    with pytest.raises(ValueError, match="same scalar type"):
        item = DataFile(
            name="mixed-membership",
            inline_table={"schema": {"technology": "string"}, "rows": []},
            proc_spec={
                "kind": "tabular",
                "steps": [
                    {
                        "op": "filter",
                        "predicate": {"is_in": ["technology", {"values": configured_values}]},
                    }
                ],
            },
        )
        DataReader().read_data_files([item], folder_path=tmp_path, placeholders={"members": values})


def test_mapping_expression_rejects_non_scalar_membership_values() -> None:
    with pytest.raises(ValueError):
        DataFile(
            name="invalid-membership",
            inline_table={"schema": {"id": "int64"}, "rows": []},
            proc_spec={
                "kind": "tabular",
                "steps": [
                    {
                        "op": "filter",
                        "predicate": {"is_in": ["id", {"values": [[1]]}]},
                    }
                ],
            },
        )


def test_inline_table_preserves_nulls_and_resolves_cell_placeholders(tmp_path: Path) -> None:
    item = DataFile(
        name="nullable_inline",
        inline_table={
            "schema": {"name": "string"},
            "rows": [{"name": None}, {"name": "{technology}"}],
        },
    )

    source = DataReader().read_data_files([item], folder_path=tmp_path, placeholders={"technology": "wind"})[
        "nullable_inline"
    ]

    assert source.values("name") == [None, "wind"]


def test_inline_table_accepts_boolean_schema_values(tmp_path: Path) -> None:
    item = DataFile(
        name="boolean_inline",
        inline_table={"schema": {"enabled": "bool"}, "rows": [{"enabled": True}, {"enabled": False}]},
    )

    source = DataReader().read_data_files([item], folder_path=tmp_path)["boolean_inline"]

    assert source.values("enabled") == [True, False]


def test_inline_table_source_constructor_rejects_unresolved_rows() -> None:
    table = InlineTable.model_validate({"schema": {"id": "int64"}, "rows": "{rows}"})

    with pytest.raises(ValueError, match="row placeholder was not resolved"):
        DataReader.create_inline_table_source(table)


def test_inline_table_missing_row_placeholder_is_an_error(tmp_path: Path) -> None:
    item = DataFile(
        name="missing_rows",
        inline_table={"schema": {"id": "int64"}, "rows": "{rows}"},
    )

    with pytest.raises(ValueError, match=r"Placeholder \{rows\} has no configured value"):
        DataReader().read_data_files([item], folder_path=tmp_path)


def test_source_selection_resolves_candidate_placeholders(tmp_path: Path) -> None:
    source = TabularSource(pl.DataFrame({"value": [3]}).lazy(), PolarsTabularBackend())
    item = DataFile(
        name="selected",
        source_selection={"mode": "first_present", "sources": ["{source_name}"]},
    )

    result = DataReader().read_data_files(
        [item],
        folder_path=tmp_path,
        placeholders={"source_name": "initial"},
        initial_sources={"initial": source},
    )

    assert result["selected"].values("value") == [3]


def test_inline_table_revalidates_placeholder_rows(tmp_path: Path) -> None:
    from pydantic import ValidationError

    item = DataFile(
        name="strict_placeholder_rows",
        inline_table={"schema": {"name": "string"}, "rows": "{rows}"},
    )

    with pytest.raises(ValidationError, match="exactly match schema keys"):
        DataReader().read_data_files(
            [item],
            folder_path=tmp_path,
            placeholders={"rows": [{"name": "wind", "extra": 1}]},
        )


def test_inline_table_mapping_expressions_support_exact_prefix_and_addition(tmp_path: Path) -> None:
    source = DataFile(
        name="derived",
        inline_table={
            "schema": {
                "technology": "string",
                "prefix": "string",
                "capacity": "float64",
                "hydro": "float64",
            },
            "rows": [
                {"technology": "wind_onshore", "prefix": "wind", "capacity": 10.0, "hydro": 2.0},
                {"technology": "gas", "prefix": "wind", "capacity": 8.0, "hydro": 1.0},
            ],
        },
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "with_columns",
                    "columns": {
                        "is_wind": {"starts_with": ["technology", "prefix"]},
                        "is_exact_wind": {"eq": ["technology", {"literal": "wind_onshore"}]},
                        "is_not_gas": {"neq": ["technology", {"literal": "gas"}]},
                        "capacity_with_hydro": {"add": ["capacity", "hydro"]},
                    },
                }
            ],
        },
    )

    frame = table_data(DataReader().read_data_files([source], folder_path=tmp_path)["derived"])

    assert frame.collect().to_dicts() == [
        {
            "technology": "wind_onshore",
            "prefix": "wind",
            "capacity": 10.0,
            "hydro": 2.0,
            "is_wind": True,
            "is_exact_wind": True,
            "is_not_gas": True,
            "capacity_with_hydro": 12.0,
        },
        {
            "technology": "gas",
            "prefix": "wind",
            "capacity": 8.0,
            "hydro": 1.0,
            "is_wind": False,
            "is_exact_wind": False,
            "is_not_gas": False,
            "capacity_with_hydro": 9.0,
        },
    ]


def test_pivot_aliases_do_not_collide_with_pivot_values(tmp_path: Path) -> None:
    source = DataFile(
        name="pivot_alias_collision",
        inline_table={
            "schema": {"region": "string", "period": "string", "load": "int64"},
            "rows": [{"region": "north", "period": "__r2x_pivot_index_0", "load": 3}],
        },
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "pivot",
                    "pivot_on": "period",
                    "group_by": ["region"],
                    "aggregate_on": {"load": "sum"},
                }
            ],
        },
    )

    frame = table_data(DataReader().read_data_files([source], folder_path=tmp_path)[source.name])

    assert frame.collect().to_dicts() == [{"region": "north", "__r2x_pivot_index_0": 3}]


def test_match_patterns_emits_defaulted_attributes_for_one_group(tmp_path: Path) -> None:
    source = DataFile(
        name="classified",
        inline_table={"schema": {"technology": "string"}, "rows": [{"technology": "upv_1"}]},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "match_patterns",
                    "column": "technology",
                    "label_column": "category",
                    "defaults": {"is_dispatchable": False, "unsupported": False},
                    "groups": [{"label": "solar", "prefixes": ["upv"]}],
                }
            ],
        },
    )

    frame = table_data(DataReader().read_data_files([source], folder_path=tmp_path)[source.name])

    assert frame.collect().to_dicts() == [
        {
            "technology": "upv_1",
            "category": "solar",
            "is_dispatchable": False,
            "unsupported": False,
        }
    ]


def test_match_patterns_allows_an_explicit_empty_pattern_list(tmp_path: Path) -> None:
    source = DataFile(
        name="exact_only",
        inline_table={"schema": {"technology": "string"}, "rows": [{"technology": "solar"}]},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "match_patterns",
                    "column": "technology",
                    "label_column": "category",
                    "groups": [{"label": "solar", "prefixes": [], "exact": ["solar"]}],
                }
            ],
        },
    )

    frame = table_data(DataReader().read_data_files([source], folder_path=tmp_path)[source.name])

    assert frame.collect().to_dicts() == [{"technology": "solar", "category": "solar"}]


@pytest.mark.parametrize(("case_sensitive", "expected"), [(True, []), (False, [{"technology": "GAS-CC", "category": "thermal"}])])
def test_match_patterns_uses_literal_case_policy(
    tmp_path: Path, case_sensitive: bool, expected: list[dict[str, str]]
) -> None:
    step = {
        "op": "match_patterns",
        "column": "technology",
        "label_column": "category",
        "groups": [{"label": "thermal", "prefixes": ["gas-"]}],
    }
    if not case_sensitive:
        step["case_sensitive"] = False
    source = DataFile(
        name="case_policy",
        inline_table={"schema": {"technology": "string"}, "rows": [{"technology": "GAS-CC"}]},
        proc_spec={"kind": "tabular", "steps": [step]},
    )

    frame = table_data(DataReader().read_data_files([source], folder_path=tmp_path)[source.name])

    assert frame.collect().to_dicts() == expected


def test_match_patterns_preserves_group_order_duplicates_and_literal_names(tmp_path: Path) -> None:
    source = DataFile(
        name="matches",
        inline_table={
            "schema": {"^tech.*$": "string"},
            "rows": [
                {"^tech.*$": "Wind.Ons-1"},
                {"^tech.*$": "Wind.Ons-1"},
                {"^tech.*$": "wind.*literal"},
                {"^tech.*$": "wind-x"},
                {"^tech.*$": None},
            ],
        },
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "match_patterns",
                    "column": "^tech.*$",
                    "label_column": "category",
                    "case_sensitive": False,
                    "defaults": {"is_dispatchable": False, "unsupported": False},
                    "groups": [
                        {
                            "label": "renewable",
                            "prefixes": ["wind.", "wind.*"],
                            "exact": ["WIND.ONS-1"],
                        },
                        {
                            "label": "wind",
                            "prefixes": ["wind."],
                            "attributes": {"is_dispatchable": True},
                        },
                    ],
                }
            ],
        },
    )

    frame = table_data(DataReader().read_data_files([source], folder_path=tmp_path)[source.name])

    assert frame.collect().to_dicts() == [
        {"^tech.*$": "Wind.Ons-1", "category": "renewable", "is_dispatchable": False, "unsupported": False},
        {"^tech.*$": "Wind.Ons-1", "category": "renewable", "is_dispatchable": False, "unsupported": False},
        {"^tech.*$": "wind.*literal", "category": "renewable", "is_dispatchable": False, "unsupported": False},
        {"^tech.*$": "Wind.Ons-1", "category": "wind", "is_dispatchable": True, "unsupported": False},
        {"^tech.*$": "Wind.Ons-1", "category": "wind", "is_dispatchable": True, "unsupported": False},
        {"^tech.*$": "wind.*literal", "category": "wind", "is_dispatchable": True, "unsupported": False},
    ]


def test_match_patterns_keeps_attribute_schema_for_empty_results(tmp_path: Path) -> None:
    step = {
        "op": "match_patterns",
        "column": "technology",
        "label_column": "category",
        "defaults": {"inferred": None, "null_only": None},
        "groups": [
            {"label": "solar", "prefixes": ["upv"], "attributes": {"inferred": True}},
            {"label": "wind", "prefixes": ["wind"]},
        ],
    }
    empty = DataFile(
        name="empty_matches",
        inline_table={"schema": {"technology": "string"}, "rows": []},
        proc_spec={"kind": "tabular", "steps": [step]},
    )
    populated = DataFile(
        name="populated_matches",
        inline_table={"schema": {"technology": "string"}, "rows": [{"technology": "upv_1"}]},
        proc_spec={"kind": "tabular", "steps": [step]},
    )

    empty_frame = table_data(DataReader().read_data_files([empty], folder_path=tmp_path)[empty.name])
    populated_frame = table_data(DataReader().read_data_files([populated], folder_path=tmp_path)[populated.name])

    assert empty_frame.collect().to_dicts() == []
    assert empty_frame.collect_schema() == populated_frame.collect_schema()
    assert empty_frame.collect_schema()["inferred"] == pl.Boolean
    assert empty_frame.collect_schema()["null_only"] == pl.Null


def test_match_patterns_merges_defaults_without_coercing_explicit_values(tmp_path: Path) -> None:
    source = DataFile(
        name="attribute_defaults",
        inline_table={"schema": {"technology": "string"}, "rows": [{"technology": "solar"}, {"technology": "wind"}]},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "match_patterns",
                    "column": "technology",
                    "label_column": "category",
                    "defaults": {
                        "is_dispatchable": False,
                        "unsupported": False,
                        "capacity": 9,
                        "description": "default",
                    },
                    "groups": [
                        {"label": "solar", "exact": ["solar"]},
                        {
                            "label": "wind",
                            "exact": ["wind"],
                            "attributes": {
                                "is_dispatchable": None,
                                "unsupported": True,
                                "capacity": 0,
                                "description": None,
                            },
                        },
                    ],
                }
            ],
        },
    )

    frame = table_data(DataReader().read_data_files([source], folder_path=tmp_path)[source.name])

    assert frame.collect().to_dicts() == [
        {
            "technology": "solar",
            "category": "solar",
            "is_dispatchable": False,
            "unsupported": False,
            "capacity": 9,
            "description": "default",
        },
        {
            "technology": "wind",
            "category": "wind",
            "is_dispatchable": None,
            "unsupported": True,
            "capacity": 0,
            "description": None,
        },
    ]


def test_match_patterns_round_trips_through_typed_json_schema() -> None:
    processing = TabularProcessing.model_validate(
        {
            "steps": [
                {
                    "op": "match_patterns",
                    "column": "technology",
                    "label_column": "category",
                    "defaults": {"is_dispatchable": False},
                    "groups": [{"label": "solar", "prefixes": ["upv"]}],
                }
            ]
        }
    )

    restored = TabularProcessing.model_validate_json(processing.model_dump_json())
    schema = TabularProcessing.model_json_schema()

    assert restored == processing
    assert restored.steps[0].case_sensitive is True
    assert "MatchPatternsStep" in schema["$defs"]
    assert "PatternMatchGroup" in schema["$defs"]
    assert set(schema["$defs"]["MatchPatternsStep"]["properties"]) >= {
        "column",
        "label_column",
        "groups",
        "defaults",
        "case_sensitive",
    }


@pytest.mark.parametrize(
    "step",
    [
        {"op": "match_patterns", "column": "technology", "label_column": "category", "groups": []},
        {
            "op": "match_patterns",
            "column": "technology",
            "label_column": "category",
            "groups": [{"label": "empty"}],
        },
        {
            "op": "match_patterns",
            "column": "technology",
            "label_column": "category",
            "groups": [{"label": "unknown", "prefixes": ["x"], "extra": 1}],
        },
        {
            "op": "match_patterns",
            "column": "technology",
            "label_column": "category",
            "groups": [{"label": "unknown", "prefixes": ["x"], "attributes": {"flag": True}}],
        },
        {
            "op": "match_patterns",
            "column": "technology",
            "label_column": "category",
            "defaults": {"category": False},
            "groups": [{"label": "unknown", "prefixes": ["x"]}],
        },
        {
            "op": "match_patterns",
            "column": "technology",
            "label_column": "category",
            "defaults": {"flag": False},
            "groups": [{"label": "unknown", "prefixes": ["x"], "attributes": {"flag": 1}}],
        },
        {
            "op": "match_patterns",
            "column": "technology",
            "label_column": "category",
            "defaults": {"flag": None},
            "groups": [
                {"label": "bool", "prefixes": ["x"], "attributes": {"flag": True}},
                {"label": "int", "prefixes": ["y"], "attributes": {"flag": 1}},
            ],
        },
        {
            "op": "match_patterns",
            "column": "technology",
            "label_column": "category",
            "groups": [{"label": "empty", "prefixes": [""]}],
        },
        {
            "op": "match_patterns",
            "column": "technology",
            "label_column": "category",
            "defaults": {"number": 2**63},
            "groups": [{"label": "overflow", "prefixes": ["x"]}],
        },
        {
            "op": "match_patterns",
            "column": "technology",
            "label_column": "category",
            "defaults": {"number": float("inf")},
            "groups": [{"label": "infinite", "prefixes": ["x"]}],
        },
    ],
)
def test_match_patterns_rejects_invalid_group_configuration(step: dict[str, object]) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DataFile(
            name="invalid_match_patterns",
            inline_table={"schema": {"technology": "string"}, "rows": []},
            proc_spec={"kind": "tabular", "steps": [step]},
        )


@pytest.mark.parametrize("existing_column", ["category", "dispatchable"])
def test_match_patterns_rejects_output_columns_that_already_exist(
    tmp_path: Path, existing_column: str
) -> None:
    source = DataFile(
        name="output_collision",
        inline_table={
            "schema": {"technology": "string", existing_column: "string"},
            "rows": [{"technology": "upv_1", existing_column: "existing"}],
        },
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "match_patterns",
                    "column": "technology",
                    "label_column": "category",
                    "defaults": {"dispatchable": False},
                    "groups": [{"label": "solar", "prefixes": ["upv"]}],
                }
            ],
        },
    )

    with pytest.raises(ReaderError, match="match_patterns output column") as captured:
        DataReader().read_data_files([source], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, ValueError)


def test_match_patterns_rejects_non_string_input_with_cause(tmp_path: Path) -> None:
    source = DataFile(
        name="non_string_pattern_input",
        inline_table={"schema": {"technology": "int64"}, "rows": [{"technology": 123}]},
        proc_spec={
            "kind": "tabular",
            "steps": [
                {
                    "op": "match_patterns",
                    "column": "technology",
                    "label_column": "category",
                    "groups": [{"label": "solar", "prefixes": ["1"]}],
                }
            ],
        },
    )

    with pytest.raises(ReaderError, match="must have a string dtype") as captured:
        DataReader().read_data_files([source], folder_path=tmp_path)

    assert isinstance(captured.value.__cause__, ValueError)
