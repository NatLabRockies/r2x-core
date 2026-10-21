---
title: "Custom Readers and Tabular Backends"
description: "Use the public reader and processing seams with application-specific adapters."
---

Use `FileReader` to override a supported file format and `TabularBackend` to
process the returned tabular representation. File extensions are registered by
r2x-core, so a custom reader selects an existing format such as CSV rather than
adding a new extension.

The example uses CSV rows as its frame representation. The custom reader takes
precedence over the built-in CSV reader, and the configured backend handles
`TabularProcessing` without importing or invoking Polars. Polars is installed by
default, but these interfaces do not depend on its frame types.

```python doctest
>>> import csv
>>> import tempfile
>>> from pathlib import Path
>>> from typing import TypeGuard
>>>
>>> from rust_ok import Ok, Result
>>> from r2x_core import DataFile, DataReader, FileReader, TabularBackend, TabularProcessing
>>> from r2x_core import FileFormat, H5PyFileReader, H5Reader, ReaderConfig
>>> from r2x_core.types import TableFormat
>>>
>>> CsvRows = list[dict[str, str]]
>>>
>>> class CsvRowsReader(FileReader[CsvRows]):
...     def supports_file_type(self, file_type: FileFormat, /) -> bool:
...         return isinstance(file_type, TableFormat)
...
...     def read_file(
...         self,
...         file_type: FileFormat,
...         /,
...         *,
...         file_path: Path,
...         reader_config: ReaderConfig,
...     ) -> CsvRows:
...         if not self.supports_file_type(file_type):
...             raise ValueError(f"Unsupported format: {type(file_type).__name__}")
...         with file_path.open(newline="", encoding="utf-8") as file:
...             rows = csv.reader(file)
...             headers = next(rows)
...             return [dict(zip(headers, row, strict=True)) for row in rows]
>>>
>>> class CsvRowsBackend(TabularBackend[CsvRows]):
...     def supports_data(self, value: object, /) -> TypeGuard[CsvRows]:
...         return isinstance(value, list) and all(
...             isinstance(row, dict)
...             and all(isinstance(key, str) and isinstance(item, str) for key, item in row.items())
...             for row in value
...         )
...
...     def process(
...         self,
...         frame: CsvRows,
...         *,
...         data_file: DataFile,
...         proc_spec: TabularProcessing,
...     ) -> Result[CsvRows, ValueError]:
...         return Ok(frame)
>>>
>>> issubclass(H5PyFileReader, H5Reader)
True
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     csv_path = Path(tmpdir) / "plants.csv"
...     _ = csv_path.write_text("plant,capacity\nA,10\n", encoding="utf-8")
...     data_file = DataFile(name="plants", fpath=csv_path)
...     rows = DataReader(file_readers=[CsvRowsReader()]).read_data_file(
...         data_file, folder_path=Path(tmpdir)
...     )
...     rows
[{'plant': 'A', 'capacity': '10'}]
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     csv_path = Path(tmpdir) / "plants.csv"
...     _ = csv_path.write_text("plant,capacity\nA,10\n", encoding="utf-8")
...     data_file = DataFile(
...         name="plants", fpath=csv_path, proc_spec=TabularProcessing()
...     )
...     rows = DataReader(
...         file_readers=[CsvRowsReader()], tabular_backend=CsvRowsBackend()
...     ).read_data_file(data_file, folder_path=Path(tmpdir))
...     rows
[{'plant': 'A', 'capacity': '10'}]
```

The backend can implement transformations over its own frame type. This stub
returns frames unchanged to keep the adapter contract visible. Use the same
interfaces to supply an application-specific reader or processing engine.

Ordered mapping steps use the separate `MappingStepBackend` protocol in
`r2x_core.tabular_backend`. Implement `apply_mapping_operation` only if your
backend needs to support `apply_mapping_steps`.
