---
title: "Pass configuration and state through PluginContext"
---

`PluginContext` carries configuration, optional systems/store, rules and metadata
between lifecycle hooks. It is mutable shared state, not a copy of each system.
This example needs only the [installed library](/r2x-core/install/).

## Inspect the public fields

```python doctest
>>> from r2x_core import PluginConfig, PluginContext, System
>>> class ScenarioConfig(PluginConfig):
...     scenario: str = "reference"
>>> original = System(name="source")
>>> context = PluginContext(config=ScenarioConfig(), system=original)
>>> # Expected: configuration is available without accessing private context fields.
>>> context.config.scenario
'reference'
>>> context.system is original
True
>>> context.store is None, context.source_system is None, context.target_system is None
(True, True, True)
>>> context.rules
()
>>> context.metadata["stage"] = "validated"
>>> context.metadata["stage"]
'validated'
>>> context.system.name = "changed"
>>> # Expected: both references point to the same mutable system.
>>> original.name
'changed'
```

## Bind a plugin to that state

The following independent example supplies an existing system to a transform.
Inside a class plugin, use `self.config` and `self.system`, not `self._ctx`.

```python doctest
>>> from r2x_core import Plugin, PluginConfig, PluginContext, System
>>> from rust_ok import Ok, Result
>>> class RenameConfig(PluginConfig):
...     name: str = "renamed"
>>> class Rename(Plugin[RenameConfig]):
...     def on_transform(self) -> Result[System, str]:
...         self.system.name = self.config.name
...         return Ok(self.system)
>>> context = PluginContext(config=RenameConfig(), system=System(name="original"))
>>> result = Rename.from_context(context).run()
>>> # Expected: the public system property exposes the supplied context system.
>>> result.system.name
'renamed'
>>> assert result.system is context.system
```

A hook that uses a missing system/store receives the public API's `PluginError`;
supply that dependency or build it in an earlier hook.
Translation plugins can use separate `source_system` and `target_system` fields.
See [lifecycle contracts](/r2x-core/references/plugins/) for which successful hooks
populate these fields, and [workflow boundaries](/r2x-core/explanations/workflow-boundaries/)
for their role in a translation pipeline.

<span id="context-fields"></span>

<span id="field-summary"></span>

<span id="direct-attribute-updates"></span>

<span id="plugin-pipeline-pattern"></span>

<span id="metadata-for-custom-data"></span>

<span id="parser-specific-options"></span>

<span id="translation-workflows"></span>

<span id="creating-context-from-command-line-arguments"></span>

<span id="stdin-handling-pattern"></span>

<span id="memory-efficiency"></span>

<span id="performance-considerations"></span>

<span id="best-practices"></span>
