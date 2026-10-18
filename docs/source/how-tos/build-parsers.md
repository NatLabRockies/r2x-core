# Parser Basics

Parser functionality in R2X Core is implemented through the plugin system. See the following guides for implementing custom parsers:

- {doc}`register-plugins` - How to create and register plugins
- {doc}`run-plugins` - How to use plugins
- {doc}`../explanations/plugin-system` - Plugin system architecture

## Working with Systems

To build power system models, use the `System` class directly:

```python
import tempfile
from pathlib import Path

from infrasys import Component

from r2x_core import (
    ComponentTarget,
    DataFile,
    DataStore,
    DatasetSource,
    PluginConfig,
    PluginContext,
    Rule,
    System,
    apply_single_rule,
)


class BusComponent(Component):
    voltage: float
    base_voltage: float


with tempfile.TemporaryDirectory() as temp_dir:
    input_folder = Path(temp_dir)
    buses_path = input_folder / "buses.csv"
    bytes_written = buses_path.write_text("name,voltage_kv\nbus-1,230.0\n")

    system = System(base_power=100.0, name="My Grid")
    store = DataStore(path=input_folder)
    store.add_data([DataFile(name="buses", fpath=buses_path)])

    # Production plugins normally point models to an importable package module.
    context = PluginContext(
        config=PluginConfig(models=("__main__",)),
        system=system,
        target_system=system,
        store=store,
    )
    bus_rule = Rule(
        name="buses",
        source=DatasetSource(dataset="buses"),
        target=ComponentTarget(component_types=("BusComponent",)),
        field_map={
            "name": "name",
            "voltage": "voltage_kv",
            "base_voltage": "voltage_kv",
        },
    )
    buses = apply_single_rule(bus_rule, context=context)
    if buses.is_err():
        raise buses.err()
```

## See Also

- {doc}`register-plugins` - Plugin registration guide
- {doc}`../references/api` - Complete API reference
