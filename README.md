<img src="./docs/src/assets/r2x-logo-full-square.svg" alt="R2X framework logo" align="left" width="220px" height="220px" hspace="10"/>

### r2x-core

Shared infrastructure for building power-system model translators.

[![PyPI](https://img.shields.io/pypi/v/r2x-core.svg)](https://pypi.org/project/r2x-core/) [![CI](https://github.com/NatLabRockies/r2x-core/actions/workflows/ci.yaml/badge.svg)](https://github.com/NatLabRockies/r2x-core/actions/workflows/ci.yaml) [![Docs](https://img.shields.io/badge/docs-guides-0079c2)](https://natlabrockies.github.io/r2x-core/)

`r2x-core` provides typed plugin configuration, lifecycle hooks, file readers, rule mappings, and unit-aware systems.
Model packages implement parsers and exporters; [r2x-cli](https://github.com/NatLabRockies/r2x-cli) installs and runs them.

<br clear="left">

## Quick Start

In a uv project with Python 3.11 through 3.14:

```bash
uv add r2x-core
uv run python -c "from r2x_core import System; print(System(name='example').name)"
# example
```

Use `uv init --bare` in an empty directory first if you do not have a project.
Follow the [first tutorial](docs/src/content/docs/tutorials/getting-started.md) to read a CSV and build a system through a class plugin.

## Documentation

- [Tutorials](docs/src/content/docs/tutorials/index.md): learn the library through small examples.
- [How-to guides](docs/src/content/docs/how-tos/index.md): configure files, plugins, units, and rules.
- [Reference/API](https://natlabrockies.github.io/r2x-core/references/api/): generated public contracts.
- [Explanation](docs/src/content/docs/explanations/index.md): architecture and data flow.
- [Troubleshooting](docs/src/content/docs/troubleshooting.md): imports, input lookup, and hook failures.
- [Changelog and versions](docs/src/content/docs/release-history.md): release notes and tagged source documentation.
- [Contributors](CONTRIBUTING.md): setup and contribution workflow.

## r2x-cli

Install the CLI separately and follow its [getting-started guide](https://github.com/NatLabRockies/r2x-cli/blob/main/docs/getting-started.md).
The CLI has a managed Python environment separate from this project.
`r2x-core` is a library and does not expose an executable translator plugin.

## Development

```bash
just setup
just hooks
just test
just docs
```

Run `npm ci --prefix docs` once before `just docs`.
`just docs` builds the Astro/Starlight site with generated Python API contracts and Pagefind search.
See [contributing](CONTRIBUTING.md) for the full checks.
The [r2x-core agent skill](skills/r2x-core/SKILL.md) contains additional development workflows.

## License

BSD-3-Clause.
See [LICENSE.txt](LICENSE.txt).
