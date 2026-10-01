# Processing File Data

Transform and filter tabular data during loading using {py:class}`~r2x_core.TabularProcessing`. This allows you to rename columns, drop unused fields, and filter rows without modifying the original files.

## Rename Columns

Use `column_mapping` to rename columns while loading:

```python doctest
>>> from pathlib import Path
>>> from r2x_core import DataFile, TabularProcessing
>>>
>>> data_file = DataFile(
...     name="data",
...     relative_fpath="data.csv",
...     proc_spec=TabularProcessing(column_mapping={"old_name": "new_name", "col1": "column_1"})
... )
>>> data_file.proc_spec.column_mapping
{'old_name': 'new_name', 'col1': 'column_1'}
```

## Drop Unwanted Columns

Use `drop_columns` to exclude columns from processing:

```python doctest
>>> from pathlib import Path
>>> from r2x_core import DataFile, TabularProcessing
>>>
>>> data_file = DataFile(
...     name="data",
...     relative_fpath="data.csv",
...     proc_spec=TabularProcessing(drop_columns=["unused_col", "temp_col"])
... )
>>> data_file.proc_spec.drop_columns
['unused_col', 'temp_col']
```

## Filter Data During Loading

Use `filter_by` to select specific rows based on column values:

```python doctest
>>> from pathlib import Path
>>> from r2x_core import DataFile, TabularProcessing
>>>
>>> # Filter by single value
>>> df = DataFile(
...     name="yearly_data",
...     relative_fpath="data.csv",
...     proc_spec=TabularProcessing(filter_by={"year": 2030})
... )
>>> df.proc_spec.filter_by
{'year': 2030}
>>>
>>> # Filter by multiple values
>>> df = DataFile(
...     name="regional_data",
...     relative_fpath="data.csv",
...     proc_spec=TabularProcessing(filter_by={"region": ["CA", "TX", "NY"]})
... )
>>> df.proc_spec.filter_by["region"]
['CA', 'TX', 'NY']
```

## Reshape, Rename, Cast, and Filter

With `unpivot_on`, `column_mapping`, `column_schema`, and `filter_by` apply after
the reshape. This supports wide year columns filtered by a runtime solve year:

```python doctest
>>> from r2x_core import DataFile, TabularProcessing
>>>
>>> processing = TabularProcessing(
...     unpivot_on=["2025", "2030"],
...     column_mapping={"variable": "year", "value": "capacity_mw"},
...     column_schema={"year": "int"},
...     filter_by={"year": "{solve_year}"},
... )
>>> processing.column_mapping
{'variable': 'year', 'value': 'capacity_mw'}
```

For a multi-row CSV/TSV header, configure `ReaderConfig(header_rows=2)`. Header
cells are joined with `header_separator` (default `|`). Use `split_column` to
turn a generated label such as `2025|NYISO_A` into `year` and `zone` columns.

## Split Columns

Use `SplitColumnSpec` to split a source column into named columns:

```python doctest
>>> from r2x_core import SplitColumnSpec
>>> split = SplitColumnSpec(separator="|", into=["year", "zone"])
>>> split.into
['year', 'zone']
```

## Preserve or Lowercase Input Case

Input case is preserved by default. Set `lowercase=True` when the mapping
expects lowercase column names and string values:

```python doctest
>>> from r2x_core import TabularProcessing
>>> processing = TabularProcessing(lowercase=True)
>>> processing.lowercase
True
```

## Normalize Formatted Numbers

Use `replace_values` for exact tokens, `strip_chars` for literal cleanup,
`column_schema` to cast, and `scale` for conversion factors. For example,
replace `-` with `0`, strip commas, currency symbols, and percent signs, cast to
float, then scale percentages by `0.01`.

## Placeholders in Paths

Placeholders can be embedded in `fpath`, `relative_fpath`, or `glob`, as well
as processing values. For example, `relative_fpath="{scenario}_loads.csv"`
resolves when `read_data(..., placeholders={"scenario": "Reference"})` is
called. Unknown placeholder names are errors.

## See Also

- {doc}`read-data-files` - Read processed data files
- {doc}`configure-data-files` - Configure data file settings
- {doc}`manage-datastores` - Manage multiple data files
- {py:class}`~r2x_core.TabularProcessing` - Tabular processing class
- {py:class}`~r2x_core.DataFile` - DataFile API reference
