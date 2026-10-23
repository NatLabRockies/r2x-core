"""Resolve inputs, dispatch registered readers, and process named sources."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import cached_property
from pathlib import Path

from loguru import logger
from pydantic import TypeAdapter
from rust_ok import is_ok

from .datafile import DataFile, InlineTable, ReaderConfig, SourceSelection
from .exceptions import ConfiguredGroupNotFoundError, ReaderError
from .file_reader import DecodedSource, DecodedSources, FileReader, TabularSource
from .json_adapter import JSONFileReader
from .models import FilterStep, SourcePredicate, TabularProcessing
from .processors import substitute_placeholders
from .types import FileProcessing, FileRequirement, JSONValue
from .utils.files import get_fpath
from .xml_adapter import XMLFileReader


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


class DataReader:
    """Read configured files into named sources and execute declared operations."""

    def __init__(self, *, file_readers: Mapping[str, FileReader] | None = None) -> None:
        """Register app readers by symbolic format name."""
        self.file_readers = dict(file_readers or {})

    @cached_property
    def polars_file_reader(self) -> FileReader:
        """Load built-in tabular support on first use."""
        from .polars_adapter import PolarsTabularFileReader

        return PolarsTabularFileReader()

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
        sources: dict[str, DecodedSource] = dict(initial_sources or {})
        validate_initial_sources(sources)
        declared_source_names = set(sources)
        configured_file_names: set[str] = set()
        decoded_cache: dict[tuple[Path, str, str], DecodedSources] = {}
        for configured_file in data_files:
            data_file = self.resolve_placeholders(configured_file, placeholders=placeholders)
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
                    declared_source_names.add(data_file.name)
                    continue
                raise error
            format_name = data_file.format_name
            reader = self.select_file_reader(format_name)
            resolved_path = file_path.resolve()
            options_key = json.dumps(data_file.reader.options, sort_keys=True, separators=(",", ":"))
            cache_key = (resolved_path, format_name, options_key)
            if cache_key not in decoded_cache:
                try:
                    decoded_cache[cache_key] = reader.read_file(
                        format_name,
                        file_path=resolved_path,
                        reader_config=data_file.reader,
                    )
                except ConfiguredGroupNotFoundError:
                    if not required:
                        declared_source_names.add(data_file.name)
                        continue
                    raise
            decoded = decoded_cache[cache_key]
            named = self.name_decoded_sources(data_file.name, decoded)
            reject_source_name_collisions(sources, named)
            declared_source_names.update(named)
            available = sources | named
            for name, source in named.items():
                sources[name] = self.process_source(source, data_file=data_file, sources=available)
        return sources

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

    @staticmethod
    def get_configured_source(data_file: DataFile, *, sources: Mapping[str, DecodedSource]) -> DecodedSource:
        """Resolve one inline, selected, or named source for a derived file."""
        if data_file.inline_table is not None:
            return DataReader.create_inline_table_source(data_file.inline_table)
        if data_file.source_selection is not None:
            return DataReader.select_source(data_file.source_selection, sources=sources)
        source_name = data_file.source
        if source_name is None:
            msg = f"Data file {data_file.name!r} has no source definition"
            raise ValueError(msg)
        try:
            return sources[source_name]
        except KeyError:
            msg = f"Named source {source_name!r} must be declared before {data_file.name!r}"
            raise ValueError(msg) from None

    @staticmethod
    def create_inline_table_source(table: InlineTable) -> DecodedSource:
        """Create a typed Polars source from validated raw inline records."""
        import polars as pl

        from .polars_adapter import PolarsTabularBackend

        if isinstance(table.rows, str):
            msg = "Inline table row placeholder was not resolved"
            raise ValueError(msg)
        dtype_mapping = {
            "bool": pl.Boolean,
            "int64": pl.Int64,
            "float64": pl.Float64,
            "string": pl.String,
        }
        schema = {column: dtype_mapping[column_type] for column, column_type in table.raw_schema.items()}
        frame = pl.DataFrame(table.rows, schema=schema, strict=True)
        return TabularSource(frame.lazy(), PolarsTabularBackend())

    @staticmethod
    def select_source(selection: SourceSelection, *, sources: Mapping[str, DecodedSource]) -> DecodedSource:
        """Choose a prior source by configured presence or nonemptiness."""
        for name in selection.sources:
            source = sources.get(name)
            if source is not None and (selection.mode == "first_present" or not source.is_empty()):
                return source
        if selection.empty_fallback is not None:
            return DataReader.create_inline_table_source(selection.empty_fallback)
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
            return source
        result = source.process(spec, sources=sources, data_file=data_file)
        if is_ok(result):
            return result.value
        error = result.err()
        msg = f"Processing DataFile {data_file.name!r} failed: {error}"
        raise ReaderError(msg) from error

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
