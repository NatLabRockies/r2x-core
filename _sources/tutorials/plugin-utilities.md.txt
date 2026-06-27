# Plugin Developer Utilities

R2X Core provides a collection of utilities to help plugin developers work with
components, validation, and data export. These utilities are now part of the
public API and available for direct import.

## Available Utilities

All utilities are available at the top level of the r2x_core package:

```python
from r2x_core import (
    components_to_records,
    export_components_to_csv,
    getter,
    create_component,
    transfer_time_series_metadata,
)
```

### Component Data Extraction

#### `components_to_records()`

Convert system components to a list of dictionary records with optional
filtering, field selection, and key mapping.

**Signature:**

```python
def components_to_records(
    system: System,
    filter_func: Callable[[Component], bool] | None = None,
    fields: list[str] | None = None,
    key_mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]
```

**Parameters:**

- `system` (System): The R2X system containing components to extract
- `filter_func` (optional): Function that accepts a component and returns bool.
  If provided, only components where `filter_func(component)` returns `True` are
  included
- `fields` (optional): List of field names to include. If None, all fields are
  included
- `key_mapping` (optional): Dictionary mapping field names to new key names in
  the output records

**Returns:**

- `list[dict[str, Any]]`: List of component dictionaries

**Example:**

```python
from r2x_core import components_to_records

# Get all components as dictionaries
records = components_to_records(system)

# Get only specific component types
records = components_to_records(
    system,
    filter_func=lambda c: isinstance(c, Bus)
)

# Get specific fields with renamed keys
records = components_to_records(
    system,
    filter_func=lambda c: isinstance(c, Bus),
    fields=["name", "voltage"],
    key_mapping={"voltage": "voltage_kv"}
)
```

#### `export_components_to_csv()`

Export components from the system to a CSV file with optional filtering and
field selection.

**Signature:**

```python
def export_components_to_csv(
    system: System,
    file_path: Path | str,
    filter_func: Callable[[Component], bool] | None = None,
    fields: list[str] | None = None,
    key_mapping: dict[str, str] | None = None,
    **dict_writer_kwargs: Any,
) -> None
```

**Parameters:**

- `system` (System): The R2X system containing components to export
- `file_path` (Path | str): Output path for the CSV file
- `filter_func` (optional): Function to filter components (same as
  `components_to_records`)
- `fields` (optional): List of field names to include in the CSV
- `key_mapping` (optional): Dictionary mapping field names to CSV column names
- `**dict_writer_kwargs`: Additional arguments passed to `csv.DictWriter` (e.g.,
  `quoting`, `delimiter`)

**Example:**

```python
from r2x_core import export_components_to_csv
from pathlib import Path

# Export all components
export_components_to_csv(system, "all_components.csv")

# Export only generators
export_components_to_csv(
    system,
    "generators.csv",
    filter_func=lambda c: isinstance(c, Generator)
)

# Export buses with field selection and renaming
export_components_to_csv(
    system,
    Path("buses.csv"),
    filter_func=lambda c: isinstance(c, Bus) and c.voltage > 100,
    fields=["name", "voltage", "area"],
    key_mapping={"voltage": "voltage_kv", "area": "area_name"}
)
```

### Component Creation

#### `create_component()`

Create and validate a component instance with optional validation skipping and
support for recovery from validation errors.

**Signature:**

```python
def create_component(
    component_class: type[T],
    skip_none: bool = True,
    skip_validation: bool = False,
    **field_values: Any,
) -> Result[T, PydanticValidationError]
```

**Parameters:**

- `component_class` (type[T]): The component class to instantiate
- `skip_none` (bool, default True): Whether to skip fields with None values when
  creating the component
- `skip_validation` (bool, default False): Skip Pydantic validation when
  creating components (faster but less safe)
- `**field_values`: Field values to pass to the component constructor

**Returns:**

- `Result[T, PydanticValidationError]`: Returns `Ok(component)` if validation
  succeeds, or `Err(error)` if validation fails

**Example:**

```python
from r2x_core import create_component
from infrasys import Generator

# Create a component with validation
result = create_component(Generator, name="Gen1", capacity=100.0)

if result.is_ok():
     print(f"Created generator: {result.value.name}")
else:
     print(f"Validation error: {result.error}")

# Create without validation (faster, but less safe)
result = create_component(
    Generator,
    name="Gen2",
    capacity=50.0,
    skip_validation=True
)
```

### Getter Decorator

#### `getter()`

Decorator for registering getter functions that can be used in rules. Getters
provide a way to extract or compute values from a translation context.

**Signature:**

```python
def getter(
    func: F | None = None,
    *,
    name: str | None = None
) -> F | Callable[[F], F]
```

**Usage Patterns:**

1. **Without parentheses** - Uses function name as the registration key:

```python
@getter
def get_bus_voltage(bus: Bus) -> float:
    return bus.voltage
```

2. **With parentheses** - Function name is the registration key:

```python
@getter()
def get_bus_voltage(bus: Bus) -> float:
    return bus.voltage
```

3. **With custom name** - Uses provided name as the registration key:

```python
@getter(name="voltage_kv")
def get_bus_voltage(bus: Bus) -> float:
    return bus.voltage / 1000
```

**Parameters:**

- `func` (optional): The function to decorate (when used without parentheses)
- `name` (optional keyword-only): Custom name for registering the getter
  (required when using parentheses)

**Raises:**

- `ValueError`: If a getter with the same name is already registered
- `TypeError`: If name is specified without parentheses, or if the first
  argument is not callable

**Example:**

```python
from r2x_core import getter

@getter
def get_generator_efficiency(gen) -> float:
    """Compute generator efficiency."""
    return gen.efficiency if hasattr(gen, 'efficiency') else 0.95

@getter(name="rated_capacity_mw")
def get_capacity(gen) -> float:
    """Get generator capacity in MW."""
    return gen.capacity_mw
```

### Time Series Management

#### `transfer_time_series_metadata()`

Transfer time series metadata from a source system to a target system, handling
component UUID mapping and deduplication.

**Signature:**

```python
def transfer_time_series_metadata(context: PluginContext) -> TimeSeriesTransferResult
```

**Parameters:**

- `context` (PluginContext): The plugin context containing both source and
  target systems

**Returns:**

- `TimeSeriesTransferResult` (dataclass): Statistics about the transfer with
  fields:
  - `transferred: int` - Number of new time series transferred
  - `updated: int` - Number of time series with updated owner mappings
  - `children_remapped: int` - Number of child component associations remapped

**Description:**

This function handles the complex process of transferring time series metadata
between systems:

1. Maps components between source and target systems by UUID
2. Transfers time series associations to the target system
3. Handles deduplication of associations
4. Remaps child component references to their parent components in the target
   system
5. Ensures unique indexes are maintained

**Example:**

```python
from r2x_core import transfer_time_series_metadata

# Transfer time series from source to target system
stats = transfer_time_series_metadata(context)

print(f"Transferred: {stats.transferred}")
print(f"Updated: {stats.updated}")
print(f"Children remapped: {stats.children_remapped}")
```

## Common Patterns

### Batch Processing Components

```python
from r2x_core import components_to_records, create_component

# Extract all generators for processing
gen_records = components_to_records(
    system,
    filter_func=lambda c: isinstance(c, Generator),
    fields=["name", "capacity", "efficiency"]
)

# Process and create new components
for record in gen_records:
    # Transform the data
    record["capacity"] *= 1.1  # Increase by 10%

    # Create new component with validation
    result = create_component(Generator, **record)
    if result.is_ok():
        system.add_component(result.value)
    else:
        print(f"Failed to create component: {result.error}")
```

### Exporting Component Subsets

```python
from r2x_core import export_components_to_csv

# Export high-voltage buses to a separate file
export_components_to_csv(
    system,
    "hvbuses.csv",
    filter_func=lambda c: isinstance(c, Bus) and c.voltage > 230000,
    fields=["name", "voltage", "longitude", "latitude"],
    key_mapping={"voltage": "voltage_v"}
)

# Export generators with their regions
export_components_to_csv(
    system,
    "generators_by_region.csv",
    filter_func=lambda c: isinstance(c, Generator),
    fields=["name", "capacity", "fuel_type", "region"]
)
```

### Error Handling with Component Creation

```python
from dataclasses import dataclass
from r2x_core import create_component

@dataclass(slots=True)
class ComponentBatchResult:
    created: list
    failed: list[dict[str, str]]

def safe_create_components(component_data_list, component_class) -> ComponentBatchResult:
    """Create components with error handling and logging."""
    created = []
    failed = []

    for data in component_data_list:
        result = create_component(component_class, **data)

        if result.is_ok():
            created.append(result.value)
        else:
            failed.append({
                "data": str(data),
                "error": str(result.error)
            })

    return ComponentBatchResult(created=created, failed=failed)
```

## API Compatibility

These utilities follow R2X Core's design principles:

- **Result-based error handling**: Functions that can fail return `Result` types
- **Functional composition**: Filter functions allow flexible component
  selection
- **Type safety**: Strong typing support throughout with generics where
  appropriate
- **Performance**: Utilities are optimized for common plugin development tasks
- **Logging**: Integration with loguru for debugging and diagnostics

## See Also

- {doc}`./plugin-context` - Working with plugin contexts
- {doc}`./plugin-system` - Understanding the plugin architecture
- {doc}`./plugin-discovery` - How plugins are discovered and loaded
