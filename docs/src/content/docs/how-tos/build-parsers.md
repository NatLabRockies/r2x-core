---
title: "Build a Parser"
---

Applications should not implement loops that read rows, construct components,
resolve references, or attach output. Define the application models and input
reader registrations, then describe construction and attachment in
`parser_rules.json`. `build_system` executes the configured component,
time-series, and supplemental-attribute instructions in declaration order.

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
'prepared'
```

## Parser basics

This example creates a temporary application model module so the model resolver
uses the same importable-module contract as an installed application. The
application supplies the model and two JSON configuration files. Core resolves
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
(1, 'Alpha', 100.0)
```

When target field names match source column names, explicit mappings can be
omitted. Use `fields` to map differing names and `references` to resolve a
previously constructed component by type and name. A missing or ambiguous
reference fails explicitly. Component names are unique within a component type;
the same name may be used by a different type.

For an uncommon physical format, register an application `FileReader` and its
symbolic `reader.format` in `file_mapping.json`. The reader returns named typed
sources; core still handles all configured output and attachment work. See
[Custom readers and typed sources](/r2x-core/how-tos/custom-readers-and-backends/)
and the [illustrative RAW example](https://github.com/NatLabRockies/r2x-core/tree/main/docs/examples/psse-raw).
That example uses an invented CSV-like grammar, not actual PSS/E RAW syntax.

## Working with systems

`System.from_json` and serialized-system loading remain serialization APIs, not
input reader modes. System-to-System translation also remains separate from
file-ingestion instructions and retains rule dependency ordering and
TimeSeries transfer/replacement behavior.

### See also

[Configure data files](/r2x-core/how-tos/configure-data-files/),
[Attach time series](/r2x-core/how-tos/attach-timeseries/), and the
[API reference](/r2x-core/references/api/).
