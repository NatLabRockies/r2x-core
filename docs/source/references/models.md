# Data Models

Core models for configured input sources, three ingestion outputs, plugin settings, and Systems.

## Quick Reference

- {py:class}`~r2x_core.DataFile` - Configures a physical, named, selected, or inline source
- {py:class}`~r2x_core.InlineTable` - Defines typed configuration-owned records
- {py:class}`~r2x_core.SourceSelection` - Selects ordered sources by presence or nonemptiness
- {py:class}`~r2x_core.ReaderConfig` - Selects a symbolic reader and validates its options
- {py:class}`~r2x_core.DataStore` - Holds file-mapping configuration and upgrade handlers
- {py:class}`~r2x_core.DecodedSource` - Typed named data with field access and paired processing
- {py:class}`~r2x_core.ComponentInstruction` - Builds validated components from a source
- {py:class}`~r2x_core.TimeSeriesInstruction` - Attaches sample data to named components
- {py:class}`~r2x_core.SupplementalAttributeInstruction` - Attaches supplemental model data
- {py:class}`~r2x_core.TabularProcessing` - Ordered tabular transformation steps
- {py:class}`~r2x_core.JSONProcessing` - Ordered JSON transformation steps
- {py:class}`~r2x_core.PluginConfig` - Registers app models and locates configuration assets
- {py:class}`~r2x_core.System` - Core System container for power-system components

## API Documentation

For complete API documentation with method signatures and implementation details, see [api](/r2x-core/references/api/).

## See Also

- [read data files](/r2x-core/how-tos/read-data-files/) - Load named typed sources with `DataReader`
- [build parsers](/r2x-core/how-tos/build-parsers/) - Configure the three standard output instructions
- [configure data files](/r2x-core/how-tos/configure-data-files/) - Configure paths, reader options, and transformations
- [data management](/r2x-core/explanations/data-management/) - Understand the design philosophy
- [system](/r2x-core/references/system/) - System model reference
