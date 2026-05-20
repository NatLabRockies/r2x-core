### r2x-core

> Extensible framework for building power system model translators
>
> [![image](https://img.shields.io/pypi/v/r2x-core.svg)](https://pypi.python.org/pypi/r2x-core)
> [![image](https://img.shields.io/pypi/l/r2x-core.svg)](https://pypi.python.org/pypi/r2x-core)
> [![image](https://img.shields.io/pypi/pyversions/r2x-core.svg)](https://pypi.python.org/pypi/r2x-core)
> [![CI](https://github.com/NatLabRockies/r2x-core/actions/workflows/ci.yaml/badge.svg)](https://github.com/NatLabRockies/r2x-core/actions/workflows/ci.yaml)
> [![codecov](https://codecov.io/gh/NatLabRockies/r2x-core/branch/main/graph/badge.svg)](https://codecov.io/gh/NatLabRockies/r2x-core)
> [![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
> [![Documentation](https://github.com/NatLabRockies/r2x-core/actions/workflows/docs.yaml/badge.svg?branch=main)](https://natlabrockies.github.io/r2x-core/)

R2X Core provides the shared infrastructure for translating between power-system
model formats. It gives translator authors a typed plugin lifecycle, a
configuration-driven data loading layer, declarative rule mapping, unit-aware
models, and versioned upgrade helpers.

Use it when you are building or extending translators for models such as ReEDS,
PLEXOS, SWITCH, Sienna, or other infrasys-backed power-system workflows.

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#core-concepts">Core concepts</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="#development">Development</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="#contributing">Contributing</a> ·
  <a href="#license">License</a>
</p>

## Install

```console
pip install r2x-core
```

Or with [uv](https://docs.astral.sh/uv/):

```console
uv add r2x-core
```

R2X Core supports Python 3.11, 3.12, and 3.13.

## Quickstart

### Load model input files

`DataStore` manages named `DataFile` definitions and reads them through the
configured `DataReader` pipeline.

```python
from r2x_core import DataFile, DataStore, TabularProcessing

store = DataStore(path="/path/to/data")
store.add_data([
    DataFile(
        name="generators",
        relative_fpath="gen.csv",
        proc_spec=TabularProcessing(
            column_mapping={"capacity_mw": "p_max_mw"},
            filter_by={"status": "active"},
        ),
    ),
    DataFile(name="loads", relative_fpath="load.parquet"),
])

generators = store.read_data("generators")
available = store.list_data()
```

Use `relative_fpath` for files under the store root, `fpath` for explicit paths,
and `ReaderConfig(kwargs=...)` when the default reader needs format-specific
options such as HDF5 dataset keys.

### Build a class-based translator plugin

Class plugins implement only the lifecycle hooks they need. Hooks return
`Ok(...)` or `Err(...)`; `Plugin.run()` returns the final `PluginContext` and
raises `PluginError` on the first hook failure.

```python
from rust_ok import Ok

from r2x_core import Plugin, PluginConfig, PluginContext, System


class MyModelConfig(PluginConfig):
    input_folder: str
    model_year: int
    scenario: str = "base"


class MyModelTranslator(Plugin[MyModelConfig]):
    def on_build(self):
        system = System(name=f"{self.config.scenario}_{self.config.model_year}")
        return Ok(system)


config = MyModelConfig(input_folder="/path/to/data", model_year=2030)
context = PluginContext(config=config)
plugin = MyModelTranslator.from_context(context)
result = plugin.run()

print(result.system.name)
```

### Create a function transform

For focused `System -> System` transformations, expose a plain function and
register it through the `r2x.transforms` entry-point group.

```python
from rust_ok import Ok, Result

from r2x_core import PluginConfig, System, expose_plugin


class ScaleConfig(PluginConfig):
    scale: float = 1.0


@expose_plugin
def scale_system(system: System, config: ScaleConfig) -> Result[System, str]:
    return Ok(system)
```

```toml
[project.entry-points."r2x.transforms"]
scale_system = "my_package.transforms:scale_system"
```

## Core concepts

| Concept                    | What it does                                                          |
| -------------------------- | --------------------------------------------------------------------- |
| `Plugin` / `PluginContext` | Coordinates translator lifecycle hooks and shared pipeline state.     |
| `PluginConfig`             | Provides typed Pydantic configuration for translators and transforms. |
| `DataFile` / `DataStore`   | Declares, reads, and processes model input files.                     |
| `Rule` / `RuleFilter`      | Maps source components to target components with declarative filters. |
| `HasUnits` / `Unit`        | Adds unit-aware field validation and display formatting.              |
| `UpgradeStep`              | Applies versioned data or schema upgrade steps.                       |

R2X Core builds on [infrasys](https://github.com/NatLabRockies/infrasys) for
`System` and `Component` primitives.

## Documentation

Full documentation is available at
[natlabrockies.github.io/r2x-core](https://natlabrockies.github.io/r2x-core/),
including tutorials, how-to guides, and the API reference.

## Development

This repository uses [uv](https://docs.astral.sh/uv/) and `just` for local
automation.

```console
just sync
just hooks
just test
just docs
```

Common tasks:

| Command       | Purpose                                   |
| ------------- | ----------------------------------------- |
| `just sync`   | Install all dependency groups.            |
| `just format` | Format Python code with Ruff.             |
| `just lint`   | Run Ruff checks.                          |
| `just type`   | Run `ty` type checks.                     |
| `just test`   | Run pytest.                               |
| `just docs`   | Build Sphinx docs.                        |
| `just verify` | Run hooks, docstring coverage, and tests. |

## Roadmap

- [Active issues](https://github.com/NatLabRockies/r2x-core/issues?q=is%3Aopen+is%3Aissue+label%3A%22Working+on+it+%F0%9F%92%AA%22+sort%3Aupdated-asc)
- [Prioritized backlog](https://github.com/NatLabRockies/r2x-core/issues?q=is%3Aopen+is%3Aissue+label%3ABacklog)
- [Nice-to-have](https://github.com/NatLabRockies/r2x-core/labels/Optional)
- [Ideas](https://github.com/NatLabRockies/r2x-core/issues?q=is%3Aopen+is%3Aissue+label%3AIdea)

## Contributing

We welcome contributions. See the
[contributing guide](https://natlabrockies.github.io/r2x-core/contributing/) for
local setup, development workflow, and review expectations.

## License

R2X Core is released under the BSD 3-Clause License. See
[LICENSE.txt](LICENSE.txt) for details.
