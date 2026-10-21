# Exceptions Reference

r2x-core provides custom exceptions for different error scenarios. All exceptions inherit from `R2XCoreError` and provide clear, actionable error messages.

## Validation Errors

### ValidationError

Raised when data validation fails, such as invalid file formats or missing required fields.

```python doctest
>>> from r2x_core import ValidationError
>>> try:
...     msg = "Invalid column name: 'missing_column'"
...     raise ValidationError(msg)
... except ValidationError as e:
...     print(f"Caught validation error: {e}")
Caught validation error: Invalid column name: 'missing_column'
```

## Component Creation Errors

### ComponentCreationError

Raised when component creation fails, such as missing dependencies or invalid configurations.

```python doctest
>>> from r2x_core import ComponentCreationError
>>> try:
...     msg = "Failed to create component: missing 'name' field"
...     raise ComponentCreationError(msg)
... except ComponentCreationError as e:
...     print(f"Caught creation error: {e}")
Caught creation error: Failed to create component: missing 'name' field
```

## Upgrade Errors

### UpgradeError

Raised when a system upgrade fails, such as incompatible version transitions or failed migration steps.

```python doctest
>>> from r2x_core import UpgradeError
>>> try:
...     msg = "Cannot upgrade from v1.0 to v3.0: missing v2.0 intermediate"
...     raise UpgradeError(msg)
... except UpgradeError as e:
...     print(f"Caught upgrade error: {e}")
Caught upgrade error: Cannot upgrade from v1.0 to v3.0: missing v2.0 intermediate
```

## CLI Errors

### CLIError

Raised during CLI plugin execution when command-line operations fail.

```python doctest
>>> from r2x_core import CLIError
>>> try:
...     msg = "Plugin execution failed: timeout after 30 seconds"
...     raise CLIError(msg)
... except CLIError as e:
...     print(f"Caught CLI error: {e}")
Caught CLI error: Plugin execution failed: timeout after 30 seconds
```

## Plugin Errors

### PluginError

Raised during plugin execution when plugin operations fail, such as missing plugin dependencies or invalid plugin configuration.

```python doctest
>>> from r2x_core import PluginError
>>> try:
...     msg = "Plugin 'my_plugin' not found in registry"
...     raise PluginError(msg)
... except PluginError as e:
...     print(f"Caught plugin error: {e}")
Caught plugin error: Plugin 'my_plugin' not found in registry
```

## Error Handling Best Practices

For symptom-led diagnosis and minimal recovery checks, see [Troubleshooting](/r2x-core/troubleshooting/).
Exception inheritance supports catching specific types or their common `R2XCoreError` base; choose the boundary based on which failures the caller can handle.
