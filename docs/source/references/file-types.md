# File Formats

`DataFile.file_type` returns a lightweight marker selected from the file extension. The format markers, extension mapping, and `TableDataFormat` alias are defined in `r2x_core.types`.

## Supported formats

| Marker | Extensions | Time-series support |
| --- | --- | --- |
| `TableFormat` | `.csv`, `.tsv` | Yes |
| `H5Format` | `.h5`, `.hdf5` | Yes |
| `ParquetFormat` | `.parquet` | Yes |
| `JSONFormat` | `.json` | No |
| `XMLFormat` | `.xml` | No |

The extension-to-marker mapping is `EXTENSION_MAPPING`. Tabular markers are represented by the `TableDataFormat` union.

```python
from pathlib import Path

from r2x_core import DataFile
from r2x_core.types import H5Format, TableDataFormat, TableFormat

csv_file = DataFile(name="profiles", fpath=Path("profiles.csv"))
assert isinstance(csv_file.file_type, TableFormat)

h5_file = DataFile(name="load", fpath=Path("load.h5"))
assert isinstance(h5_file.file_type, H5Format)

file_type: TableDataFormat = csv_file.file_type
```

All format markers are dataclasses with slots. `supports_timeseries` is a class-level capability flag. A `DataFile` marked as time-series data cannot use a format whose marker sets this flag to `False`.

Adding a new extension requires a marker in `r2x_core.types.EXTENSION_MAPPING` and a reader that supports that marker. Applications can supply tabular readers and backends through the public reader interfaces without changing the core processing pipeline.
