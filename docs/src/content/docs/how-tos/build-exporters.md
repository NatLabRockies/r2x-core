---
title: "Export a system"
---

Use `System.to_json()` for an infrasys-compatible system artifact.
The output includes serialization metadata; model-specific target formats still need an exporter supplied by their model package.
Install the library as described in [install](/r2x-core/install/).
This checked example exports a generic named component and verifies an independent reload:

<span id="exporting-systems"></span>

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from infrasys import Component
>>> from r2x_core import System
>>> with TemporaryDirectory() as folder:
...     output = Path(folder) / "system.json"
...     system = System(name="example")
...     system.add_component(Component(name="Generator1"))
...     system.to_json(output)
...     assert output.is_file()
...     restored = System.from_json(output)
...     assert restored.name == "example"
...
>>> restored.name
'example'
>>> [component.name for component in restored.get_components(Component)]
['Generator1']
```

The round trip verifies that the exported system can be loaded.
The temporary directory is deleted when the example exits; choose a durable path for real outputs.
`to_json(fname, overwrite=False, indent=None, data=None)` rejects an existing output unless overwriting is explicitly enabled.
Keep the JSON entrypoint and any time-series sidecars together when transferring an artifact.
A class-based exporter can place this operation in `on_export()` and return `Ok(None)` on success.
See [api](/r2x-core/references/api/) for serialization options and [plugins](/r2x-core/references/plugins/) for lifecycle contracts.

<span id="see-also"></span>

Continue with the [plugin lifecycle contracts](/r2x-core/references/plugins/) and [API reference](/r2x-core/references/api/).
