# Data and serialization contracts

This reference specifies input configuration, typed source loading, configured
construction, and system serialization. The generated [full API](/r2x-core/references/api/)
supplies inherited members and model fields.

## File mapping and typed sources

```python
DataStore(path: str | Path | None = None)
DataStore.add_data(data_files: Sequence[DataFile], *, overwrite: bool = False) -> None
DataStore.load_file_mapping(mapping_path: Path) -> None
DataStore.list_data() -> list[str]
DataReader(
    *,
    file_readers: Mapping[str, FileReader] | None = None,
    step_handlers: Mapping[str, MappingStepHandler[Any, Any, Any]] | None = None,
)
DataReader.read_data_files(
    data_files: Iterable[DataFile],
    *,
    folder_path: Path,
    placeholders: Mapping[str, JSONValue] | None = None,
    initial_sources: Mapping[str, DecodedSource] | None = None,
) -> DecodedSources
DataReader.read_and_assemble_sources(
    data_files: Iterable[DataFile], /, *, folder_path: Path, mapping_path: Path,
    backend: TableMappingBackend, placeholders: Mapping[str, JSONValue] | None = None,
    initial_sources: Mapping[str, DecodedSource] | None = None,
    initial_tables: Mapping[str, TabularSource] | None = None,
) -> DecodedSources
DataReader.read_and_assemble_records(
    data_files: Iterable[DataFile], records: Sequence[TableMappingRecord], /, *,
    folder_path: Path, backend: TableMappingBackend,
    placeholders: Mapping[str, JSONValue] | None = None,
    initial_sources: Mapping[str, DecodedSource] | None = None,
    initial_tables: Mapping[str, TabularSource] | None = None,
) -> DecodedSources
FileReader.read_file(
    format_name: str,
    /,
    *,
    file_path: Path,
    reader_config: ReaderConfig,
) -> DecodedSources
```

`DataStore` manages validated mapping configuration and upgrade handlers; it
does not read or process physical inputs. `DataReader.read_data_files` resolves
paths and optional inputs, selects the configured symbolic reader, and returns
named `DecodedSource` values. A reader may decode one physical file into several
source names. Results are reused only within that call, keyed by resolved path,
format, reader options, and native column declarations. `initial_sources` seeds ordered processing with
already decoded values. The input mapping is copied, seed values remain in the
returned mapping, and configured name collisions raise `ValueError`. Named-source,
join, concat, and conditional-input dependencies are validated before any input
is read. Application `step_handlers` are shared by the built-in Polars file
reader and inline tables.

A `DataFile` may also define an `InlineTable` with a raw schema and exact-shape
records, or a `SourceSelection` over prior names. `first_present` preserves an
available empty source; `first_nonempty` skips empty sources. A typed inline
fallback is explicit. Missing optional physical inputs without a declared
`columns` schema are omitted, while present-empty inputs remain named and
malformed inputs fail. A missing optional input with declared native columns is
exposed as a typed, zero-row `TabularSource` marked absent. It is distinct from a
present-empty source. Inline schemas and physical column declarations apply
before their processing spec, and placeholders are resolved before records are
validated.

A physical `DataFile.columns` value is an optional list of records with native
`name`, `dtype` (`bool`, `int64`, `float64`, `string`, or `datetime`), optional
`rename`, and optional strict boolean `required` (default `true`). `DataReader`
passes the declarations to readers in `reader_config.columns`, which is empty
when no columns are declared. CSV readers use declared dtypes during decoding.
Present columns are strictly cast before
renaming. Floating-point columns declared as `int64` are rejected rather than
truncated. A missing required name in a present file is an error. A missing
`required: false` column becomes a typed null field while preserving rows.
Other present columns remain available with their reader-provided types.
Renamed names must be unique. For an absent optional input, declarations
provide its complete known schema and the source is marked absent. No rows are
fabricated and no schema is inferred from a missing file.

For example, declare the native columns of an optional CSV before reading it.
When the file is absent, the returned source retains its renamed fields and is
marked absent instead of being treated as a present, empty file:

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from r2x_core import DataFile, DataReader, InputColumn, SourceAvailability
>>> with TemporaryDirectory() as folder:
...     file = DataFile(
...         name="generation", relative_fpath="generation.csv",
...         info={"requirement": "optional"},
...         columns=[
...             InputColumn(name="t", dtype="int64", rename="year"),
...             InputColumn(name="mw", dtype="float64", required=False),
...         ],
...     )
...     source = DataReader().read_data_files([file], folder_path=Path(folder))["generation"]
>>> source.availability is SourceAvailability.ABSENT
True
>>> source.fields()
['year', 'mw']
>>> list(source.iter_rows())
[]
```

An optional physical input may declare `required_when` with the name of an
already available tabular source and a typed expression predicate. The input is
required when any source row matches. A true predicate preserves the original
missing-file or missing-group error. A false predicate allows an absent input,
but does not hide malformed present data. `read_data_files` requires the
predicate source to be declared before the conditional input.

`read_and_assemble_sources` is the opt-in cross-boundary form. It loads and
validates one table-mapping snapshot, resolves file and table source references,
rejects unknown references and cycles before opening inputs, then schedules the
graph in deterministic dependency order. File-to-file and table-to-table
references retain their declaration-order rules. Cross-boundary dependencies
can interleave file reads and table assembly, so an assembled table can gate a
conditional input. Ready file batches share one decode cache across the whole
schedule. The ordinary `read_data_files` API remains declaration ordered and
single phase.

Use `initial_sources` for decoded file or external sources and `initial_tables`
for explicitly preassembled table outputs. Initial tables must name declared
table records, cannot collide with file inputs, and their mapping declarations
are still checked for unknown sources and output collisions. The supplied table
rows are reused without rerunning their record. `read_and_assemble_records`
accepts an already-loaded sequence of typed records and is useful when the
configuration snapshot must be held constant across input-upgrade retries.
Missing table-mapping configuration is raised before `build_system` enters its
missing-input upgrade retry. Only a missing configured input can trigger that
retry.

`build_system(config, /, *, name, input_folder=None, readers=None, step_handlers=None, table_mapping_path=None, table_mapping_backend=None, placeholders=None, system_options=None)` is the standard configured construction operation. Configuration assets are read from `config.config_path`; physical inputs are resolved from `input_folder` (or the current working directory when omitted). `table_mapping_path` explicitly opts into named-table assembly between input decoding and parser instructions. `system_options` are passed to `System`. It validates parser instructions before reading inputs, then delegates output construction to the same engine used by `build_system_from_sources`.

```python
build_system_from_sources(
    sources: DecodedSources,
    /,
    *,
    config: PluginConfig,
    instructions: Sequence[ParserInstruction],
    name: str,
    system_options: Mapping[str, object] | None = None,
) -> System
```

The source-based operation executes component, time-series, and supplemental-
attribute instructions in declaration order. It performs no configuration or
input-file I/O, while still resolving models through `config.models`. Each output
is validated before attachment. Missing sources, fields, references, invalid
models, or invalid time-series metadata and axes raise their validation errors.
A later failure does not roll back outputs already attached.

A missing input may invoke the configured `DataStore` upgrade handler once and
retry the configured read. This handler receives keyword-only `store` and `ctx`
and succeeds with `None` or `Ok(None)`; `Err(error)` is a failure. Invalid
success values raise `TypeError` before the coordinator is marked complete.
`System.from_json` migration hooks and serialized-system loading are separate
from file ingestion. System-to-System translation also remains a separate
rule-driven workflow with dependency ordering and time-series transfer and
replacement.

See [Read data files](/r2x-core/how-tos/read-data-files/),
[Build a parser](/r2x-core/how-tos/build-parsers/), and the
[processor reference](/r2x-core/references/processors/).

## System serialization

### Write a system

{py:meth}`System.to_json <r2x_core.System.to_json>` serializes a {py:class}`~r2x_core.System`.
[Implementation](https://github.com/NatLabRockies/r2x-core/blob/7eb201999706103b4ea965aeb4b6e42d4801703f/src/r2x_core/system.py#L251-L321).
The displayed instance signature omits `self`.

```python
System.to_json(
    fname: Path | str | None = None,
    overwrite: bool = False,
    indent: int | None = None,
    data: Any = None,
) -> bytes | None
```

### Reload a system

{py:meth}`System.from_json <r2x_core.System.from_json>` returns a {py:class}`~r2x_core.System`.
[Implementation](https://github.com/NatLabRockies/r2x-core/blob/7eb201999706103b4ea965aeb4b6e42d4801703f/src/r2x_core/system.py#L323-L386).
`source` is positional-only; `upgrade_handler` is keyword-only.

```python
System.from_json(
    source: Path | str | bytes,
    /,
    *,
    upgrade_handler: Callable[..., Any] | None = None,
    **kwargs: Any,
) -> System
```

With a filename, `to_json` writes through the infrasys file serializer and rejects existing output unless `overwrite=True`.
Without a filename, core returns serialized bytes backed by cache storage; the caller is responsible for transmitting those bytes.
It does not itself print them to stdout.
The filename form is the durable boundary used by the tutorial.
`indent` and `data` are optional serialization arguments; a loading `upgrade_handler` is an optional callable.

`from_json` returns a new `System`; it needs the referenced storage and importable component classes.
File lookup, JSON decoding, schema, and class-import failures can prevent a reload.
An artifact with valid JSON syntax is not necessarily portable by itself.
Preserve the companion storage directory, keep model packages compatible, and test a fresh-process load.

## Lifecycle execution

```python
Plugin.from_context(ctx: PluginContext[ConfigT]) -> Plugin[ConfigT]
Plugin.run(*, ctx: PluginContext[ConfigT] | None = None) -> PluginContext[ConfigT]
```

`from_context` binds shared state to an instance.
`run` optionally replaces that context, invokes implemented hooks in order, and returns the final context.
A hook returning `Err` becomes `PluginError`; other hook exceptions propagate.
There is no automatic rollback of earlier state or filesystem changes.
See [hook order and context outputs](/r2x-core/references/plugins/).
