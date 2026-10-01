# Plugin Context

The `PluginContext` is the unified interface for passing data to plugins. It uses immutable, copy-on-write semantics to efficiently pass large objects (like `System`) through plugin pipelines.

## Context Fields

```python
from r2x_core import PluginContext, PluginConfig, System, DataStore

class Config(PluginConfig):
    name: str

# Minimal context (just config)
ctx = PluginContext(config=Config(name="test"))
ctx.config.name
'test'

# Context with system (for transform/export)
system = System(name="my_system")
ctx2 = PluginContext(config=Config(name="test"), system=system)
ctx2.system.name
'my_system'

# Context with data store (for build/export)
store = DataStore()
ctx3 = PluginContext(config=Config(name="test"), store=store)
ctx3.store is not None
True
```

### Field Summary

| Field                          | Type                | Required | Purpose                          |
| ------------------------------ | ------------------- | -------- | -------------------------------- |
| `config`                       | `ConfigT`           | Always   | Plugin configuration (typed)     |
| `store`                        | `DataStore \| None` | Optional | File I/O operations              |
| `system`                       | `System \| None`    | Optional | System object (created/modified) |
| `source_system`                | `System \| None`    | Optional | Source for translation           |
| `target_system`                | `System \| None`    | Optional | Output of translation            |
| `rules`                        | `Sequence[Rule]`    | Optional | Transformation rules             |
| `metadata`                     | `dict[str, Any]`    | Optional | Arbitrary metadata               |
| `skip_validation`              | `bool`              | Optional | Skip Pydantic validation         |
| `auto_add_composed_components` | `bool`              | Optional | Auto-add composed components     |

## Direct Attribute Updates

Context fields can be updated directly for memory efficiency. Since `PluginContext` uses `__slots__`, memory overhead is minimal:

```python
from r2x_core import PluginContext, PluginConfig, System

class Config(PluginConfig):
    pass

# Create context
ctx = PluginContext(config=Config())

# Update system directly
system = System(name="new")
ctx.system = system
ctx.system.name
'new'

# Update metadata
ctx.metadata["step"] = 1
ctx.metadata
{'step': 1}
```

This is memory-efficient: the `System` object is not copied, only referenced. The `__slots__` design minimizes context overhead.

## Plugin Pipeline Pattern

Pass context through a plugin pipeline. Context is updated in-place for efficiency:

```python
from r2x_core import Plugin, PluginContext, PluginConfig, System
from rust_ok import Ok

class Config(PluginConfig):
    pass

class BuildPlugin(Plugin[Config]):
    def on_build(self):
        return Ok(System(name="built"))

class TransformPlugin(Plugin[Config]):
    def on_transform(self):
        # Modify system
        return Ok(self.system)

class ExportPlugin(Plugin[Config]):
    def on_export(self):
        return Ok(None)

# Build
ctx = PluginContext(config=Config())
build_plugin = BuildPlugin.from_context(ctx)
ctx = build_plugin.run()
ctx.system.name
'built'

# Transform
transform_plugin = TransformPlugin.from_context(ctx)
ctx = transform_plugin.run()
ctx.system.name
'built'

# Export
export_plugin = ExportPlugin.from_context(ctx)
ctx = export_plugin.run()
ctx.system.name
'built'
```

## Metadata for Custom Data

Use `metadata` dict for plugins to exchange custom data:

```python
from r2x_core import PluginContext, PluginConfig

class Config(PluginConfig):
    pass

ctx = PluginContext(config=Config())

# Add metadata
ctx.metadata["step"] = "build"
ctx.metadata["duration_ms"] = 1234
ctx.metadata["step"]
'build'

# Extend metadata
ctx.metadata["exported"] = True
ctx.metadata
{'step': 'build', 'duration_ms': 1234, 'exported': True}
```

## Parser-Specific Options

Some fields control parser behavior:

```python
from r2x_core import PluginContext, PluginConfig

class Config(PluginConfig):
    pass

# Skip validation for faster parsing
ctx = PluginContext(
    config=Config(),
    skip_validation=True,
    auto_add_composed_components=False
)
ctx.skip_validation
True
ctx.auto_add_composed_components
False

# Update options
ctx.skip_validation = False
ctx.skip_validation
False
```

## Translation Workflows

Translation plugins use `source_system`, `target_system`, and `rules`:

```python
from r2x_core import PluginContext, PluginConfig, System

class Config(PluginConfig):
    pass

source = System(name="plexos")
rules = []  # Translation rules

ctx = PluginContext(
    config=Config(),
    source_system=source,
    rules=tuple(rules)
)
ctx.source_system.name
'plexos'
```

After translation, update target:

```python
from r2x_core import PluginContext, PluginConfig, System

class Config(PluginConfig):
    pass

ctx = PluginContext(
    config=Config(),
    source_system=System(name="plexos")
)

# After translation
target = System(name="sienna")
ctx.target_system = target
ctx.target_system.name
'sienna'
```

## Creating Context from Command-Line Arguments

In your Rust CLI, deserialize arguments and create context:

```python
import json
from pathlib import Path
from r2x_core import PluginContext, PluginConfig, DataStore
import tempfile

class MyConfig(PluginConfig):
    model_year: int

# From Rust CLI args
args = json.loads('{"model_year": 2030}')
config = MyConfig(**args)
# Use temp directory for DataStore
with tempfile.TemporaryDirectory() as tmpdir:
    ctx = PluginContext(
        config=config,
        store=DataStore(path=tmpdir)
    )
    print(ctx.config.model_year)
2030
```

## Stdin Handling Pattern

When Rust CLI pipes a system via stdin, deserialize at the orchestrator level:

```python
from r2x_core import PluginContext, PluginConfig, System

class Config(PluginConfig):
    pass

# In practice, the CLI deserializes a system from stdin
# For this example, we just create one directly
system = System(name="piped_system")
ctx = PluginContext(config=Config(), system=system)
ctx.system.name
'piped_system'
```

The plugin never sees raw stdin - it just sees a populated `ctx.system`.

## Memory Efficiency

`PluginContext` uses `__slots__` to minimize memory overhead. Fields are mutable for efficiency:

```python
from r2x_core import PluginContext, PluginConfig, System

class Config(PluginConfig):
    pass

ctx = PluginContext(config=Config())

# Update fields directly
ctx.metadata["key"] = "value"
ctx.metadata
{'key': 'value'}

# System references are not copied
system = System(name="test")
ctx.system = system
ctx.system.name
'test'
```

The `__slots__` design minimizes memory overhead while allowing efficient updates.

## Performance Considerations

- \***\*slots** design\*\* - Minimal memory overhead per context instance
- **Direct assignment** - O(1) field updates, no copying
- **Shared references** - System objects are passed by reference, not copied
- **Type-checked** - Generic `ConfigT` provides static type safety

For large systems being passed through many plugins, context updates are efficient.

## Best Practices

1. **Update fields directly** - Simple and efficient
2. **Declare type hints for context fields** - Indicates required vs optional
3. **Use metadata for cross-plugin data** - Plugins can exchange custom data
4. **Deserialize stdin at orchestrator level** - Plugins see populated context
5. **Pass context to plugins** - Use `from_context()` or `run(ctx)`
