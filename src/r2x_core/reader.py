"""Resolve inputs, dispatch registered readers, and process named sources."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from functools import cached_property
from pathlib import Path
from typing import Literal, TypeAlias

from loguru import logger
from pydantic import TypeAdapter
from rust_ok import is_ok

from .datafile import DataFile, InlineTable, ReaderConfig, SourceSelection, parse_inline_table_rows
from .exceptions import ConfiguredGroupNotFoundError, ReaderError
from .file_reader import (
    DecodedSource,
    DecodedSources,
    FileReader,
    SourceAvailability,
    TabularSource,
)
from .json_adapter import JSONFileReader
from .models import (
    CastColumnsStep,
    ConcatStep,
    FilterStep,
    JoinStep,
    MappingStep,
    MatchSourcePatternsStep,
    RenameColumnsStep,
    SourcePredicate,
    TabularProcessing,
)
from .processors import substitute_placeholders
from .table_mapping import (
    TableMappingRecord,
    assemble_table_records,
    load_table_mapping,
    table_record_sources,
)
from .tabular_backend import StepHandlers, TableMappingBackend
from .types import FileProcessing, FileRequirement, JSONValue
from .utils.files import get_fpath
from .xml_adapter import XMLFileReader

AssemblyNode: TypeAlias = tuple[Literal["file", "table"], str]


def validate_initial_sources(sources: Mapping[str, DecodedSource], /) -> None:
    """Validate the public source seed boundary before processing begins."""
    for name, source in sources.items():
        if not isinstance(name, str) or not name:
            msg = "Initial source names must be non-empty strings"
            raise ValueError(msg)
        if not isinstance(source, DecodedSource):
            msg = f"Initial source {name!r} must be a DecodedSource"
            raise TypeError(msg)


def reject_source_name_collisions(existing: Mapping[str, DecodedSource], names: Iterable[str], /) -> None:
    """Keep decoded and derived source names unique within one read operation."""
    duplicates = set(existing).intersection(names)
    if duplicates:
        duplicate = sorted(duplicates)[0]
        msg = f"Duplicate named source {duplicate!r}"
        raise ValueError(msg)


def data_file_source_references(data_file: DataFile, /) -> tuple[tuple[str, str], ...]:
    """Return configured named-source dependencies and their declaration fields."""
    dependencies: list[tuple[str, str]] = []
    if data_file.source is not None:
        dependencies.append((data_file.source, "source"))
    if data_file.source_selection is not None:
        dependencies.extend((name, "source selection") for name in data_file.source_selection.sources)
    if data_file.required_when is not None:
        dependencies.append((data_file.required_when.source, "required_when"))
    if isinstance(data_file.proc_spec, TabularProcessing):
        for index, step in enumerate(data_file.proc_spec.steps):
            if isinstance(step, (JoinStep, MatchSourcePatternsStep)):
                dependencies.append((step.source, f"operation {index} ({step.op})"))
            elif isinstance(step, ConcatStep):
                dependencies.extend((name, f"operation {index} ({step.op})") for name in step.sources)
    return tuple(dependencies)


def validate_data_file_dependencies(
    data_files: Iterable[DataFile],
    /,
    *,
    initial_names: set[str],
    qualified_file_output_names: Iterable[str] = (),
) -> None:
    """Validate ordered source dependencies before decoding any input."""
    declared_names = set(initial_names)
    qualified_names = set(qualified_file_output_names)
    for data_file in data_files:
        if data_file.name in declared_names:
            msg = f"Duplicate named source {data_file.name!r}"
            raise ValueError(msg)

        for source_name, purpose in data_file_source_references(data_file):
            available = source_name in declared_names or any(
                source_name.startswith(f"{file_name}.") for file_name in qualified_names
            )
            if not available:
                msg = (
                    f"DataFile {data_file.name!r} {purpose} references source "
                    f"{source_name!r} before it is declared"
                )
                raise ValueError(msg)
        declared_names.add(data_file.name)
        if any((data_file.fpath, data_file.relative_fpath, data_file.glob)):
            qualified_names.add(data_file.name)


def plan_source_assembly(
    data_files: Sequence[DataFile],
    table_records: Sequence[TableMappingRecord],
    /,
    *,
    initial_sources: Mapping[str, DecodedSource],
    initial_table_names: set[str],
) -> list[AssemblyNode]:
    """Validate a cross-boundary source graph and return a stable execution order."""
    file_names = [data_file.name for data_file in data_files]
    table_names = [record.name for record in table_records]
    if len(set(file_names)) != len(file_names):
        msg = "Duplicate named source in file mapping"
        raise ValueError(msg)
    if len(set(table_names)) != len(table_names):
        msg = "Duplicate table name in table mapping"
        raise ValueError(msg)
    if set(file_names) & set(table_names):
        msg = f"File and table mappings declare the same name: {sorted(set(file_names) & set(table_names))[0]!r}"
        raise ValueError(msg)

    initial_names = set(initial_sources)
    file_collisions = initial_names & set(file_names)
    if file_collisions:
        msg = f"Initial source collides with a configured file: {sorted(file_collisions)[0]!r}"
        raise ValueError(msg)
    output_collisions = initial_names & set(table_names)
    if output_collisions:
        msg = f"Initial source collides with a table output: {sorted(output_collisions)[0]!r}"
        raise ValueError(msg)
    unknown_initial_tables = initial_table_names - set(table_names)
    if unknown_initial_tables:
        msg = f"Initial table is not declared by the table mapping: {sorted(unknown_initial_tables)[0]!r}"
        raise ValueError(msg)
    file_indices = {name: index for index, name in enumerate(file_names)}
    qualified_file_names = {
        data_file.name
        for data_file in data_files
        if any((data_file.fpath, data_file.relative_fpath, data_file.glob))
    }
    table_indices = {name: index for index, name in enumerate(table_names)}

    def resolve_source(source_name: str, /, *, consumer: str) -> AssemblyNode | None:
        if source_name in initial_names:
            return None
        if source_name in table_indices:
            return ("table", source_name)
        if source_name in file_indices:
            return ("file", source_name)
        matching_files = [name for name in qualified_file_names if source_name.startswith(f"{name}.")]
        if matching_files:
            file_name = max(matching_files, key=lambda name: len(name))
            return ("file", file_name)
        msg = f"Unknown source {source_name!r} referenced by {consumer}"
        raise ValueError(msg)

    nodes: list[AssemblyNode] = [("file", name) for name in file_names]
    nodes.extend(("table", name) for name in table_names)
    ranks = {node: index for index, node in enumerate(nodes)}
    dependencies: dict[AssemblyNode, set[AssemblyNode]] = {node: set() for node in nodes}

    for index, data_file in enumerate(data_files):
        node: AssemblyNode = ("file", data_file.name)
        for source_name, _purpose in data_file_source_references(data_file):
            producer = resolve_source(source_name, consumer=f"file {data_file.name!r}")
            if producer is None:
                continue
            if producer[0] == "file" and file_indices[producer[1]] >= index:
                msg = f"DataFile {data_file.name!r} references source {source_name!r} before it is declared"
                raise ValueError(msg)
            if producer[0] == "table" and producer[1] in initial_table_names:
                continue
            dependencies[node].add(producer)

    for index, record in enumerate(table_records):
        node: AssemblyNode = ("table", record.name)
        for source_name in table_record_sources(record):
            producer = resolve_source(source_name, consumer=f"table {record.name!r}")
            if producer is None:
                continue
            if producer[0] == "table" and table_indices[producer[1]] >= index:
                msg = f"Table source {source_name!r} is referenced before it is declared"
                raise ValueError(msg)
            if record.name not in initial_table_names:
                dependencies[node].add(producer)

    dependents: dict[AssemblyNode, set[AssemblyNode]] = {node: set() for node in nodes}
    remaining_dependencies: dict[AssemblyNode, set[AssemblyNode]] = {}
    for node in nodes:
        if node[0] == "table" and node[1] in initial_table_names:
            continue
        prerequisites: set[AssemblyNode] = set()
        for dependency in dependencies[node]:
            if dependency[0] != "table" or dependency[1] not in initial_table_names:
                prerequisites.add(dependency)
        remaining_dependencies[node] = prerequisites
        for dependency in prerequisites:
            dependents[dependency].add(node)

    ready: list[AssemblyNode] = [node for node, deps in remaining_dependencies.items() if not deps]
    ordered: list[AssemblyNode] = []
    while ready:
        ready.sort(key=lambda candidate: ranks[candidate])
        node = ready.pop(0)
        ordered.append(node)
        for dependent in dependents[node]:
            remaining_dependencies[dependent].remove(node)
            if not remaining_dependencies[dependent]:
                ready.append(dependent)

    if len(ordered) != len(remaining_dependencies):
        cyclic = sorted(set(remaining_dependencies) - set(ordered), key=ranks.__getitem__)
        labels = [f"{kind}:{name}" for kind, name in cyclic]
        msg = f"Source assembly dependency cycle: {labels}"
        raise ValueError(msg)
    return ordered


class DataReader:
    """Read configured files into named sources and execute declared operations."""

    def __init__(
        self,
        *,
        file_readers: Mapping[str, FileReader] | None = None,
        step_handlers: StepHandlers | None = None,
    ) -> None:
        """Register app readers and mapping handlers by symbolic name."""
        self.file_readers = dict(file_readers or {})
        self.step_handlers = dict(step_handlers or {})

    @cached_property
    def polars_file_reader(self) -> FileReader:
        """Load built-in tabular support on first use."""
        from .polars_adapter import PolarsTabularFileReader

        return PolarsTabularFileReader(step_handlers=self.step_handlers)

    @cached_property
    def json_file_reader(self) -> FileReader:
        """Load the built-in JSON reader on first use."""
        return JSONFileReader()

    @cached_property
    def xml_file_reader(self) -> FileReader:
        """Load the built-in XML reader on first use."""
        return XMLFileReader()

    def select_file_reader(self, format_name: str, /) -> FileReader:
        """Select a registered reader for a symbolic input format."""
        registered = self.file_readers.get(format_name)
        if registered is not None:
            return registered
        if format_name in {"csv", "tsv", "parquet", "hdf5"}:
            return self.polars_file_reader
        if format_name == "json":
            return self.json_file_reader
        if format_name == "xml":
            return self.xml_file_reader
        if format_name == "hdf5_array":
            from .h5_adapter import H5PyFileReader

            return H5PyFileReader()
        msg = f"No reader registered for format {format_name!r}"
        raise ValueError(msg)

    def read_data_files(
        self,
        data_files: Iterable[DataFile],
        *,
        folder_path: Path,
        placeholders: Mapping[str, JSONValue] | None = None,
        initial_sources: Mapping[str, DecodedSource] | None = None,
    ) -> DecodedSources:
        """Decode and process inputs in declaration order with execution-local reuse.

        ``initial_sources`` seeds ordered processing with already decoded sources.
        The input mapping is copied, seed values are returned with newly processed
        sources, and configured names may not replace existing names.
        """
        return self.read_file_batch(
            data_files,
            folder_path=folder_path,
            placeholders=placeholders,
            initial_sources=initial_sources,
            prior_declared_source_names=(),
            prior_file_output_names=(),
            decoded_cache={},
            absent_source_names=set(),
        )

    def read_file_batch(
        self,
        data_files: Iterable[DataFile],
        *,
        folder_path: Path,
        placeholders: Mapping[str, JSONValue] | None,
        initial_sources: Mapping[str, DecodedSource] | None,
        prior_declared_source_names: Iterable[str],
        prior_file_output_names: Iterable[str],
        decoded_cache: dict[tuple[Path, str, str, str], DecodedSources],
        absent_source_names: set[str],
    ) -> DecodedSources:
        """Read one ordered file batch while sharing execution-local cache state."""
        sources: dict[str, DecodedSource] = dict(initial_sources or {})
        validate_initial_sources(sources)
        configured_files = tuple(
            self.resolve_placeholders(data_file, placeholders=placeholders) for data_file in data_files
        )
        declared_source_names = set(sources) | set(prior_declared_source_names)
        validate_data_file_dependencies(
            configured_files,
            initial_names=declared_source_names,
            qualified_file_output_names=prior_file_output_names,
        )
        configured_file_names: set[str] = set()
        for data_file in configured_files:
            required = data_file.info.requirement is FileRequirement.REQUIRED or self.is_required_by_source(
                data_file, sources=sources
            )
            if data_file.name in configured_file_names or data_file.name in sources:
                msg = f"Duplicate named source {data_file.name!r}"
                raise ValueError(msg)
            configured_file_names.add(data_file.name)
            if (
                data_file.source is not None
                or data_file.source_selection is not None
                or data_file.inline_table is not None
            ):
                reject_source_name_collisions(sources, (data_file.name,))
                self.validate_source_selection(data_file, declared_source_names=declared_source_names)
                source = self.get_configured_source(data_file, sources=sources)
                sources[data_file.name] = self.process_source(
                    source,
                    data_file=data_file,
                    sources=sources,
                )
                declared_source_names.add(data_file.name)
                continue

            path_result = get_fpath(data_file, folder_path=folder_path)
            if is_ok(path_result):
                file_path = path_result.value
            else:
                error = path_result.err()
                if isinstance(error, FileNotFoundError) and not required:
                    logger.info("Skipping optional file: {}", data_file.name)
                    if data_file.columns is not None:
                        absent = self.create_absent_source(data_file)
                        sources[data_file.name] = self.process_absent_source(
                            absent, data_file=data_file, sources=sources
                        )
                    else:
                        absent_source_names.add(data_file.name)
                    declared_source_names.add(data_file.name)
                    continue
                raise error
            format_name = data_file.format_name
            reader = self.select_file_reader(format_name)
            resolved_path = file_path.resolve()
            options_key = json.dumps(data_file.reader.options, sort_keys=True, separators=(",", ":"))
            columns_key = json.dumps(
                [column.model_dump(mode="json") for column in data_file.columns or ()],
                sort_keys=True,
                separators=(",", ":"),
            )
            cache_key = (resolved_path, format_name, options_key, columns_key)
            if cache_key not in decoded_cache:
                try:
                    reader_config = data_file.reader.model_copy(
                        update={"columns": tuple(data_file.columns or ())}
                    )
                    decoded_cache[cache_key] = reader.read_file(
                        format_name,
                        file_path=resolved_path,
                        reader_config=reader_config,
                    )
                except ConfiguredGroupNotFoundError:
                    if not required:
                        if data_file.columns is not None:
                            absent = self.create_absent_source(data_file)
                            sources[data_file.name] = self.process_absent_source(
                                absent, data_file=data_file, sources=sources
                            )
                        else:
                            absent_source_names.add(data_file.name)
                        declared_source_names.add(data_file.name)
                        continue
                    raise
            decoded = decoded_cache[cache_key]
            named = self.name_decoded_sources(data_file.name, decoded)
            reject_source_name_collisions(sources, named)
            if data_file.columns is not None:
                if len(named) != 1:
                    msg = f"DataFile {data_file.name!r} column declarations require one tabular source"
                    raise ValueError(msg)
                named = {
                    name: self.apply_native_columns(source, data_file=data_file, sources=sources | named)
                    for name, source in named.items()
                }
            declared_source_names.update(named)
            available = sources | named
            for name, source in named.items():
                sources[name] = self.process_source(source, data_file=data_file, sources=available)
        return sources

    def read_and_assemble_sources(
        self,
        data_files: Iterable[DataFile],
        /,
        *,
        folder_path: Path,
        mapping_path: Path,
        backend: TableMappingBackend,
        placeholders: Mapping[str, JSONValue] | None = None,
        initial_sources: Mapping[str, DecodedSource] | None = None,
        initial_tables: Mapping[str, TabularSource] | None = None,
    ) -> DecodedSources:
        """Read inputs and assemble mapped tables in stable dependency order.

        This opt-in integration schedules cross-boundary file/table dependencies
        before any input is opened. File batches share one decode cache, and
        ``initial_tables`` supplies explicitly preassembled table outputs.
        ``read_data_files`` retains its declaration-ordered, single-phase rules.
        """
        records = load_table_mapping(mapping_path)
        return self.read_and_assemble_records(
            data_files,
            records,
            folder_path=folder_path,
            backend=backend,
            placeholders=placeholders,
            initial_sources=initial_sources,
            initial_tables=initial_tables,
        )

    def read_and_assemble_records(
        self,
        data_files: Iterable[DataFile],
        records: Sequence[TableMappingRecord],
        /,
        *,
        folder_path: Path,
        backend: TableMappingBackend,
        placeholders: Mapping[str, JSONValue] | None = None,
        initial_sources: Mapping[str, DecodedSource] | None = None,
        initial_tables: Mapping[str, TabularSource] | None = None,
    ) -> DecodedSources:
        """Schedule inputs and table records against one validated mapping snapshot."""
        records = TypeAdapter(list[TableMappingRecord]).validate_python(records)
        raw_files = tuple(data_files)
        configured_files = tuple(
            self.resolve_placeholders(data_file, placeholders=placeholders) for data_file in raw_files
        )
        seed_sources = dict(initial_sources or {})
        validate_initial_sources(seed_sources)
        seed_tables = dict(initial_tables or {})
        invalid_tables = [
            name
            for name, source in seed_tables.items()
            if not isinstance(name, str) or not name or not isinstance(source, TabularSource)
        ]
        if invalid_tables:
            msg = f"Initial tables must be named TabularSource values: {invalid_tables}"
            raise TypeError(msg)

        table_names = {record.name for record in records}
        if set(seed_tables) - table_names:
            msg = (
                f"Initial tables are not declared in table mapping: {sorted(set(seed_tables) - table_names)}"
            )
            raise ValueError(msg)
        if set(seed_sources) & set(seed_tables):
            msg = (
                f"Initial source and table names collide: {sorted(set(seed_sources) & set(seed_tables))[0]!r}"
            )
            raise ValueError(msg)

        order = plan_source_assembly(
            configured_files,
            records,
            initial_sources=seed_sources,
            initial_table_names=set(seed_tables),
        )
        file_by_name = {data_file.name: data_file for data_file in raw_files}
        all_sources = {**seed_sources, **seed_tables}
        file_source_names = set(seed_sources)
        prior_declared_source_names = set(all_sources)
        prior_file_output_names: set[str] = set()
        decoded_cache: dict[tuple[Path, str, str, str], DecodedSources] = {}
        absent_source_names: set[str] = set()
        table_output_names = {record.name for record in records}
        declared_table_source_names = {
            source_name
            for record in records
            for source_name in table_record_sources(record)
            if source_name not in table_output_names and source_name not in seed_sources
        }

        index = 0
        while index < len(order):
            kind = order[index][0]
            end = index + 1
            while end < len(order) and order[end][0] == kind:
                end += 1
            batch = order[index:end]
            if kind == "file":
                batch_files = [file_by_name[name] for _, name in batch]
                existing_names = set(all_sources)
                all_sources = self.read_file_batch(
                    batch_files,
                    folder_path=folder_path,
                    placeholders=placeholders,
                    initial_sources=all_sources,
                    prior_declared_source_names=prior_declared_source_names,
                    prior_file_output_names=prior_file_output_names,
                    decoded_cache=decoded_cache,
                    absent_source_names=absent_source_names,
                )
                file_source_names.update(set(all_sources) - existing_names)
                prior_declared_source_names.update(set(all_sources) | absent_source_names)
                prior_file_output_names.update(
                    data_file.name
                    for data_file in batch_files
                    if any((data_file.fpath, data_file.relative_fpath, data_file.glob))
                )
            else:
                collisions = file_source_names & table_output_names
                if collisions:
                    msg = f"File source collides with a table output: {sorted(collisions)[0]!r}"
                    raise ValueError(msg)
                table_sources = {
                    name: source for name, source in all_sources.items() if name not in table_output_names
                }
                available_tables = {
                    name: source for name, source in all_sources.items() if name in table_output_names
                }
                assembled = assemble_table_records(
                    table_sources,
                    records,
                    backend=backend,
                    placeholders=placeholders,
                    table_names=[name for _, name in batch],
                    initial_tables=available_tables,
                    declared_source_names=tuple(declared_table_source_names),
                    absent_source_names=tuple(absent_source_names),
                )
                all_sources.update(assembled)
            index = end
        return all_sources

    @staticmethod
    def is_required_by_source(data_file: DataFile, *, sources: Mapping[str, DecodedSource]) -> bool:
        """Require an optional physical input when a prior table has a matching row."""
        requirement = data_file.required_when
        if requirement is None:
            return False
        source = sources.get(requirement.source)
        if source is None:
            msg = f"required_when source {requirement.source!r} is not available before {data_file.name!r}"
            raise ValueError(msg)
        if not isinstance(source, TabularSource):
            msg = f"required_when source {requirement.source!r} must be tabular"
            raise TypeError(msg)
        if source.availability is SourceAvailability.ABSENT:
            msg = f"required_when source {requirement.source!r} is absent"
            raise ValueError(msg)
        processing = TabularProcessing(steps=[FilterStep(op="filter", predicate=requirement.predicate)])
        result = source.process(processing, sources=sources, data_file=data_file)
        if not is_ok(result):
            error = result.err()
            raise ReaderError(error) from error
        import polars as pl

        try:
            return not result.value.is_empty()
        except pl.exceptions.PolarsError as error:
            raise ReaderError(error) from error

    @staticmethod
    def validate_source_selection(
        data_file: DataFile,
        *,
        declared_source_names: set[str],
    ) -> None:
        """Require selection candidates to come from prior or seeded declarations."""
        selection = data_file.source_selection
        if selection is None:
            return
        undeclared = [name for name in selection.sources if name not in declared_source_names]
        if undeclared:
            msg = f"Source selection candidates must be declared before {data_file.name!r}: {undeclared}"
            raise ValueError(msg)

    def get_configured_source(
        self, data_file: DataFile, *, sources: Mapping[str, DecodedSource]
    ) -> DecodedSource:
        """Resolve one inline, selected, or named source for a derived file."""
        if data_file.inline_table is not None:
            return self.create_inline_table_source(data_file.inline_table)
        if data_file.source_selection is not None:
            return self.select_source(data_file.source_selection, sources=sources)
        source_name = data_file.source
        if source_name is None:
            msg = f"Data file {data_file.name!r} has no source definition"
            raise ValueError(msg)
        try:
            return sources[source_name]
        except KeyError:
            msg = f"Named source {source_name!r} must be declared before {data_file.name!r}"
            raise ValueError(msg) from None

    def create_inline_table_source(self, table: InlineTable) -> DecodedSource:
        """Create a typed Polars source from validated raw inline records."""
        import polars as pl

        from .polars_adapter import PolarsTabularBackend

        rows = parse_inline_table_rows(table)
        dtype_mapping = {
            "bool": pl.Boolean,
            "int64": pl.Int64,
            "float64": pl.Float64,
            "string": pl.String,
            "datetime": pl.Datetime,
        }
        schema = {column: dtype_mapping[column_type] for column, column_type in table.raw_schema.items()}
        frame = pl.DataFrame(rows, schema=schema, strict=True)
        return TabularSource(frame.lazy(), PolarsTabularBackend(step_handlers=self.step_handlers))

    def create_absent_source(self, data_file: DataFile) -> TabularSource:
        """Create the declared empty schema for one absent optional input."""
        import polars as pl

        from .polars_adapter import PolarsTabularBackend

        if data_file.columns is None:
            msg = f"DataFile {data_file.name!r} requires declared columns to retain absence"
            raise ValueError(msg)
        dtype_mapping = {
            "bool": pl.Boolean,
            "int64": pl.Int64,
            "float64": pl.Float64,
            "string": pl.String,
            "datetime": pl.Datetime,
        }
        schema = {column.rename or column.name: dtype_mapping[column.dtype] for column in data_file.columns}
        return TabularSource(
            pl.DataFrame(schema=schema).lazy(),
            PolarsTabularBackend(step_handlers=self.step_handlers),
            availability=SourceAvailability.ABSENT,
            absent_inputs=frozenset({data_file.name}),
        )

    def process_absent_source(
        self,
        source: TabularSource,
        *,
        data_file: DataFile,
        sources: Mapping[str, DecodedSource],
    ) -> TabularSource:
        """Apply input-boundary processing without allowing absent inputs to gain rows."""
        processed = self.process_source(source, data_file=data_file, sources=sources)
        if not isinstance(processed, TabularSource):
            msg = f"Absent DataFile {data_file.name!r} did not remain tabular"
            raise TypeError(msg)
        return processed

    @staticmethod
    def apply_native_columns(
        source: DecodedSource,
        *,
        data_file: DataFile,
        sources: Mapping[str, DecodedSource],
    ) -> DecodedSource:
        """Strictly cast and rename declared native columns before file processing."""
        if not isinstance(source, TabularSource):
            msg = f"DataFile {data_file.name!r} column declarations require a tabular reader"
            raise TypeError(msg)
        if data_file.columns is None:
            return source
        steps: list[MappingStep] = [
            CastColumnsStep(
                op="cast_columns",
                column_schema={column.name: column.dtype for column in data_file.columns},
                optional_columns=[column.name for column in data_file.columns if not column.required],
                float_to_int="reject",
            )
        ]
        renames = {column.name: column.rename for column in data_file.columns if column.rename is not None}
        if renames:
            steps.append(RenameColumnsStep(op="rename_columns", column_mapping=renames))
        processing = TabularProcessing(steps=steps)
        result = source.process(processing, sources=sources, data_file=data_file)
        if is_ok(result):
            return result.value
        error = result.err()
        msg = f"Native columns for DataFile {data_file.name!r} failed: {error}"
        raise ReaderError(msg) from error

    def select_source(
        self, selection: SourceSelection, *, sources: Mapping[str, DecodedSource]
    ) -> DecodedSource:
        """Choose a prior source by configured presence or nonemptiness."""
        for name in selection.sources:
            source = sources.get(name)
            if (
                source is not None
                and not (
                    isinstance(source, TabularSource) and source.availability is SourceAvailability.ABSENT
                )
                and (selection.mode == "first_present" or not source.is_empty())
            ):
                return source
        if selection.empty_fallback is not None:
            return self.create_inline_table_source(selection.empty_fallback)
        msg = f"No source matched {selection.mode!r} selection among {selection.sources!r}"
        raise ValueError(msg)

    @staticmethod
    def resolve_path_placeholders(
        value: Path | str | None,
        *,
        placeholders: Mapping[str, JSONValue] | None,
    ) -> Path | str | None:
        """Substitute a configured path while preserving its Python representation."""
        if value is None or "{" not in str(value):
            return value
        result = substitute_placeholders(str(value), placeholders=placeholders)
        if not is_ok(result):
            raise result.err()
        if not isinstance(result.value, str):
            msg = "Path placeholders must resolve to strings"
            raise ValueError(msg)
        return Path(result.value) if isinstance(value, Path) else result.value

    @staticmethod
    def resolve_source_model_placeholders(
        model: InlineTable | SourceSelection | SourcePredicate,
        *,
        placeholders: Mapping[str, JSONValue] | None,
    ) -> InlineTable | SourceSelection | SourcePredicate:
        """Substitute and revalidate placeholder-backed source declarations."""
        raw_model = model.model_dump(mode="python")
        result = substitute_placeholders(raw_model, placeholders=placeholders)
        if not is_ok(result):
            raise result.err()
        if result.value == raw_model:
            return model
        if isinstance(model, InlineTable):
            return InlineTable.model_validate(result.value)
        if isinstance(model, SourceSelection):
            return SourceSelection.model_validate(result.value)
        return SourcePredicate.model_validate(result.value)

    @staticmethod
    def resolve_source_declarations(
        data_file: DataFile,
        *,
        placeholders: Mapping[str, JSONValue] | None,
    ) -> dict[str, object]:
        """Resolve placeholder-backed inline, selection, and requirement declarations."""
        resolved: dict[str, object] = {}
        for field, model in (
            ("inline_table", data_file.inline_table),
            ("source_selection", data_file.source_selection),
            ("required_when", data_file.required_when),
        ):
            if model is not None:
                resolved_model = DataReader.resolve_source_model_placeholders(
                    model, placeholders=placeholders
                )
                if resolved_model is not model:
                    resolved[field] = resolved_model
        return resolved

    @staticmethod
    def name_decoded_sources(name: str, decoded: DecodedSources) -> dict[str, DecodedSource]:
        """Qualify reader outputs while keeping the conventional single output concise."""
        if not decoded:
            msg = f"Reader for {name!r} returned no named sources"
            raise ValueError(msg)
        if any(
            not isinstance(key, str) or not key or not isinstance(value, DecodedSource)
            for key, value in decoded.items()
        ):
            msg = f"Reader for {name!r} returned an invalid named source"
            raise TypeError(msg)
        if len(decoded) == 1 and "data" in decoded:
            return {name: decoded["data"]}
        return {f"{name}.{key}": value for key, value in decoded.items()}

    @staticmethod
    def process_source(
        source: DecodedSource,
        *,
        data_file: DataFile,
        sources: Mapping[str, DecodedSource],
    ) -> DecodedSource:
        """Apply configured operations through the source's representation contract."""
        spec = data_file.proc_spec
        if spec is None or not spec.steps:
            processed = source
        else:
            result = source.process(spec, sources=sources, data_file=data_file)
            if is_ok(result):
                processed = result.value
            else:
                error = result.err()
                msg = f"Processing DataFile {data_file.name!r} failed: {error}"
                raise ReaderError(msg) from error
        if isinstance(source, TabularSource) and source.availability is SourceAvailability.ABSENT:
            if not isinstance(processed, TabularSource):
                msg = f"Absent DataFile {data_file.name!r} did not remain tabular"
                raise TypeError(msg)
            if not processed.is_empty():
                msg = f"Processing absent DataFile {data_file.name!r} created rows"
                raise ValueError(msg)
        return processed

    @staticmethod
    def resolve_placeholders(
        data_file: DataFile,
        *,
        placeholders: Mapping[str, JSONValue] | None,
    ) -> DataFile:
        """Substitute paths, reader options, source declarations, and operations before execution."""
        updates: dict[str, object] = DataReader.resolve_source_declarations(
            data_file, placeholders=placeholders
        )
        for field in ("fpath", "relative_fpath", "glob", "source"):
            original = getattr(data_file, field)
            substituted = DataReader.resolve_path_placeholders(original, placeholders=placeholders)
            if substituted != original:
                updates[field] = substituted

        if data_file.reader.options:
            result = substitute_placeholders(data_file.reader.options, placeholders=placeholders)
            if is_ok(result):
                options = TypeAdapter(dict[str, JSONValue]).validate_python(result.value)
            else:
                raise result.err()
            updates["reader"] = ReaderConfig(format=data_file.reader.format, options=options)

        if data_file.proc_spec is not None:
            raw_spec = data_file.proc_spec.model_dump(mode="python")
            result = substitute_placeholders(raw_spec, placeholders=placeholders)
            if is_ok(result):
                if result.value != raw_spec:
                    updates["proc_spec"] = TypeAdapter(FileProcessing).validate_python(result.value)
            else:
                raise result.err()

        return data_file.model_copy(update=updates) if updates else data_file
