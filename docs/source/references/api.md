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

A file-mapping document contains `files` (physical `DataFile` inputs),
`sources` (named runtime frames), and `tables` (prepared-table definitions).
Runtime sources can generate calendars, load typed config records, select the
first present configured input, or project public System fields and time series.
A prepared table can start from a physical file, runtime source, another table,
or declared named frame input. Its joins use the same sources. `DataStore.prepare_table(name,
inputs=...)` supplies in-memory frames to the same executor used by `read_table`.
Many-to-one joins reject null keys and duplicate right keys by default. Backward
`asof` joins preserve left row order, leave permitted null left keys unmatched,
and reject duplicate temporal keys. Each join configures missing-source behavior
as `error` (default), `skip`, or `null`. Physical-file optionality does not
weaken that per-join contract. Shared sources are materialized once within one
`prepare_tables` request and are read again on the next request. Removing a
physical file referenced by a first-present source is rejected. Prepared-table
errors retain table and source names.

Typed assignment sources are public processing models:

```python doctest
>>> from r2x_core import AsOfJoinSpec, ColumnAssignmentSource, LiteralAssignmentSource
>>> AsOfJoinSpec(left_on="year", right_on="year").allow_exact_matches
False
>>> ColumnAssignmentSource(kind="column", column="fom_cost").column
'fom_cost'
>>> LiteralAssignmentSource(kind="literal", value=None).value is None
True
```

```{eval-rst}
.. autoclass:: r2x_core.FileMapping
   :members:

.. autoclass:: r2x_core.PreparedTable
   :members:

.. autoclass:: r2x_core.TableJoin
   :members:

.. autoclass:: r2x_core.AsOfJoinSpec
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
