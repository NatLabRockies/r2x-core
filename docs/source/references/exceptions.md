# Exceptions Reference

R2X Core provides custom exceptions for different error scenarios. All exceptions inherit from `R2XCoreError` and provide clear, actionable error messages.

## Validation Errors

### ValidationError

Raised when data validation fails, such as invalid file formats or missing required fields.

```python doctest
>>> from r2x_core import ValidationError
>>> try:
...     raise ValidationError("Invalid column name: 'missing_column'")
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
...     raise ComponentCreationError("Failed to create component: missing 'name' field")
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
...     raise UpgradeError("Cannot upgrade from v1.0 to v3.0: missing v2.0 intermediate")
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
...     raise CLIError("Plugin execution failed: timeout after 30 seconds")
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
...     raise PluginError("Plugin 'my_plugin' not found in registry")
... except PluginError as e:
...     print(f"Caught plugin error: {e}")
Caught plugin error: Plugin 'my_plugin' not found in registry
```

## Error Handling Best Practices

For symptom-led diagnosis and minimal recovery checks, see [Troubleshooting](/r2x-core/troubleshooting/).
Exception inheritance supports catching specific types or their common `R2XCoreError` base; choose the boundary based on which failures the caller can handle.
