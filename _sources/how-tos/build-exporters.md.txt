# Exporter Basics

Exporter functionality in R2X Core is implemented through the plugin system. See the following guides for implementing custom exporters:

- {doc}`register-plugins` - How to create and register plugins
- {doc}`run-plugins` - How to use plugins
- {doc}`../explanations/plugin-system` - Plugin system architecture

## Exporting Systems

To export power system models, use the `System` class and data writing utilities:

```python
from r2x_core import System
from infrasys.components import ACBus, ThermalStandard
from pathlib import Path
import polars as pl

# Assume you have a system with components
system = System(base_power=100.0, name="My Grid")

# Extract components and convert to records
buses = list(system.get_components(ACBus))
bus_records = [
    {
        "name": bus.name,
        "voltage_kv": bus.voltage,
        "base_voltage": bus.base_voltage,
    }
    for bus in buses
]

# Write to CSV
output_dir = Path("./output")
output_dir.mkdir(exist_ok=True)

bus_df = pl.DataFrame(bus_records)
bus_df.write_csv(output_dir / "buses.csv")

# Export generators
generators = list(system.get_components(ThermalStandard))
gen_records = [
    {
        "name": gen.name,
        "bus": gen.bus,
        "capacity_mw": gen.active_power,
    }
    for gen in generators
]

gen_df = pl.DataFrame(gen_records)
gen_df.write_csv(output_dir / "generators.csv")

print(f"Exported system to {output_dir}")
```

## See Also

- {doc}`register-plugins` - Plugin registration guide
- {doc}`../references/api` - Complete API reference
