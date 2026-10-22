<img src="./docs/src/assets/r2x-logo-full-square.svg" alt="R2X framework logo" align="left" width="220px" height="220px" hspace="10"/>
<img align="left" alt="" width="0" height="220px" hspace="10"/>

#### r2x-core
<p><small>Shared Python infrastructure for power-system model translators.</small></p>

[![CI](https://github.com/NatLabRockies/r2x-core/actions/workflows/ci.yaml/badge.svg)](https://github.com/NatLabRockies/r2x-core/actions/workflows/ci.yaml) [![PyPI](https://img.shields.io/pypi/v/r2x-core.svg)](https://pypi.org/project/r2x-core/) [![Last commit](https://img.shields.io/github/last-commit/NatLabRockies/r2x-core?style=flat-square)](https://github.com/NatLabRockies/r2x-core/commits/main) [![Docs](https://img.shields.io/badge/docs-guides-0079c2?style=flat-square)](https://natlabrockies.github.io/r2x-core/)
<br/>
[![Python 3.11–3.14](https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776ab?logo=python&logoColor=white)](https://natlabrockies.github.io/r2x-core/install/) [![Managed with uv](https://img.shields.io/badge/managed%20with-uv-6f42c1)](https://docs.astral.sh/uv/) [![BSD 3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](./LICENSE.txt)

<br clear="left">

`r2x-core` provides typed plugin configuration, lifecycle hooks, file readers,
rule mappings, and unit-aware systems for model translators.
Model packages implement parsers and exporters;
[r2x-cli](https://github.com/NatLabRockies/r2x-cli) installs and runs them in its own managed Python environment.
`r2x-core` is a library; it does not install the `r2x` executable.

## Quick Start

### Install

Use Python 3.11 through 3.14. In an activated virtual environment:

```bash
python -m pip install r2x-core
```

Polars is installed as a runtime dependency for the built-in tabular reader and
processor. It is imported lazily, so configuration-only imports do not load it.
Applications can supply custom `FileReader` and `TabularProcessor` implementations.
See [Installation](https://natlabrockies.github.io/r2x-core/install/) for environment and upgrade instructions.

Verify the installation and create a system:

```bash
python -c "from r2x_core import System; print(System(name='example').name)"
```

Expect `example`. Continue with the CSV capacity tutorial to build, transform,
export, and independently reload a system.

## Documentation

Use the guide that matches your task:

- [Getting started](https://natlabrockies.github.io/r2x-core/install/): install the library and prepare your environment.
- [Tutorials](https://natlabrockies.github.io/r2x-core/tutorials/): learn through runnable examples.
- [How-to guides](https://natlabrockies.github.io/r2x-core/how-tos/): configure files, plugins, units, and rules.
- [API reference](https://natlabrockies.github.io/r2x-core/references/api/): public contracts, signatures, and implementation links.
- [Explanation](https://natlabrockies.github.io/r2x-core/explanations/): architecture and data flow.
- [Troubleshooting](https://natlabrockies.github.io/r2x-core/troubleshooting/): diagnose input, lifecycle, unit, and serialization failures.
- [Changelog](CHANGELOG.md): release history.

See the [documentation site](https://natlabrockies.github.io/r2x-core/) for the complete guide map.

## Development

Install `uv`, a supported Python version, Node.js 22.22 or newer for the docs, and `mise`.
From a source checkout:

```bash
mise run setup
mise run hooks
mise run test
```

Build the searchable documentation site:

```bash
npm ci --prefix docs
mise run docs
```

See [Contributing](CONTRIBUTING.md) for setup and checks, and the [r2x-core agent skill](skills/r2x-core/SKILL.md) for additional development workflows.

## License

BSD-3-Clause.
See [LICENSE.txt](./LICENSE.txt) for the full license text.
