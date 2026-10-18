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
.. autoclass:: r2x_core.SafeDivideSpec
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
.. autoclass:: r2x_core.PluginConfigAsset
   :members:

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

## Prepared Tables

A file-mapping document contains a `files` list of physical `DataFile` inputs
and a `tables` list of named prepared-table definitions. Prepared tables use
left many-to-one joins, reject null keys and duplicate right keys by default,
and can apply `TabularProcessing` after joining. Optional missing sources are
skipped. Prepared-table errors retain the table and source names.

```{eval-rst}
.. autoclass:: r2x_core.FileMapping
   :members:

.. autoclass:: r2x_core.PreparedTable
   :members:

.. autoclass:: r2x_core.TableJoin
   :members:

.. autoclass:: r2x_core.SelectFirst
   :members:

.. autoclass:: r2x_core.PreparedTableError
   :members:
```

## Rules and Batch Construction

`Rule` and `RuleMapping` share the same field mapping, getter, default, filter,
validation, and output-construction contract. A `Rule` adds a typed component or
dataset source. `RulePlan` resolves named mappings, target models, and ordered
stages before execution. `apply_mapping_records` runs computed rows through the
same construction and attachment path using either a fixed mapping or an
explicit keyed selection. A computed batch validates every row before
attachment; if insertion later fails, its error reports completed output groups
and those earlier groups remain attached.

```{eval-rst}
.. autoclass:: r2x_core.RuleMapping
   :members:

.. autoclass:: r2x_core.MappingSelection
   :members:

.. autoclass:: r2x_core.FixedMappingRoute
   :members:

.. autoclass:: r2x_core.SelectedMappingRoute
   :members:

.. autoclass:: r2x_core.RulePlan
   :members:

.. autofunction:: r2x_core.apply_mapping_records
```

## Rules and Translation

```{eval-rst}
.. autoclass:: r2x_core.Rule
   :members:
```

```{eval-rst}
.. autoclass:: r2x_core.RuleFilter
   :members:
```

## Getters

```{eval-rst}
.. autofunction:: r2x_core.getter
```

```python doctest
>>> from r2x_core import getter, resolve_getter
>>>
>>> @getter(name="api_resolve_getter")
... def api_resolve_getter(component, *, context):
...     _ = component
...     _ = context
...     return "resolved"
>>>
>>> resolved = resolve_getter("api_resolve_getter")
>>> resolved.is_ok()
True
>>> resolved.unwrap() is api_resolve_getter
True
```

```{eval-rst}
.. autofunction:: r2x_core.resolve_getter
```

```{eval-rst}
.. autofunction:: r2x_core.replace_single_time_series
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

```{eval-rst}
.. autofunction:: r2x_core.utils.export_components_to_csv
```

```{eval-rst}
.. autofunction:: r2x_core.utils.components_to_records
```

```{eval-rst}
.. autofunction:: r2x_core.utils.create_component
```

```{eval-rst}
.. autofunction:: r2x_core.utils.run_upgrade_step
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
