---
title: "Read data and build a system"
---

Create a tiny input file, load it through `DataStore`, and pass a typed configuration into a class plugin.
This example needs no external model datasets.

## Install

Create a Python project in an empty directory and install the library:

```bash
uv init --bare
uv add r2x-core
uv run python -c "import r2x_core; print(r2x_core.__version__)"
```

The final command prints the installed package version.
See [install](/r2x-core/install/) for Python compatibility and other installation options.

## Read a CSV

Save the following as `example.py` in that project:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from r2x_core import DataFile, DataStore

with TemporaryDirectory() as folder:
    root = Path(folder)
    (root / "generators.csv").write_text("name,capacity_mw\nGenerator1,100\n")
    store = DataStore(root)
    store.add_data([DataFile(name="generators", relative_fpath="generators.csv")])
    frame = store.read_data("generators")
    assert frame.collect().height == 1
    print(store.list_data())
```

Run it:

```bash
uv run python example.py
# ['generators']
```

The store root must exist.
`relative_fpath` resolves beneath it, while `fpath` names an explicit path.
CSV reads return a Polars lazy frame; `collect()` materializes it.

## Build a system with a plugin

Append this code to `example.py`:

```python
from rust_ok import Ok, Result

from r2x_core import Plugin, PluginConfig, PluginContext, System


class ExampleConfig(PluginConfig):
    name: str = "example"


class ExamplePlugin(Plugin[ExampleConfig]):
    def on_build(self) -> Result[System, str]:
        return Ok(System(name=self.config.name))


context = PluginContext(config=ExampleConfig())
result = ExamplePlugin.from_context(context).run()
assert result.system is not None
assert result.system.name == "example"
print(result.system.name)
```

Run `uv run python example.py` again.
It now prints `example` after the data-file list.
`from_context()` binds the configuration and shared state; `run()` calls implemented lifecycle hooks and returns the final context.
A hook returning `Err(...)` stops the lifecycle with `PluginError`.

## Next steps

- [configure data files](/r2x-core/how-tos/configure-data-files/): declare reader and processing options.
- [plugins](/r2x-core/references/plugins/): inspect hook order and return contracts.
- [api](/r2x-core/references/api/): look up the generated API.
- [troubleshooting](/r2x-core/troubleshooting/): recover from common failures.
