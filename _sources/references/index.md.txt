# Reference

R2X Core provides data file management, plugin configuration, and system management classes:

## Core Classes

- {py:class}`~r2x_core.System` - Core system container
- {py:class}`~r2x_core.DataStore` - Data file storage
- {py:class}`~r2x_core.DataReader` - Data reading utility
- {py:class}`~r2x_core.DataFile` - Data file configuration
- {py:class}`~r2x_core.FileInfo` - Data file metadata
- {py:class}`~r2x_core.ReaderConfig` - File reader configuration
- {py:class}`~r2x_core.TabularProcessing` - Tabular processing pipeline
- {py:class}`~r2x_core.JSONProcessing` - JSON processing pipeline
- {py:class}`~r2x_core.PluginConfig` - Plugin configuration
- {py:class}`~r2x_core.Plugin` - Plugin base class
- {py:class}`~r2x_core.PluginContext` - Plugin execution context
- {py:class}`~r2x_core.FileFormat` - File format enum
- {py:class}`~r2x_core.H5Format` - HDF5 file format enum

## Rules and Translation

- {py:class}`~r2x_core.Rule` - Rule definition and validation
- {py:class}`~r2x_core.RuleFilter` - Component filtering predicates
- {py:class}`~r2x_core.RuleResult` - Per-rule results
- {py:class}`~r2x_core.TranslationResult` - Translation result summary
- {py:func}`~r2x_core.apply_rules_to_context` - Execute all rules in a context
- {py:func}`~r2x_core.apply_single_rule` - Apply one rule to components

## Utilities

- {py:func}`~r2x_core.components_to_records` - Export components as records
- {py:func}`~r2x_core.export_components_to_csv` - Export components to CSV
- {py:func}`~r2x_core.create_component` - Create and validate components
- {py:func}`~r2x_core.getter` - Register getter functions
- {py:func}`~r2x_core.transfer_time_series_metadata` - Transfer time series metadata

## Versioning and Upgrades

- {py:class}`~r2x_core.VersionStrategy` - Versioning protocol base class
- {py:class}`~r2x_core.SemanticVersioningStrategy` - Semantic versioning
- {py:class}`~r2x_core.GitVersioningStrategy` - Git-based versioning
- {py:class}`~r2x_core.UpgradeStep` - Upgrade step definition
- {py:class}`~r2x_core.UpgradeType` - Upgrade type enum
- {py:func}`~r2x_core.run_upgrade_step` - Execute a single upgrade step
- {py:class}`~r2x_core.VersionReader` - Version detection utility

For detailed API documentation with examples and method signatures, see the [Complete API Documentation](./api.md).

## Documentation Coverage

```{eval-rst}
.. report:doc-coverage::
   :packageid: src
```

```{toctree}
:maxdepth: 2
:hidden:

api
system
units
parser
exporter
plugins
versioning
upgrader
processors
utils
exceptions
file-formats
file-types
models
results
```
