"""Polars-backed readers for tabular formats."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from typing import Any, Literal

import polars as pl
from loguru import logger
from pydantic import ConfigDict
from pydantic import ValidationError as PydanticValidationError

from ..datafile import ReaderConfig
from ..file_reader import ArraySource, DecodedSources, FileReader, TabularSource
from ..h5_adapter import H5PyFileReader, H5Reader
from ..models import StrictConfigModel
from ..tabular_backend import StepHandlers
from ..type_vocabulary import NonEmptyString, PositiveInteger
from .backend import PolarsTabularBackend


class CSVReaderOptions(StrictConfigModel):
    """Validate options consumed by the built-in Polars CSV/TSV reader."""

    header_rows: PositiveInteger = 1
    header_separator: NonEmptyString = "|"


class ParquetReaderOptions(StrictConfigModel):
    """JSON-compatible public options supported by the Parquet reader."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    n_rows: int | None = None
    row_index_name: str | None = None
    row_index_offset: int = 0
    parallel: Literal["auto", "columns", "row_groups", "prefiltered", "none"] = "auto"
    use_statistics: bool = True
    hive_partitioning: bool | None = None
    glob: bool = True
    hidden_file_prefix: str | list[str] | None = None
    try_parse_hive_dates: bool = True
    rechunk: bool | None = None
    low_memory: bool = False
    cache: bool = True
    storage_options: dict[str, str] | None = None
    credential_provider: Literal["auto"] | None = "auto"
    retries: int | None = None
    include_file_paths: str | None = None
    missing_columns: Literal["insert", "raise"] = "raise"
    allow_missing_columns: bool | None = None
    extra_columns: Literal["ignore", "raise"] = "raise"


HEADER_READ_OPTIONS = frozenset(
    {
        "separator",
        "comment_prefix",
        "quote_char",
        "skip_rows",
        "skip_lines",
        "encoding",
        "eol_char",
        "decimal_comma",
    }
)


def read_polars_table_file(
    *,
    file_path: Path,
    format_name: str,
    header_rows: int = 1,
    header_separator: str = "|",
    **reader_kwargs: Any,
) -> pl.LazyFrame:
    """Read CSV or TSV input as a Polars lazy frame."""
    if header_rows < 1:
        msg = "header_rows must be at least 1"
        raise ValueError(msg)
    scan_kwargs = dict(reader_kwargs)
    if format_name == "tsv":
        scan_kwargs.setdefault("separator", "\t")
    unknown = scan_kwargs.keys() - signature(pl.scan_csv).parameters.keys()
    if unknown:
        msg = f"Unsupported CSV reader option(s): {sorted(unknown)}"
        raise ValueError(msg)
    if header_rows == 1:
        logger.debug("Scanning {}", file_path)
        return pl.scan_csv(file_path, **scan_kwargs)
    if scan_kwargs.get("has_header") is True:
        msg = "Do not set reader.kwargs.has_header=True when header_rows is greater than 1"
        raise ValueError(msg)
    if "new_columns" in scan_kwargs:
        msg = "Do not set reader.kwargs.new_columns when header_rows is greater than 1"
        raise ValueError(msg)
    if scan_kwargs.get("skip_rows_after_header", 0):
        msg = "skip_rows_after_header cannot be combined with multiple header rows"
        raise ValueError(msg)

    header_options = {key: value for key, value in scan_kwargs.items() if key in HEADER_READ_OPTIONS}
    header = pl.read_csv(
        file_path,
        has_header=False,
        n_rows=header_rows,
        infer_schema=False,
        **header_options,
    )
    if header.height != header_rows:
        msg = f"Expected {header_rows} header rows in {file_path}, found {header.height}"
        raise ValueError(msg)

    header_values = header.rows()
    names: list[str] = []
    for index in range(header.width):
        values = [row[index] for row in header_values]
        parts = [str(value).strip() for value in values if value is not None and str(value).strip()]
        names.append(header_separator.join(parts) if parts else f"column_{index + 1}")
    if len(set(names)) != len(names):
        msg = f"Combining {header_rows} header rows produced duplicate column names: {names}"
        raise ValueError(msg)

    skip_rows = int(scan_kwargs.pop("skip_rows", 0) or 0)
    scan_kwargs["skip_rows"] = skip_rows + header_rows
    scan_kwargs["has_header"] = False
    scan_kwargs["new_columns"] = names
    logger.debug("Scanning {} with {} header rows", file_path, header_rows)
    return pl.scan_csv(file_path, **scan_kwargs)


def read_polars_h5_file(
    *,
    file_path: Path,
    reader_config: ReaderConfig,
    h5_reader: H5Reader | None = None,
) -> pl.LazyFrame:
    """Read a configured HDF5 table into a Polars lazy frame."""
    reader = H5PyFileReader() if h5_reader is None else h5_reader
    source = reader.read_file("hdf5_array", file_path=file_path, reader_config=reader_config)["data"]
    if not isinstance(source, ArraySource) or not isinstance(source.data, dict):
        msg = "HDF5 reader must return one named array mapping"
        raise ValueError(msg)
    return pl.DataFrame(source.data).lazy()


class PolarsTabularFileReader(FileReader):
    """Read supported tabular files into Polars lazy frames."""

    def __init__(
        self,
        *,
        h5_reader: H5Reader | None = None,
        step_handlers: StepHandlers | None = None,
    ) -> None:
        """Select the HDF5 format reader and matching processing backend."""
        self.h5_reader = h5_reader
        self.backend: PolarsTabularBackend = PolarsTabularBackend(step_handlers=step_handlers)

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        """Read tabular formats into Polars-backed named sources."""
        frame: pl.LazyFrame
        if format_name in {"csv", "tsv"}:
            reader_kwargs = dict(reader_config.options)
            option_values = {
                name: reader_kwargs.pop(name)
                for name in ("header_rows", "header_separator")
                if name in reader_kwargs
            }
            try:
                options = CSVReaderOptions.model_validate(option_values)
            except PydanticValidationError as error:
                msg = f"Invalid CSV reader options: {error}"
                raise ValueError(msg) from error
            frame = read_polars_table_file(
                file_path=file_path,
                format_name=format_name,
                header_rows=options.header_rows,
                header_separator=options.header_separator,
                **reader_kwargs,
            )
        elif format_name == "hdf5":
            frame = read_polars_h5_file(
                file_path=file_path,
                reader_config=reader_config,
                h5_reader=self.h5_reader,
            )
        elif format_name == "parquet":
            try:
                parquet_options = ParquetReaderOptions.model_validate(reader_config.options)
            except PydanticValidationError as error:
                msg = f"Invalid Parquet reader options: {error}"
                raise ValueError(msg) from error
            frame = pl.scan_parquet(
                file_path,
                n_rows=parquet_options.n_rows,
                row_index_name=parquet_options.row_index_name,
                row_index_offset=parquet_options.row_index_offset,
                parallel=parquet_options.parallel,
                use_statistics=parquet_options.use_statistics,
                hive_partitioning=parquet_options.hive_partitioning,
                glob=parquet_options.glob,
                hidden_file_prefix=parquet_options.hidden_file_prefix,
                try_parse_hive_dates=parquet_options.try_parse_hive_dates,
                rechunk=parquet_options.rechunk,
                low_memory=parquet_options.low_memory,
                cache=parquet_options.cache,
                storage_options=parquet_options.storage_options,
                credential_provider=parquet_options.credential_provider,
                retries=parquet_options.retries,
                include_file_paths=parquet_options.include_file_paths,
                missing_columns=parquet_options.missing_columns,
                allow_missing_columns=parquet_options.allow_missing_columns,
                extra_columns=parquet_options.extra_columns,
            )
        else:
            msg = f"Polars cannot read format {format_name!r}"
            raise ValueError(msg)
        return {"data": TabularSource(frame, self.backend)}
