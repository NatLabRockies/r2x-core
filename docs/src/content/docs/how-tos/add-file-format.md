---
title: "Register an Application Format"
---

An application format does not need a core extension or whitelist change. Give it a symbolic name, implement `FileReader.read_file`, return typed
named sources, and pass the registration to `DataReader` or `build_system`.
JSON configuration selects the name and options but never an implementation
string.

```python doctest
>>> from r2x_core import DecodedSource, DecodedSources, FileReader, ReaderConfig
>>> DecodedSource.__name__, FileReader.__name__, ReaderConfig.__name__
# ('DecodedSource', 'FileReader', 'ReaderConfig')
```

`DecodedSources` maps names defined by the application to `DecodedSource` values. Use `TabularSource` with a paired `TabularProcessor` for a
native tabular payload, `DocumentSource` for supported JSON or XML documents,
and `ArraySource` for named arrays. A vendor payload can implement
`DecodedSource` directly. Pair processing with the payload through
`SourceProcessor`, rather than teaching core about each file format.

The source loader, named transformations, and construction workflow remain
shared. See [Custom readers and typed sources](/r2x-core/how-tos/custom-readers-and-backends/)
and the [runnable illustrative RAW example](https://github.com/NatLabRockies/r2x-core/tree/main/examples/psse-raw).
The example grammar is deliberately invented and is not PSS/E RAW compatibility.

Add a format to core only when it shares a reader and behavior with existing formats. In that case, follow the repository's contribution workflow,
add a real file fixture and tests, and document reader options. Output purpose
still comes from the configured component, time series, or supplemental
attribute instruction, not from the file extension.
