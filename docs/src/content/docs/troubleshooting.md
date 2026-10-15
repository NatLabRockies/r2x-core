---
title: "Troubleshooting"
---

## An import fails or an example uses an unknown API

Check the interpreter and installed version in the same environment as the failing script:

```bash
uv run python -c "import sys, r2x_core; print(sys.executable); print(r2x_core.__version__)"
```

Compare that version with [release history](/r2x-core/release-history/) and the tagged source docs.
Current class plugins use `Plugin.from_context(...)` and lifecycle hooks such as `on_build()`, rather than an `execute(context)` entry method.
See [getting started](/r2x-core/tutorials/getting-started/) for a complete example.

## DataStore cannot find an input

The store root must exist before constructing `DataStore(path)`.
Confirm the root directory and each `DataFile.relative_fpath`.
Use `store.list_data()` to verify that a file definition was registered before calling `store.read_data(name)`.
File registration does not prove the input exists or can be parsed.
For explicit absolute paths use `DataFile.fpath`; reader options belong in `ReaderConfig(kwargs=...)`.
See [configure data files](/r2x-core/how-tos/configure-data-files/).

## A lifecycle hook fails

`Plugin.run()` raises `PluginError` when a hook returns `Err(...)`.
Read the hook name and error in the exception, correct the input or configuration, then rerun from a fresh context.
Earlier hooks can have changed state or written artifacts; the lifecycle is not transactional.
The cleanup hook is not guaranteed to run after a failure.
See [plugins](/r2x-core/references/plugins/) for the execution order.

## The CLI cannot discover a plugin

The library does not install or discover packages on behalf of the CLI.
Use `r2x list` and `r2x sync` in the CLI's managed environment, then inspect `r2x run PLUGIN_REF --help` using a reference returned by `list`.
See [CLI plugin management](https://github.com/NatLabRockies/r2x-cli/blob/main/docs/plugin-management.md).

## The CSV tutorial prints the wrong total or reload fails

Run from `docs/examples/csv-system` and inspect `inputs/generators.csv`.
The active rows are 100 and 50 MW; the retired 25 MW row must be filtered out before component construction.
The default scale is 1.1, so the expected total is 165 MW, not 192.5 MW (all three rows scaled) or 150 MW (no scaling).

```bash
uv run --no-dev python build_system.py
uv run --no-dev python inspect_system.py
```

The first script checks the in-memory component count; the second independently loads the saved artifact and checks names and capacities.
A `capacity_mw` validation error for a negative active row is expected: correct the input instead of disabling model validation.
An export is not produced when construction fails, but an older successful output may still exist.
Use the command's exit status and the fresh-process assertions to distinguish the latest run from a stale artifact.

For `ModuleNotFoundError: tutorial_model`, use the fixture directory so its model module is importable.
For a storage-file error, keep `system.json` and `system_time_series/` together.
See [the complete tutorial](/r2x-core/tutorials/getting-started/) and [artifact boundaries](/r2x-core/explanations/workflow-boundaries/).
