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
  <a href="#skill-installation">Skills</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#r2x-cli">r2x CLI</a> ·
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

## Skill installation

This repository includes the `r2x-core` agent skill at
`skills/r2x-core/`. Install it for Pi with either supported skill manager.
Replace `NatLabRockies/r2x-core` with the canonical published repository if
this skill is distributed from another fork.

### Skills CLI (`npx skills`)

Install globally:

```console
npx skills add NatLabRockies/r2x-core --skill r2x-core --agent pi --global --yes
```

Install for the current project by omitting `--global`:

```console
npx skills add NatLabRockies/r2x-core --skill r2x-core --agent pi --yes
```

Update one installed copy:

```console
npx skills update r2x-core --global --yes
# For a project-scoped installation, use --project instead of --global.
```

List installed skills with `npx skills list --global` or `npx skills list`.
The updater uses source metadata recorded by the installer; manually copied
skills must be reinstalled before automatic updates can work.

### GitHub CLI (`gh skill`)

Install globally or for the current project:

```console
gh skill install NatLabRockies/r2x-core r2x-core --agent pi --scope user
gh skill install NatLabRockies/r2x-core r2x-core --agent pi --scope project
```

Check for updates, then update one skill or all managed skills:

```console
gh skill update r2x-core --dry-run
gh skill update r2x-core
gh skill update --all
```

Pin a reproducible release when needed:

```console
gh skill install NatLabRockies/r2x-core r2x-core@v0.7.0 \
  --agent pi --scope user
```

Edit the repository copy under `skills/r2x-core/` when contributing changes.
Do not patch an installed copy and expect those changes to flow back here.

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

## r2x CLI

The Rust `r2x` CLI is the recommended orchestration layer for installed
r2x-core plugins. It installs plugin packages, discovers `r2x_plugin` and
`r2x.transforms` entry points, refreshes plugin metadata, and runs direct
plugins or YAML pipelines. The binary is maintained in the
[`r2x-cli`](https://github.com/NatLabRockies/r2x-cli) repository.

Install the latest release on macOS/Linux:

```console
curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/NatLabRockies/r2x-cli/releases/latest/download/r2x-installer.sh | sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://github.com/NatLabRockies/r2x-cli/releases/latest/download/r2x-installer.ps1 | iex"
```

Verify the binary and its command surface:

```console
r2x --version
r2x --help
```

The published binary requires Python shared libraries at runtime. If it
reports missing `libpython`, install a supported shared Python with
`uv python install 3.12`. Use the published release installers or binaries
only; do not build `r2x` from source as part of the r2x-core workflow.

### Install and discover an r2x-core plugin

```console
r2x install r2x-reeds
r2x list
r2x sync
r2x run plugin
```

For a local plugin package under development, run the command from that
plugin's checkout. `r2x-core` itself is a framework package and does not expose
an installable plugin entry point:

```console
cd /path/to/my-translator
r2x install -e .
r2x sync
r2x list
```

Check a plugin's generated public CLI contract before running it:

```console
r2x run plugin r2x-reeds.reeds-parser --show-help
```

### Validate and run a pipeline

Use the CLI's validation stages before executing data translation:

```console
r2x init
r2x run pipeline.yaml --list
r2x run pipeline.yaml --print reeds-to-sienna
r2x run pipeline.yaml reeds-to-sienna --dry-run
r2x run pipeline.yaml reeds-to-sienna --output output/system.json
```

Use `--list` to validate the pipeline name, `--print` to inspect resolved
configuration, and `--dry-run` to verify ordering without translating data. Keep
plugin diagnostics on stderr and translation artifacts on stdout or a durable
`--output` path. Use `set -o pipefail` for streamed plugin pipelines.

The CLI's `-q`, `-v`, and `-vv` flags control CLI verbosity. Use
`--log-python` or `r2x log set log-python true` when Python/Loguru diagnostics
must be shown. See the skill's [r2x CLI reference](skills/r2x-core/references/R2X_CLI.md)
for discovery, direct execution, durable `-o`/`-i` boundaries, pipeline
validation, and failure triage.

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
just setup
just hooks
just test
just docs
```

Common tasks:

| Command        | Purpose                                   |
| -------------- | ----------------------------------------- |
| `just setup`   | Install all dependency groups.            |
| `just format`  | Format Python code with Ruff.             |
| `just lint`    | Run Ruff checks.                          |
| `just type`    | Run `ty` type checks.                     |
| `just test`    | Run pytest.                               |
| `just docs`    | Build Sphinx docs.                        |
| `just verify`  | Run hooks, docstring coverage, and tests. |

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
