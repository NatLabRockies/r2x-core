---
title: "Create and Register Plugins"
---

A plugin consists of a configuration class and a plugin implementation.

## Configuration

Define a `PluginConfig` subclass:

```python
>>> from r2x_core import PluginConfig
>>> from pathlib import Path
>>> class MyPluginConfig(PluginConfig):
...     input_folder: Path
...     year: int
>>> config = MyPluginConfig(input_folder=Path("/data"), year=2030)
>>> config.year
2030
```

## Plugin Implementation

Extend `Plugin` and implement lifecycle hooks:

```python
>>> from r2x_core import Plugin, PluginConfig, PluginContext
>>> from rust_ok import Ok
>>> class MyPluginConfig(PluginConfig):
...     pass
>>> class MyPlugin(Plugin[MyPluginConfig]):
...     def on_build(self):
...         from r2x_core import System
...         return Ok(System(name="result"))
>>> config = MyPluginConfig()
>>> ctx = PluginContext(config=config)
>>> plugin = MyPlugin.from_context(ctx)
>>> result = plugin.run()
>>> result.system.name
'result'
```

## Entry Point Registration

Register plugins in `pyproject.toml` for automatic discovery:

```toml
[project.entry-points."r2x.parsers"]
my-parser = "my_package.plugins:MyPlugin"
```

The group declares the runtime role; the entry name is the CLI reference.
For function transforms use `r2x.transforms` and an `@expose_plugin` function accepting `System` and typed configuration.
The [CLI worked example](https://github.com/NatLabRockies/r2x-cli/tree/main/docs/examples/first-pipeline) installs and executes both forms.

## See Also

- [structure plugin directories](/r2x-core/how-tos/structure-plugin-directories/) - Directory structure
- [run plugins](/r2x-core/how-tos/run-plugins/) - Using plugins
