---
title: Verify installation and first use
---

After [installing the published package](/r2x-core/install/), check the version and construct an empty system:

```bash
python -c "import r2x_core; from r2x_core import System; system = System(); print(r2x_core.__version__); print(type(system).__name__)"
```

Expect the installed version followed by `System`.
In a uv project, prefix the same command with `uv run`.
An import failure usually means the command is using a different environment. See [Troubleshooting](/r2x-core/troubleshooting/).

Next, [build and verify a CSV capacity scenario](/r2x-core/tutorials/getting-started/).
That worked example ships its own data and uses the repository's locked runtime to keep the fixture and implementation aligned.
It verifies a 165 MW system and reloads the exported artifact in a fresh process.
For method contracts and source links, use the [API reference](/r2x-core/references/api/).

## Choose the plugin contract you need

`r2x-core` provides infrastructure and registers no runnable CLI plugins of its own.
Model packages provide input parsers, modifiers, and exporters. [r2x-cli](https://github.com/NatLabRockies/r2x-cli/blob/main/docs/plugin-management.md) installs and discovers them.
The contracts you implement depend on the work:

| Work | Public contract | Next step |
| --- | --- | --- |
| Read native data into a system | `Plugin.on_build()` returns `Result[System, str]` | [Build a parser](/r2x-core/how-tos/build-parsers/) |
| Modify a system | `on_transform()` or an exposed `System, config` callable | [Create a function plugin](/r2x-core/how-tos/create-function-plugins/) |
| Translate component schemas | `on_translate()` and rule mappings | [Apply rules](/r2x-core/how-tos/apply-rules/) |
| Write output for a model | `on_export()` | [Build an exporter](/r2x-core/how-tos/build-exporters/) |

A model package may call a modifier a sysmod. That is not a built in electrical operation in this library.
Use the package's registered reference and configuration instead of guessing a class or CLI command.
For native model inputs, start with [r2x-reeds](https://natlabrockies.github.io/r2x-reeds/) or the model package linked from the [R2X architecture guide](https://natlabrockies.github.io/R2X/explanation/architecture/).
