"""Build ordered processing specs for behavioral parity tests."""

from __future__ import annotations

from functools import partial
from typing import Any

import polars as pl
from rust_ok import Err

from r2x_core.datafile import DataFile
from r2x_core.json_adapter.processing import drop_keys, filter_records, rename_keys, select_keys
from r2x_core.models import (
    AggregateStep,
    CastColumnsStep,
    DropColumnsStep,
    FillNullStep,
    FilterColumnsStep,
    JSONProcessing,
    LowercaseStep,
    MappingStep,
    PivotStep,
    RenameColumnsStep,
    ReplaceValuesStep,
    ScaleColumnsStep,
    SelectColumnsStep,
    SortStep,
    SplitColumnsStep,
    StripCharactersStep,
    TabularProcessing,
    UniqueStep,
    UnpivotColumnsStep,
)
from r2x_core.polars_adapter import PolarsTabularBackend
from r2x_core.polars_adapter.processing import apply_polars_step
from r2x_core.result import TabularTransformResult


def tabular_processing(**options: Any) -> TabularProcessing:
    """Translate a former compact fixture into equivalent ordered operations."""
    remaining = dict(options)
    steps: list[MappingStep] = []
    lowercase = remaining.pop("lowercase", False)
    if lowercase is not False:
        steps.append(LowercaseStep(op="lowercase", lowercase=lowercase))
    for name, step_type, operation, field in (
        ("drop_columns", DropColumnsStep, "drop_columns", "drop_columns"),
        ("unpivot_on", UnpivotColumnsStep, "unpivot_columns", "columns"),
        ("split_column", SplitColumnsStep, "split_columns", "split_column"),
        ("column_mapping", RenameColumnsStep, "rename_columns", "column_mapping"),
        ("replace_values", ReplaceValuesStep, "replace_values", "replace_values"),
        ("strip_chars", StripCharactersStep, "strip_characters", "strip_chars"),
        ("column_schema", CastColumnsStep, "cast_columns", "column_schema"),
        ("scale", ScaleColumnsStep, "scale_columns", "scale"),
        ("fill_null", FillNullStep, "fill_null", "fill_null"),
        ("filter_by", FilterColumnsStep, "filter_columns", "filter_by"),
    ):
        value = remaining.pop(name, None)
        if value:
            steps.append(step_type.model_validate({"op": operation, field: value}))

    pivot_on = remaining.pop("pivot_on", None)
    group_by = remaining.pop("group_by", None)
    aggregate_on = remaining.pop("aggregate_on", None)
    if pivot_on is not None:
        steps.append(
            PivotStep.model_validate(
                {
                    "op": "pivot",
                    "pivot_on": pivot_on,
                    "group_by": group_by or [],
                    "aggregate_on": aggregate_on or {},
                }
            )
        )
    elif aggregate_on is not None or group_by is not None:
        steps.append(
            AggregateStep.model_validate(
                {"op": "aggregate", "aggregate_on": aggregate_on or {}, "group_by": group_by or []}
            )
        )
    if distinct_on := remaining.pop("distinct_on", None):
        steps.append(UniqueStep(op="unique", subset=distinct_on))
    if sort_by := remaining.pop("sort_by", None):
        directions = {"ascending": "asc", "descending": "desc"}
        steps.append(
            SortStep.model_validate(
                {"op": "sort", "by": {k: directions.get(v, v) for k, v in sort_by.items()}}
            )
        )
    if select_columns := remaining.pop("select_columns", None):
        steps.append(SelectColumnsStep(op="select_columns", select_columns=select_columns))
    return TabularProcessing.model_validate({"steps": steps, **remaining})


def json_processing(**options: Any) -> JSONProcessing:
    """Translate a former compact JSON fixture into equivalent ordered operations."""
    remaining = dict(options)
    steps: list[dict[str, Any]] = []
    for name, operation, field in (
        ("key_mapping", "rename_keys", "mapping"),
        ("drop_keys", "drop_keys", "keys"),
        ("filter_by", "filter", "where"),
        ("replace_values", "replace_values", "mapping"),
        ("select_keys", "select_keys", "keys"),
    ):
        value = remaining.pop(name, None)
        if value:
            steps.append({"op": operation, field: value})
    return JSONProcessing.model_validate({"steps": steps, **remaining})


def process_tabular_data(
    data_frame: pl.LazyFrame, *, data_file: DataFile, proc_spec: TabularProcessing
) -> pl.LazyFrame:
    """Run the spec through the production tabular backend."""
    result = PolarsTabularBackend().process(data_frame, data_file=data_file, proc_spec=proc_spec)
    if isinstance(result, Err):
        raise result.err()
    return result.unwrap()


def apply_one_step(
    data_frame: pl.LazyFrame,
    *,
    data_file: DataFile,
    proc_spec: TabularProcessing,
    step_type: type[MappingStep],
) -> TabularTransformResult[pl.LazyFrame]:
    """Run one operation for focused regression tests."""
    step = next((item for item in proc_spec.steps if isinstance(item, step_type)), None)
    result = data_frame if step is None else apply_polars_step(data_frame, step=step, data_file=data_file)
    return TabularTransformResult(data_frame=result, schema_names=result.collect_schema().names())


pl_apply_filters = partial(apply_one_step, step_type=FilterColumnsStep)
pl_drop_columns = partial(apply_one_step, step_type=DropColumnsStep)
pl_rename_columns = partial(apply_one_step, step_type=RenameColumnsStep)
pl_cast_schema = partial(apply_one_step, step_type=CastColumnsStep)
pl_select_columns = partial(apply_one_step, step_type=SelectColumnsStep)
pl_lowercase = partial(apply_one_step, step_type=LowercaseStep)
pl_split_columns = partial(apply_one_step, step_type=SplitColumnsStep)
pl_strip_chars = partial(apply_one_step, step_type=StripCharactersStep)
pl_scale = partial(apply_one_step, step_type=ScaleColumnsStep)
pl_fill_null = partial(apply_one_step, step_type=FillNullStep)
pl_aggregate = partial(apply_one_step, step_type=AggregateStep)
pl_pivot_on = partial(apply_one_step, step_type=PivotStep)
pl_distinct = partial(apply_one_step, step_type=UniqueStep)
pl_sort = partial(apply_one_step, step_type=SortStep)
pl_unpivot_on = partial(apply_one_step, step_type=UnpivotColumnsStep)
pl_replace_values = partial(apply_one_step, step_type=ReplaceValuesStep)


def json_rename_keys(value: Any, *, data_file: DataFile, proc_spec: JSONProcessing) -> Any:
    step = next((item for item in proc_spec.steps if item.op == "rename_keys"), None)
    return value if step is None else rename_keys(value, mapping=step.mapping)


def json_drop_columns(value: Any, *, data_file: DataFile, proc_spec: JSONProcessing) -> Any:
    step = next((item for item in proc_spec.steps if item.op == "drop_keys"), None)
    return value if step is None else drop_keys(value, keys=frozenset(step.keys))


def json_select_columns(value: Any, *, data_file: DataFile, proc_spec: JSONProcessing) -> Any:
    return json_select_keys(value, data_file=data_file, proc_spec=proc_spec)


def json_apply_filters(value: Any, *, data_file: DataFile, proc_spec: JSONProcessing) -> Any:
    step = next((item for item in proc_spec.steps if item.op == "filter"), None)
    return value if step is None else filter_records(value, where=step.where)


def json_select_keys(value: Any, *, data_file: DataFile, proc_spec: JSONProcessing) -> Any:
    step = next((item for item in proc_spec.steps if item.op == "select_keys"), None)
    return value if step is None else select_keys(value, keys=frozenset(step.keys))
