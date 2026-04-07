# Read Data Files

Load and process data files using `DataReader` and `DataFile` configurations.

## Create a DataFile Configuration

A {py:class}`~r2x_core.DataFile` specifies where and how to read a data file:

```python doctest
>>> from r2x_core import DataFile
>>>
>>> # Create a configuration with a relative path
>>> data_file = DataFile(name="generators", relative_fpath="data/generators.csv")
>>> data_file.name
'generators'
>>> data_file.relative_fpath
'data/generators.csv'
```

## Supported File Formats

{py:class}`~r2x_core.DataReader` supports multiple file formats:

```python doctest
>>> from r2x_core import DataReader
>>>
>>> reader = DataReader()
>>> formats = sorted(reader.get_supported_file_types())
>>> formats
['.csv', '.h5', '.hdf5', '.json', '.parquet', '.tsv', '.xml']
```

## Apply Processing Rules While Reading

Use {py:class}`~r2x_core.TabularProcessing` to filter, rename, and transform data during loading:

```python doctest
>>> from r2x_core import DataFile, TabularProcessing
>>>
>>> # Configure transformations
>>> processing = TabularProcessing(
...     filter_by={"region": "North"},
...     column_mapping={"value": "amount"},
...     drop_columns=["temp_id"]
... )
>>>
>>> # Create data file with transformations
>>> data_file = DataFile(
...     name="north_data",
...     relative_fpath="data/regional_data.csv",
...     proc_spec=processing
... )
>>> data_file.proc_spec.column_mapping
{'value': 'amount'}
>>> data_file.proc_spec.filter_by
{'region': 'North'}
```

## Read Data Files

Use {py:class}`~r2x_core.DataReader` to load a configured data file:

```python doctest
>>> import tempfile
>>> from pathlib import Path
>>> from r2x_core import DataReader, DataFile
>>>
>>> # Create a temporary CSV file with sample data
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     # Write sample CSV file
...     csv_file = Path(tmpdir) / "generators.csv"
...     csv_content = "id,name,capacity\n1,Gen1,500\n2,Gen2,300\n3,Gen3,400\n"
...     _ = csv_file.write_text(csv_content)
...
...     # Read using DataReader
...     data_file = DataFile(name="generators", relative_fpath="generators.csv")
...     reader = DataReader()
...     df = reader.read_data_file(data_file, folder_path=Path(tmpdir))
...
...     # Collect and verify the result
...     result = df.collect()
...     print("Columns:", result.columns)
...     print("Rows:", result.height)
...     print("First row:", result.row(0))
Columns: ['id', 'name', 'capacity']
Rows: 3
First row: (1, 'Gen1', 500)
```

## See Also

- {doc}`configure-data-files` - Configure file transformations in detail
- {doc}`configure-data-settings` - Manage global data configuration
- {doc}`manage-datastores` - Work with collections of data files
