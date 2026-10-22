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
DataReader(file_readers: Mapping[str, FileReader] | None = None)
DataReader.read_data_files(
    data_files: Iterable[DataFile],
    *,
    folder_path: Path,
    placeholders: Mapping[str, JSONValue] | None = None,
) -> DecodedSources
```

`DataStore` manages validated mapping configuration and upgrade handlers; it
does not read or process physical inputs. `DataReader.read_data_files` resolves
paths and optional inputs, selects the configured symbolic reader, and returns
named `DecodedSource` values. A reader may decode one physical file into several
source names. Results are reused only within that call, keyed by canonical path,
format, and reader options.

`build_system(config, /, *, name, readers=None, placeholders=None)` is the standard
configured construction operation. It validates parser instructions before
reading inputs, then executes component, time-series, and supplemental-attribute
instructions in declaration order. Each output is validated before attachment.
A later failure does not roll back outputs already attached.

A missing input may invoke the configured upgrade handler once and retry the
canonical read. `System.from_json` and serialized-system loading are separate
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
