# Plugin System Architecture

This document explains the design and architecture of the r2x-core plugin
system, providing insight into how it works and why it was designed this way.

## Purpose and Goals

The plugin system enables **extensibility** and **modularity** in r2x-core by
allowing applications and external packages to register custom components
without modifying the core library. This separation of concerns provides:

- **Model-agnostic workflows**: Parse from any input model, export to any output
  model
- **Decentralized development**: Model-specific code lives in separate packages
- **Dynamic discovery**: Automatically find and load installed plugins
- **Reusable components**: Share parsers, exporters, and transformations across
  applications

## Architecture Overview

The plugin system consists of three main layers:

### 1. Plugin Types

r2x-core supports three distinct plugin types, each serving a different purpose:

#### Model Plugins

Model plugins register custom functionality for specific energy models (e.g.,
ReEDS, PLEXOS, Sienna). Each model plugin consists of:

- **Configuration**: A `PluginConfig` subclass defining model-specific
  parameters with automatic path resolution and JSON defaults loading
- **Plugin Implementation**: A `Plugin` subclass implementing custom logic

**Rationale**: The plugin system allows flexible, extensible workflows where
model-specific code is decoupled from the core library.

**PluginConfig Features**:

- Automatic configuration directory discovery (looks for `config/` subdirectory
  relative to the config class)
- Load default parameters from `config/defaults.json`
- Load file mappings from `config/file_mapping.json`
- Pydantic-based validation and type safety
- Full IDE support for field completion

```{seealso}
See {doc}`../how-tos/structure-plugin-directories` for configuration best practices and standards.
```

#### System Modifier Plugins

System modifiers are functions that post-process a `System` after parsing. They
enable:

- Adding components (storage, electrolyzers, etc.)
- Removing or filtering components
- Adding time series from external sources
- Setting constraints or limits
- Modifying attributes based on scenarios

**Rationale**: System modifiers provide a hook for custom logic without
requiring parser subclassing. This allows combining base model parsers with
application-specific customizations.

**Signature**: `(system: System, context: PluginContext, **kwargs) -> System`

The `PluginContext` provides access to configuration and the source system
during modifications.

#### Filter Plugins

Filters are data transformation functions applied during parsing. They operate
on raw data (typically `polars.LazyFrame` or `dict`) before component creation.

**Rationale**: Filters provide reusable data transformations that can be shared
across parsers and models. Common operations (rename columns, filter rows,
convert units) become first-class, discoverable functions.

**Signature**: `(data: Any, **kwargs) -> Any`

The flexible signature supports polymorphic filters that work with multiple data
types.

#### Function-Based Transform Plugins

Transform functions are simple, zero-overhead plugins for System transformations.
They are marked with the `@expose_plugin` decorator for CLI discovery.

**Rationale**: For simple transforms, function-based plugins avoid boilerplate
while maintaining full type safety via `PluginConfig`. The decorator is purely
a marker—no auto-injection or magic at runtime. Users call functions explicitly
with all arguments.

**Signature**: `(system: System, config: C) -> Result[System, str]` where C is a
`PluginConfig` subclass.

**Decorator**: `@expose_plugin` - marks function for AST-grep discovery, sets `__r2x_exposed__` attribute.

**Example**:

```python doctest
from r2x_core import expose_plugin, PluginConfig, System
from pydantic import Field
from rust_ok import Ok, Result

class BreakGensConfig(PluginConfig):
    """Configuration for breaking generators."""
    threshold: int = Field(default=5, ge=0)

@expose_plugin
def break_generators(
    system: System,
    config: BreakGensConfig,
) -> Result[System, str]:
    """Break generators into sub-units based on threshold."""
    # Implementation here
    return Ok(system)

# Direct usage (explicit, no magic):
config = BreakGensConfig(threshold=10)
my_system = System(name="test")
result = break_generators(my_system, config)
assert result.is_ok()
new_system = result.unwrap()
assert new_system.name == "test"
```

The function can optionally accept a `ctx: PluginContext | None` parameter for
access to the DataStore or metadata during execution.

### 2. Plugin Registry

The `Plugin` base class and `PluginContext` provide the core mechanism for
plugin execution and context management.

#### PluginContext

The `PluginContext` is passed to plugin implementations during execution:

```python
context: PluginContext = PluginContext(
    source_system=...,     # System being transformed
    target_system=...,     # Target system for results
    config=...,            # Plugin configuration
)
```

Plugin methods receive this context and use it to access both systems and
configuration.

#### Plugin Base Class

Custom plugins inherit from `Plugin`:

```python
from r2x_core import Plugin, PluginConfig, PluginContext

class MyPlugin(Plugin):
    """Custom plugin for data transformation."""

    def apply(self, context: PluginContext) -> None:
        """Apply plugin logic to context systems."""
        source = context.source_system
        target = context.target_system
        # Custom logic here
```

### 3. Plugin Configuration

Plugins use `PluginConfig` for type-safe, validated configuration:

```python
from r2x_core import PluginConfig
from pydantic import field_validator

class MyPluginConfig(PluginConfig):
    """Configuration for custom plugin."""

    folder: str
    year: int
    scenario: str = "base"

    @field_validator("year")
    @classmethod
    def validate_year(cls, v):
        if v < 2020 or v > 2050:
            raise ValueError("Year must be between 2020 and 2050")
        return v
```

Configuration loads automatically from `config/defaults.json` and
`config/file_mapping.json` relative to the config class location.

## Data Flow

### Plugin Execution Model

Plugins are called during the system transformation process:

1. **Initialization**: Plugin receives configuration (PluginConfig subclass)
2. **Context Creation**: PluginContext is created with source and target systems
3. **Plugin Execution**: Plugin.apply(context) performs custom logic
4. **Result**: Modified or new system is returned

### Filter Application in Parsers

Filters are optional transformations that can be applied during component
creation:

```
Raw Data File
  ↓
Filter 1: rename_columns()
  ↓
Filter 2: filter_by_year()
  ↓
Filter 3: convert_units()
  ↓
create_component(ComponentClass)
  ↓
Add to System
```

Filters are composable and can be chained together for complex data
transformations.

## Design Decisions

### Why Use PluginConfig Subclasses?

PluginConfig provides a structured approach to plugin configuration.

**Advantages**:

- Type safety with Pydantic validation
- IDE support and autocomplete
- JSON schema generation for tooling
- Automatic path resolution for config files
- Clear documentation of required parameters

### Why Flexible Plugin Signatures?

System modifiers and filters use flexible `**kwargs` rather than strict typed
signatures.

**Rationale**:

- Different modifiers need different context (some need config, some don't)
- Filters may work with different data types (DataFrame, dict, etc.)
- Easier to extend without breaking existing plugins
- Applications can pass custom parameters

**Trade-off**: Less type safety, but more flexibility. We rely on documentation
and type hints.

### Why PluginContext Instead of Individual Parameters?

The `PluginContext` bundles source system, target system, and configuration
together.

**Advantages**:

- Single parameter instead of scattered arguments
- Consistent interface across plugins
- Easy to extend with new context fields
- Clear separation of concerns

### Why Support Both Plugins and Filter Functions?

Plugins handle complex logic, while filters handle data transformations.

**Use cases**:

- **Plugins**: Add storage, modify constraints, merge systems
- **Filters**: Rename columns, filter rows, convert units

This separation allows:

- Composable transformations for data pipelines
- Reusable logic across multiple parsers
- Flexibility in implementation approach

## Extension Points

The plugin system provides several extension points for customization:

### 1. Custom Plugin Classes

Applications can create custom Plugin subclasses for specific functionality:

```python
from r2x_core import Plugin, PluginContext, PluginConfig

class StoragePlugin(Plugin):
    """Add storage components to a system."""

    def apply(self, context: PluginContext) -> None:
        for storage_config in self.config.storages:
            component = create_component(
                Storage,
                name=storage_config.name,
                capacity=storage_config.capacity_mw
            )
            context.target_system.add_component(component)
```

### 2. Filter Functions

Custom filter functions can be defined and used during parsing:

```python
def filter_by_year(data: Any, *, year: int) -> Any:
    """Filter components by year."""
    return data[data["year"] == year]

# Use in parser
filtered = filter_by_year(raw_data, year=2030)
```

### 3. Configuration Validation

PluginConfig supports comprehensive validation:

```python
class AdvancedConfig(PluginConfig):
    models: list[str]
    solver: str = "gurobi"

    @field_validator("models")
    @classmethod
    def validate_models(cls, v):
        if not v:
            raise ValueError("At least one model required")
        return v
```

## Security Considerations

### Trusted Plugins Only

The plugin system executes code from external packages. Only install plugins
from **trusted sources**.

### Entry Point Validation

PluginManager validates entry points during discovery:

- Catches and logs errors if a plugin fails to load
- Continues initialization even if one plugin fails
- Provides clear error messages for debugging

### No Sandboxing

Plugins run with full application privileges. There is **no sandboxing** or
permission system.

**Mitigation**: Document clearly which plugins are official/trusted, and
encourage users to review plugin code before installation.

## Future Considerations

### Plugin Dependencies

Currently, plugins can have dependencies on each other implicitly (e.g., a
modifier might expect certain filters to be registered). Future versions could:

- Add explicit dependency declaration
- Validate plugin dependencies at registration
- Provide dependency resolution

### Plugin Versioning

Future versions could support:

- Version requirements for plugins
- Compatibility checking (plugin API version)
- Migration paths for breaking changes

### Plugin Configuration

Future versions could add:

- Plugin-level configuration
- Enable/disable plugins dynamically
- Plugin priority/ordering for modifiers

## See Also

- {doc}`../how-tos/register-plugins` : How to register plugins
- {doc}`../how-tos/run-plugins` : How to use registered plugins
- {doc}`../how-tos/run-plugins` : Using plugins in workflows
- {doc}`../references/plugins` : Plugin API reference
