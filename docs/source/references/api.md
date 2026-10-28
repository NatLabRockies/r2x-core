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
   :exclude-members: unit, base, DEVICE_BASE, SYSTEM_BASE, NATURAL_UNITS
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
.. autoclass:: r2x_core.FileReader
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.H5Reader
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.H5PyFileReader
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.DecodedSource
   :members:
```

```{eval-rst}
.. autoclass:: r2x_core.ProcessingSource
   :members:
   :show-inheritance:
```

```{eval-rst}
.. autoclass:: r2x_core.SourceProcessor
   :members:
```

```{eval-rst}
.. autoclass:: r2x_core.TabularProcessor
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

## Configured construction

```{eval-rst}
.. autofunction:: r2x_core.build_system
```

```{eval-rst}
.. autoclass:: r2x_core.ComponentInstruction
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.ComponentReference
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.ComponentOwner
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.TimeSeriesInstruction
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.SupplementalAttributeInstruction
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.ColumnTimeAxis
   :members:
   :no-index:
```

```{eval-rst}
.. autoclass:: r2x_core.RegularTimeAxis
   :members:
   :no-index:
```

```python doctest
>>> from r2x_core import ArraySource
>>> from r2x_core import DecodedSource
>>> from r2x_core import DecodedSources
>>> from r2x_core import DocumentSource
>>> from r2x_core import ProcessingSource
>>> from r2x_core import SourceProcessor
>>> from r2x_core import TabularProcessor
>>> from r2x_core import TabularSource
>>> from r2x_core import ComponentInstruction
>>> from r2x_core import ComponentOwner
>>> from r2x_core import ComponentReference
>>> from r2x_core import TimeSeriesInstruction
>>> from r2x_core import SupplementalAttributeInstruction
>>> from r2x_core import ColumnTimeAxis
>>> from r2x_core import RegularTimeAxis
>>> from r2x_core import build_system
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
# True
>>> resolved.unwrap() is api_resolve_getter
# True
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
.. autofunction:: r2x_core.utils.filter_kwargs_for
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

See [processors](/r2x-core/references/processors/) for complete processor documentation.
