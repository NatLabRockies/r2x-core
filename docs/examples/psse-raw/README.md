# Illustrative RAW ingestion

This runnable example shows the production `build_system` API. The application
provides component models, a registered reader, and configuration. Core handles
source processing, component construction, and reference attachment.

The `.raw` file uses an invented CSV-like grammar. It is not a valid PSS/E RAW
case and does not claim PSS/E compatibility.

Run from the repository root with the existing environment:

```bash
UV_NO_SYNC=1 uv run --no-sync python docs/examples/psse-raw/run.py
```

The reader decodes `BUS` and `GEN` records into named tables. `file_mapping.json`
filters out-of-service generators, joins bus names, and derives generator names.
`parser_rules.json` builds validated model instances and resolves each generator's
bus by component type and name. Same-named fields such as `base_kv` need no
mapping, while explicit mappings take precedence.
