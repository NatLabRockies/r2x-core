---
title: Verify installation and first use
---

After [installing the published package](/r2x-core/install/), check the version and construct an empty system:

```bash
uv run python -c "import r2x_core; from r2x_core import System; system = System(); print(r2x_core.__version__); print(type(system).__name__)"
```

Expect the installed version followed by `System`.
For pip, run the same Python statement with the virtual environment's `python`, without `uv run`.
An import failure usually means the command is using a different environment; see [Troubleshooting](/r2x-core/troubleshooting/).

Next, [build and verify a CSV capacity scenario](/r2x-core/tutorials/getting-started/).
That worked example ships its own data and uses the repository's locked runtime to keep the fixture and implementation aligned.
It verifies a 165 MW system and reloads the exported artifact in a fresh process.
For method contracts and source links, use the [API reference](/r2x-core/references/api/).
