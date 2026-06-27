(api-reference)=

# API Reference

Complete API documentation for all r2x-core classes and functions.

## System

```{eval-rst}
.. autoclass:: r2x_core.System
   :members:
   :undoc-members:
   :show-inheritance:
```

```{eval-rst}
.. automodule:: r2x_core.units
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:
```

## Data Management

```{eval-rst}
.. autoclass:: r2x_core.DataStore
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.DataReader
   :members:
```

```{eval-rst}
.. autopydantic_model:: r2x_core.DataFile
   :model-show-json: False
   :model-show-config-summary: False
   :model-show-validator-members: False
   :model-show-validator-summary: False
   :field-list-validators: False
```

```{eval-rst}
.. autoclass:: r2x_core.FileInfo
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.ReaderConfig
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.TabularProcessing
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.JSONProcessing
   :members:
   :no-index:
```

## Plugin Configuration

```{eval-rst}
.. autopydantic_model:: r2x_core.PluginConfig
   :model-show-json: False
   :model-show-config-summary: False
   :model-show-validator-members: False
   :model-show-validator-summary: False
   :field-list-validators: False
   :no-index:
```

## Plugin System

```{eval-rst}
.. autoclass:: r2x_core.Plugin
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.PluginContext
   :members:
   :show-inheritance:
   :no-index:
```

## File Types

```{eval-rst}
.. autoclass:: r2x_core.FileFormat
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.H5Format
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:
```

## Rules and Translation

```{eval-rst}
.. autoclass:: r2x_core.Rule
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.RuleFilter
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.RuleResult
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.TranslationResult
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autofunction:: r2x_core.apply_rules_to_context
```

```{eval-rst}
.. autofunction:: r2x_core.apply_single_rule
```

## Exceptions

```{eval-rst}
.. autoclass:: r2x_core.ValidationError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.ComponentCreationError
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.CLIError
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.PluginError
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.UpgradeError
   :members:
   :show-inheritance:
   :no-index:
```

## Versioning and Upgrades

```{eval-rst}
.. autoclass:: r2x_core.SemanticVersioningStrategy
   :members:
   :undoc-members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.GitVersioningStrategy
   :members:
   :undoc-members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.VersionReader
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.VersionStrategy
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.UpgradeStep
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.UpgradeType
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autofunction:: r2x_core.run_upgrade_step
```

## Utilities

```{eval-rst}
.. autofunction:: r2x_core.components_to_records
```

```{eval-rst}
.. autofunction:: r2x_core.export_components_to_csv
```

```{eval-rst}
.. autofunction:: r2x_core.create_component
```

```{eval-rst}
.. autofunction:: r2x_core.getter
```

```{eval-rst}
.. autofunction:: r2x_core.transfer_time_series_metadata
```

```{eval-rst}
.. autoclass:: r2x_core.time_series.TimeSeriesTransferResult
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autofunction:: r2x_core.utils.filter_valid_kwargs
```

```{eval-rst}
.. autofunction:: r2x_core.utils.validate_file_extension
```

## Results

```{eval-rst}
.. autoclass:: r2x_core.Result
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.Ok
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.Err
   :members:
   :show-inheritance:
   :no-index:
```

```{eval-rst}
.. autofunction:: r2x_core.is_ok
```

```{eval-rst}
.. autofunction:: r2x_core.is_err
```

## Data Processors

See {doc}`./processors` for complete processor documentation.
