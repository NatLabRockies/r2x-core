# Parser Basics

Parser functionality in R2X Core is implemented through the plugin system. See the following guides for implementing custom parsers:

- {doc}`register-plugins` - How to create and register plugins
- {doc}`run-plugins` - How to use plugins
- {doc}`../explanations/plugin-system` - Plugin system architecture

## Working with Systems

To build power system models, use the `System` class directly:

```python
from r2x_core import System, DataStore, DataFile
from infrasys.components import ACBus, ThermalStandard
from pathlib import Path

# Create a system
system = System(base_power=100.0, name="My Grid")

# Create a data store for reading input files
store = DataStore(
    name="input_data",
    data_files=[
        DataFile(name="buses", fpath=Path("buses.csv")),
        DataFile(name="generators", fpath=Path("generators.csv")),
    ]
)

# Read data and create components
bus_data = store.read_file("buses")
for row in bus_data.collect().iter_rows(named=True):
    bus = ACBus(
        name=row["name"],
        voltage=row["voltage_kv"],
        base_voltage=row["voltage_kv"]
    )
    system.add_component(bus)

# Add generators
gen_data = store.read_file("generators")
for row in gen_data.collect().iter_rows(named=True):
    gen = ThermalStandard(
        name=row["name"],
        bus=row["bus_name"],
        active_power=row["capacity_mw"]
    )
    system.add_component(gen)
```

## See Also

- {doc}`register-plugins` - Plugin registration guide
- {doc}`../references/api` - Complete API reference
