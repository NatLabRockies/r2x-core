---
title: "Inspect plugin contracts and discovery"
---

<span id="plugin-discovery"></span>

A plugin must be installed and registered before the CLI can discover it.
Core defines configuration and lifecycle contracts; the Rust `r2x` executable
owns installed-package discovery and generated command help.
This tutorial first inspects a complete class without requiring external model data.

## Inspect a complete plugin

```python doctest
>>> import inspect
>>> from r2x_core import Plugin, PluginConfig, PluginContext, System
>>> from rust_ok import Ok, Result
>>> class DemoConfig(PluginConfig):
...     scenario: str = "reference"
>>> class BuildDemo(Plugin[DemoConfig]):
...     def on_build(self) -> Result[System, str]:
...         return Ok(System(name=self.config.scenario))
>>> plugin = BuildDemo.from_context(PluginContext(config=DemoConfig()))
>>> # Expected: this class implements a build hook, not a hidden parser registry.
>>> sorted(name for name, value in vars(BuildDemo).items() if name.startswith("on_") and callable(value))
['on_build']
>>> list(inspect.signature(BuildDemo.on_build).parameters)
['self']
>>> DemoConfig.model_json_schema()["properties"]["scenario"]["default"]
'reference'
>>> plugin.run().system.name
'reference'
```

The hook list and schema above come from the actual class and configuration,
not a hand-written catalog claiming ReEDS or PLEXOS behavior.
A real parser that reads files is demonstrated in [Build a parser](/r2x-core/how-tos/build-parsers/).

<span id="4-generic-configuration-types"></span>

## Inspect a Python 3.12 generic transform

This example uses PEP 695 type parameters and requires Python 3.12 or newer.
The `... def` line is valid here: it continues the statement started by
`>>> @expose_plugin`. An undecorated top-level definition would start with `>>> def`.
The type parameter bound supports static checking; it is not a replacement for
runtime validation of plugin configuration.

```python doctest requires-python=3.12
>>> from r2x_core import expose_plugin, PluginConfig, System
>>> from rust_ok import Ok, Result

>>> class BaseTransformConfig(PluginConfig):
...     pass

>>> class ScaleConfig(BaseTransformConfig):
...     factor: float = 1.0

>>> class RotateConfig(BaseTransformConfig):
...     angle: float = 0.0

>>> @expose_plugin
... def generic_transform[C: BaseTransformConfig](
...     system: System,
...     config: C,
... ) -> Result[System, str]:
...     """Generic transform accepting constrained config types."""
...     system.name = f"{system.name}_transformed"
...     return Ok(system)

>>> scale_cfg = ScaleConfig(factor=2.5)
>>> result = generic_transform(System(name="grid"), scale_cfg)
>>> # Expected: the typed transform executed and changed the system name.
>>> result.unwrap().name
'grid_transformed'
```

## Register an installable package

For a class parser, the package declares its module and class in `r2x.parsers`.
For an exposed function transform, use `r2x.transforms`.
Names in these entry points are the CLI references; Python class names are not
automatically executable commands.
The [complete CLI fixture package](https://natlabrockies.github.io/r2x-cli/getting-started/)
contains actual package metadata and can be installed without licensed model data.

<span id="integration-with-cli"></span>

## Inspect installed references with the Rust CLI

After installing that fixture with the CLI tutorial, these commands inspect its
real `create` and `scale` references:

```bash
r2x list r2x-tutorial
r2x run create --help
r2x run scale --help
```

There is no `plugins list` subcommand or Python-module CLI invocation.
If discovery differs, use [CLI troubleshooting](https://natlabrockies.github.io/r2x-cli/troubleshooting/).
The [function-plugin guide](/r2x-core/how-tos/create-function-plugins/) explains
configuration and callable contracts with checked examples.

<span id="discovery-information"></span>

<span id="example-discovering-reedsparser"></span>

<span id="programmatic-discovery"></span>

<span id="using-plugin-introspection"></span>

<span id="detecting-capabilities"></span>

<span id="detecting-required-context"></span>

<span id="ast-grep-rules-for-discovery"></span>

<span id="rule-1-find-plugin-classes"></span>

<span id="rule-2-find-implemented-hooks"></span>

<span id="rule-3-find-config-classes"></span>

<span id="rule-4-find-required-context-properties"></span>

<span id="function-based-plugins-with-expose_plugin"></span>

<span id="basic-function-plugin"></span>

<span id="function-plugin-with-nested-models"></span>

<span id="multiple-configuration-ways"></span>

<span id="1-simple-configuration"></span>

<span id="2-configuration-with-validation"></span>

<span id="3-configuration-with-complex-nested-structure"></span>

<span id="4-configuration-with-python-312-type-parameters"></span>

<span id="building-a-plugin-registry"></span>

<span id="example-discovery-json-with-mixed-plugins"></span>

<span id="integration-with-the-rust-cli"></span>
