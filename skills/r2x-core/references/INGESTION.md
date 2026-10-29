# Parser Ingestion Reference

Use this for the configured parser path from input files to an infrasys `System`.
For file configuration and reading, see [DATA_STORE.md](./DATA_STORE.md). For
named-table assembly, see [TABLE_MAPPING.md](./TABLE_MAPPING.md).

## Contents

- [Public entry points](#public-entry-points)
- [Configure a parser](#configure-a-parser)
- [Instruction types](#instruction-types)
- [Use already decoded sources](#use-already-decoded-sources)
- [Failure and upgrade behavior](#failure-and-upgrade-behavior)

## Public entry points

```python
build_system(
    config: PluginConfig,
    /,
    *,
    name: str,
    input_folder: Path | None = None,
    readers: Mapping[str, FileReader] | None = None,
    step_handlers: StepHandlers | None = None,
    table_mapping_path: Path | None = None,
    table_mapping_backend: TableMappingBackend | None = None,
    placeholders: Mapping[str, JSONValue] | None = None,
    system_options: Mapping[str, object] | None = None,
) -> System

build_system_from_sources(
    sources: DecodedSources,
    /,
    *,
    config: PluginConfig,
    instructions: Sequence[ParserInstruction],
    name: str,
    system_options: Mapping[str, object] | None = None,
) -> System
```

Both functions are exported from `r2x_core`. `build_system` reads configured
inputs and parser instructions. `build_system_from_sources` skips configuration
and file I/O, but resolves model classes through `config.models` and validates
all constructed outputs. The signature uses source-level type aliases such as
`StepHandlers`, `JSONValue`, and `ParserInstruction`; they are not all root
exports. Pass mappings and concrete root-exported instruction models without
adding imports for unexported aliases.

## Configure a parser

`build_system` reads `file_mapping.json` and `parser_rules.json` under
`config.config_path`; use `PluginConfig.config_path_override` to point elsewhere.
It resolves files under `input_folder`, or the current working directory when
omitted. File mappings define `DataFile` records. Parser rules are a JSON array
of typed output instructions.

A minimal parser configuration can construct components whose target fields
match input columns:

```json
[
  {
    "kind": "component",
    "source": "generators",
    "component_type": "Generator"
  }
]
```

```python
from pathlib import Path
from r2x_core import PluginConfig, build_system

config = PluginConfig(
    models=("my_translator.models",),
    config_path_override=Path("config"),
)
system = build_system(config, name="parsed", input_folder=Path("/data"))
```

For target fields with different source names, use `fields` as a target-to-source
mapping. Use `references` to resolve a previously constructed component by its
type and a source name field. The builder validates components before attaching
them. Component names must be nonempty and unique within their type.

`build_system` accepts app-specific reader implementations in `readers` and
mapping-step handlers in `step_handlers`. Set `table_mapping_path` to opt into
table assembly between file reading and parser instructions. A supplied
`table_mapping_backend` requires `table_mapping_path`; otherwise the configured
path uses the built-in Polars backend.

## Instruction types

The parser instruction union currently has three `kind` variants. Import the
concrete models from `r2x_core` when constructing instructions in Python.

- `component`: `source`, `component_type`, optional `fields` and `references`.
- `time_series`: `source`, `name`, `values`, `time_axis`, and one or more
  `owners`; optional `units`, literal `metadata`, row-derived
  `metadata_columns`, and `skip_if_empty`.
- `supplemental_attribute`: `source`, `attribute_type`, `fields`, and one or
  more `owners`.

An owner identifies a component type and exactly one of `name`, `names`, or
`name_field`. A regular time axis declares `initial_timestamp` and
`resolution_seconds`. A column time axis identifies a timestamp column and may
provide `resolution_seconds`; input timestamps must be strictly increasing and
regular for `SingleTimeSeries`.

Instructions execute in declaration order. Component references and
supplemental attributes therefore depend on earlier components. Time-series
owners must already exist. A failure raises its validation error; outputs
attached before a later failure are not rolled back.

## Use already decoded sources

Use this when another boundary has already produced `DecodedSources` or when
inputs are prepared in memory:

```python
from r2x_core import ComponentInstruction, PluginConfig, build_system_from_sources

system = build_system_from_sources(
    sources,
    config=PluginConfig(models=("my_translator.models",)),
    instructions=[
        ComponentInstruction(
            kind="component",
            source="generators",
            component_type="Generator",
            fields={"capacity_mw": "capacity"},
        )
    ],
    name="parsed",
)
```

`build_system_from_sources` does not read files or parser configuration. The
same output engine validates component classes, references, time axes, and
supplemental attributes.

## Failure and upgrade behavior

- Missing config assets or invalid parser instructions fail before construction.
- Missing source fields, unresolved model types, duplicate component identities,
  invalid references, and invalid time-series metadata raise errors.
- A configured `PluginConfig.upgrade_handler` is run at most once by
  `build_system` when a configured input is missing, then the input read is
  retried. Malformed present files and table-mapping configuration errors do
  not trigger that retry.
- `System.from_json` is a serialization API, not a parser input mode. Route
  foundational serialized-system schema changes through infrasys migration
  hooks.

## Source modules

- `r2x_core.ingestion`: `build_system`, `build_system_from_sources`, and output
  attachment behavior.
- `r2x_core.models`: `ComponentInstruction`, `ComponentOwner`,
  `ComponentReference`, `TimeSeriesInstruction`, and
  `SupplementalAttributeInstruction`.
- `r2x_core.plugin_config`: configuration-asset paths and model-module list.
- `r2x_core.reader`: file source loading before construction.
