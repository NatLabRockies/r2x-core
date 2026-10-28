---
title: "Why file definitions are separate from loaded data"
---

<span id="data-management-design-philosophy"></span>

`DataFile` describes an input, `DataStore` manages mapping configuration, and
`DataReader` loads and processes named sources. A definition is not the loaded
data and registration is not proof that every file can be read.

## Separate configuration from I/O

A file root must exist when constructing a store. Reader errors occur when the
input is read; processing and component validation are later boundaries.
The separation lets a parser request only the inputs it needs.

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from r2x_core import DataFile, DataReader, TabularProcessing
>>> with TemporaryDirectory() as directory:
...     root = Path(directory)
...     _ = (root / "generators.csv").write_text("name,capacity_mw,status\nAlpha,100,active\nRetired,25,retired\n", encoding="utf-8")
...     processing = TabularProcessing(steps=[{"op": "filter_columns", "filter_by": {"status": "active"}}])
...     item = DataFile(name="generators", relative_fpath="generators.csv", proc_spec=processing)
...     sources = DataReader().read_data_files([item], folder_path=root)
...     records = sources["generators"].data.collect().to_dicts()
>>> # Expected: the source reader applies the configured filter.
>>> [record["name"] for record in records]
# ['Alpha']
>>> records
# [{'name': 'Alpha', 'capacity_mw': 100, 'status': 'active'}]
```

## Processing is a separate contract

The CSV source is paired with its Polars processor; `collect()` materializes
its rows. `TabularProcessing` describes operations such as filtering and
reshaping, while `ReaderConfig.options` holds reader-specific options. Keeping
these apart avoids mixing format selection with transformations.
The [processor reference](/r2x-core/references/processors/) specifies operation
order and constraints; [process file data](/r2x-core/how-tos/process-file-data/)
shows how to configure them.

## Validation does not imply availability

A valid configuration can still refer to unavailable or malformed input.
Diagnose the root path, registered logical name, physical input and processed
schema in that order. The [troubleshooting guide](/r2x-core/troubleshooting/)
provides checks for each boundary.
For a complete data-to-artifact journey, use the [CSV capacity scenario](/r2x-core/tutorials/getting-started/).

<span id="overview"></span>

<span id="configuration-driven-approach"></span>

<span id="reproducibility"></span>

<span id="flexibility-without-redeployment"></span>

<span id="separation-of-concerns"></span>

<span id="lazy-evaluation"></span>

<span id="why-lazy"></span>

<span id="example"></span>

<span id="composable-processing"></span>

<span id="processing-pipeline-order"></span>

<span id="configuration-validation"></span>

<span id="placeholders-and-runtime-parameterization"></span>

<span id="trade-offs-and-design-decisions"></span>

<span id="why-not-automatic-discovery"></span>

<span id="why-separate-reader-config-from-file-path"></span>

<span id="why-json-configuration"></span>

<span id="see-also"></span>
