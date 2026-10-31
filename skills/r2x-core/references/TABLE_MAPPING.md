# r2x-core Table Mapping Reference

Use this for named-table mappings, table operations, table backends, and
cross-boundary file/table scheduling. For `DataFile.proc_spec`, see
[DATA_STORE.md](./DATA_STORE.md). For parser construction, see
[INGESTION.md](./INGESTION.md).

## Contents

- [Public entry points](#public-entry-points)
- [Mapping schema](#mapping-schema)
- [Assemble tables](#assemble-tables)
- [Keep the schemas distinct](#keep-the-schemas-distinct)

## Public entry points

- `TableMappingRecord` describes one named output table.
- `TableMappingBackend` is the backend protocol. The built-in implementation is
  `PolarsTabularBackend` from `r2x_core.polars_adapter`.
- `DataReader.read_and_assemble_sources(...)` reads files and table mappings in
  one dependency-aware schedule.
- `DataReader.read_and_assemble_records(...)` accepts already loaded typed
  records and schedules them with file inputs.
- `assemble_tables(...)` loads a mapping file and assembles from decoded sources.
- `assemble_table_records(...)` assembles from supplied typed records.
- `build_system(..., table_mapping_path=...)` opts parser construction into
  table assembly; it selects the Polars backend when none is supplied.

The assembly functions and `TableMappingRecord` are exported from `r2x_core`.
`PolarsTabularBackend` is imported from `r2x_core.polars_adapter`.

## Mapping schema

A table mapping file is one JSON array of strict table records. Each record has
`name` and ordered `operations`, plus optional `source`, final `columns`
projection, and `materialize`. Each table starts from exactly one earlier
`source` or a first-position constructor. Source-free constructors are `rows`,
`concat`, `first_present`, and `first_nonempty`. Dependencies must be declared
before their consumers.

```json
[
  {
    "name": "selected_generators",
    "source": "generator_inputs",
    "operations": [
      {"operation": "filter", "column": "year", "comparison": "equals", "value": 2030}
    ],
    "columns": {
      "name": "generator_name",
      "capacity_mw": "capacity"
    }
  }
]
```

`columns` is a final output projection. A string selects a source column;
`{"value": "text"}` adds literal text; `{"value": scalar, "dtype": type}` adds
an explicitly typed scalar; and `{"optional_column": ..., "dtype": ...}` casts
a column if present or creates a typed null column if absent. Exact value forms
and types are defined
in the [table-mapping reference](https://natlabrockies.github.io/r2x-core/references/table-mapping/).

The current operation tags are `join`, `match_patterns`,
`match_source_patterns`, `filter`, `choose`, `group_by`, `unpivot`, `concat`,
`first_present`, `first_nonempty`, `multiply`, `add`, `divide`, `absolute`,
`casefold`, `datetime_part`, `concat_strings`, `split`, `rows`, `fill_null`,
`head`, `sort`, `unique`, `cast`, `object`, and `list`. Aggregation functions
are selected inside `group_by`, not used as standalone operations. Read the
schema reference before generating nontrivial mappings; operations are strict
and have no implicit join keys, deduplication, or business defaults.

## Assemble tables

For already decoded file sources and an on-disk mapping:

```python
from pathlib import Path

from r2x_core import DataReader
from r2x_core.polars_adapter import PolarsTabularBackend

sources = DataReader().read_and_assemble_sources(
    data_files,
    folder_path=Path("/data"),
    mapping_path=Path("config/table_mapping.json"),
    backend=PolarsTabularBackend(),
)
resource_rows = sources["selected_generators"]
```

For a stable typed snapshot or selected outputs, use
`assemble_table_records(sources, records, backend=..., table_names=...)`. Use
`assemble_tables(sources, mapping_path=..., backend=...)` when records are
loaded from a file. Both operate on decoded sources and return named
`TabularSource` values.

`read_and_assemble_sources` and `read_and_assemble_records` schedule file and
table dependencies before opening inputs. They reject unknown references,
forward dependencies, duplicate names, and cycles. Ordinary
`read_data_files(...)` remains declaration-ordered and does not assemble a
separate table-mapping file. Use the combined scheduler when table outputs feed
other table operations or conditional file inputs.

Optional physical inputs without a declared column schema are omitted when
absent. With declared columns, an absent input is represented by a typed
`TabularSource` with `SourceAvailability.ABSENT`, distinct from a present-empty
table. `first_present` selects a present empty table; `first_nonempty` skips
absent and empty tables. `materialize=True` eagerly snapshots the final
projected output in memory before dependent records run. It is not a persistent
cache.

## Keep the schemas distinct

- `DataFile.proc_spec` uses `TabularProcessing` or `JSONProcessing`, each with
  ordered `steps` tagged by `op`.
- A named-table mapping uses `TableMappingRecord.operations`, whose steps are
  tagged by `operation`, and a table-level final `columns` projection.
- `DataReader.read_data_files(...)` reads and processes configured `DataFile`
  records. It does not accept table-mapping `operations`.
- `DataReader.read_and_assemble_*` or `assemble_*` handles the separate
  table-mapping schema.

Do not translate an example from one schema to the other by renaming only
`steps` to `operations`; their operation names, fields, ordering contracts, and
outputs differ.
