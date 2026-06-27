# Attaching Time Series

Time series data represents values that change over time, such as load profiles, generation forecasts, or weather data. Use {py:class}`~r2x_core.FileInfo` to mark data files as containing time series and optionally add descriptive metadata.

## Mark a File as Time Series

Set the `is_timeseries` attribute to indicate that a {py:class}`~r2x_core.DataFile` contains time-varying data:

```python doctest
>>> from pathlib import Path
>>> from r2x_core import DataFile, FileInfo
>>>
>>> # Time series file (e.g., hourly load profiles)
>>> timeseries_file = DataFile(
...     name="generation_profiles",
...     relative_fpath="data/profiles.csv",
...     info=FileInfo(is_timeseries=True)
... )
>>> timeseries_file.info.is_timeseries
True
>>>
>>> # Non-time series file (e.g., generator static properties)
>>> component_file = DataFile(
...     name="generators",
...     relative_fpath="data/generators.csv",
...     info=FileInfo(is_timeseries=False)
... )
>>> component_file.info.is_timeseries
False
```

## Configure Time Series Files in a DataStore

Separate time series and static component data in a {py:class}`~r2x_core.DataStore` by marking each file appropriately with {py:class}`~r2x_core.FileInfo`:

```python doctest
>>> from pathlib import Path
>>> from r2x_core import DataFile, FileInfo
>>>
>>> # Create data file for time series (e.g., capacity factor profiles)
>>> profile_file = DataFile(
...     name="cf_profiles",
...     relative_fpath="inputs/profiles.h5",
...     info=FileInfo(is_timeseries=True),
... )
>>>
>>> # Create data file for static data (e.g., generator properties)
>>> gen_file = DataFile(
...     name="generators",
...     relative_fpath="inputs/generators.csv",
...     info=FileInfo(is_timeseries=False),
... )
>>>
>>> # Verify the time series flags
>>> profile_file.info.is_timeseries
True
>>> gen_file.info.is_timeseries
False
```

## Add Metadata to Time Series Files

Include descriptive information about the time series data using {py:class}`~r2x_core.FileInfo`:

```python doctest
>>> from pathlib import Path
>>> from r2x_core import DataFile, FileInfo
>>>
>>> # Create a documented time series file
>>> load_profiles = DataFile(
...     name="load_profiles",
...     relative_fpath="load_profiles.csv",
...     info=FileInfo(
...         description="Hourly load time series data",
...         is_timeseries=True
...     )
... )
>>>
>>> # Verify the metadata
>>> load_profiles.info.description
'Hourly load time series data'
>>> load_profiles.info.is_timeseries
True
```

## Transfer Time Series Metadata

Use {py:func}`~r2x_core.transfer_time_series_metadata` to transfer time series metadata from a source system to a target system:

```python doctest
>>> from r2x_core import transfer_time_series_metadata, PluginContext
>>> # transfer_time_series_metadata transfers metadata between systems
>>> # It requires both source_system and target_system in the context
>>> # See {doc}`../references/utils` for complete documentation
>>> transfer_time_series_metadata.__doc__[:50]
'Transfer time series metadata for target system.'
```

## See Also

- {doc}`manage-datastores` - Manage collections of files
- {doc}`read-data-files` - Read time series and static data
- {doc}`process-file-data` - Apply time series transformations
- {py:class}`~r2x_core.FileInfo` - File metadata class
- {py:class}`~r2x_core.DataStore` - DataStore API reference
- {py:func}`~r2x_core.transfer_time_series_metadata` - Transfer metadata function
