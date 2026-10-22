"""Resolve inputs, dispatch registered readers, and process named sources."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import cached_property
from pathlib import Path

from loguru import logger
from pydantic import TypeAdapter
from rust_ok import is_ok

from .datafile import DataFile, ReaderConfig
from .exceptions import ConfiguredGroupNotFoundError, ReaderError
from .file_reader import DecodedSource, DecodedSources, FileReader
from .json_adapter import JSONFileReader
from .processors import substitute_placeholders
from .types import FileProcessing, FileRequirement, JSONValue
from .utils.files import get_fpath
from .xml_adapter import XMLFileReader


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
    ) -> DecodedSources:
        """Decode and process inputs in declaration order with execution-local reuse."""
        sources: dict[str, DecodedSource] = {}
        decoded_cache: dict[tuple[Path, str, str], DecodedSources] = {}
        for configured_file in data_files:
            data_file = self.resolve_placeholders(configured_file, placeholders=placeholders)
            if data_file.source is not None:
                if data_file.name in sources:
                    msg = f"Duplicate named source {data_file.name!r}"
                    raise ValueError(msg)
                try:
                    source = sources[data_file.source]
                except KeyError:
                    msg = f"Named source {data_file.source!r} must be declared before {data_file.name!r}"
                    raise ValueError(msg) from None
                sources[data_file.name] = self.process_source(
                    source,
                    data_file=data_file,
                    sources=sources,
                )
                continue

            path_result = get_fpath(data_file, folder_path=folder_path)
            if is_ok(path_result):
                file_path = path_result.value
            else:
                error = path_result.err()
                if (
                    isinstance(error, FileNotFoundError)
                    and data_file.info.requirement is FileRequirement.OPTIONAL
                ):
                    logger.info("Skipping optional file: {}", data_file.name)
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
                    if data_file.info.requirement is FileRequirement.OPTIONAL:
                        continue
                    raise
            decoded = decoded_cache[cache_key]
            named = self.name_decoded_sources(data_file.name, decoded)
            if set(named) & sources.keys():
                duplicate = sorted(set(named) & sources.keys())[0]
                msg = f"Duplicate named source {duplicate!r}"
                raise ValueError(msg)
            available = sources | named
            for name, source in named.items():
                sources[name] = self.process_source(source, data_file=data_file, sources=available)
        return sources

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
        raise ReaderError(error) from error

    @staticmethod
    def resolve_placeholders(
        data_file: DataFile,
        *,
        placeholders: Mapping[str, JSONValue] | None,
    ) -> DataFile:
        """Substitute paths, reader options, source names, and operations before execution."""

        def substitute_path(value: Path | str | None) -> Path | str | None:
            if value is None or "{" not in str(value):
                return value
            result = substitute_placeholders(str(value), placeholders=placeholders)
            if is_ok(result):
                resolved = result.value
            else:
                raise result.err()
            if not isinstance(resolved, str):
                msg = "Path placeholders must resolve to strings"
                raise ValueError(msg)
            return Path(resolved) if isinstance(value, Path) else resolved

        updates: dict[str, object] = {}
        for field in ("fpath", "relative_fpath", "glob", "source"):
            original = getattr(data_file, field)
            substituted = substitute_path(original)
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
