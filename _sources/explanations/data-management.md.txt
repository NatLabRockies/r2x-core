# Data Management: Design Philosophy

## Overview

r2x-core's data management system ({py:class}`~r2x_core.DataStore`,
{py:class}`~r2x_core.DataFile`, {py:class}`~r2x_core.DataReader`) embodies three
core design principles: configuration-driven workflows, lazy evaluation, and
composable processing. Understanding these principles helps you build
maintainable, debuggable data pipelines.

## Configuration-Driven Approach

The core insight is: **data workflows should be expressed as configuration, not
code**. This separation enables several benefits:

### Reproducibility

When your data transformations are defined in JSON/YAML, they become
version-controllable artifacts alongside your code. You can:

- Track changes to data workflows in git
- Associate data configurations with specific code versions
- Run the same parser against different data configs without recompilation

Example workflow:

```
repo/
├── src/
│   └── my_parser.py (fixed logic)
├── configs/
│   ├── dev_config.json (development data)
│   ├── staging_config.json (staging data)
│   └── prod_config.json (production data)
```

### Flexibility Without Redeployment

In deployment scenarios, particularly cloud-native ones, the ability to change
which files are processed or how they're transformed at runtime is invaluable.
You can update the configuration and restart the application, and the data
pipeline adapts immediately. This eliminates the need to recompile or redeploy
code just to handle a new data source or adjust a transformation rule.

### Separation of Concerns

Data engineers who understand data schemas and business logic (but may not know
Python) can configure data files. Python developers focus on the parser logic.
The JSON configuration becomes a contract between teams.

## Lazy Evaluation

{py:class}`~r2x_core.DataStore` uses lazy evaluation: data is read and processed
only when requested.

### Why Lazy?

Lazy evaluation provides several practical benefits. First, efficiency: large
projects often configure hundreds of data files but only need a subset in any
given run. Without lazy evaluation, you'd pay the cost of reading all files
upfront, which is wasteful. Second, error localization: if a data file is
broken, you discover it only when you try to read it. This is actually desirable
in some workflows where you want to continue processing even if certain optional
files fail. Third, composition: you can create a DataStore with all possible
data files, then selectively read what you need based on runtime parameters like
solver year, region, or scenario. This pattern enables flexible, parameterized
workflows without configuration duplication.

### Example

```python
from r2x_core import DataStore

# Create store with 50 data file configs
store = DataStore("data_folder")

# Only the files you actually read are loaded
data1 = store.read_data("file1")  # File1 loaded now
data2 = store.read_data("file2")  # File2 loaded now
# Files 3-50 are never touched
```

This is distinct from eager loading, where all files would be read at
initialization time.

## Composable Processing

Data transformations (filtering, column selection, pivoting, etc.) are expressed
declaratively through {py:class}`~r2x_core.TabularProcessing` and
{py:class}`~r2x_core.JSONProcessing` objects. These compose naturally:

### Processing Pipeline Order

1. **File Selection**: Locate the file (absolute path, relative path, or glob
   pattern)
2. **Reading**: Use reader (default or custom) with specified kwargs
3. **Transformations**: Apply processing operations in sequence:
   - Column/key selection
   - Filtering
   - Type coercion
   - Reshaping (pivot, unpivot)
   - Aggregation
   - Sorting and deduplication
   - Value replacement
   - Null handling

Each step builds on previous ones. The design ensures transformations are
readable (looking at a processing spec tells you exactly what happens to the
data), debuggable (if something's wrong, each transformation step can be tested
independently), reusable (a processing spec can be applied to multiple similar
files), and version-controllable (processing pipelines are data, not code, so
they live in config files and track with git history).

### Example

```python
from r2x_core import DataFile, TabularProcessing

processing = TabularProcessing(
    select_columns=["date", "region", "sales"],  # Step 1: select
    filter_by={"region": "North"},                # Step 2: filter
    column_mapping={"sales": "revenue"},          # Step 3: rename
    column_schema={"date": "datetime64"},         # Step 4: type
    sort_by={"date": "ascending"}                 # Step 5: sort
)

data_file = DataFile(
    name="north_sales",
    relative_fpath="all_sales.csv",
    proc_spec=processing
)
```

When you read this file, the exact transformation sequence is clear. You can
debug by disabling each step and observing the effect.

## Configuration Validation

{py:class}`~r2x_core.DataStore` uses Pydantic models for validation. This
catches errors early:

```python
# Bad config: file doesn't exist, glob is invalid, etc.
# Error raised at initialization, not at runtime
store = DataStore("config.json")

# Or: caught when you add a data file
store.add_data(bad_file)  # Raises ValidationError with clear message
```

This "fail fast" approach saves debugging time. Configuration errors surface
immediately with helpful error messages, not mysterious failures deep in data
processing.

## Placeholders and Runtime Parameterization

Lazy evaluation enables another pattern: runtime parameterization through
placeholders:

```python
processing = TabularProcessing(
    filter_by={"year": "{solve_year}"}  # Placeholder
)

# At read time, provide the value
data = store.read_data("file", placeholders={"solve_year": 2024})
```

This allows a single DataStore configuration to work across multiple years,
scenarios, or regions without modification.

## Trade-offs and Design Decisions

### Why Not Automatic Discovery?

You might ask: why not automatically discover CSV files and create DataFile
configs? The answer is intentionality. Automatic discovery is convenient for
one-off scripts but problematic in production:

- Brittle: Adding a file to a folder unexpectedly changes behavior
- Unclear: You can't see at a glance which files are being processed
- Problematic: Temporary or debug files might get accidentally included

By requiring explicit configuration, you get clarity and control at the cost of
slightly more setup.

### Why Separate Reader Config from File Path?

{py:class}`~r2x_core.ReaderConfig` lets you specify how to read a file
independently of where it is. This enables:

- Using different reader functions for similar files
- Passing reader-specific kwargs (CSV delimiter, HDF5 dataset name, etc.)
- Testing readers in isolation

### Why JSON Configuration?

JSON is chosen as the configuration format because:

- Human-readable
- Language-independent (non-Python tools can generate configs)
- Native git-friendly (diffs are clear)
- Supported by Pydantic for validation

Python APIs are also provided for programmatic creation.

## See Also

- {doc}`../how-tos/manage-datastores` - How-to guide for DataStore
- {doc}`../how-tos/configure-data-files` - How-to guide for DataFile and
  transformations
- {py:class}`~r2x_core.DataStore` - API reference
- {py:class}`~r2x_core.DataFile` - API reference
- {py:class}`~r2x_core.DataReader` - API reference
