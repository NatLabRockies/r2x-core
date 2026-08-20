# File Types API Reference

This document describes the file type system in r2x-core, which is used to validate and handle different data file formats.

## Overview

The `FileType` class hierarchy provides a type-safe way to work with different file formats. Each file type knows whether it can support time series data through the `supports_timeseries` attribute.

## Base Class

### `FileType`

```python
@dataclass(slots=True)
class FileType:
    """Base class for file data types."""

    supports_timeseries: bool = False
    model_config = ConfigDict(arbitrary_types_allowed=True)
```

**Attributes:**

- `supports_timeseries` (bool): Whether this file type can store time series data. Default is `False`.

## File Type Classes

### `TableFile`

Represents tabular data files (CSV, TSV).

```python
class TableFile(FileType):
    """Data model for tabular data (CSV, TSV, etc.)."""

    supports_timeseries: bool = True
```

**Supported Extensions:**

- `.csv` - Comma-separated values
- `.tsv` - Tab-separated values

**Time Series Support:** ✅ Yes

**Use Cases:**

- Component definitions (generators, buses, lines)
- Time series profiles (hourly generation, load)
- Human-readable data interchange

**Example:**

```python
from pathlib import Path
from r2x_core import DataFile, FileInfo

# Component data
components = DataFile(
    name="generators",
    fpath=Path("data/generators.csv"),
)
assert isinstance(components.file_type, TableFile)

# Time series data
profiles = DataFile(
    name="profiles",
    fpath=Path("data/profiles.csv"),
    info=FileInfo(is_timeseries=True),
)
assert isinstance(profiles.file_type, TableFile)
```

### `H5File`

Represents HDF5 (Hierarchical Data Format) files.

```python
class H5File(FileType):
    """Data model for HDF5 data."""

    supports_timeseries: bool = True
```

**Supported Extensions:**

- `.h5` - HDF5 format
- `.hdf5` - HDF5 format (alternate extension)

**Time Series Support:** ✅ Yes

**Use Cases:**

- Large time series datasets
- Multi-year profiles in hierarchical structure
- High-performance data storage
- Complex nested data structures

**Example:**

```python
# Multi-year time series in HDF5
profiles = DataFile(
    name="generation_profiles",
    fpath=Path("data/profiles_2020_2050.h5"),
    info=FileInfo(is_timeseries=True),
)
assert isinstance(profiles.file_type, H5File)
assert profiles.file_type.supports_timeseries
```

### `ParquetFile`

Represents Apache Parquet columnar storage files.

```python
class ParquetFile(FileType):
    """Data model for Parquet data."""

    supports_timeseries: bool = True
```

**Supported Extensions:**

- `.parquet` - Apache Parquet format

**Time Series Support:** ✅ Yes

**Use Cases:**

- Large time series with excellent compression
- Wide tables with many columns
- Data interchange with analytics tools
- Efficient columnar queries

**Example:**

```python
# Load profiles in Parquet format
load_data = DataFile(
    name="load_profiles",
    fpath=Path("data/load.parquet"),
    info=FileInfo(is_timeseries=True),
)
assert isinstance(load_data.file_type, ParquetFile)
```

### `JSONFile`

Represents JSON (JavaScript Object Notation) files.

```python
class JSONFile(FileType):
    """Data model for JSON data."""

    supports_timeseries: bool = False
```

**Supported Extensions:**

- `.json` - JSON format

**Time Series Support:** ❌ No

**Use Cases:**

- Component definitions
- Configuration files
- Metadata
- Hierarchical component relationships

**Example:**

```python
# Component metadata in JSON
metadata = DataFile(
    name="model_metadata",
    fpath=Path("data/metadata.json"),
    info=FileInfo(is_timeseries=False),  # Default
)
assert isinstance(metadata.file_type, JSONFile)
assert not metadata.file_type.supports_timeseries

# This would raise ValueError
# bad = DataFile(
#     fpath=Path("data/profiles.json"),
#     info=FileInfo(is_timeseries=True),  # ERROR! JSON doesn't support time series
# )
```

### `XMLFile`

Represents XML (eXtensible Markup Language) files.

```python
class XMLFile(FileType):
    """Data model for XML data."""

    supports_timeseries: bool = False
```

**Supported Extensions:**

- `.xml` - XML format

**Time Series Support:** ❌ No

**Use Cases:**

- Legacy model formats
- Hierarchical component definitions
- Configuration with complex nesting

**Example:**

```python
# Component definitions in XML
components = DataFile(
    name="network",
    fpath=Path("data/network.xml"),
)
assert isinstance(components.file_type, XMLFile)
assert not components.file_type.supports_timeseries
```

## Extension Mapping

The `EXTENSION_MAPPING` dictionary maps file extensions to their corresponding `FileType` classes:

```python
EXTENSION_MAPPING: dict[str, type[FileType]] = {
    ".csv": TableFile,
    ".tsv": TableFile,
    ".h5": H5File,
    ".hdf5": H5File,
    ".parquet": ParquetFile,
    ".json": JSONFile,
    ".xml": XMLFile,
}
```

This mapping is used internally by `DataFile.file_type` to determine the file type from the file extension.

## Type Alias

### `TableDataFileType`

A type alias for file types that represent tabular data:

```python
TableDataFileType: TypeAlias = TableFile | H5File
```

**Usage:**

```python
from r2x_core.file_types import TableDataFileType

def process_table_data(file_type: TableDataFileType) -> None:
    """Process tabular data files."""
    match file_type:
        case TableFile():
            # Handle CSV/TSV
            ...
        case H5File():
            # Handle HDF5
            ...
```

## Validation

File types are validated automatically when accessing `DataFile.file_type`:

```python
from pathlib import Path
from r2x_core import DataFile, FileInfo

# Valid: CSV supports time series
valid = DataFile(
    name="profiles",
    fpath=Path("data/profiles.csv"),
    info=FileInfo(is_timeseries=True),
)
print(valid.file_type)  # TableFile()

# Invalid: Unknown extension
try:
    invalid_ext = DataFile(
        name="data",
        fpath=Path("data/file.xyz"),
    )
    _ = invalid_ext.file_type  # Raises ValueError
except ValueError as e:
    print(e)  # "Unsupported file extension: .xyz"

# Invalid: JSON doesn't support time series
try:
    invalid_ts = DataFile(
        name="profiles",
        fpath=Path("data/profiles.json"),
        info=FileInfo(is_timeseries=True),
    )
    _ = invalid_ts.file_type  # Raises ValueError
except ValueError as e:
    print(e)  # "File type JSONFile does not support time series data..."
```

## Adding New File Types

To add support for a new file format:

1. **Create a new FileType subclass:**

```python
@dataclass(slots=True)
class NetCDFFile(FileType):
    """Data model for NetCDF data."""

    supports_timeseries: bool = True  # If it supports time series
```

2. **Add to EXTENSION_MAPPING:**

```python
EXTENSION_MAPPING: dict[str, type[FileType]] = {
    # ... existing mappings ...
    ".nc": NetCDFFile,
    ".netcdf": NetCDFFile,
}
```

3. **Update TableDataFileType if needed:**

```python
# If the new type represents tabular data
TableDataFileType: TypeAlias = TableFile | H5File | NetCDFFile
```

That's it! The validation and type checking will work automatically.

## Best Practices

1. **Set supports_timeseries correctly**: This determines what kinds of data can be stored in this format.

2. **Use type hints**: When writing functions that work with specific file types, use type hints for better IDE support:

   ```python
   def process_csv(file_type: TableFile) -> None:
       ...
   ```

3. **Pattern matching**: Use structural pattern matching to handle different file types:

   ```python
   match datafile.file_type:
       case TableFile():
           ...
       case H5File():
           ...
       case ParquetFile():
           ...
   ```

4. **Check supports_timeseries**: Before processing time series, verify the file type supports it:
   ```python
   if datafile.info and datafile.info.is_timeseries:
       assert datafile.file_type.supports_timeseries
       # Safe to process as time series
   ```

## See Also

- [DataFile Reference](models.md) - Complete DataFile API
- {doc}`../how-tos/attach-timeseries` - Time series guide
- {doc}`../how-tos/build-parsers` - Using file types in parsers
