# Plugin System

The r2x plugin system uses a capability-based design where plugins implement only the hooks
they need. The plugin lifecycle runs hooks in a fixed order, skipping any that aren't
implemented. This approach provides remarkable flexibility because plugins do only what they
need—whether that's building systems from scratch, transforming existing systems,
translating between formats, or exporting results.

Required context fields are declared through type hints on properties, making it immediately
clear what each plugin needs to function. The ast-grep tool can automatically extract plugin
config types and their capabilities by analyzing the plugin structure, enabling discovery and
documentation generation. The generic `Plugin[ConfigT]` class provides type-safe access to
configuration, catching configuration errors at runtime through Pydantic validation.

## Creating a Simple Plugin

Plugins inherit from `Plugin[ConfigT]` where `ConfigT` is your configuration class:

```python
from r2x_core import Plugin, PluginContext, PluginConfig, System
from rust_ok import Ok

class MyConfig(PluginConfig):
    name: str
    count: int = 1

class MyPlugin(Plugin[MyConfig]):
    def on_build(self):
        system = System(name=self.config.name)
        return Ok(system)

# Create context and run
ctx = PluginContext(config=MyConfig(name="test"))
plugin = MyPlugin.from_context(ctx)
result_ctx = plugin.run()
result_ctx.system.name
'test'
```

## Plugin Lifecycle

The plugin lifecycle consists of seven optional hooks, called in this fixed order:

```{list-table}
:header-rows: 1

* - Hook
  - Purpose
* - `on_validate()`
  - Validate inputs and configuration
* - `on_prepare()`
  - Load data, setup resources
* - `on_build()`
  - Create a new system from scratch
* - `on_transform()`
  - Modify an existing system in-place
* - `on_translate()`
  - Convert source system to target system
* - `on_export()`
  - Write system to files
* - `on_cleanup()`
  - Cleanup resources
```

```{mermaid}
flowchart TD
    Start([Start]) --> Validate[on_validate]
    Validate --> Prepare[on_prepare]
    Prepare --> Build[on_build]
    Build --> Transform[on_transform]
    Transform --> Translate[on_translate]
    Translate --> Export[on_export]
    Export --> Cleanup[on_cleanup]
```

Each hook returns `Result[None | System, Exception]`. If any hook returns an error, execution stops and a `PluginError` is raised.

### Complete Lifecycle Example

```python
from r2x_core import Plugin, PluginContext, PluginConfig, System
from rust_ok import Ok, Err, Result

class FullConfig(PluginConfig):
    input_name: str
    scale_factor: float = 1.0
    output_dir: str = "/tmp"

class FullPlugin(Plugin[FullConfig]):
    def on_validate(self) -> Result[None, Exception]:
        if self.config.scale_factor <= 0:
            return Err(ValueError("scale_factor must be positive"))
        return Ok(None)
...
    def on_prepare(self) -> Result[None, Exception]:
        # Load data, setup
        return Ok(None)
...
    def on_build(self) -> Result[System, Exception]:
        system = System(name=self.config.input_name)
        return Ok(system)
...
    def on_transform(self) -> Result[System, Exception]:
        # Modify system
        return Ok(self.system)
...
    def on_cleanup(self) -> None:
        pass

ctx = PluginContext(config=FullConfig(input_name="example", scale_factor=2.0))
plugin = FullPlugin.from_context(ctx)
result = plugin.run()
result.system.name
'example'
```

## Required vs Optional Context Fields

Plugins indicate which context fields they need via **property return types**:

- **Non-Optional return type** (e.g., `-> System`) = **required** - raises `PluginError` if missing
- **Optional return type** (e.g., `-> System | None`) = **optional** - returns None if missing

### Example: Parser (Requires config, store)

```python
from r2x_core import Plugin, PluginContext, PluginConfig, System, DataStore
from pathlib import Path
from rust_ok import Ok, Result

class ParserConfig(PluginConfig):
    input_file: str

class SimpleParser(Plugin[ParserConfig]):
    @property
    def store(self) -> DataStore:  # Non-Optional = required
        if self._ctx.store is None:
            raise RuntimeError("DataStore required for parsing")
        return self._ctx.store
...
    def on_build(self) -> Result[System, Exception]:
        system = System(name="parsed_system")
        return Ok(system)

store = DataStore()
ctx = PluginContext(config=ParserConfig(input_file="data.csv"), store=store)
parser = SimpleParser.from_context(ctx)
result = parser.run()
result.system.name
'parsed_system'
```

### Example: Exporter (Requires config, system, store)

```python
from r2x_core import Plugin, PluginContext, PluginConfig, System, DataStore
from rust_ok import Ok, Result

class ExporterConfig(PluginConfig):
    output_dir: str

class SimpleExporter(Plugin[ExporterConfig]):
    @property
    def system(self) -> System:  # Non-Optional = required
        if self._ctx.system is None:
            raise RuntimeError("System required for export")
        return self._ctx.system
...
    def on_export(self) -> Result[None, Exception]:
        # Export system to files
        return Ok(None)

system = System(name="my_system")
store = DataStore()
ctx = PluginContext(config=ExporterConfig(output_dir="/tmp"), system=system, store=store)
exporter = SimpleExporter.from_context(ctx)
result = exporter.run()
result.system.name
'my_system'
```

## Plugin Capabilities (Inferred from Hooks)

Plugin capabilities are automatically inferred from which hooks are implemented. A build
plugin implements `on_build()` to create systems from data. A transform plugin implements
`on_transform()` to modify existing systems in-place. A translate plugin implements
`on_translate()` to convert from a source system format to a target system format. An export
plugin implements `on_export()` to write systems to files in various formats. More complex
workflows combine multiple capabilities—a plugin can both translate and export, or validate
and transform, depending on what the workflow requires.

### Example: Multi-Capability Plugin

```python
from r2x_core import Plugin, PluginContext, PluginConfig, System
from rust_ok import Ok, Result

class TranslateExportConfig(PluginConfig):
    format: str = "json"

class Plexos2SiennaExporter(Plugin[TranslateExportConfig]):
    def on_translate(self) -> Result[System, Exception]:
        # Create target system from source
        target = System(name="sienna_system")
        return Ok(target)
...
    def on_export(self) -> Result[None, Exception]:
        # Also export the result
        return Ok(None)

source = System(name="plexos_system")
ctx = PluginContext(config=TranslateExportConfig(), source_system=source)
plugin = Plexos2SiennaExporter.from_context(ctx)
result = plugin.run()
result.target_system.name
'sienna_system'
```

## Configuration with Type Safety

Plugin config types are extracted via generics, enabling type-safe access to plugin-specific
fields. The ast-grep discovery tool can automatically analyze plugin classes to extract config
schemas. Automatic validation happens through Pydantic, catching configuration errors before
plugins execute.

Config fields can be either required or optional. Fields without defaults are required and
must be provided when instantiating the config. Fields with defaults are optional and will
use their default values if not provided:

```python
from r2x_core import PluginConfig

class FullConfig(PluginConfig):
    model_year: int              # Required - no default
    input_folder: str            # Required - no default
    scenario: str = "base"       # Optional - has default
    verbose: bool = False        # Optional - has default

# Valid: provides all required fields
cfg = FullConfig(model_year=2030, input_folder="/data")
cfg.scenario
'base'

# Invalid: missing required field
try:
    bad_cfg = FullConfig(model_year=2030)
except Exception as e:
    "input_folder" in str(e)
True
```

Pydantic validates all fields during instantiation, so configuration errors are caught
immediately rather than later during plugin execution when they would be harder to debug.

## Plugin Discovery

Plugins are discovered through entry points registered in `pyproject.toml`. The discovery
process reads the config type from the generic parameter (e.g., `class MyPlugin(Plugin[MyConfig])`),
determining what configuration the plugin accepts. It identifies implemented hooks by scanning
for method names like `on_validate`, `on_build`, `on_transform`, `on_translate`, `on_export`,
and `on_cleanup`. Required context fields are inferred from non-Optional property return types—a
property returning `System` requires a system, while `System | None` makes it optional. The
config schema is extracted directly from Pydantic field definitions, enabling full documentation
generation without parsing the plugin code.

Plugins are registered as entry points in external packages:

```toml
[project.entry-points."r2x.plugins"]
my_model_parser = "my_package.plugins:MyModelPlugin"
```

## Passing Context Through Pipelines

Use the `evolve()` method for memory-efficient context updates:

```python
from r2x_core import Plugin, PluginContext, PluginConfig, System
from rust_ok import Ok, Result

class Config(PluginConfig):
    pass

# Build a system
build_ctx = PluginContext(config=Config())
system = System(name="built")

# Pass to next step
transform_ctx = build_ctx.evolve(system=system)
transform_ctx.system.name
'built'

# Continue pipeline
export_ctx = transform_ctx.evolve(metadata={"exported": True})
export_ctx.system.name
'built'
export_ctx.metadata
{'exported': True}
```

## Error Handling

Plugins use `Result[T, E]` for error handling. If any hook returns `Err`, execution stops:

```python
from r2x_core import Plugin, PluginContext, PluginConfig
from rust_ok import Ok, Err, Result

class FailConfig(PluginConfig):
    should_fail: bool = False

class FailPlugin(Plugin[FailConfig]):
    def on_validate(self) -> Result[None, Exception]:
        if self.config.should_fail:
            return Err(ValueError("Validation failed!"))
        return Ok(None)

# Success case
ctx1 = PluginContext(config=FailConfig(should_fail=False))
result1 = FailPlugin.from_context(ctx1).run()
result1 is not None
True

# Failure case
ctx2 = PluginContext(config=FailConfig(should_fail=True))
try:
    FailPlugin.from_context(ctx2).run()
except Exception as e:
    "Validation failed" in str(e)
True
```

## Introspection for Plugin Discovery

Extract plugin metadata programmatically:

```python
from r2x_core import Plugin, PluginConfig
from rust_ok import Ok

class MyConfig(PluginConfig):
    name: str

class MyPlugin(Plugin[MyConfig]):
    def on_validate(self):
        return Ok(None)
...
    def on_build(self):
        return Ok(None)

# Get config type
MyPlugin.get_config_type().__name__
'MyConfig'

# Get implemented hooks
sorted(MyPlugin.get_implemented_hooks())
['on_build', 'on_validate']
```

## Best Practices

When designing plugins, implement only the hooks you actually need. Adding unnecessary hooks
creates complexity and makes testing harder. Use type hints on context properties to clearly
indicate what each plugin requires—this makes dependencies explicit and enables the discovery
system to work properly.

Validate configuration and inputs early in the `on_validate()` hook before any expensive
operations. This catches errors immediately rather than failing partway through a long
computation. Use the `on_cleanup()` hook to properly release resources like database
connections, file handles, or temporary files, ensuring clean shutdown even if errors occur.

When chaining plugins together in pipelines, use the `evolve()` method to efficiently pass
context forward. This is more memory-efficient than creating new contexts from scratch.
Return specific exception types rather than generic `Exception` so callers can handle
different error conditions appropriately. Finally, add docstrings to config classes to help
with discoverability and so the discovery system can extract meaningful documentation about
what configuration each plugin accepts.

## Function-Based Transform Plugins

For simple System transformations, you can use function-based plugins with the `@expose_plugin` decorator.
These are zero-overhead alternatives to the full Plugin class pattern:

```python
from r2x_core import expose_plugin, PluginConfig, System
from rust_ok import Ok, Result

class MyTransformConfig(PluginConfig):
    threshold: int = 5

@expose_plugin
def my_transform(system: System, config: MyTransformConfig) -> Result[System, str]:
    """Transform system based on config."""
    return Ok(system)

# Call directly in Python:
config = MyTransformConfig(threshold=10)
result = my_transform(system, config)
```

Function-based plugins:
- Use `PluginConfig` for type-safe configuration
- Return `Result[System, str]` for consistent error handling
- Are marked with `@expose_plugin` for CLI discovery via entry points
- Are called explicitly with all arguments (no auto-injection)

See {doc}`../how-tos/create-function-plugins` for detailed examples and best practices.

## Next Steps

For working with function-based plugins, see {doc}`../how-tos/create-function-plugins`. For
detailed patterns on how to use plugin context effectively in complex workflows with class-based
plugins, see {doc}`./plugin-context`. Additional examples of working plugins can be found in
`tests/test_plugin*.py`, covering edge cases and advanced patterns not shown in this introduction.
