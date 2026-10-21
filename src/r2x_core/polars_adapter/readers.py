"""Polars-backed readers for tabular formats."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger
from pydantic import ValidationError as PydanticValidationError

from ..datafile import ReaderConfig
from ..file_reader import FileReader
from ..h5_adapter import H5PyFileReader, H5Reader
from ..models import StrictConfigModel
from ..types import FileFormat, H5Format, NonEmptyString, ParquetFormat, PositiveInteger, TableFormat


class CSVReaderOptions(StrictConfigModel):
    """Validate options consumed by the built-in Polars CSV/TSV reader."""

    header_rows: PositiveInteger = 1
    header_separator: NonEmptyString = "|"


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
    header_rows: int = 1,
    header_separator: str = "|",
    **reader_kwargs: Any,
) -> pl.LazyFrame:
    """Read CSV or TSV input as a Polars lazy frame."""
    if header_rows < 1:
        msg = "header_rows must be at least 1"
        raise ValueError(msg)
    scan_kwargs = dict(reader_kwargs)
    if file_path.suffix.lower() == ".tsv":
        scan_kwargs.setdefault("separator", "\t")
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
    data = reader.read_file(H5Format(), file_path=file_path, reader_config=reader_config)
    return pl.DataFrame(data).lazy()


class PolarsTabularFileReader(FileReader[pl.LazyFrame]):
    """Read supported tabular files into Polars lazy frames."""

    def __init__(self, *, h5_reader: H5Reader | None = None) -> None:
        """Select the HDF5 format reader used by Polars."""
        self.h5_reader = h5_reader

    def supports_file_type(self, file_type: FileFormat, /) -> bool:
        """Return whether this reader supports the file format."""
        return isinstance(file_type, (TableFormat, H5Format, ParquetFormat))

    def read_file(
        self,
        file_type: FileFormat,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> pl.LazyFrame:
        """Read a supported file format into a Polars lazy frame."""
        if isinstance(file_type, TableFormat):
            reader_kwargs = dict(reader_config.kwargs)
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
            return read_polars_table_file(
                file_path=file_path,
                header_rows=options.header_rows,
                header_separator=options.header_separator,
                **reader_kwargs,
            )
        if isinstance(file_type, H5Format):
            return read_polars_h5_file(
                file_path=file_path,
                reader_config=reader_config,
                h5_reader=self.h5_reader,
            )
        if isinstance(file_type, ParquetFormat):
            return pl.scan_parquet(file_path, **reader_config.kwargs)
        msg = f"Polars cannot read file type {type(file_type).__name__}"
        raise ValueError(msg)
