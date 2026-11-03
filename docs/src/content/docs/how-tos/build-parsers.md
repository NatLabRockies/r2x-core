---
title: "Build a Parser"
---

Applications should not implement loops that read rows, construct components,
resolve references, or attach output. Define the application models and input
reader registrations, then describe construction and attachment in
`parser_rules.json`. `build_system` runs the configured component, time series,
and supplemental attribute instructions in declaration order.

If an application has already decoded and processed its sources, call
`build_system_from_sources(sources, config=..., instructions=..., name=...)`
with `DecodedSources` and validated typed instructions. It uses the same output
engine without reading configuration or input files. Missing sources, fields,
references, invalid models, or time axes raise their validation errors. Outputs
attached before a later failure are not rolled back.

```python doctest
>>> from r2x_core import PluginConfig, build_system_from_sources
>>> prepared = build_system_from_sources(
...     {},
...     config=PluginConfig(),
...     instructions=[],
...     name="prepared",
... )
>>> prepared.name
# 'prepared'
```

## Parser basics

This example creates a temporary model module so the resolver can import it as
it would a model in an installed application. The application supplies the model
and two JSON configuration files. Core resolves
the CSV input, validates component instances, and adds them to the `System`.

### Build validated components from configuration

```python doctest
>>> import json
>>> import sys
>>> import tempfile
>>> import types
>>> from pathlib import Path
>>> from infrasys import Component
>>> from pydantic import Field
>>> from r2x_core import PluginConfig, build_system
>>> module = types.ModuleType("parser_example_models")
>>> class Generator(Component):
...     capacity_mw: float = Field(ge=0)
...
>>> module.Generator = Generator
>>> sys.modules[module.__name__] = module
>>> with tempfile.TemporaryDirectory() as directory:
...     root = Path(directory)
...     config_dir = root / "config"
...     config_dir.mkdir()
...     _ = (root / "generators.csv").write_text(
...         "name,capacity_mw\nAlpha,100\n", encoding="utf-8"
...     )
...     _ = (config_dir / "file_mapping.json").write_text(
...         json.dumps([{"name": "generators", "relative_fpath": "generators.csv"}]),
...         encoding="utf-8",
...     )
...     _ = (config_dir / "parser_rules.json").write_text(
...         json.dumps([{"kind": "component", "source": "generators", "component_type": "Generator"}]),
...         encoding="utf-8",
...     )
...     config = PluginConfig(
...         models=(module.__name__,),
...         config_path_override=config_dir,
...     )
...     system = build_system(config, name="parsed", input_folder=root)
...     generators = tuple(system.get_components(Generator))
...     len(generators), generators[0].name, generators[0].capacity_mw
# (1, 'Alpha', 100.0)
```

When target field names match source column names, explicit mappings can be
omitted. Use `fields` to map differing names and `references` to resolve a
previously constructed component by type and name. A missing or ambiguous
reference fails explicitly. Component names are unique within a component type.
The same name may be used by a different type.

### Resolve a list of components

Use `resolve_as: "list"` when a component field contains a list of existing
components. The source field must contain a list of nonempty names. The parser
resolves each name by `component_type` and passes the existing objects to the
model. Omit `resolve_as`, or set it to `"component"`, for one name and one
component. A scalar and a list are not converted into each other.

For example, suppose an earlier table named `membership` has one `group` and
`bus_name` per row. A record in `table_mapping.json` collects each group's
names without listing them in the configuration:

```json
{
  "name": "group_rows",
  "source": "membership",
  "operations": [
    {
      "operation": "group_by",
      "columns": ["group"],
      "aggregate": [{"operation": "list", "column": "bus_name", "output": "bus_names"}]
    }
  ],
  "columns": {"name": "group", "bus_names": "bus_names"}
}
```

Given application models `Bus` and `BusGroup`, where `BusGroup.buses` is a
`list[Bus]`, the relevant `parser_rules.json` instructions are:

```json
[
  {"kind": "component", "source": "bus_rows", "component_type": "Bus"},
  {
    "kind": "component",
    "source": "group_rows",
    "component_type": "BusGroup",
    "references": {
      "buses": {
        "component_type": "Bus",
        "name_field": "bus_names",
        "resolve_as": "list"
      }
    }
  }
]
```

Supply `table_mapping_path` to `build_system` to run the table mapping. The
referenced components must be constructed by earlier instructions. The parser
preserves list order and repeated names. Empty lists reach the target model for
validation. A null list, non-string or empty name, missing field, and missing or
ambiguous component raise an error. Table `group_by` retains null inputs, so
clean or reject them before resolving references.

Target-model validation must preserve each resolved object's identity. A list
reference must also remain a list with the same members in the same order. If
validation copies, replaces, removes, or reorders references, or converts the
list to a tuple, the parser raises a `ValueError` before attaching the component.
For example, configuring a referenced model with Pydantic's
`revalidate_instances="always"` can create copies and cause this error.
Validators receive the stored objects, so they must not mutate them. A failure
does not roll back mutations made by validators.

The same behavior is available when sources and instructions are already in
memory:

```python doctest
>>> import sys
>>> import types
>>> import polars as pl
>>> from infrasys import Component
>>> from r2x_core import (
...     ComponentInstruction, ComponentReference, DocumentSource, PluginConfig,
...     TableMappingRecord, TabularSource, assemble_table_records, build_system_from_sources,
... )
>>> from r2x_core.polars_adapter import PolarsTabularBackend
>>> class Bus(Component):
...     pass
...
>>> class BusGroup(Component):
...     buses: list[Bus]
...
>>> models = types.ModuleType("reference_example_models")
>>> models.Bus = Bus
>>> models.BusGroup = BusGroup
>>> sys.modules[models.__name__] = models
>>> backend = PolarsTabularBackend()
>>> members = pl.DataFrame({"group": ["North-South", "North-South"], "bus_name": ["South", "North"]})
>>> mapping = TableMappingRecord.model_validate({
...     "name": "group_rows", "source": "membership",
...     "operations": [{"operation": "group_by", "columns": ["group"], "aggregate": [
...         {"operation": "list", "column": "bus_name", "output": "bus_names"}
...     ]}],
...     "columns": {"name": "group", "bus_names": "bus_names"},
... })
>>> tables = assemble_table_records({"membership": TabularSource(members.lazy(), backend)}, [mapping], backend=backend)
>>> instructions = [
...     ComponentInstruction(kind="component", source="bus_rows", component_type="Bus"),
...     ComponentInstruction(
...         kind="component", source="group_rows", component_type="BusGroup",
...         references={"buses": ComponentReference(component_type="Bus", name_field="bus_names", resolve_as="list")},
...     ),
... ]
>>> sources = {"bus_rows": DocumentSource([{"name": "North"}, {"name": "South"}], None)} | tables
>>> system = build_system_from_sources(sources, config=PluginConfig(models=(models.__name__,)), instructions=instructions, name="example")
>>> group = system.get_component(BusGroup, "North-South")
>>> [bus.name for bus in group.buses]
# ['South', 'North']
>>> group.buses[0] is system.get_component(Bus, "South")
# True
```

For an uncommon physical format, register an application `FileReader` and its
symbolic `reader.format` in `file_mapping.json`. The reader returns named typed
sources. Core still handles configured output and attachment. See
[Custom readers and typed sources](/r2x-core/how-tos/custom-readers-and-backends/)
and the [illustrative RAW example](https://github.com/NatLabRockies/r2x-core/tree/main/examples/psse-raw).
That example uses an invented grammar that looks like CSV, not actual PSS/E RAW syntax.

## Working with systems

`System.from_json` and loading saved systems are serialization operations, not
file readers. Translating one system to another is also separate from reading
input files. Translation keeps rule dependency ordering and time series transfer
and replacement behavior.

### See also

[Configure data files](/r2x-core/how-tos/configure-data-files/),
[Attach time series](/r2x-core/how-tos/attach-timeseries/), and the
[API reference](/r2x-core/references/api/).
