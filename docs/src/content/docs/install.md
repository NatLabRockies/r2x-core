---
title: "Installation"
---

`r2x-core` is a Python library, not a standalone executable.
Current package metadata supports Python 3.11 through 3.14 (`>=3.11,<3.15`).
Check the [PyPI package page](https://pypi.org/project/r2x-core/) when choosing a released version.

## Add to a project

In an existing uv project:

```bash
uv add r2x-core
uv run python -c "import r2x_core; print(r2x_core.__version__)"
```

The verification prints the installed version.
If you do not yet have a project, run `uv init --bare` in an empty directory first.

For an existing virtual environment managed with pip:

```bash
python -m pip install r2x-core
python -c "import r2x_core; print(r2x_core.__version__)"
```

## Upgrade

For a uv project, update its lockfile and environment:

```bash
uv lock --upgrade-package r2x-core
uv sync
uv run python -c "import r2x_core; print(r2x_core.__version__)"
```

For a pip environment, use `python -m pip install --upgrade r2x-core` and repeat the import check in that same environment.

## Orchestrate installed plugins

Install [r2x-cli](https://github.com/NatLabRockies/r2x-cli#quick-start) separately to run translator packages.
`r2x-core` itself has no plugin entry point to run.
The CLI manages its own Python environment; adding a package to a uv project does not install it there.
See [getting started](/r2x-core/tutorials/getting-started/) for direct library usage.
