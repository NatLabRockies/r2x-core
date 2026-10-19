"""Typed configuration models for tables prepared from files and named frames."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .datafile import ColumnPredicate, DataFile, TabularProcessing
from .processors import apply_processing
from .sources import FirstPresentSource, RuntimeSource

NonEmptyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PreparedTableError(ValueError):
    """A named prepared table could not be read or validated."""


class SelectFirst(BaseModel):
    """Stable duplicate-key selection policy for a many-to-one join."""

    order_by: dict[NonEmptyName, Literal["asc", "desc"]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", frozen=True)


class AsOfJoinSpec(BaseModel):
    """Backward temporal lookup between configured left and right columns."""

    left_on: NonEmptyName
    right_on: NonEmptyName
    allow_exact_matches: bool = False

    model_config = ConfigDict(extra="forbid", frozen=True)


class TableJoin(BaseModel):
    """Explicit relational join from one physical, table, or named frame source."""

    source: NonEmptyName
    on: dict[NonEmptyName, NonEmptyName] = Field(default_factory=dict)
    columns: dict[NonEmptyName, NonEmptyName] = Field(default_factory=dict)
    how: Literal["left", "inner", "cross", "semi"] = "left"
    cardinality: Literal["m:1", "1:m", "m:m"] = "m:1"
    broadcast: Literal["left", "right"] | None = None
    select_first: SelectFirst | None = None
    allow_null_left_keys: bool = False
    missing_source: Literal["error", "skip", "null"] = Field(
        default="error",
        description="Behavior when the join source is absent or returns no data.",
    )
    required_when: list[ColumnPredicate] = Field(
        default_factory=list,
        description="Predicates that make an absent join source required when any left row matches.",
    )
    asof: AsOfJoinSpec | None = None
    right_filter: list[ColumnPredicate] = Field(default_factory=list)
    ensure_null_columns: list[NonEmptyName] = Field(
        default_factory=list,
        description="Explicit optional right-source columns to add as null before filtering and joining.",
    )

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_columns(self) -> TableJoin:
        """Require unique keys and payload, without repeating join keys as payload."""
        if self.how == "cross":
            if self.on or self.broadcast is not None:
                raise ValueError("cross joins cannot declare keyed or broadcast join columns")
            if self.cardinality != "m:m":
                raise ValueError("cross joins require cardinality='m:m'")
            if self.select_first is not None or self.asof is not None:
                raise ValueError("cross joins reject select_first and temporal joins")
            if self.missing_source != "error":
                raise ValueError("cross join sources cannot be optional")
        elif self.broadcast is None and not self.on:
            raise ValueError("keyed joins require at least one join key")
        if self.how == "semi":
            if self.broadcast is not None or self.cardinality != "m:1":
                raise ValueError("semi joins require keyed m:1 cardinality")
            if self.columns:
                raise ValueError("semi joins do not accept payload columns")
            if self.select_first is not None or self.asof is not None:
                raise ValueError("semi joins reject select_first and temporal joins")
            if self.missing_source != "error":
                raise ValueError("semi join sources cannot be optional")
        elif not self.columns:
            raise ValueError("joins require at least one payload column")
        if self.broadcast is not None and self.on:
            raise ValueError("broadcast joins cannot declare keyed join columns")
        if len(set(self.on.values())) != len(self.on):
            raise ValueError("right join-key references must be unique")
        if (
            self.cardinality != "m:1"
            and self.how not in {"inner", "cross"}
            and not (self.broadcast == "left" and self.how == "left")
        ):
            raise ValueError("expanding joins require how='inner' except left-singleton broadcasts")
        if self.broadcast is not None:
            expected_cardinality = "1:m" if self.broadcast == "left" else "m:1"
            if self.cardinality != expected_cardinality:
                raise ValueError(
                    f"broadcast={self.broadcast!r} requires cardinality={expected_cardinality!r}"
                )
            if self.select_first is not None:
                raise ValueError("broadcast joins reject select_first; singleton inputs must be exact")
            if self.asof is not None:
                raise ValueError("broadcast joins cannot be temporal joins")
        if self.cardinality != "m:1" and self.select_first is not None:
            raise ValueError("select_first is only valid for m:1 joins")
        if self.missing_source != "error" and self.how != "left":
            raise ValueError("missing_source='skip' or 'null' requires how='left'")
        if self.asof is not None and (self.how != "left" or self.cardinality != "m:1"):
            raise ValueError("asof joins require how='left' and cardinality='m:1'")
        if self.asof is not None and self.select_first is not None:
            raise ValueError("asof joins reject duplicate temporal keys instead of selecting a row")
        if self.asof is not None and (self.asof.left_on in self.on or self.asof.right_on in self.on.values()):
            raise ValueError("asof time columns cannot also be equality join keys")
        if self.asof is not None and self.asof.right_on in self.columns:
            raise ValueError("asof right time column cannot also be a payload column")
        if len(set(self.ensure_null_columns)) != len(self.ensure_null_columns):
            raise ValueError("ensure_null_columns must be unique")
        required_right_keys = set(self.on.values()) | ({self.asof.right_on} if self.asof else set())
        if set(self.ensure_null_columns) & required_right_keys:
            raise ValueError("ensure_null_columns cannot contain join keys")
        if len(set(self.columns.values())) != len(self.columns):
            raise ValueError("join payload output columns must be unique")
        source_overlap = set(self.on.values()) & set(self.columns)
        if source_overlap:
            raise ValueError(
                f"join payload references cannot repeat right join keys: {sorted(source_overlap)}"
            )
        output_overlap = set(self.on.values()) & set(self.columns.values())
        if output_overlap:
            raise ValueError(f"join payload outputs cannot repeat right join keys: {sorted(output_overlap)}")
        return self


class PreparedTable(BaseModel):
    """A table prepared from physical files, table dependencies, or named frames."""

    name: NonEmptyName
    source: NonEmptyName
    frame_sources: list[NonEmptyName] = Field(default_factory=list)
    required_columns: Annotated[list[NonEmptyName], Field(min_length=1)]
    non_null_columns: list[NonEmptyName] = Field(default_factory=list)
    unique_keys: list[list[NonEmptyName]] = Field(default_factory=list)
    joins: list[TableJoin] = Field(default_factory=list)
    proc_spec: TabularProcessing | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_required_columns(self) -> PreparedTable:
        """Require unique output columns and constrain non-null checks to them."""
        if len(set(self.required_columns)) != len(self.required_columns):
            raise ValueError("required_columns must be unique")
        if len(set(self.non_null_columns)) != len(self.non_null_columns):
            raise ValueError("non_null_columns must be unique")
        undeclared = sorted(set(self.non_null_columns) - set(self.required_columns))
        if undeclared:
            raise ValueError(f"non_null_columns must be required_columns: {undeclared}")
        key_sets = [tuple(keys) for keys in self.unique_keys]
        if any(not keys or len(set(keys)) != len(keys) for keys in self.unique_keys):
            raise ValueError("unique_keys must contain non-empty distinct column names")
        if len(set(key_sets)) != len(key_sets):
            raise ValueError("unique_keys must be unique")
        undeclared_keys = sorted(
            {column for keys in self.unique_keys for column in keys} - set(self.required_columns)
        )
        if undeclared_keys:
            raise ValueError(f"unique_keys columns must be required_columns: {undeclared_keys}")
        if len(set(self.frame_sources)) != len(self.frame_sources):
            raise ValueError("frame_sources must be unique")
        used_frame_sources = ({self.source} | {join.source for join in self.joins}) & set(self.frame_sources)
        unused_frame_sources = sorted(set(self.frame_sources) - used_frame_sources)
        if unused_frame_sources:
            raise ValueError(f"frame_sources contains unused names: {unused_frame_sources}")
        return self


class FileMapping(BaseModel):
    """Validated physical, runtime-source, and prepared-table mapping."""

    files: list[DataFile]
    tables: list[PreparedTable]
    sources: list[RuntimeSource] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_names_and_sources(self) -> FileMapping:
        """Ensure names, sources, and the prepared-table dependency graph are valid."""
        file_names = [data_file.name for data_file in self.files]
        table_names = [table.name for table in self.tables]
        source_names = [source.name for source in self.sources]
        if len(set(file_names)) != len(file_names):
            raise ValueError("file mapping contains duplicate physical file names")
        if len(set(table_names)) != len(table_names):
            raise ValueError("file mapping contains duplicate prepared table names")
        if len(set(source_names)) != len(source_names):
            raise ValueError("file mapping contains duplicate runtime source names")
        collisions = (
            (set(file_names) & set(table_names))
            | (set(file_names) & set(source_names))
            | (set(table_names) & set(source_names))
        )
        if collisions:
            raise ValueError(f"file, source, and table names must be unique: {sorted(collisions)}")

        known_files = set(file_names)
        known_tables = set(table_names)
        known_sources = set(source_names)
        source_by_name = {source.name: source for source in self.sources}
        for source in self.sources:
            if not isinstance(source, FirstPresentSource):
                continue
            candidates = set(source.candidates)
            unknown_candidates = sorted(candidates - known_files - known_sources)
            if unknown_candidates:
                raise ValueError(
                    f"First-present source {source.name!r} references unknown candidate(s): "
                    f"{unknown_candidates}"
                )
            nested_choices = sorted(
                name
                for name in candidates & known_sources
                if isinstance(source_by_name[name], FirstPresentSource)
            )
            if nested_choices:
                raise ValueError(
                    f"First-present source {source.name!r} cannot select another first-present source: "
                    f"{nested_choices}"
                )
            for data_file in self.files:
                if data_file.name in candidates and not (data_file.info and data_file.info.is_optional):
                    raise ValueError(
                        f"First-present source {source.name!r} physical candidate {data_file.name!r} "
                        "must be optional"
                    )
        for table in self.tables:
            frame_sources = set(table.frame_sources)
            ambiguous = sorted(frame_sources & (known_files | known_tables))
            if ambiguous:
                raise ValueError(
                    f"prepared table {table.name!r} frame source name(s) collide with registered data: {ambiguous}"
                )
            sources = {table.source, *(join.source for join in table.joins)}
            undeclared_runtime = sorted((sources & known_sources) - frame_sources)
            if undeclared_runtime:
                raise ValueError(
                    f"prepared table {table.name!r} runtime source(s) must be declared in frame_sources: "
                    f"{undeclared_runtime}"
                )
            unknown = sorted(sources - known_files - known_tables - known_sources - frame_sources)
            if unknown:
                raise ValueError(
                    f"prepared table {table.name!r} references unknown file, table, runtime, or frame source(s): "
                    f"{unknown}"
                )
            if table.source not in known_files | known_tables | known_sources | frame_sources:
                raise ValueError(
                    f"prepared table {table.name!r} source {table.source!r} must be a file, table, runtime, "
                    "or declared frame source"
                )

        dependencies = {
            table.name: {
                source
                for source in {table.source, *(join.source for join in table.joins)}
                if source in known_tables
            }
            for table in self.tables
        }
        states: dict[str, int] = {}
        path: list[str] = []

        def visit(table_name: str) -> None:
            """Reject recursive table dependencies before any source is read."""
            state = states.get(table_name, 0)
            if state == 2:
                return
            if state == 1:
                start = path.index(table_name)
                cycle = [*path[start:], table_name]
                raise ValueError(f"prepared table dependency cycle: {' -> '.join(cycle)}")
            states[table_name] = 1
            path.append(table_name)
            for dependency in sorted(dependencies[table_name]):
                visit(dependency)
            path.pop()
            states[table_name] = 2

        for table_name in sorted(dependencies):
            visit(table_name)
        return self


class FileMappingDocument(BaseModel):
    """JSON envelope used to load file mappings before resolving file paths."""

    files: list[dict[str, object]]
    tables: list[PreparedTable]
    sources: list[RuntimeSource] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def _join_asof(
    left: pl.DataFrame,
    right: pl.DataFrame,
    *,
    table: PreparedTable,
    join: TableJoin,
) -> pl.DataFrame:
    """Join strict or inclusive prior rows while retaining left-row identity and order."""
    spec = join.asof
    if spec is None:
        raise ValueError("asof join specification is required")

    by_left = list(join.on)
    by_right = list(join.on.values())
    temporal_keys = [*by_right, spec.right_on]
    if right.select(temporal_keys).is_duplicated().any():
        raise PreparedTableError(
            f"Prepared table {table.name!r} join source {join.source!r} has duplicate temporal keys "
            f"for {[*join.on.values(), spec.right_on]}"
        )

    output_columns = [*left.columns, *join.columns.values()]
    reserved_names = set(left.columns) | set(right.columns) | set(join.columns.values())

    def internal_name(base: str) -> str:
        """Choose a temporary name outside input and configured output namespaces."""
        candidate = base
        while candidate in reserved_names:
            candidate = f"_{candidate}"
        reserved_names.add(candidate)
        return candidate

    order_column = internal_name("__prepared_table_order")
    right_time_column = internal_name("__prepared_table_time")
    ordered_columns = [*output_columns, order_column]
    left = left.with_row_index(order_column)
    matchable = pl.all_horizontal([pl.col(column).is_not_null() for column in [*by_left, spec.left_on]])
    matched_left = left.filter(matchable).sort(spec.left_on, maintain_order=True)
    unmatched_left = left.filter(~matchable)

    right_columns = list(dict.fromkeys([*by_right, spec.right_on, *join.columns]))
    right_for_join = (
        right.select(right_columns).rename({spec.right_on: right_time_column}).rename(join.columns)
    )
    try:
        matched = matched_left.join_asof(
            right_for_join.sort(right_time_column, maintain_order=True),
            left_on=spec.left_on,
            right_on=right_time_column,
            by_left=by_left,
            by_right=by_right,
            strategy="backward",
            allow_exact_matches=spec.allow_exact_matches,
            coalesce=True,
            check_sortedness=False,
        ).select(ordered_columns)
    except pl.exceptions.PolarsError as exc:
        raise PreparedTableError(
            f"Prepared table {table.name!r} failed temporal join from source {join.source!r}: {exc}"
        ) from exc

    if unmatched_left.height:
        unmatched_left = unmatched_left.with_columns(
            pl.lit(None, dtype=right.schema[source]).alias(output) for source, output in join.columns.items()
        ).select(ordered_columns)
        matched = pl.concat([matched, unmatched_left])
    return matched.sort(order_column, maintain_order=True).drop(order_column)


def _required_when_matches(
    left: pl.DataFrame,
    /,
    *,
    table: PreparedTable,
    join: TableJoin,
    placeholders: dict[str, Any] | None,
) -> bool:
    """Check whether any current left row makes this join source required."""
    if not join.required_when:
        return False
    processing = apply_processing(
        left.lazy(),
        data_file=table,
        proc_spec=TabularProcessing(filter_rows=join.required_when),
        placeholders=placeholders,
    )
    if processing.is_err():
        error = processing.err()
        raise PreparedTableError(
            f"Prepared table {table.name!r} could not evaluate required_when for source {join.source!r}: {error}"
        ) from error
    filtered = processing.ok()
    if isinstance(filtered, pl.LazyFrame):
        try:
            return filtered.select(pl.len()).collect().item() > 0
        except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
            raise PreparedTableError(
                f"Prepared table {table.name!r} could not evaluate required_when for source {join.source!r}: {exc}"
            ) from exc
    if isinstance(filtered, pl.DataFrame):
        return filtered.height > 0
    raise PreparedTableError(
        f"Prepared table {table.name!r} required_when for source {join.source!r} returned a non-tabular result"
    )


def _join_broadcast(
    left: pl.DataFrame,
    right: pl.DataFrame,
    /,
    *,
    table: PreparedTable,
    join: TableJoin,
) -> pl.DataFrame:
    """Apply a left- or right-singleton Cartesian join with left-join empty semantics."""
    if join.broadcast == "right" and right.height != 1:
        raise PreparedTableError(
            f"Prepared table {table.name!r} broadcast source 'right' for join {join.source!r} "
            f"must contain exactly one row (singleton cardinality), got {right.height}"
        )

    overlapping = sorted(set(join.columns.values()) & set(left.columns))
    if overlapping:
        raise PreparedTableError(
            f"Prepared table {table.name!r} join source {join.source!r} has overlapping payload "
            f"column(s): {overlapping}"
        )
    payload = right.select(pl.col(source).alias(output) for source, output in join.columns.items())
    if not payload.height and join.broadcast == "left":
        base = left if join.how == "left" else left.head(0)
        return base.with_columns(
            pl.lit(None, dtype=right.schema[source]).alias(output) for source, output in join.columns.items()
        )
    try:
        return left.join(payload, how="cross", maintain_order="left")
    except pl.exceptions.PolarsError as exc:
        raise PreparedTableError(
            f"Prepared table {table.name!r} failed broadcast join from source {join.source!r}: {exc}"
        ) from exc


def prepare_table_frames(
    table: PreparedTable,
    /,
    frames: Mapping[str, pl.DataFrame | pl.LazyFrame | None],
    *,
    placeholders: dict[str, Any] | None = None,
) -> pl.LazyFrame | None:
    """Join and process named tabular frames using one prepared-table recipe."""
    declared_sources = {table.source, *(join.source for join in table.joins)}
    unexpected_sources = sorted(set(frames) - declared_sources)
    if unexpected_sources:
        raise PreparedTableError(
            f"Prepared table {table.name!r} received undeclared frame source(s): {unexpected_sources}"
        )

    source_cache: dict[str, pl.DataFrame | None] = {}

    def collect_source(source: str, *, required: bool = False) -> pl.DataFrame | None:
        """Materialize each named source once for this recipe execution."""
        if source in source_cache:
            data = source_cache[source]
        elif source not in frames:
            data = None
            source_cache[source] = None
        else:
            supplied = frames[source]
            if supplied is None:
                data = None
            elif isinstance(supplied, pl.DataFrame):
                data = supplied
            elif isinstance(supplied, pl.LazyFrame):
                try:
                    data = supplied.collect()
                except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
                    raise PreparedTableError(
                        f"Prepared table {table.name!r} failed while collecting source {source!r}: {exc}"
                    ) from exc
            else:
                raise PreparedTableError(
                    f"Prepared table {table.name!r} source {source!r} returned "
                    f"{type(supplied).__name__}, expected a Polars DataFrame or LazyFrame"
                )
            source_cache[source] = data

        if data is None and required:
            if source in frames:
                raise PreparedTableError(
                    f"Prepared table {table.name!r} required source {source!r}, but it returned no data"
                )
            raise PreparedTableError(f"Prepared table {table.name!r} has no frame for source {source!r}")
        return data

    result = collect_source(table.source, required=True)
    if result is None:
        return None

    for join in table.joins:
        if join.broadcast == "left" and result.height != 1:
            raise PreparedTableError(
                f"Prepared table {table.name!r} broadcast source 'left' for join {join.source!r} "
                f"must contain exactly one row (singleton cardinality), got {result.height}"
            )
        required = _required_when_matches(
            result,
            table=table,
            join=join,
            placeholders=placeholders,
        )
        right = collect_source(join.source)
        if right is None:
            if required:
                raise PreparedTableError(
                    f"Prepared table {table.name!r} required source {join.source!r} because required_when matched"
                )
            if join.missing_source == "error":
                raise PreparedTableError(
                    f"Prepared table {table.name!r} required source {join.source!r} is missing for this join"
                )
            if join.missing_source == "null":
                overlapping = sorted(set(join.columns.values()) & set(result.columns))
                if overlapping:
                    raise PreparedTableError(
                        f"Prepared table {table.name!r} join source {join.source!r} has overlapping payload "
                        f"column(s): {overlapping}"
                    )
                result = result.with_columns(pl.lit(None).alias(column) for column in join.columns.values())
            continue

        right_columns = [
            *join.on.values(),
            *join.columns,
            *(join.select_first.order_by if join.select_first else {}),
            *([join.asof.right_on] if join.asof else []),
            *(predicate.column for predicate in join.right_filter),
        ]
        left_columns = [*join.on, *([join.asof.left_on] if join.asof else [])]
        missing_optional = sorted(set(join.ensure_null_columns) - set(right.columns))
        if missing_optional:
            right = right.with_columns(pl.lit(None).alias(column) for column in missing_optional)

        for source, source_frame, columns in (
            (join.source, right, right_columns),
            (table.source, result, left_columns),
        ):
            missing = sorted(set(columns) - set(source_frame.columns))
            if missing:
                raise PreparedTableError(
                    f"Prepared table {table.name!r} source {source!r} is missing column(s): {missing}"
                )
        overlapping = sorted(set(join.columns.values()) & set(result.columns))
        if overlapping:
            raise PreparedTableError(
                f"Prepared table {table.name!r} join source {join.source!r} has overlapping payload "
                f"column(s): {overlapping}"
            )

        if join.right_filter:
            processing = apply_processing(
                right.lazy(),
                data_file=table,
                proc_spec=TabularProcessing(filter_rows=join.right_filter),
                placeholders=placeholders,
            )
            if processing.is_err():
                error = processing.err()
                raise PreparedTableError(
                    f"Prepared table {table.name!r} could not filter source {join.source!r}: {error}"
                ) from error
            filtered = processing.ok()
            if not isinstance(filtered, pl.LazyFrame):
                raise PreparedTableError(
                    f"Prepared table {table.name!r} filtering source {join.source!r} returned a non-lazy frame"
                )
            try:
                right = filtered.collect()
            except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
                raise PreparedTableError(
                    f"Prepared table {table.name!r} failed filtering source {join.source!r}: {exc}"
                ) from exc

        left_key_columns = [*join.on, *([join.asof.left_on] if join.asof else [])]
        if not join.allow_null_left_keys and any(
            result.get_column(column).null_count() > 0 for column in left_key_columns
        ):
            raise PreparedTableError(
                f"Prepared table {table.name!r} source {table.source!r} contains null join key(s) "
                f"for join source {join.source!r}: {left_key_columns}"
            )
        right_key_columns = [*join.on.values(), *([join.asof.right_on] if join.asof else [])]
        if any(right.get_column(column).null_count() > 0 for column in right_key_columns):
            raise PreparedTableError(
                f"Prepared table {table.name!r} source {join.source!r} contains null join key(s): "
                f"{right_key_columns}"
            )

        if join.asof is not None:
            result = _join_asof(result, right, table=table, join=join)
            continue
        if join.broadcast is not None:
            result = _join_broadcast(result, right, table=table, join=join)
            continue

        if join.cardinality == "m:1" and join.select_first is None:
            if right.select(list(join.on.values())).is_duplicated().any():
                raise PreparedTableError(
                    f"Prepared table {table.name!r} join source {join.source!r} has duplicate keys "
                    f"for {join.on}; configure select_first to choose a representative row"
                )
        elif join.select_first is not None:
            sort_columns = list(join.select_first.order_by)
            if sort_columns:
                right = right.sort(
                    sort_columns,
                    descending=[join.select_first.order_by[column] == "desc" for column in sort_columns],
                    maintain_order=True,
                )
            right = right.unique(subset=list(join.on.values()), keep="first", maintain_order=True)

        if join.cardinality == "1:m" and result.select(list(join.on)).is_duplicated().any():
            raise PreparedTableError(
                f"Prepared table {table.name!r} base source {table.source!r} has duplicate keys "
                f"for one-to-many join source {join.source!r}: {join.on}"
            )

        right = right.select(list(dict.fromkeys([*join.on.values(), *join.columns]))).select(
            [
                *join.on.values(),
                *(pl.col(source).alias(output) for source, output in join.columns.items()),
            ]
        )
        if join.how == "cross":
            try:
                result = result.join(right, how="cross", maintain_order="left_right")
            except pl.exceptions.PolarsError as exc:
                raise PreparedTableError(
                    f"Prepared table {table.name!r} failed cross joining source {join.source!r}: {exc}"
                ) from exc
            continue
        if join.how == "semi":
            try:
                result = result.join(
                    right.select(list(join.on.values())),
                    left_on=list(join.on),
                    right_on=list(join.on.values()),
                    how="semi",
                    maintain_order="left",
                    coalesce=True,
                )
            except pl.exceptions.PolarsError as exc:
                raise PreparedTableError(
                    f"Prepared table {table.name!r} failed semi joining source {join.source!r}: {exc}"
                ) from exc
            continue

        try:
            result = result.join(
                right,
                left_on=list(join.on),
                right_on=list(join.on.values()),
                how=join.how,
                validate=join.cardinality,
                maintain_order="left",
                coalesce=True,
            )
        except pl.exceptions.PolarsError as exc:
            raise PreparedTableError(
                f"Prepared table {table.name!r} failed joining source {join.source!r}: {exc}"
            ) from exc

    prepared = result.lazy()
    if table.proc_spec is not None:
        processing = apply_processing(
            prepared,
            data_file=table,
            proc_spec=table.proc_spec,
            placeholders=placeholders,
        )
        if processing.is_err():
            error = processing.err()
            raise PreparedTableError(f"Prepared table {table.name!r} processing failed: {error}") from error
        prepared_result = processing.ok()
        if isinstance(prepared_result, pl.LazyFrame):
            prepared = prepared_result
        elif isinstance(prepared_result, pl.DataFrame):
            prepared = prepared_result.lazy()
        else:
            raise PreparedTableError(
                f"Prepared table {table.name!r} processing returned a non-tabular result"
            )

    try:
        final_result = prepared.collect()
    except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
        raise PreparedTableError(
            f"Prepared table {table.name!r} failed while collecting source {table.source!r}: {exc}"
        ) from exc
    missing_result_columns = sorted(set(table.required_columns) - set(final_result.columns))
    if missing_result_columns:
        raise PreparedTableError(
            f"Prepared table {table.name!r} result is missing column(s): {missing_result_columns}"
        )
    null_result_columns = [
        column for column in table.non_null_columns if final_result.get_column(column).null_count()
    ]
    if null_result_columns:
        raise PreparedTableError(
            f"Prepared table {table.name!r} from source {table.source!r} contains null value(s) "
            f"in non-null column(s): {null_result_columns}"
        )
    for key_columns in table.unique_keys:
        if final_result.select(key_columns).is_duplicated().any():
            raise PreparedTableError(
                f"Prepared table {table.name!r} from source {table.source!r} contains duplicate key rows "
                f"for {key_columns}"
            )
    return final_result.lazy()
