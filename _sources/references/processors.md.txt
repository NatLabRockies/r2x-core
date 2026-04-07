# Data Processors

Data processors are used internally by the DataReader to apply transformations to data files based on specifications in DataFile configurations. These transformations are applied automatically and do not need to be called directly.

## Usage Examples

### Automatic Transformation

Transformations are applied automatically by DataReader:

```python
from pathlib import Path
from r2x_core import DataReader, DataFile, TabularProcessing

# Define data file with transformations
data_file = DataFile(
    name="generators",
    fpath=Path("data/generators.csv"),
    proc_spec=TabularProcessing(
        drop_columns=["old_col"],
        column_mapping={"gen_id": "id", "gen_name": "name"},
        column_schema={"capacity": "Float64", "year": "Int64"},
        filter_by={"year": 2030},
        select_columns=["capacity", "name"],
    ),
)

# Transformations applied automatically
reader = DataReader()
data = reader.read_data_file(folder=".", data_file=data_file)
# Returns transformed LazyFrame with dropped columns, renamed, cast, filtered, and selected
```

### Manual Transformation

```python
from r2x_core.processors import process_tabular_data
import polars as pl

# Load raw data
df = pl.scan_csv("data/generators.csv")

# Apply transformations manually
transformed = process_tabular_data(data_file, df)

# Collect results
result = transformed.collect()
```

### Custom Transformation

Register a custom transformation for a new data type:

```python
from r2x_core.processors import register_transformation
from r2x_core import DataFile

class MyDataType:
    def __init__(self, data):
        self.data = data

def transform_my_data(data_file: DataFile, data: MyDataType) -> MyDataType:
    """Custom transformation for MyDataType."""
    # Apply transformations
    transformed_data = data.data.upper()
    return MyDataType(transformed_data)

# Register the transformation
register_transformation(MyDataType, transform_my_data)

# Now apply_processing will use it automatically
from r2x_core.processors import apply_processing

my_data = MyDataType("hello")
transformed = apply_processing(data_file, my_data)
```

### Polars Filter Expressions

Build custom filter expressions:

```python
from r2x_core.processors import pl_build_filter_expr
import polars as pl

# Simple value filter
expr1 = pl_build_filter_expr("year", 2030)
# Returns: pl.col("year") == 2030

# List filter (IN)
expr2 = pl_build_filter_expr("status", ["active", "planned"])
# Returns: pl.col("status").is_in(["active", "planned"])

# Datetime year filter
expr3 = pl_build_filter_expr("datetime", 2030)
# Returns: pl.col("datetime").dt.year() == 2030

# Datetime year list filter
expr4 = pl_build_filter_expr("datetime", [2030, 2035, 2040])
# Returns: pl.col("datetime").dt.year().is_in([2030, 2035, 2040])

# Apply filters to dataframe
df = pl.scan_csv("data.csv")
filtered = df.filter(expr1 & expr2)
```

## Type System

The processors use Polars type strings for schema casting:

```python
# Schema mapping in DataFile
schema = {
    "capacity": "Float64",      # Float
    "year": "Int64",            # Integer
    "name": "Utf8",             # String
    "active": "Boolean",        # Boolean
    "date": "Date",             # Date
    "datetime": "Datetime",     # Datetime
}

processing = TabularProcessing(column_schema=schema)
```

Supported Polars types include:

- Numeric: Int8, Int16, Int32, Int64, UInt8, UInt16, UInt32, UInt64, Float32, Float64
- String: Utf8, Categorical
- Boolean: Boolean
- Temporal: Date, Datetime, Duration, Time
- Complex: List, Struct

## Functional Design

The processors module uses functional programming patterns:

- **Pure functions**: All transformations are side-effect free
- **Partial application**: Bind DataFile to create reusable transforms
- **Function composition**: Pipeline multiple transformations
- **Single dispatch**: Automatic selection based on type

```python
from functools import partial
from r2x_core.processors import pl_lowercase, pl_drop_columns

# Create bound transformation
lowercase_transform = partial(pl_lowercase, data_file)

# Apply to multiple dataframes
df1_transformed = lowercase_transform(df1)
df2_transformed = lowercase_transform(df2)
```

## See Also

- {doc}`../how-tos/read-data-files` - Data reading guide
- {doc}`./file-formats` - File format configuration
- {doc}`./models` - DataFile model reference
