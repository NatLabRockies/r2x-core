# Data and serialization contracts used by the tutorial

Use this page to choose the boundary to test; the generated [full API](/r2x-core/references/api/) supplies complete inherited members and configuration fields.
The [DataStore source](https://github.com/NatLabRockies/r2x-core/blob/0b904d7cc8e9dde1a87d849b1cd3298bbcf34a82/src/r2x_core/store.py) and [System source](https://github.com/NatLabRockies/r2x-core/blob/0b904d7cc8e9dde1a87d849b1cd3298bbcf34a82/src/r2x_core/system.py) define these contracts.

## File registration and reading

```python
DataStore(path: str | Path | None = None, *,
          reader: DataReader | None = None,
          upgrade_handler: Callable[..., Any] | None = None)
DataStore.add_data(data_files: Sequence[DataFile], *, overwrite: bool = False) -> None
DataStore.list_data() -> list[str]
DataStore.read_data(name: str, *, placeholders: dict[str, Any] | None = None) -> Any
```

`path=None` uses the current directory; an explicit root must already exist.
The optional reader is a `DataReader`; the optional upgrade handler is a callable used by upgrade-aware loading.
`add_data` registers definitions and rejects duplicate names unless overwriting is enabled.
`list_data` returns registered logical names in sorted order.
`read_data` returns the format-specific reader result, not always a DataFrame: the tutorial's CSV path returns a Polars lazy frame.
A missing root raises `FileNotFoundError`; an unknown logical name raises `KeyError`; parsing and processing failures propagate from the reader.
Use `relative_fpath` under the root, or `fpath` for an explicit file path.

The [CSV scenario](/r2x-core/tutorials/getting-started/) demonstrates registration, filtering, materialization with `collect()`, and component construction as separate operations.
See [processing specifications](/r2x-core/references/processors/) before combining column mappings, filtering, and reshaping.

## System serialization

```python
System.to_json(fname: Path | str | None = None, overwrite: bool = False,
               indent: int | None = None, data: Any = None) -> bytes | None
System.from_json(source: Path | str | bytes, /, *,
                 upgrade_handler: Callable[..., Any] | None = None,
                 **kwargs: Any) -> System
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
