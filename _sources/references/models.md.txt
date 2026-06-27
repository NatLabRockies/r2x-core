# Data Models

Core data models for file management, system representation, and configuration in R2X Core.

## Quick Reference

- {py:class}`~r2x_core.DataFile` - Configures a single data file with transformations
- {py:class}`~r2x_core.DataStore` - Container for managing multiple data files
- {py:class}`~r2x_core.FileInfo` - Metadata about a data file location and type
- {py:class}`~r2x_core.ReaderConfig` - Specifies how to read a file (reader type and options)
- {py:class}`~r2x_core.TabularProcessing` - Transformation pipeline for tabular (CSV, etc.) data
- {py:class}`~r2x_core.JSONProcessing` - Transformation pipeline for JSON data
- {py:class}`~r2x_core.PluginConfig` - Base class for plugin configuration
- {py:class}`~r2x_core.System` - Core system container for power system components

## API Documentation

For complete API documentation with method signatures and implementation details, see {doc}`./api`.

## See Also

- {doc}`../how-tos/read-data-files` - How to read data files
- {doc}`../how-tos/configure-data-files` - Configure data files
- {doc}`../explanations/data-management` - Understand the design philosophy
- {doc}`./system` - System model reference
