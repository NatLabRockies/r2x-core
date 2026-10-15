---
title: "Using Plugins"
---

Execute plugins in your R2X Core workflows.

## Basic Usage

```python
>>> from r2x_core import PluginContext, Plugin, PluginConfig
>>> from rust_ok import Ok
>>> class MyPluginConfig(PluginConfig):
...     pass
>>> class MyPlugin(Plugin[MyPluginConfig]):
...     def on_build(self):
...         from r2x_core import System
...         return Ok(System(name="test"))
>>> config = MyPluginConfig()
>>> context = PluginContext(config=config)
>>> plugin = MyPlugin.from_context(context)
>>> result = plugin.run()
>>> result.system.name
'test'
```

## Plugin Lifecycle Hooks

Implement any of these hooks in your plugin class:

- `on_validate()` - Validate inputs and configuration
- `on_prepare()` - Load and setup resources
- `on_upgrade()` - Upgrade an existing system
- `on_build()` - Create a new system
- `on_transform()` - Modify an existing system
- `on_translate()` - Convert between model formats
- `on_export()` - Write system to files
- `on_cleanup()` - Clean up resources

## See Also

- [register plugins](/r2x-core/how-tos/register-plugins/) - Creating plugins
- [structure plugin directories](/r2x-core/how-tos/structure-plugin-directories/) - Plugin structure
