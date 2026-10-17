<img src="./docs/src/assets/r2x-logo-full-square.svg" alt="R2X framework logo" align="left" width="220px" height="220px" hspace="10"/>
<img align="left" alt="" width="0" height="220px" hspace="10"/>

#### r2x-core
<p><small>Shared Python infrastructure for power-system model translators.</small></p>

[![CI](https://github.com/NatLabRockies/r2x-core/actions/workflows/ci.yaml/badge.svg)](https://github.com/NatLabRockies/r2x-core/actions/workflows/ci.yaml) [![PyPI](https://img.shields.io/pypi/v/r2x-core.svg)](https://pypi.org/project/r2x-core/) [![Last commit](https://img.shields.io/github/last-commit/NatLabRockies/r2x-core?style=flat-square)](https://github.com/NatLabRockies/r2x-core/commits/main) [![Docs](https://img.shields.io/badge/docs-guides-0079c2?style=flat-square)](https://natlabrockies.github.io/r2x-core/)
<br/>
[![Python 3.11–3.14](https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776ab?logo=python&logoColor=white)](docs/src/content/docs/install.md) [![Managed with uv](https://img.shields.io/badge/managed%20with-uv-6f42c1)](https://docs.astral.sh/uv/) [![BSD 3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](./LICENSE.txt)

<br clear="left">

`r2x-core` provides typed plugin configuration, lifecycle hooks, file readers,
rule mappings, and unit-aware systems for model translators.
Model packages implement parsers and exporters;
[r2x-cli](https://github.com/NatLabRockies/r2x-cli) installs and runs them in its own managed Python environment.
Core is a library; it does not install the `r2x` executable.

## Quick Start

### Install

Use Python 3.11 through 3.14. In an existing uv project:

```bash
uv add r2x-core
```

For a new project, run `uv init --bare` in an empty directory first.
See [Installation](docs/src/content/docs/install.md) for pip and upgrade instructions.

Verify the installation and create a system:

```bash
uv run python -c "from r2x_core import System; print(System(name='example').name)"
```

Expect `example`. Continue with the [CSV capacity tutorial](docs/src/content/docs/tutorials/getting-started.md) to build, transform, export, and independently reload a system.

## Documentation

Use the guide that matches your task:

- [Getting started](docs/src/content/docs/install.md): install the library and prepare your environment.
- [Tutorials](docs/src/content/docs/tutorials/index.md): learn through runnable examples.
- [How-to guides](docs/src/content/docs/how-tos/index.md): configure files, plugins, units, and rules.
- [API reference](https://natlabrockies.github.io/r2x-core/references/api/): public contracts, signatures, and implementation links.
- [Explanation](docs/src/content/docs/explanations/index.md): architecture and data flow.
- [Troubleshooting](docs/src/content/docs/troubleshooting.md): diagnose input, lifecycle, unit, and serialization failures.
- [Changelog](CHANGELOG.md): release history.

See the [documentation site](https://natlabrockies.github.io/r2x-core/) for the complete guide map.

## Development

Install `uv`, a supported Python version, Node.js 22.12 or newer for the docs, and `just`.
From a source checkout:

```bash
just setup
just hooks
just test
```

Build the searchable documentation site:

```bash
npm ci --prefix docs
just docs
```

See [Contributing](CONTRIBUTING.md) for setup and checks, and the [r2x-core agent skill](skills/r2x-core/SKILL.md) for additional development workflows.

## License

BSD-3-Clause.
See [LICENSE.txt](./LICENSE.txt) for the full license text.
