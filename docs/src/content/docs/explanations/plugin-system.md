---
title: "Why configuration, context and lifecycle are separate"
---

<span id="plugin-system-architecture"></span>

A translator combines three kinds of information: validated configuration,
mutable workflow state, and operations on that state. Keeping those responsibilities
separate lets a hook be tested without launching the CLI or loading a real model dataset.

<span id="plugin-configuration"></span>

## Configuration describes intent

`PluginConfig` is a Pydantic model. Its fields describe settings, while a
`PluginContext` carries systems, file stores, rules and metadata between hooks.
A class plugin receives this context through `from_context()` and accesses
public properties such as `config`, `system` and `store`.
It does not need to override those properties or read `_ctx`.

## Hooks make ordering explicit

`on_build()` returns the system for a later `on_transform()` or `on_export()`.
Only implemented hooks run. This ordering makes dependencies visible, but it does
not provide rollback: changes made before a failed hook may remain.
The [lifecycle tutorial](/r2x-core/tutorials/plugin-system/) checks success and
failure paths with a complete implementation; the [reference](/r2x-core/references/plugins/)
records the exact hook order and result contracts.

## Class plugins and function transforms

A class is useful when several lifecycle stages share context. An exposed function
is useful for a single transform with explicit system and configuration arguments.
This complete example shows that the function changes a supplied system:

```python doctest
>>> from r2x_core import PluginConfig, System, expose_plugin
>>> from rust_ok import Ok, Result
>>> class RenameConfig(PluginConfig):
...     name: str = "renamed"
>>> @expose_plugin
... def rename(system: System, config: RenameConfig) -> Result[System, str]:
...     system.name = config.name
...     return Ok(system)
>>> system = System(name="original")
>>> result = rename(system, RenameConfig())
>>> # Expected: a successful Result contains the same changed system.
>>> result.unwrap().name
# 'renamed'
>>> assert result.unwrap() is system
```

## Discovery belongs to the installed package boundary

The Rust CLI discovers registered entry points and manages its own Python environment.
Adding core to a separate project does not install a translator there.
See [plugin discovery](/r2x-core/tutorials/plugin-discovery/) and the
[CLI package-management guide](https://github.com/NatLabRockies/r2x-cli/blob/main/docs/plugin-management.md).
Installing a plugin executes Python code with the host process's permissions;
this architecture is not a sandbox.

<span id="purpose-and-goals"></span>

<span id="architecture-overview"></span>

<span id="1-plugin-types"></span>

<span id="model-plugins"></span>

<span id="system-modifier-plugins"></span>

<span id="filter-plugins"></span>

<span id="function-based-transform-plugins"></span>

<span id="2-plugin-registry"></span>

<span id="plugincontext"></span>

<span id="plugin-base-class"></span>

<span id="3-plugin-configuration"></span>

<span id="data-flow"></span>

<span id="plugin-execution-model"></span>

<span id="filter-application-in-parsers"></span>

<span id="design-decisions"></span>

<span id="why-use-pluginconfig-subclasses"></span>

<span id="why-flexible-plugin-signatures"></span>

<span id="why-plugincontext-instead-of-individual-parameters"></span>

<span id="why-support-both-plugins-and-filter-functions"></span>

<span id="extension-points"></span>

<span id="1-custom-plugin-classes"></span>

<span id="2-filter-functions"></span>

<span id="3-configuration-validation"></span>

<span id="security-considerations"></span>

<span id="trusted-plugins-only"></span>

<span id="entry-point-validation"></span>

<span id="no-sandboxing"></span>

<span id="future-considerations"></span>

<span id="plugin-dependencies"></span>

<span id="plugin-versioning"></span>

<span id="see-also"></span>
