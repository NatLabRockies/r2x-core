# Plugin Discovery

Plugins can be automatically discovered and cataloged using ast-grep rules. This
enables:

- Plugin registry generation
- CLI help text generation
- Documentation generation
- Type checking and validation

## Discovery Information

For each plugin, we can extract:

1. **Config Type**: From generic parameter `class MyPlugin(Plugin[MyConfig])`
2. **Implemented Hooks**: From method names (`on_validate`, `on_build`, etc.)
3. **Required Context Fields**: From non-Optional property return types
4. **Config Schema**: Field names, types, defaults, and metadata

## Example: Discovering ReEDSParser

Given this plugin:

```python
from r2x_core import Plugin, PluginContext, PluginConfig, System, DataStore
from rust_ok import Ok, Result

class ReEDSConfig(PluginConfig):
    """Configuration for ReEDS parser."""
    model_year: int
    scenario: str = "base"
    input_folder: str
    skip_buses: bool = False

class ReEDSParser(Plugin[ReEDSConfig]):
    """Parses ReEDS model data."""

    @property
    def config(self) -> ReEDSConfig:
        return self._ctx.config

    @property
    def store(self) -> DataStore:  # Non-Optional = required
        if self._ctx.store is None:
            raise RuntimeError("DataStore required")
        return self._ctx.store

    def on_validate(self) -> Result[None, Exception]:
        if not self.config.input_folder:
            return Err(ValueError("input_folder required"))
        return Ok(None)

    def on_build(self) -> Result[System, Exception]:
        system = System(name=f"reeds_{self.config.model_year}")
        # ... build logic
        return Ok(system)
```

Discovery would extract:

```json
{
  "ReEDSParser": {
    "config_type": "ReEDSConfig",
    "file": "plugins/reeds_parser.py",
    "line": 12,
    "hooks": ["on_validate", "on_build"],
    "required_context": ["config", "store"],
    "accepts_stdin": false,
    "config_schema": {
      "model_year": {
        "type": "int",
        "required": true
      },
      "scenario": {
        "type": "str",
        "required": false,
        "default": "base"
      },
      "input_folder": {
        "type": "str",
        "required": true
      },
      "skip_buses": {
        "type": "bool",
        "required": false,
        "default": false
      }
    }
  }
}
```

## Programmatic Discovery

### Using Plugin Introspection

```python
from r2x_core import Plugin, PluginConfig
from rust_ok import Ok

class MyConfig(PluginConfig):
    value: int

class MyPlugin(Plugin[MyConfig]):
    def on_validate(self):
        return Ok(None)
...
    def on_build(self):
        return Ok(None)

# Get config type
config_type = MyPlugin.get_config_type()
config_type.__name__
'MyConfig'

# Get implemented hooks
hooks = MyPlugin.get_implemented_hooks()
sorted(list(hooks))
['on_build', 'on_validate']
```

### Detecting Capabilities

```python
def get_plugin_capabilities(plugin_class: type[Plugin]) -> list[str]:
    """Infer plugin capabilities from implemented hooks."""
    hooks = plugin_class.get_implemented_hooks()
    capabilities = []

    if 'on_build' in hooks:
        capabilities.append('build')
    if 'on_transform' in hooks:
        capabilities.append('transform')
    if 'on_translate' in hooks:
        capabilities.append('translate')
    if 'on_export' in hooks:
        capabilities.append('export')

    return capabilities

# Usage
caps = get_plugin_capabilities(MyPlugin)
# ['build', 'validate']
```

### Detecting Required Context

```python
import inspect

def get_required_context_fields(plugin_class: type[Plugin]) -> list[str]:
    """Extract required context fields from property return types."""
    required = ['config']  # Always required

    for name in ['store', 'system', 'source_system', 'target_system']:
        try:
            prop = getattr(plugin_class, name)
            if isinstance(prop, property):
                # Check return type annotation
                # Non-Optional return type = required
                # For now, assume all are required if property exists
                required.append(name)
        except AttributeError:
            pass

    return required

# Usage
fields = get_required_context_fields(MyPlugin)
# ['config', 'store', 'system']
```

## ast-grep Rules for Discovery

The following ast-grep rules can be used to discover plugins at scale:

### Rule 1: Find Plugin Classes

```yaml
id: discover-plugin-classes
language: python
severity: info
message: "Plugin class: $CLASS with config $CONFIG"
rule:
  kind: class_definition
  has:
    kind: identifier
    regex: ".*Plugin$"  # Classes ending in 'Plugin'
    stopBy: neighbor
  has:
    kind: argument_list
    has:
      kind: subscript
      pattern: Plugin[$CONFIG]
      stopBy: end
    stopBy: end
```

**Usage:**

```bash
ast-grep scan --rule discover_plugins.yml /path/to/plugins/
```

### Rule 2: Find Implemented Hooks

```yaml
id: discover-plugin-hooks
language: python
severity: info
message: "Hook: $NAME"
rule:
  kind: function_definition
  has:
    kind: identifier
    regex: "^on_(validate|prepare|build|transform|translate|export|cleanup)$"
    stopBy: neighbor
  inside:
    kind: class_definition
    has:
      pattern: Plugin[$_]
      stopBy: end
    stopBy: end
```

### Rule 3: Find Config Classes

```yaml
id: discover-config-classes
language: python
severity: info
message: "Config: $CLASS"
rule:
  kind: class_definition
  has:
    kind: identifier
    regex: ".*Config$"  # Classes ending in 'Config'
    stopBy: neighbor
  has:
    kind: argument_list
    has:
      kind: identifier
      regex: "^PluginConfig$"
      stopBy: end
    stopBy: end
```

### Rule 4: Find Required Context Properties

```yaml
id: discover-required-context
language: python
severity: info
message: "Required context field: $NAME"
rule:
  kind: function_definition
  all:
    # Has @property decorator
    - has:
        kind: decorator
        has:
          kind: identifier
          regex: "^property$"
        stopBy: end
    # Return type is NOT Optional
    - has:
        kind: type
        not:
          any:
            - has:
                pattern: "None"
                stopBy: end
            - has:
                pattern: "Optional[$_]"
                stopBy: end
            - pattern: "$_ | None"
        stopBy: end
    # Inside a Plugin class
    - inside:
        kind: class_definition
        has:
          pattern: Plugin[$_]
          stopBy: end
        stopBy: end
```

## Function-Based Plugins with @expose_plugin

Function-based plugins offer a simpler alternative to class-based plugins. They are marked with the `@expose_plugin` decorator and can have complex configurations including nested models.

### Basic Function Plugin

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from rust_ok import Ok, Result

>>> class SimpleTransformConfig(PluginConfig):
...     name: str
...     enabled: bool = True

>>> @expose_plugin
... def simple_transform(system: System, config: SimpleTransformConfig) -> Result[System, str]:
...     """Basic transformation that renames the system."""
...     if config.enabled:
...         system.name = f"{system.name}_{config.name}"
...     return Ok(system)

>>> # Direct Python usage
>>> config = SimpleTransformConfig(name="updated")
>>> system = System(name="grid")
>>> result = simple_transform(system, config)
>>> result.unwrap().name
'grid_updated'
```

### Function Plugin with Nested Models

Configuration fields can contain nested Pydantic models for complex structures:

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from pydantic import BaseModel, Field
>>> from rust_ok import Ok, Result

>>> class FilterCriteria(BaseModel):
...     """Nested criteria for filtering."""
...     min_value: float = Field(default=0.0, description="Minimum threshold")
...     max_value: float = Field(default=100.0, description="Maximum threshold")
...     enabled: bool = Field(default=True, description="Enable filtering")

>>> class AdvancedFilterConfig(PluginConfig):
...     """Configuration with nested models."""
...     filter_type: str = Field(default="range", description="Type of filter")
...     criteria: FilterCriteria = Field(
...         default_factory=FilterCriteria,
...         description="Nested filtering criteria"
...     )
...     apply_to_all: bool = Field(default=False, description="Apply to all components")

>>> @expose_plugin
... def advanced_filter(system: System, config: AdvancedFilterConfig) -> Result[System, str]:
...     """Apply advanced filtering with nested configuration."""
...     # Access nested fields
...     if config.criteria.enabled:
...         system.name = f"{system.name}_filtered"
...     return Ok(system)

>>> # Usage with nested configuration
>>> filter_config = AdvancedFilterConfig(
...     filter_type="custom",
...     criteria=FilterCriteria(min_value=10.0, max_value=50.0, enabled=True),
...     apply_to_all=True
... )
>>> system = System(name="power_grid")
>>> result = advanced_filter(system, filter_config)
>>> result.unwrap().name
'power_grid_filtered'
```

### Multiple Configuration Ways

Function plugins support several ways to define and use configurations:

#### 1. Simple Configuration

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from rust_ok import Ok, Result

>>> class RenameConfig(PluginConfig):
...     suffix: str = "_renamed"

>>> @expose_plugin
... def rename_system(system: System, config: RenameConfig) -> Result[System, str]:
...     system.name = f"{system.name}{config.suffix}"
...     return Ok(system)

>>> config = RenameConfig(suffix="_v2")
>>> result = rename_system(System(name="sys"), config)
>>> result.unwrap().name
'sys_v2'
```

#### 2. Configuration with Validation

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from pydantic import Field, field_validator
>>> from rust_ok import Ok, Result

>>> class ValidatedConfig(PluginConfig):
...     value: int = Field(default=1, ge=1, le=100, description="Value between 1 and 100")
...     operation: str = Field(default="add", description="Operation to perform")
...
...     @field_validator("operation")
...     @classmethod
...     def validate_operation(cls, v):
...         if v not in ["add", "subtract", "multiply"]:
...             raise ValueError("Invalid operation")
...         return v

>>> @expose_plugin
... def validated_transform(system: System, config: ValidatedConfig) -> Result[System, str]:
...     system.name = f"{system.name}_{config.operation}"
...     return Ok(system)

>>> config = ValidatedConfig(value=50, operation="multiply")
>>> result = validated_transform(System(name="data"), config)
>>> result.is_ok()
True
```

#### 3. Configuration with Complex Nested Structure

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from pydantic import BaseModel, Field
>>> from rust_ok import Ok, Result
>>> from typing import Optional

>>> class TimeSeriesConfig(BaseModel):
...     """Configuration for time series handling."""
...     frequency: str = Field(default="hourly", description="Data frequency")
...     interpolate: bool = Field(default=False, description="Interpolate missing values")

>>> class DataProcessingConfig(BaseModel):
...     """Nested data processing settings."""
...     clean_outliers: bool = Field(default=True)
...     time_series: TimeSeriesConfig = Field(
...         default_factory=TimeSeriesConfig,
...         description="Time series configuration"
...     )

>>> class ComplexTransformConfig(PluginConfig):
...     """Complex configuration with multiple nested levels."""
...     name: str = Field(description="Transform name")
...     data_processing: DataProcessingConfig = Field(
...         default_factory=DataProcessingConfig,
...         description="Data processing settings"
...     )
...     output_format: Optional[str] = Field(default=None, description="Output format")

>>> @expose_plugin
... def complex_transform(system: System, config: ComplexTransformConfig) -> Result[System, str]:
...     """Transform with deeply nested configuration."""
...     processing_mode = config.data_processing.time_series.frequency
...     system.name = f"{system.name}_{config.name}_{processing_mode}"
...     return Ok(system)

>>> # Usage with complex nested config
>>> config = ComplexTransformConfig(
...     name="advanced",
...     data_processing=DataProcessingConfig(
...         clean_outliers=True,
...         time_series=TimeSeriesConfig(frequency="daily", interpolate=True)
...     ),
...     output_format="json"
... )
>>> result = complex_transform(System(name="analysis"), config)
>>> result.unwrap().name
'analysis_advanced_daily'
```

#### 4. Configuration with Python 3.12 Type Parameters

```python doctest
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from rust_ok import Ok, Result

>>> class BaseTransformConfig(PluginConfig):
...     pass

>>> class ScaleConfig(BaseTransformConfig):
...     factor: float = 1.0

>>> class RotateConfig(BaseTransformConfig):
...     angle: float = 0.0

>>> @expose_plugin
... def generic_transform[C: BaseTransformConfig](
...     system: System,
...     config: C,
... ) -> Result[System, str]:
...     """Generic transform accepting constrained config types."""
...     system.name = f"{system.name}_transformed"
...     return Ok(system)

>>> scale_cfg = ScaleConfig(factor=2.5)
>>> result = generic_transform(System(name="grid"), scale_cfg)
>>> result.is_ok()
True
```

## Building a Plugin Registry

Here's a Python script that uses ast-grep to build a plugin registry:

```python
import json
import subprocess
from pathlib import Path
from typing import Any

def discover_plugins(plugin_dir: Path) -> dict[str, Any]:
    """Build a plugin registry using ast-grep."""

    registry = {}

    # Find all plugin classes
    result = subprocess.run([
        "ast-grep", "scan",
        "--inline-rules", """id: find-plugins
language: python
rule:
  kind: class_definition
  has:
    kind: argument_list
    has:
      kind: subscript
      pattern: Plugin[$CONFIG]
      stopBy: end
    stopBy: end""",
        "--json",
        str(plugin_dir)
    ], capture_output=True, text=True)

    if result.returncode != 0:
        return registry

    # Parse results
    for match in json.loads(result.stdout):
        plugin_name = match.get('name', 'Unknown')
        config_type = match.get('config_type', 'Unknown')
        file_path = match.get('file', '')

        # Find implemented hooks for this plugin
        hooks = []  # Would extract with another ast-grep call

        # Find required context fields
        required_ctx = ['config']  # Would extract with another ast-grep call

        registry[plugin_name] = {
            'config_type': config_type,
            'file': file_path,
            'hooks': hooks,
            'required_context': required_ctx,
        }

    return registry

# Usage
plugins = discover_plugins(Path('plugins/'))
print(json.dumps(plugins, indent=2))
```

## Example: Discovery JSON with Mixed Plugins

Here's what a complete plugin discovery result looks like with both class-based and function-based plugins:

```json
{
  "plugins": {
    "ReEDSParser": {
      "type": "class",
      "file": "src/plugins/reeds_parser.py",
      "line": 45,
      "class_name": "ReEDSParser",
      "config_type": "ReEDSConfig",
      "hooks": [
        "on_validate",
        "on_build"
      ],
      "required_context": [
        "config",
        "store"
      ],
      "config_schema": {
        "model_year": {
          "type": "int",
          "required": true,
          "description": "Target model year"
        },
        "scenario": {
          "type": "str",
          "required": false,
          "default": "base",
          "description": "Scenario name"
        },
        "input_folder": {
          "type": "str",
          "required": true,
          "description": "Path to input data"
        },
        "skip_buses": {
          "type": "bool",
          "required": false,
          "default": false,
          "description": "Skip bus components"
        }
      }
    },
    "PlexosExporter": {
      "type": "class",
      "file": "src/plugins/plexos_exporter.py",
      "line": 23,
      "class_name": "PlexosExporter",
      "config_type": "PlexosExportConfig",
      "hooks": [
        "on_validate",
        "on_export"
      ],
      "required_context": [
        "config",
        "system",
        "store"
      ],
      "config_schema": {
        "output_dir": {
          "type": "str",
          "required": true,
          "description": "Output directory path"
        },
        "compress": {
          "type": "bool",
          "required": false,
          "default": true,
          "description": "Compress output files"
        },
        "format": {
          "type": "str",
          "required": false,
          "default": "xml",
          "enum": ["xml", "json", "parquet"],
          "description": "Output format"
        },
        "export_timeseries": {
          "type": "object",
          "required": false,
          "description": "Time series export settings",
          "properties": {
            "enabled": {
              "type": "bool",
              "default": true,
              "description": "Enable time series export"
            },
            "frequency": {
              "type": "str",
              "default": "hourly",
              "enum": ["hourly", "daily", "monthly"],
              "description": "Export frequency"
            },
            "interpolate_missing": {
              "type": "bool",
              "default": false,
              "description": "Interpolate missing values"
            }
          }
        }
      }
    },
    "normalize_units": {
      "type": "function",
      "file": "src/plugins/transforms.py",
      "line": 87,
      "function_name": "normalize_units",
      "config_type": "NormalizeUnitsConfig",
      "decorator": "@expose_plugin",
      "config_schema": {
        "base_unit": {
          "type": "str",
          "required": true,
          "enum": ["MW", "kW", "W"],
          "description": "Base unit for normalization"
        },
        "tolerance": {
          "type": "float",
          "required": false,
          "default": 0.01,
          "minimum": 0.0,
          "maximum": 1.0,
          "description": "Tolerance threshold for unit matching"
        },
        "strict_mode": {
          "type": "bool",
          "required": false,
          "default": false,
          "description": "Fail on unit mismatch instead of warning"
        }
      }
    },
    "filter_by_threshold": {
      "type": "function",
      "file": "src/plugins/transforms.py",
      "line": 145,
      "function_name": "filter_by_threshold",
      "config_type": "ThresholdFilterConfig",
      "decorator": "@expose_plugin",
      "config_schema": {
        "threshold": {
          "type": "float",
          "required": true,
          "minimum": 0.0,
          "description": "Threshold value for filtering"
        },
        "operation": {
          "type": "str",
          "required": false,
          "default": "greater_than",
          "enum": ["greater_than", "less_than", "equal", "between"],
          "description": "Comparison operation"
        },
        "criteria": {
          "type": "object",
          "required": false,
          "description": "Filtering criteria",
          "properties": {
            "apply_to_components": {
              "type": "array",
              "items": {"type": "string"},
              "default": [],
              "description": "Component types to filter"
            },
            "match_all": {
              "type": "bool",
              "default": true,
              "description": "Match all criteria (AND) vs any (OR)"
            }
          }
        },
        "exclude_components": {
          "type": "array",
          "items": {"type": "string"},
          "default": [],
          "description": "Component names to exclude from filtering"
        }
      }
    }
  },
  "summary": {
    "total_plugins": 4,
    "class_based": 2,
    "function_based": 2,
    "config_types": 4,
    "total_hooks": 4,
    "implemented_hooks": [
      "on_validate",
      "on_build",
      "on_export"
    ]
  }
}
```

This JSON shows:

**Class-Based Plugins (2)**:
- `ReEDSParser`: Parser with config and hooks
- `PlexosExporter`: Exporter with nested config (export_timeseries object)

**Function-Based Plugins (2)**:
- `normalize_units`: Transform with simple config
- `filter_by_threshold`: Transform with nested criteria and exclude list

**Key Features**:
- Type field distinguishes class vs function plugins
- Function plugins have decorator field
- Nested objects shown as nested properties
- Enums and constraints (minimum, maximum, enum values)
- Array fields with items type
- Descriptions for all fields

## Integration with CLI

The discovery system enables auto-generated CLI help:

```
$ python -m cli plugins list

Discovered Plugins:
  ReEDSParser
    Config: ReEDSConfig
    Hooks: on_validate, on_build
    Requires: config, store
    Accepts stdin: No

  PlexosExporter
    Config: PlexosExportConfig
    Hooks: on_export
    Requires: config, system, store
    Accepts stdin: Yes

$ python -m cli run ReEDSParser --model-year 2030 --input-folder /data

$ python -m cli run PlexosExporter --output-dir /export < system.json
```
