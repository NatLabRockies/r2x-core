# HDF5 Reader System

## Overview

The HDF5 reader in r2x-core uses a configuration-driven approach to read files
with any structure. Instead of hardcoding logic for specific file formats, users
describe their file's structure through configuration parameters.

## Design Philosophy

HDF5 files have no standard structure. Different models, tools, and users
organize data differently. Dataset names vary between `data`, `values`,
`measurements`, and countless other possibilities. Column names might be in
separate datasets or embedded within the data. Datetime fields have different
formats and timezone handling requirements. Metadata can be stored anywhere in
the file hierarchy.

The reader addresses this variability through configuration. Users describe what
their file contains and where to find it. A file with data in a dataset called
`measurements` and column names in `sensor_names` needs only this configuration:

```python
reader_kwargs = {
    "data_key": "measurements",
    "columns_key": "sensor_names"
}
```

This approach keeps the library model-agnostic. The framework doesn't need to
know about ReEDS, PLEXOS, or any specific model format. Users adapt the reader
to their files through configuration rather than waiting for library updates or
writing custom code.

## How the Reader Works

The `configurable_h5_reader()` function adapts its behavior based on the
configuration provided.

### Default Behavior

When no configuration is provided, the reader finds the first dataset in the
file and reads it. For 1D arrays, this creates a single column. For 2D arrays,
it creates numbered columns like `col_0`, `col_1`, and so on.

```python
from pathlib import Path
from r2x_core import DataFile

# No reader_kwargs provided
datafile = DataFile(name="data", fpath=Path("file.h5"))
```

### Specifying the Data Location

The `data_key` parameter tells the reader which dataset contains the main data.
This is useful when files contain multiple datasets and you want a specific one
rather than just the first.

```python
reader_kwargs = {"data_key": "measurements"}
```

### Adding Column Names

For 2D data arrays, the `columns_key` parameter points to a dataset containing
column names. The reader splits the 2D array into named columns using these
names. Byte strings are automatically decoded to UTF-8 for convenience.

```python
reader_kwargs = {
    "data_key": "values",
    "columns_key": "sensor_names"
}
```

### Parsing Datetime Fields

The `datetime_key` parameter identifies a dataset containing datetime strings.
The reader parses these strings, stripping timezone information by default, and
converts them to numpy `datetime64[us]` format for compatibility with Polars.
The resulting column is named `datetime` by default, though this can be
customized with `datetime_column_name`.

```python
reader_kwargs = {
    "data_key": "data",
    "datetime_key": "timestamps"
}
```

Timezone stripping handles the common case where energy models use a single
reference timezone. Most datetime parsing in numpy and Polars is simpler without
timezone information. Users who need to preserve the original timezone strings
can set `strip_timezone=False`.

### Including Additional Metadata

The `additional_keys` parameter specifies other datasets to include as columns.
The reader automatically formats these names for cleaner output, converting
names like `index_year` to `solve_year`. If a specified key doesn't exist in the
file, it's simply skipped.

```python
reader_kwargs = {
    "data_key": "data",
    "columns_key": "columns",
    "additional_keys": ["year", "scenario", "location"]
}
```

## Configuration Parameters

Configuration parameters fall into three categories based on what data they
extract from your HDF5 file.

For data configuration, the `data_key` parameter tells the reader which dataset
contains the main data array. It accepts a string and defaults to the first
dataset if not provided, making it optional for simple files. The `columns_key`
parameter points to a dataset containing column names for 2D data arrays. This
is optional and only needed if your file stores column names separately. The
`index_key` parameter identifies a dataset to include as an index column
separate from datetime indices, useful for zone names, component IDs, or other
index-like information.

For datetime configuration, the `datetime_key` parameter specifies which dataset
contains datetime strings to parse. Datetime parsing is optional if your time
series doesn't need temporal information. The `datetime_column_name` parameter
sets what to name the resulting datetime column in your DataFrame. It defaults
to "datetime" but can be customized to match your naming convention. The
`strip_timezone` parameter controls timezone handling. It defaults to true,
stripping timezone information before parsing. Set it to false if you need to
preserve the original timezone strings from your HDF5 file.

For additional data, the `additional_keys` parameter lists other datasets to
include as columns in your output. This defaults to an empty list and accepts a
list of strings pointing to any other datasets you want. The `decode_bytes`
parameter controls whether byte strings (how HDF5 often stores text) are decoded
to UTF-8. It defaults to true, which is appropriate for almost all use cases
where you want human-readable strings in your output DataFrame.

## Automatic Behaviors

The reader automatically detects array dimensions and creates appropriate
columns. A 1D array becomes a single column. A 2D array without column names
gets numbered columns like `data_col_0` and `data_col_1`. A 2D array with column
names (via `columns_key`) gets those human-readable names applied.

Column name formatting happens automatically for cleaner output. Dataset keys
like `index_year` are automatically transformed to `solve_year` following energy
model conventions. The `index_` prefix common in HDF5 files is stripped away to
produce clean column names in your DataFrame. This saves configuration and makes
the resulting data more usable without manual column renaming.

Byte string decoding converts HDF5 byte strings to Python Unicode strings
automatically when `decode_bytes` is true. HDF5 typically stores text as bytes
since it predates Python 3's Unicode strings. The reader handles this conversion
transparently, so your DataFrame contains native Python strings ready for
analysis.

## Architecture Decisions

### Configuration Over Custom Functions

The library could allow users to provide custom reader functions that contain
arbitrary logic for reading files. While flexible, this approach doesn't work
with JSON configuration files. Users would need to write Python code, making it
harder to version control configurations separately from code. Testing would
require understanding each custom function's logic. Configuration, by contrast,
works seamlessly with JSON, requires no code, and is self-documenting.

### Single Generic Reader Over Multiple Reader Classes

The library could provide different reader classes for different model formats,
like `ReedsH5Reader` or `PlexosH5Reader`. This would create coupling between the
library and specific models. The library would need to know about every format
and maintain code for each. Users would be locked into predefined formats. A
single generic reader configured by users avoids all these issues while
providing unlimited flexibility.

### Single Dispatch for File Types

The file reading system uses Python's `functools.singledispatch` to route
different file formats to appropriate readers. Each file format type
(`H5Format`, `TableFormat`, etc.) gets dedicated reading logic. This provides
type-based routing at runtime, makes it easy to extend with new formats, and
maintains clear separation of concerns between different file types.

## Trade-offs

Configuration requires users to specify file structure explicitly. This
verbosity is acceptable because most users read the same files repeatedly, so
configuration is written once. The explicitness prevents silent errors from
wrong assumptions. Configuration serves as documentation of file structure and
can be version controlled alongside data.

The reader doesn't validate that specified keys exist until files are actually
read. Early validation would require opening files during configuration, which
is expensive and unnecessary. Delayed validation provides better error messages
with context about what failed during reading. Missing keys in lists like
`additional_keys` are gracefully handled by skipping them.

Datetime parsing assumes ISO 8601 format with specific timezone handling. This
covers the vast majority of HDF5 datetime storage. Edge cases can disable
automatic parsing with `strip_timezone=False` and handle conversion manually.
Complex datetime parsing belongs in preprocessing steps rather than the core
library.

## Future Considerations

Chunk reading for very large files could improve memory efficiency by processing
data in pieces. Lazy evaluation could defer reading until data is actually
needed. Optional schema validation could check file structure against expected
configurations. Automatic compression handling could simplify working with
compressed datasets.

The library intentionally avoids auto-detecting file structure. Users should
know their data. Format conversion between different HDF5 structures belongs in
external tools. Model-specific logic defeats the purpose of a generic,
configuration-driven approach.

## Power System Data in HDF5

Power system models (ReEDS, PLEXOS, SWITCH, Sienna, etc.) store results as time
series data in HDF5 format. Understanding the structure of power system outputs
is key to configuring the reader correctly.

### Common Power System Data Characteristics

Power system models output data at consistent temporal intervals, though the
granularity varies by tool. ReEDS produces 8760 hourly records per year,
covering a complete year at hourly resolution. PLEXOS can generate much
finer-grained data with 5-minute interval output (105,120 intervals per year).
When analyzing multi-year scenarios, these intervals simply stack together, so a
10-year ReEDS run contains 87,600 records. This temporal structure fundamentally
drives decisions about how the HDF5 file should be organized.

Spatial aggregation also varies significantly across power system models. ReEDS
aggregates results to approximately 134 geographic regions, maintaining
consistent spatial definitions across different output types like generation,
demand, and curtailment. PLEXOS, by contrast, operates at the bus level for
maximum nodal detail. SWITCH uses zones for spatial aggregation. Within a single
model, different output types can have different spatial definitions. For
example, generation results might be aggregated to regions while price results
remain at the bus level. This complexity requires careful configuration to
extract the right data.

A single HDF5 file rarely contains just one output metric. Most power system
runs produce multiple related outputs stored in the same file: generation by
resource type, transmission flows, nodal prices, reserve margins, load shedding,
and many more. Each metric may have different spatial resolution (regional
versus bus-level) or temporal resolution (hourly versus sub-hourly intervals).
This creates a nested structure in the HDF5 file where each metric gets its own
group or set of datasets.

Power system models typically explore multiple scenarios representing different
policy assumptions, technology costs, or operational strategies. A single model
run might include ten scenarios under different decarbonization pathways, and
longer planning analyses examine multiple years or decades. The output file
includes metadata identifying which scenario, base year, and solve year
corresponds to each record. This metadata is often stored alongside the time
series data, requiring careful configuration to extract and include it.

Most power system models use a reference timezone throughout analysis, often UTC
or a specific regional timezone. HDF5 stores datetime strings with explicit
timezone information (like `2026-01-18T12:30:00Z`). The configurable reader
strips timezones by default because most power system analysis uses a single
consistent timezone. This simplifies parsing and matches the typical workflow
where analysts work in their model's reference timezone rather than converting
between zones.

### Typical Power System HDF5 Layout

```
power_system_results.h5
├── time_series_metric_1/
│   ├── data                    # 2D array (time × space)
│   ├── columns                 # Spatial dimension names
│   ├── timestamps              # Temporal dimension
│   └── metadata_columns        # Scenario, year, or other attributes
├── time_series_metric_2/
│   ├── data
│   ├── columns
│   ├── timestamps
│   └── metadata_columns
├── ...
└── attributes/
    ├── scenario_name
    ├── base_year
    ├── version
    └── description
```

Different power system models use different naming conventions that reflect
their design philosophy and intended use. ReEDS uses descriptive flat names like
`hourly_demand`, `hourly_generation`, and `hourly_curtailment` making the HDF5
structure self-documenting. PLEXOS employs hierarchical groups organizing
results by category: `Solution/Generator Output`, `Solution/Price`, and so on,
separating results from metadata. SWITCH uses a flat naming structure like
`dispatch_zone_power_mw` where the name itself describes the metric. Sienna
stores time series with resource-specific names reflecting its component-based
architecture.

Despite these differences in naming and organization, all require configuration
to tell r2x-core where to find the data arrays, column definitions, and temporal
information. The configurable reader abstracts away these naming differences,
allowing your translation pipeline to handle ReEDS, PLEXOS, and other models
with nothing more than configuration changes.

## Examples of File Structures

### ReEDS Hourly Time Series

ReEDS (Regional Energy Deployment System) structures its hourly time series
output in HDF5 with the following layout:

```
reeds_hourly_data.h5
├── hourly_demand/
│   ├── data (8760 x 134)          # Hourly generation, 134 regions
│   ├── columns (134,)             # Region/zone IDs
│   ├── timestamps (8760,)         # ISO 8601 UTC timestamps
│   └── year (8760,)               # Solve year for each hour
├── hourly_curtailment/
│   ├── data (8760 x 134)          # Curtailment by region
│   ├── columns (134,)
│   ├── timestamps (8760,)
│   └── year (8760,)
└── metadata/
    ├── scenario_name               # Scenario identifier
    ├── regions (134,)              # Full region names
    └── base_year                   # Reference year
```

ReEDS organizes multiple datasets representing different output types like
generation, demand, and curtailment. All output types share the same column
definitions (the same 134 regions), simplifying the configuration process.
Datetime information is stored as ISO 8601 strings with UTC timezone. Year
metadata is stored alongside the time series to support multi-year simulations
where different records correspond to different solve years. Region names appear
both as column indices in the data array and as full descriptive names in a
separate dataset, allowing the reader to create self-documenting DataFrames.

**Configuration for ReEDS Generation Data**:

```python
reader_kwargs = {
    "data_key": "hourly_demand/data",
    "columns_key": "hourly_demand/columns",
    "datetime_key": "hourly_demand/timestamps",
    "additional_keys": ["hourly_demand/year"],
    "strip_timezone": True
}
```

### PLEXOS Interval Output

PLEXOS (energy market and operations model) stores interval-based results with
this structure:

```
plexos_results.h5
├── Solution/
│   ├── Generator Output (8760 x 500)    # Generation by unit
│   ├── Generator Output_names (500,)    # Generator names
│   ├── Generator Output_regions (500,)  # Region identifiers
│   ├── Price (8760 x 50)                # LMP by bus
│   ├── Price_names (50,)                # Bus names
│   ├── Period (8760,)                   # Period identifiers
│   └── Interval (8760,)                 # Interval timestamps
└── Information/
    ├── run_id
    ├── description
    └── model_version
```

PLEXOS uses a hierarchical structure separating results into a Solution group
and metadata into an Information group. Unlike ReEDS where all metrics share the
same spatial definitions, PLEXOS Generator Output has 500 generators while Price
data has only 50 buses, requiring separate column definitions for each metric.
The temporal dimension uses mixed identifiers: Period represents sequential
periods in the optimization (day, week, etc.) while Interval contains the actual
timestamps. Generator output operates at the unit level for maximum detail
rather than aggregating to regions. Model metadata like run identifier and
version is stored separately in the Information group rather than alongside the
time series.

**Configuration for PLEXOS Generation Output**:

```python
reader_kwargs = {
    "data_key": "Solution/Generator Output",
    "columns_key": "Solution/Generator Output_names",
    "datetime_key": "Solution/Interval",
    "additional_keys": ["Solution/Generator Output_regions", "Solution/Period"],
    "strip_timezone": True,
    "datetime_column_name": "interval"
}
```

### Generic Energy Model Time Series

```
file.h5
├── data (8760 x 50)        # Hourly data, 50 regions
├── columns (50,)           # Region names
├── index_datetime (8760,)  # Timestamps
└── index_year (8760,)      # Solve year for each hour
```

**Configuration**:

```python
reader_kwargs = {
    "data_key": "data",
    "columns_key": "columns",
    "datetime_key": "index_datetime",
    "additional_keys": ["index_year"]
}
```

### Scientific Measurements

```
measurements.h5
├── temperature (1000,)     # 1D time series
├── pressure (1000,)        # 1D time series
├── timestamps (1000,)      # When measured
├── sensor_id (1000,)       # Which sensor
└── location (1000,)        # Where measured
```

**Configuration**:

```python
reader_kwargs = {
    "data_key": "temperature",
    "datetime_key": "timestamps",
    "additional_keys": ["pressure", "sensor_id", "location"]
}
```

### Simple Tabular Data

```
simple.h5
└── values (100 x 3)        # Just a 2D array
```

**Configuration**:

```python
# No configuration needed - uses default
reader_kwargs = {}
```

## Summary

The HDF5 reader achieves flexibility through configuration rather than code. The
library remains model-agnostic with no hardcoded knowledge of specific power
system models (ReEDS, PLEXOS, SWITCH, Sienna, etc.) or any other data format.
Users control everything through configuration parameters. The approach works
seamlessly with JSON configuration files and is self-documenting. A single code
path handles all formats and power system models, making the system
maintainable. New power system models, formats, or file structures need only new
configuration, never code changes.

### Practical Workflow

Using the configurable HDF5 reader starts with understanding your specific power
system file. Begin by exploring the HDF5 structure with standard tools like
`h5py` or the command-line `h5dump` utility. Map out where the main data array
lives, which dataset contains column names, and where datetime information is
stored. Some files organize everything in flat groups while others use
hierarchical structures.

With the file structure mapped, write your configuration by creating
`reader_kwargs` that tells r2x-core where to find each piece of information.
Point `data_key` to your data array, `columns_key` to column names,
`datetime_key` to timestamps, and `additional_keys` to any metadata you want to
include. This configuration is just a Python dictionary and can be stored in
JSON for easy version control.

Test your configuration by reading a small sample of your file. Verify that the
resulting DataFrame has the expected columns, correct datetime parsing, and all
required metadata. Iterate on the configuration if needed. Once working, store
the configuration alongside your translation code. The configuration becomes
documentation of your power system model's file structure, making it trivial for
colleagues to understand and reproduce your exact translation pipeline.
Configuration changes stay in version control, creating an audit trail of how
your data processing evolved.
