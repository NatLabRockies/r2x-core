# Getting Started with R2X Core

Learn the fundamentals of R2X Core by working with power system data, components, and the plugin system.

## Prerequisites

Install R2X Core:

```console
pip install r2x-core
```

## Working with Systems

Create and manage power system models using the `System` class:

```python
from r2x_core import System
from infrasys.components import ACBus, ThermalStandard

# Create a system with a base power rating
system = System(base_power=100.0, name="My Grid")

# Add components
bus = ACBus(name="Bus 1", voltage=345.0, base_voltage=345.0)
system.add_component(bus)

# Retrieve components
buses = system.get_components(ACBus)
print(f"System has {len(buses)} buses")
```

## Working with Data Files

Use `DataFile` and `DataStore` to manage external data sources:

```python
from r2x_core import DataFile, DataStore, TabularProcessing
from pathlib import Path

# Define a data file with processing rules
data_file = DataFile(
    name="generator_data",
    fpath=Path("data/generators.csv"),
    proc_spec=TabularProcessing(
        column_mapping={"gen_id": "id", "gen_name": "name"}
    )
)

# Create a data store
store = DataStore(data_files=[data_file])

# Read data
df = store.read_file("generator_data")
print(df.collect())
```

## Plugin Configuration

Define type-safe configuration for your plugins using `PluginConfig`:

```python
from r2x_core import PluginConfig
from pydantic import Field
from pathlib import Path

class MyPluginConfig(PluginConfig):
    """Configuration for my plugin."""
    input_folder: Path
    output_folder: Path
    year: int = Field(ge=2020, le=2050)
    scenario: str = "base"

# Use it
config = MyPluginConfig(
    input_folder=Path("./input"),
    output_folder=Path("./output"),
    year=2030
)
```

## Creating a Plugin

Implement a plugin by extending the `Plugin` class:

```python
from r2x_core import Plugin, PluginContext, PluginConfig
from rust_ok import Ok

class MyPlugin(Plugin[MyPluginConfig]):
    """A simple plugin that processes data."""

    def on_prepare(self):
        """Execute the plugin logic."""
        # Access configuration
        config = self.config

        # Access the system if available
        if self.system:
            print(f"System: {self.system.name}")

        # Perform plugin operations
        print(f"Plugin executed with config: {config}")
        return Ok(None)

# Use the plugin
config = MyPluginConfig(
    input_folder=Path("./input"),
    output_folder=Path("./output"),
    year=2030
)
plugin = MyPlugin(config)
context = PluginContext(config=config)
plugin = MyPlugin.from_context(context)
plugin.run()
```

## Working with Rules

Apply transformation rules to power system components:

```python
from r2x_core import Rule, RuleFilter, apply_single_rule
from types import SimpleNamespace

# Define a rule
rule = Rule(
    source_type="Generator",
    target_type="Unit",
    version=1,
    field_map={"name": "name", "capacity": "rating"},
    filter=RuleFilter(field="status", op="eq", values=["active"])
)

# Create sample components
components = [
    SimpleNamespace(name="Gen1", capacity=500, status="active"),
    SimpleNamespace(name="Gen2", capacity=300, status="inactive"),
]

# Apply the rule
result = apply_single_rule(rule, components)
print(f"Converted {result.converted} components")
```

## Version Management

Track and manage data versions using versioning strategies:

```python
from r2x_core import SemanticVersioningStrategy

# Create a versioning strategy
strategy = SemanticVersioningStrategy()

# Compare versions
comparison = strategy.compare("1.0.0", "2.0.0")
if comparison < 0:
    print("Upgrade needed")
```

## Next Steps

- [Working with Units](working-with-units.md) - Learn about unit handling in components
- [How-To Guides](../how-tos/index.md) - Detailed guides for specific tasks
- [API Reference](../references/api.md) - Complete API documentation
