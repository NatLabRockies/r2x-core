# Versioning Strategies

For complete API documentation of versioning classes, see {doc}`./api`.

## Quick Reference

- {py:class}`~r2x_core.VersionStrategy` - Versioning protocol base class
- {py:class}`~r2x_core.SemanticVersioningStrategy` - Semantic versioning (e.g., "1.2.3")
- {py:class}`~r2x_core.GitVersioningStrategy` - Git-based versioning
- {py:class}`~r2x_core.VersionReader` - Version detection utility

## Overview

The versioning system provides flexible strategies for managing version information in data structures and system objects. Supported strategies include semantic versioning and git-based versioning.

## Protocol: VersionReader

The {py:class}`~r2x_core.VersionReader` protocol defines the interface for detecting versions from data:

```python doctest
>>> from r2x_core import VersionReader
>>> from typing import Protocol
>>> # VersionReader is a Protocol (structural typing)
>>> isinstance(VersionReader, type)
True
```

## Usage Examples

### Semantic Versioning

Use semantic versioning for human-readable version strings following the `MAJOR.MINOR.PATCH` format:

```python
from r2x_core import SemanticVersioningStrategy

# Create strategy
strategy = SemanticVersioningStrategy(version_field="version")

# Get version from data
data = {"version": "1.2.3", "buses": [...]}
current = strategy.get_version(data)  # "1.2.3"

# Compare versions
comparison = strategy.compare("1.2.3", "2.0.0")  # -1 (current < target)
comparison = strategy.compare("2.0.0", "1.2.3")  # 1 (current > target)
comparison = strategy.compare("1.2.3", "1.2.3")  # 0 (equal)

# Set new version
updated_data = strategy.set_version(data, "2.0.0")
```

### Custom Version Field

Specify a custom field name for version storage:

```python
# Use custom field name
strategy = SemanticVersioningStrategy(
    version_field="schema_version",
    default_version="0.0.0"
)

data = {"schema_version": "2.1.0", "config": {...}}
version = strategy.get_version(data)  # "2.1.0"
```

### Git-Based Versioning

Use git commit hashes or timestamps for version tracking:

```python
from r2x_core import GitVersioningStrategy

# Using commit hashes (string comparison)
strategy = GitVersioningStrategy(version_field="git_version")

data = {"git_version": "abc123def", "data": [...]}
current = strategy.get_version(data)

# Using ISO timestamps
strategy = GitVersioningStrategy(
    version_field="git_version",
    use_timestamps=True
)

data = {
    "git_version": "2024-01-01T00:00:00Z",
    "data": [...]
}
comparison = strategy.compare(
    "2024-01-01T00:00:00Z",
    "2024-06-01T00:00:00Z"
)  # -1 (earlier < later)
```

## Version Comparison

All strategies follow the same comparison convention:

- **-1**: Current version is less than target (upgrade needed)
- **0**: Versions are equal (no upgrade needed)
- **1**: Current version is greater than target (downgrade or error)

```python
from r2x_core import SemanticVersioningStrategy

strategy = SemanticVersioningStrategy()

# Check if upgrade is needed
if strategy.compare("1.0.0", "2.0.0") < 0:
    print("Upgrade required")

# Handle None current version (treated as earliest)
strategy.compare(None, "1.0.0")  # -1 (always needs upgrade)
```

## Working with Objects

Versioning strategies work with dictionaries and objects with attributes:

```python
from pydantic import BaseModel
from r2x_core import SemanticVersioningStrategy

class Config(BaseModel):
    version: str
    name: str

strategy = SemanticVersioningStrategy(version_field="version")

# Works with Pydantic models
config = Config(version="1.0.0", name="test")
current = strategy.get_version(config)  # "1.0.0"

# Set version on object
strategy.set_version(config, "2.0.0")
assert config.version == "2.0.0"
```

## Best Practices

### Choose the Right Strategy

- **SemanticVersioningStrategy**: For human-readable versions with clear upgrade paths
- **GitVersioningStrategy**: For tracking changes tied to git commits or timestamps

### Version Field Naming

Use consistent field names across your data structures:

```python
# Good: Consistent naming
strategy = SemanticVersioningStrategy(version_field="schema_version")

# All data uses same field
data_v1 = {"schema_version": "1.0.0", ...}
data_v2 = {"schema_version": "2.0.0", ...}
```

### Handle Missing Versions

Always handle cases where version information is missing:

```python
strategy = SemanticVersioningStrategy(default_version="0.0.0")

# Missing version treated as default
data_without_version = {"name": "test"}
version = strategy.get_version(data_without_version)  # None

# Compare treats None as earliest version
strategy.compare(None, "1.0.0")  # -1 (upgrade needed)
```

## See Also

- {doc}`./upgrader` - Upgrade system using versioning strategies
- {doc}`../how-tos/manage-versions` - Version management guide
- {doc}`./api` - Complete API documentation
