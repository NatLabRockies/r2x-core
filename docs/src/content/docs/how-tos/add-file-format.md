---
title: Add a file format to core
---

This is a source-development task for core contributors. It changes the format registry;
it does not register an installed translator plugin. Start with [development setup](/r2x-core/contributing/).

## Inspect the supported types

The current registry is defined in [type_vocabulary.py](https://github.com/NatLabRockies/r2x-core/blob/main/src/r2x_core/type_vocabulary.py) and exposed through [types.py](https://github.com/NatLabRockies/r2x-core/blob/main/src/r2x_core/types.py).
Use the [file type reference](/r2x-core/references/file-types/) to check whether the extension already has a supported type before adding one.

## Extend the registry and reader together

Add a `FileFormat` subclass with the appropriate `supports_timeseries` value, map its extensions in `EXTENSION_MAPPING`, and update `TableDataFormat` if the format is tabular.
These are edits to core's source definitions, not a public runtime registration API.
Implement the matching reading path in a format-specific adapter package, such as [xml_adapter/readers.py](https://github.com/NatLabRockies/r2x-core/blob/main/src/r2x_core/xml_adapter/readers.py).
A recognized extension alone does not make a file readable.

Check `DataFile`'s format-specific validation and processing constraints as well.
Do not declare time-series support merely because the file can contain numeric arrays;
the implemented reader and model workflow must support the required time-series representation.

## Verify the new format

Add a small actual fixture and tests covering extension selection, parsed values/schema,
processing compatibility and time-series acceptance or rejection.
Run the affected file-type, DataFile and reader tests using the contributor workflow.
Confirm the new format loads its expected records and that unsupported extensions and incompatible settings still fail.
Document supported extensions and constraints in the reference; put model-specific parsing instructions in the model package.

The existing contracts stay at [File Types API Reference](/r2x-core/references/file-types/).
