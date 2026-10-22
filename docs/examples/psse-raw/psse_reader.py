"""Decoder for an illustrative CSV-like grammar, not actual PSS/E RAW."""

import csv
from pathlib import Path

import polars as pl

from r2x_core.datafile import ReaderConfig
from r2x_core.file_reader import DecodedSources, FileReader, TabularSource
from r2x_core.models import StrictConfigModel
from r2x_core.polars_adapter import PolarsTabularBackend


class DummyRawOptions(StrictConfigModel):
    """Options accepted by this example reader."""

    encoding: str = "utf-8"


class DummyPSSEReader(FileReader):
    """Decode the invented BUS/GEN records into named tabular sources."""

    def __init__(self) -> None:
        """Pair decoded tables with their Polars processing implementation."""
        self.backend = PolarsTabularBackend()

    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        """Decode syntax only, retaining all generator records for configured filters."""
        if format_name != "dummy_raw":
            msg = f"Unsupported illustrative format {format_name!r}"
            raise ValueError(msg)
        options = DummyRawOptions.model_validate(reader_config.options)
        buses: list[dict[str, object]] = []
        generators: list[dict[str, object]] = []
        with file_path.open(encoding=options.encoding, newline="") as file:
            for row in csv.reader(file, skipinitialspace=True):
                if not row or row[0].startswith("#"):
                    continue
                match row:
                    case ["BUS", number, name, base_kv]:
                        buses.append({"bus_number": int(number), "bus_name": name, "base_kv": float(base_kv)})
                    case ["GEN", number, machine_id, power, status]:
                        generators.append(
                            {
                                "bus_number": int(number),
                                "machine_id": machine_id,
                                "p_mw": float(power),
                                "status": int(status),
                            }
                        )
                    case _:
                        msg = f"Invalid illustrative record: {row}"
                        raise ValueError(msg)
        return {
            "buses": TabularSource(
                pl.DataFrame(
                    buses,
                    schema={"bus_number": pl.Int64, "bus_name": pl.String, "base_kv": pl.Float64},
                ).lazy(),
                self.backend,
            ),
            "generators": TabularSource(
                pl.DataFrame(
                    generators,
                    schema={
                        "bus_number": pl.Int64,
                        "machine_id": pl.String,
                        "p_mw": pl.Float64,
                        "status": pl.Int64,
                    },
                ).lazy(),
                self.backend,
            ),
        }
