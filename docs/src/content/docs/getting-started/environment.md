---
title: Prerequisites and environment
---

Use Python 3.11 through 3.14, as declared by the package (`>=3.11,<3.15`).
Install [uv](https://docs.astral.sh/uv/getting-started/installation/) to manage a project and its isolated environment.
In a new, empty directory:

```bash
uv init --bare
```

Continue with [Installation](/r2x-core/install/) to add the published package.
Run library commands through `uv run` so they use this project's environment.
An existing pip virtual environment is also supported by the installation guide.

`r2x-core` is a library. It does not install the `r2x` executable.
[r2x-cli](https://github.com/NatLabRockies/r2x-cli/blob/main/docs/getting-started.md#install) manages a separate Python environment for translator plugins.
Installing a library in a uv project does not register it with that CLI.

Git is needed only when obtaining repository examples or developing the package.
For source installation and contributor tools, use [Development setup](/r2x-core/contributing/#development-setup).
