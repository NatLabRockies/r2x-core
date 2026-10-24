---
title: "Attach Time Series"
---

Time-series output is selected by a `time_series` instruction in
`parser_rules.json`, not by a file extension. A CSV, JSON document, HDF5 array,
or application-defined source can supply samples if its decoded source exposes
the configured fields. The standard `build_system` operation constructs
`SingleTimeSeries` values and attaches them through the public infrasys API.

## Attaching time series

A `TimeSeriesInstruction` names its source, sample-value field, time axis,
metadata, units, and component owners. Owners use component type and name.
`name_field` groups long-form rows so each owner receives only its own samples;
literal `names` intentionally shares one sample vector across those owners.
`metadata_columns` maps row fields to infrasys feature names and partitions samples
by both resolved owners and the mapped values. Each mapped value must be an exact
built-in string, boolean, integer, or finite float. Missing fields, nulls,
non-finite numbers, and non-scalar values fail. Boolean and integer values are
distinct. Literal and mapped feature names cannot overlap. `context`, `self`, and
`time_series` are reserved infrasys arguments.

```python doctest
>>> from r2x_core import ColumnTimeAxis, ComponentOwner, TimeSeriesInstruction
>>> load = TimeSeriesInstruction(
...     kind="time_series",
...     source="loads",
...     name="load_mw",
...     values="load",
...     time_axis=ColumnTimeAxis(kind="column", column="timestamp"),
...     units="MW",
...     metadata={"scenario": "base", "enabled": False},
...     metadata_columns={"weather_year": "weather_year"},
...     owners=[ComponentOwner(component_type="Bus", name_field="bus_name")],
... )
>>> load.owners[0].name_field
'bus_name'
>>> load.metadata["enabled"]
False
>>> load.metadata_columns["weather_year"]
'weather_year'
```

A regular axis uses `initial_timestamp` and a positive
`resolution_seconds`. A column axis must be strictly increasing and regular.
Core preserves source order and does not sort or coerce timestamps.
SingleTimeSeries requires at least two samples. By default, an empty source is
an error. Set `skip_if_empty=true` for an explicitly optional series that should
be absent when its source has no rows. Nonempty sources with missing fields,
invalid axes, unknown owners, or infrasys validation errors still fail before
that output is attached. Explicit null values are not treated as absent fields.

Units are passed as a `ureg.Quantity` when the series is created, so
`TimeSeriesMetadata.units` records the unit. Other instruction metadata is
stored as infrasys features, including `False` and `0` values.

## Keep system translation separate

`build_system` executes the three configured ingestion outputs: components,
time series, and supplemental attributes. System-to-System translation remains
a separate workflow and retains its dependency ordering, time-series transfer,
and replacement behavior.

```python doctest
>>> from r2x_core import replace_single_time_series, transfer_time_series_metadata
>>> replace_single_time_series.__doc__.splitlines()[0]
'Replace exactly one time series association without removing shared data.'
>>> transfer_time_series_metadata.__doc__.splitlines()[0]
'Transfer time series metadata for target system.'
```

See [Build a parser](/r2x-core/how-tos/build-parsers/),
[Read data files](/r2x-core/how-tos/read-data-files/), and the
[time-series transfer API](/r2x-core/references/api/).
