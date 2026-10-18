---
title: Diagnose input, lifecycle, and serialization failures
---

Start with the first failing boundary: import, file lookup, parsing/processing, component validation, lifecycle, or reload.
Keep the complete exception and traceback. A file from an earlier run is not evidence that the latest run succeeded.
The checks below use the [CSV example](/r2x-core/tutorials/getting-started/) where a concrete input is needed.

## ImportError, ModuleNotFoundError, or a missing public method

Run this with the same environment and working directory as the failing script:

```bash
uv run python -c "import sys, r2x_core; print(sys.executable); print(r2x_core.__version__); print(r2x_core.__file__)"
```

A failed import means that interpreter cannot load the package. A surprising file path can reveal a different checkout or a local `r2x_core.py` shadowing the installed library.
Compare the version with the [installed release's source tags](https://github.com/NatLabRockies/r2x-core/tags), rather than assuming these `main` docs describe an older release.
Install the dependency in the intended project using [Installation](/r2x-core/install/); rename a shadowing local module if that is the cause.
Repeat the command and [first-use check](/r2x-core/getting-started/verify/) before retrying the application.

For `ModuleNotFoundError: tutorial_model` during reload, run the example from `docs/examples/csv-system`, where that module lives.
For another model, install its component-defining package in the loading environment. Installing core alone cannot supply those classes.

## “Path does not exist” or a data name is absent from the store

`DataStore` requires an existing root; registering a `DataFile` does not prove its input exists.
Run this from the CSV fixture directory:

```bash
uv run --no-dev python -c "from pathlib import Path; print(Path.cwd()); p=Path('inputs/generators.csv'); print(p.resolve()); print(p.is_file())"
```

The final line must be `True`. If false, correct the working directory or provide the actual input root. Do not create an empty replacement input just to satisfy lookup.
For your actual store, compare `store.folder` and `store.list_data()` with the expected root and logical names.
This self-contained check shows an existing but empty root:

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from r2x_core import DataStore
>>> with TemporaryDirectory() as directory:
...     store = DataStore(directory)
...     root_matches = store.folder == Path(directory).resolve()
...     names = store.list_data()
...
>>> # Expected: the empty example store resolves its root but has no registered inputs.
>>> root_matches, names
(True, [])
```

A name missing from `list_data()` explains a `KeyError` from `read_data(name)`; register its actual `DataFile` before reading it.
If the name is present but the physical file is absent, correct its `relative_fpath` under the root or use an explicit `fpath`.
Then call `store.read_data(name)` again and inspect its result, not just the registered names.
See [file configuration](/r2x-core/how-tos/configure-data-files/) and [DataStore contracts](/r2x-core/references/api/#data-management).

## A CSV parses incorrectly, a column is missing, or the result is still lazy

First inspect the raw header and rows independently of processing:

```bash
uv run --no-dev python -c "import polars as pl; f=pl.read_csv('inputs/generators.csv'); print(f.schema); print(f.head())"
```

For the shipped input, expect `name`, `capacity_mw`, and `status`, including Alpha 100, Bravo 50 and Retired 25.
A different header, delimiter, skipped row, or string-valued numeric column needs a matching reader configuration or a corrected source export.
Reader options go in `ReaderConfig(kwargs=...)`; transformation rules belong in `proc_spec`.
Compare the raw columns with the requested mappings and filters before adding more processing.

CSV reads in this workflow return a Polars lazy frame. Materialize it with `collect()` before inspecting rows or constructing components.
After fixing the reader/specification, rerun the [CSV tutorial](/r2x-core/tutorials/getting-started/): two active generators and 165 MW after scaling prove that filtering and transformation both ran.
See [processing specifications](/r2x-core/references/processors/).
Some reshaping requests remain tracked in [issue #132](https://github.com/NatLabRockies/r2x-core/issues/132); check the current source and issue status before assuming a requested processing feature is implemented.

## A component rejects capacity or unit input

A `capacity_mw` validation error on a negative active CSV row is expected in the tutorial.
Inspect the row, correct the source value, and rerun both scripts:

```bash
uv run --no-dev python build_system.py
uv run --no-dev python inspect_system.py
```

Both must exit successfully; the reloaded total must be 165 MW. Construction failure produces no new export, but an older artifact can remain.
Do not disable model validation to make bad data load.

For unit-aware fields, inspect the declared `Unit(...)` annotation and the supplied value together.
A structured unit value must contain both keys:

```json
{"value": 80.0, "unit": "MW"}
```

A plain float for a per-unit field is already per-unit; `80.0` does not mean 80 MW.
An explicit natural-unit value needs the field's declared base, such as `base_power`, and compatible unit annotations.
“Base field … is required for unit conversion” means that base was absent or `None`; supply the physical base required by the model, not an arbitrary constant.
Verify the normalized value: the [tested generator example](/r2x-core/how-tos/convert-units/) converts 80 MW on a 100 MVA base to 0.8 per-unit.
For incompatible dimensions, correct the input unit or model annotation and repeat construction before running the pipeline.
See [unit contracts](/r2x-core/references/units/).

## PluginError identifies a failed lifecycle hook

Inspect the hook name and wrapped error in the traceback. Compare the resolved context configuration and input names with the hook's requirements; inspect `ctx.config` and `ctx.system` at that boundary when debugging your own plugin.
A returned `Err(...)` becomes `PluginError`; unrelated exceptions can propagate directly.
Fix the specific input or configuration, then rerun from a fresh context and verify its returned system or exported artifact.

Earlier hooks may already have mutated state or written files. There is no automatic rollback, and cleanup is not guaranteed after failure.
Do not rerun against partially transformed state unless the plugin explicitly supports that.
See [lifecycle ordering and public API](/r2x-core/references/plugins/) and the [working example](/r2x-core/tutorials/getting-started/).
For CLI discovery errors, use [CLI troubleshooting](https://natlabrockies.github.io/r2x-cli/troubleshooting/); core does not manage the CLI's environment.

## JSON reload fails, storage is missing, or output already exists

Check the artifact and companion directory from the fixture directory:

```bash
uv run --no-dev python -c "from pathlib import Path; print(Path('output/system.json').is_file()); print(Path('output/system_time_series').is_dir())"
```

Both should be `True` for the tutorial's file export. A missing sidecar requires restoring or regenerating the complete export; copying JSON alone is insufficient.
Keep the model package importable, then run `inspect_system.py` in a fresh process to verify names and capacities.
Native PLEXOS or Sienna files need their model parser; `System.from_json` expects an infrasys-compatible system artifact.

The bytes-loading path can raise “Data is missing time series information” or “Data is missing time series directory” when given an arbitrary JSON object.
Use a supported `System.to_json(...)` export instead of hand-editing serialization metadata.
Check actual method signatures and source in [serialization contracts](/r2x-core/references/data-workflow/#system-serialization).
For an existing-output rejection, choose a new destination; use `overwrite=True` only when deliberately replacing that artifact.
Verify the new destination by loading it independently, rather than trusting an old file's timestamp or mere existence.

The diagnostic boundaries are implemented in [DataStore](https://github.com/NatLabRockies/r2x-core/blob/7eb201999706103b4ea965aeb4b6e42d4801703f/src/r2x_core/store.py), [unit conversion](https://github.com/NatLabRockies/r2x-core/blob/7eb201999706103b4ea965aeb4b6e42d4801703f/src/r2x_core/units/_utils.py), and [lifecycle execution](https://github.com/NatLabRockies/r2x-core/blob/7eb201999706103b4ea965aeb4b6e42d4801703f/src/r2x_core/plugin_base.py#L294-L379).

## Report a reproducible bug

Include the interpreter/version/path check above, operating system, exact command and working directory, full traceback, and the smallest input/configuration that reproduces the failure.
State the expected result, observed result, and whether failure occurs before or after export.
For units, include annotations, units and bases; for processing, raw headers and `ReaderConfig`/`proc_spec`; for reload, component package versions and whether companion storage is present.
Remove credentials and proprietary data while retaining the failing shape and types.
If reproduction needs unavailable licensed/model data, say so and provide a synthetic reduced case when possible.
[Open a core issue](https://github.com/NatLabRockies/r2x-core/issues) with the diagnostic results and the first failing boundary.
