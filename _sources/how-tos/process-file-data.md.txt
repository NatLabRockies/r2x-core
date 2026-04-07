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

## See Also

- {doc}`read-data-files` - Read processed data files
- {doc}`configure-data-files` - Configure data file settings
- {doc}`manage-datastores` - Manage multiple data files
- {py:class}`~r2x_core.TabularProcessing` - Tabular processing class
- {py:class}`~r2x_core.DataFile` - DataFile API reference
