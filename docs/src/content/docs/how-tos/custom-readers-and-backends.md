---
title: "Custom Readers and Typed Sources"
description: "Register an application reader while keeping source processing and construction in core."
---

Use `ReaderConfig.format` to select a symbolic format. Common CSV, TSV, Parquet,
HDF5, JSON, and XML formats are inferred from their extensions when that is
unambiguous. An uncommon format supplies an application `FileReader` and a
registration mapping. JSON configuration never imports implementation names.

A reader returns a mapping of source names to `DecodedSource` instances. One
physical input may return several names. `DataReader` resolves input paths,
validates options through the selected reader, reuses decodes only within one
read execution, and resolves named processing dependencies. Use
`DataReader.read_data_files` when an application needs decoded sources without
constructing a `System`.

For configured component construction, applications provide their model module,
reader registration, and the three output instructions in `parser_rules.json`.
`build_system` performs processing, model validation, component construction,
reference resolution, and attachment. The runnable
[illustrative RAW example](https://github.com/NatLabRockies/r2x-core/tree/main/docs/examples/psse-raw) demonstrates
the full route. Its invented CSV-like grammar is not actual PSS/E RAW syntax.

## Pair a payload with its processor

`SourceProcessor[Payload]` processes a particular payload type. A
`ProcessingSource[Payload]` keeps that implementation paired with the payload.
For table-like data, implement `TabularProcessor[Payload]` to provide field,
row, and value access as well as processing. The built-in Polars reader pairs
`LazyFrame` with `PolarsTabularBackend`. JSON and HDF5 array readers retain their
native representations and use their corresponding processors where configured.

An application-defined representation can implement `DecodedSource` directly.
Its `process` method is the processing seam. The reader orchestrator calls that
contract without probing for a built-in wrapper type. Implementations must
return an explicit error for a requested operation they do not support. With
no requested operations, the source passes through unchanged.

```python
from collections.abc import Mapping
from pathlib import Path

from rust_ok import Result
from r2x_core import DataFile, DecodedSource, FileReader, ReaderConfig
from r2x_core.file_reader import DecodedSources
from r2x_core.types import FileProcessing


class VendorReader(FileReader):
    def read_file(
        self,
        format_name: str,
        /,
        *,
        file_path: Path,
        reader_config: ReaderConfig,
    ) -> DecodedSources:
        # Decode vendor syntax and return named typed sources.
        ...
```

The reader owns syntax decoding and option validation, not component creation
or attachment loops. Use existing `TabularProcessing` operations, expressions,
joins, or registered custom mapping handlers where they apply. If decoding
changes representation, make that conversion explicit in the reader or
processor.

## Register and use a custom format

```python
from r2x_core import PluginConfig, build_system
from psse_reader import DummyPSSEReader

config = PluginConfig(
    models=("psse_models",),
    config_path_override="path/to/config",
)
system = build_system(
    config,
    name="case",
    readers={"dummy_raw": DummyPSSEReader()},
)
```

The corresponding `file_mapping.json` selects the symbolic registration with
`{"reader": {"format": "dummy_raw", "options": {}}}`. Reader-specific
options are validated by the application reader. Core does not accept a Python
module path in JSON.
