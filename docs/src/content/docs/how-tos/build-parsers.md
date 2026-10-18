---
title: "Build a parser"
---

<span id="parser-basics"></span>

Implement `on_build()` to read input data and return a populated `System`.
Install the library as described in [install](/r2x-core/install/).
The checked example below uses a temporary input file and verifies the resulting component:

<span id="working-with-systems"></span>

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from infrasys import Component
>>> from rust_ok import Ok, Result
>>> from r2x_core import DataFile, DataStore, Plugin, PluginConfig, PluginContext, System
>>> class Generator(Component):
...     capacity_mw: float
...
>>> class ParserConfig(PluginConfig):
...     folder: Path
...
>>> class Parser(Plugin[ParserConfig]):
...     def on_build(self) -> Result[System, str]:
...         store = DataStore(self.config.folder)
...         store.add_data([DataFile(name="generators", relative_fpath="generators.csv")])
...         system = System(name="parsed")
...         for row in store.read_data("generators").collect().iter_rows(named=True):
...             system.add_component(Generator(**row))
...         return Ok(system)
...
>>> with TemporaryDirectory() as folder:
...     path = Path(folder)
...     _ = (path / "generators.csv").write_text("name,capacity_mw\nGenerator1,100\n")
...     context = PluginContext(config=ParserConfig(folder=path))
...     result = Parser.from_context(context).run()
...     assert result.system is not None
...     generators = list(result.system.get_components(Generator))
...     assert len(generators) == 1
...     assert generators[0].capacity_mw == 100
...
>>> generators[0].name, generators[0].capacity_mw
('Generator1', 100.0)
```

The assertions verify that the input row became a component.
`Generator` is an example model defined here, not a built-in electrical component.
Use your model package's component classes and validate units when building a real parser.
Register the parser through [register plugins](/r2x-core/how-tos/register-plugins/) when it needs CLI discovery.

<span id="see-also"></span>

Continue with the [plugin lifecycle contracts](/r2x-core/references/plugins/) and [API reference](/r2x-core/references/api/).
