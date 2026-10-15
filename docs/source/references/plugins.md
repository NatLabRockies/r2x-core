# Plugin lifecycle

`Plugin[ConfigT]` binds a typed `PluginConfig` to a `PluginContext`.
See [api](/r2x-core/references/api/) for generated signatures, attributes, defaults, and return types.
The implementation at [this documentation baseline](https://github.com/NatLabRockies/r2x-core/blob/f107604b73885fe849aafb915f2488d77f44de67/src/r2x_core/plugin_base.py) defines the lifecycle below.

## Construction and execution

`Plugin.from_context(ctx)` accepts a `PluginContext[ConfigT]` and returns a plugin bound to it.
`Plugin.run(*, ctx=None)` optionally replaces that context and returns the final `PluginContext[ConfigT]`.
It calls only hooks implemented by the plugin, in this order:

| Hook | Context field updated by an `Ok` result |
| --- | --- |
| `on_validate` | None |
| `on_prepare` | None |
| `on_upgrade` | `system` |
| `on_build` | `system` |
| `on_transform` | `system` |
| `on_translate` | `target_system` |
| `on_export` | None |
| `on_cleanup` | None |

Hooks take no explicit context argument; use `self.config`, `self.system`, and the bound context as appropriate.
Return `Ok(value)` for success or `Err(error)` for a hook failure.
The first `Err` raises `PluginError` and stops execution, so cleanup is not a guaranteed failure handler.
Arbitrary exceptions raised inside hooks propagate as well.
See [getting started](/r2x-core/tutorials/getting-started/) for an executable class-plugin example.

## Function transforms

A function transform accepts a `System` and a typed configuration, returning `Result[System, str]`.
The decorator exposes metadata used by discovery tooling:

```python
from rust_ok import Ok, Result
from r2x_core import PluginConfig, System, expose_plugin


class RenameConfig(PluginConfig):
    name: str = "renamed"


@expose_plugin
def rename(system: System, config: RenameConfig) -> Result[System, str]:
    system.name = config.name
    return Ok(system)
```

Register this function in its installable package:

```toml
[project.entry-points."r2x.transforms"]
rename = "my_package.transforms:rename"
```

Replace `my_package.transforms` with the real module containing the function.
The CLI owns installed-package discovery and execution; `r2x-core` owns the lifecycle and metadata contracts.
For configuration resource loading and registration details, see [api](/r2x-core/references/api/) and [create function plugins](/r2x-core/how-tos/create-function-plugins/).
