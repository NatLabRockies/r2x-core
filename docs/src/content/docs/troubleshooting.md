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
