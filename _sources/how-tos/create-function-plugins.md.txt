# Create Function-Based Transform Plugins

Function-based plugins are simple, zero-overhead transforms that modify a `System` using a `PluginConfig`. They are marked with the `@expose_plugin` decorator for CLI discovery.

## Basic Transform Function

Create a simple transform that modifies a system:

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from pydantic import Field
>>> from rust_ok import Ok, Result

>>> class RenameConfig(PluginConfig):
...     suffix: str = Field(default="_v2", description="Suffix to append to system name")

>>> @expose_plugin
... def rename_system(system: System, config: RenameConfig) -> Result[System, str]:
...     """Append suffix to system name."""
...     system.name = f"{system.name}{config.suffix}"
...     return Ok(system)

>>> # Call directly in Python:
>>> config = RenameConfig(suffix="_updated")
>>> system = System(name="my_system")
>>> result = rename_system(system, config)
>>> result.is_ok()
True
>>> result.unwrap().name
'my_system_updated'
```

## With Configuration Validation

Use Pydantic field validators to enforce configuration constraints:

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from pydantic import Field, field_validator
>>> from rust_ok import Ok, Result

>>> class ThresholdConfig(PluginConfig):
...     threshold: int = Field(default=100, ge=0, le=1000)
...     description: str = Field(default="Filter components")
...
...     @field_validator("threshold")
...     @classmethod
...     def validate_threshold(cls, v):
...         if v % 10 != 0:
...             raise ValueError("Threshold must be a multiple of 10")
...         return v

>>> @expose_plugin
... def filter_by_threshold(
...     system: System,
...     config: ThresholdConfig,
... ) -> Result[System, str]:
...     """Filter components by threshold."""
...     # Implementation would filter based on config.threshold
...     return Ok(system)

>>> config = ThresholdConfig(threshold=100)  # Valid: multiple of 10
>>> system = System(name="test")
>>> result = filter_by_threshold(system, config)
>>> result.is_ok()
True
```

## With Complex Configuration

Use nested Pydantic models for complex configurations:

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from pydantic import BaseModel, Field
>>> from rust_ok import Ok, Result

>>> class FilterCriteria(BaseModel):
...     min_capacity: float = Field(default=0.0)
...     max_capacity: float = Field(default=10000.0)

>>> class AdvancedFilterConfig(PluginConfig):
...     filter_criteria: FilterCriteria = Field(
...         default_factory=FilterCriteria,
...         description="Filtering thresholds"
...     )
...     remove_unmatched: bool = Field(default=False)

>>> @expose_plugin
... def advanced_filter(
...     system: System,
...     config: AdvancedFilterConfig,
... ) -> Result[System, str]:
...     """Advanced filtering with nested config."""
...     # Use config.filter_criteria.min_capacity, etc.
...     return Ok(system)

>>> config = AdvancedFilterConfig(
...     filter_criteria=FilterCriteria(min_capacity=5.0, max_capacity=500.0),
...     remove_unmatched=True,
... )
>>> system = System(name="test")
>>> result = advanced_filter(system, config)
>>> result.is_ok()
True
```

## Error Handling with Result

Return errors when operations fail:

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from rust_ok import Ok, Err, Result

>>> class ValidateConfig(PluginConfig):
...     min_name_length: int = 3

>>> @expose_plugin
... def validate_system_name(
...     system: System,
...     config: ValidateConfig,
... ) -> Result[System, str]:
...     """Validate system name meets minimum length requirement."""
...     if len(system.name) < config.min_name_length:
...         return Err(f"System name too short (< {config.min_name_length} chars)")
...     return Ok(system)

>>> config = ValidateConfig(min_name_length=10)
>>> system = System(name="short")
>>> result = validate_system_name(system, config)
>>> result.is_err()
True
>>> result.error
'System name too short (< 10 chars)'
```

## Direct Usage in Python

Call exposed functions directly with explicit arguments:

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from rust_ok import Ok, Result

>>> class SimpleConfig(PluginConfig):
...     action: str = "modify"

>>> @expose_plugin
... def simple_transform(system: System, config: SimpleConfig) -> Result[System, str]:
...     """Simple transform action."""
...     return Ok(system)

>>> # Direct Python usage - explicit and clear:
>>> config = SimpleConfig(action="modify")
>>> system = System(name="original")
>>> result = simple_transform(system, config)

>>> # Get the result:
>>> if result.is_ok():
...     modified_system = result.unwrap()
...     print(f"Success: {modified_system.name}")
... else:
...     print(f"Error: {result.error()}")
Success: original
```

### Advanced: Python 3.12 Type Parameters (PEP 695)

Use PEP 695 type parameter syntax for generic plugin functions with constrained config types:

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from rust_ok import Ok, Result
>>> from pydantic import Field

>>> # Define config types that implement a specific interface
>>> class BaseTransformConfig(PluginConfig):
...     """Base config for transform operations."""
...     pass

>>> class ScaleConfig(BaseTransformConfig):
...     """Config for scaling operations."""
...     factor: float = Field(default=1.0, ge=0.1)

>>> class RotateConfig(BaseTransformConfig):
...     """Config for rotation operations."""
...     angle: float = Field(default=0.0)

>>> # Python 3.12 type parameter syntax with constraint
>>> @expose_plugin
... def transform_system[C: BaseTransformConfig](
...     system: System,
...     config: C,
... ) -> Result[System, str]:
...     """Generic transform accepting any BaseTransformConfig subclass."""
...     # Config type is guaranteed to be BaseTransformConfig or subclass
...     system.name = f"{system.name}_transformed"
...     return Ok(system)

>>> # Usage - type parameter is inferred from config type
>>> system = System(name="grid")
>>> scale_config = ScaleConfig(factor=2.5)
>>> result = transform_system(system, scale_config)
>>> result.unwrap().name
'grid_transformed'

>>> # Type checker ensures config matches the constraint
>>> rotate_config = RotateConfig(angle=45.0)
>>> result2 = transform_system(system, rotate_config)
>>> result2.is_ok()
True
```

**PEP 695 Type Parameter Syntax Benefits**:

Constraint checking with `[C: BaseTransformConfig]` ensures config type validity, type parameters are automatically inferred from the config argument, full auto-completion and type checking support in IDEs, cleaner and more readable syntax compared to the `TypeVar` approach, and constraints clearly visible in the function signature for self-documenting code.

**When to Use**:

Use PEP 695 for plugins accepting multiple config types with a common interface. Use simple `config: SpecificConfig` for single config types. Use `config: C` with TypeVar for backward compatibility with Python versions earlier than 3.12.

## CLI Registration via Entry Points

To make your function discoverable by the Rust CLI, register it as an entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."r2x.transforms"]
rename_system = "my_package.transforms:rename_system"
filter_components = "my_package.transforms:filter_by_threshold"
advanced_filter = "my_package.transforms:advanced_filter"
```

The Rust CLI will:
1. **Discover** exposed functions via AST-grep scanning for `@expose_plugin` decorator
2. **Introspect** the `PluginConfig` class to generate CLI arguments
3. **Invoke** the function with parsed arguments and system data

## Best Practices

### ✅ Do

- **Use `PluginConfig` subclasses** for type safety and validation
- **Return `Result[System, str]`** for consistent error handling
- **Document config fields** with descriptions in `Field()`
- **Use Pydantic validators** for complex validation logic
- **Keep functions pure** - no side effects beyond modifying the system
- **Name functions clearly** - indicate what they do (`rename_system`, `filter_components`)

### ❌ Don't

- Don't accept arbitrary keyword arguments in the signature
- Don't modify the system in-place without returning it in a Result
- Don't use global state or external dependencies without injecting them
- Don't raise exceptions - use `Err()` instead
- Don't use overly complex config structures - break into nested models if needed

## Full Example: Break Generators Plugin

Here's a complete example of a real-world transform plugin:

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from pathlib import Path
>>> from pydantic import Field, field_validator
>>> from rust_ok import Ok, Err, Result

>>> class BreakGensConfig(PluginConfig):
...     """Configuration for breaking generators into sub-units."""
...
...     drop_capacity_threshold: int = Field(
...         default=5,
...         ge=0,
...         description="Generators below this capacity (MW) are dropped"
...     )
...     skip_categories: list[str] = Field(
...         default_factory=list,
...         description="Generator categories to skip"
...     )
...     break_category: str = Field(
...         default="category",
...         description="Field name to break generators on"
...     )

>>> @expose_plugin
... def break_generators(
...     system: System,
...     config: BreakGensConfig,
... ) -> Result[System, str]:
...     """Break generators into sub-units based on reference data.
...
...     This transform splits large generators into smaller units,
...     allowing more granular modeling of generation resources.
...
...     Parameters
...     ----------
...     system : System
...         The system containing generators to break
...     config : BreakGensConfig
...         Configuration for breaking logic
...
...     Returns
...     -------
...     Result[System, str]
...         Modified system with broken generators or error message
...     """
...     if config.drop_capacity_threshold < 0:
...         return Err("drop_capacity_threshold must be non-negative")
...
...     # Implementation would iterate through generators and break them
...     # based on the configuration
...
...     return Ok(system)

>>> # Example usage:
>>> config = BreakGensConfig(
...     drop_capacity_threshold=10,
...     skip_categories=["nuclear"],
...     break_category="fuel_type"
... )
>>> system = System(name="western_grid")
>>> result = break_generators(system, config)
>>> result.is_ok()
True
```

## See Also

- {doc}`../explanations/plugin-system` - Plugin system architecture
- {doc}`../references/api` - API reference for `@expose_plugin` decorator
- {doc}`manage-datastores` - Working with DataStore for file operations
