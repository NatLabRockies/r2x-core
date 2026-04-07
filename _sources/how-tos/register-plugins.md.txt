# Create and Register Plugins

A plugin consists of a configuration class and a plugin implementation.

## Configuration

Define a `PluginConfig` subclass:

```python doctest
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

```python doctest
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
[project.entry-points.r2x_plugin]
my_plugin = "my_package.plugins:my_plugin_instance"
```

## See Also

- {doc}`structure-plugin-directories` - Directory structure
- {doc}`run-plugins` - Using plugins
