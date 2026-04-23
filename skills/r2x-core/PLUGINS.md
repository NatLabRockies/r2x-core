# r2x-core Plugin System Reference

Use this document when the task is about defining, registering, exposing,
or running an r2x-core `Plugin`.

## Scope in this skill

This reference covers:

- `Plugin` lifecycle hooks and capability detection
- `PluginConfig` (Pydantic v2) configuration contract
- `PluginContext` shared state across hooks
- `@expose_plugin` decorator and `r2x_plugin` entry-point discovery
- Result-type usage in lifecycle hooks
- Common failure modes around discovery and registration

## Mental model

- A `Plugin` is a typed translator: `Plugin[ConfigType]` binds the plugin to
  a specific `PluginConfig` subclass.
- The plugin **only implements the hooks it needs**. Hooks are capability
  flags, not a fixed sequence everyone overrides.
- Hooks share state through a single `PluginContext`, not via plugin
  instance attributes.
- Hooks return `Result[T, E]`. Raising for control flow is a bug.

## Lifecycle hooks (in execution order)

| Hook | Purpose | Typical return |
| --- | --- | --- |
| `on_validate` | Cheap precondition checks | `Ok(None)` / `Err(ValidationError)` |
| `on_prepare` | Load inputs, set up resources | `Ok(None)` / `Err(...)` |
| `on_build` | Create the `System` skeleton | `Ok(System)` |
| `on_transform` | Mutate inputs before translation | `Ok(None)` |
| `on_translate` | Apply rules to populate `System` | `Ok(System)` |
| `on_export` | Emit artifacts | `Ok(path-or-payload)` |
| `on_cleanup` | Release resources | `Ok(None)` |

`Plugin.run()` invokes only the implemented hooks. The first `Err`
short-circuits.

## Minimal plugin

```python
from r2x_core import Plugin, PluginConfig, System, Ok

class MyConfig(PluginConfig):
    input_folder: str
    model_year: int
    scenario: str = "base"

class MyTranslator(Plugin[MyConfig]):
    def on_prepare(self):
        # populate self.context with loaded data here
        return Ok(None)

    def on_build(self):
        system = System(name=f"{self.config.scenario}_{self.config.model_year}")
        return Ok(system)
```

## PluginConfig contract

- Inherit from `r2x_core.PluginConfig` (a `BaseModel`); do not roll your own
  base class.
- Use Pydantic v2 idioms: `Field(...)`, `model_validator`, `field_validator`,
  `model_config`.
- Required fields go first, optional fields with defaults next, computed or
  derived fields via `model_validator(mode="after")`.
- Avoid `Any`; prefer concrete types or `Annotated[..., Field(...)]`.

```python
from typing import Annotated
from pydantic import Field
from r2x_core import PluginConfig

class MyConfig(PluginConfig):
    input_folder: Annotated[str, Field(min_length=1)]
    model_year: Annotated[int, Field(ge=1990, le=2100)]
    scenario: str = "base"
```

## PluginContext

`PluginContext` is the shared state object passed across hooks and into
rule executors.

```python
from r2x_core import PluginContext

context = PluginContext(config=MyConfig(input_folder="/data", model_year=2030))
plugin = MyTranslator.from_context(context)
result = plugin.run()
```

Patterns:

- Attach the in-progress `System` to the context when `on_build` produces it.
- Stash loaded data frames or intermediate caches on the context, not on
  the plugin instance, so rule executors can see them.
- Treat the context as the single source of mutable translator state.

## Capability introspection

```python
MyTranslator.get_implemented_hooks()
# -> ["on_prepare", "on_build"]

config_type = MyTranslator.get_config_type()
# -> MyConfig
```

Use these for:

- Reporting which capabilities a plugin actually provides.
- Building UIs or CLIs that adapt to plugin capabilities.
- Cross-checking that a plugin actually implements the hook a workflow
  expects.

## Exposing and registering plugins

Per repository convention: use `r2x_core.PluginConfig` and `@expose_plugin`
directly, no compatibility `try/except` fallbacks.

### Decorate

```python
from r2x_core import expose_plugin

@expose_plugin
class MyTranslator(Plugin[MyConfig]):
    ...
```

### Register through `pyproject.toml`

```toml
[project.entry-points.r2x_plugin]
my_translator = "my_pkg.plugins:MyTranslator"
```

After install (e.g. `uv sync` or `uv pip install -e .`), the plugin is
discoverable by anything iterating the `r2x_plugin` entry-point group.

Run [tools/inspect_plugins.py](./tools/inspect_plugins.py) to enumerate
discovered plugins, their resolved `PluginConfig`, and their implemented
hooks.

## Result-type usage

```python
from r2x_core import Ok, Err, is_ok, is_err

def on_prepare(self):
    if not Path(self.config.input_folder).exists():
        return Err(FileNotFoundError(self.config.input_folder))
    return Ok(None)
```

When orchestrating outside of `Plugin.run()`:

```python
result = plugin.run()
if is_err(result):
    # surface the underlying error type, do not unwrap blindly
    err = result.err()
    raise RuntimeError(f"translation failed: {err!r}")
system = result.ok()
```

## Common failure modes

- Plugin not discovered:
  - Check entry-point string spelling and module path in `pyproject.toml`.
  - Confirm the package is installed in the active environment.
  - Run `tools/inspect_plugins.py`.
- `Plugin[Config]` parametrization mismatch:
  - The annotation must match the actual `PluginConfig` subclass instance
    passed at runtime.
- Hook raises instead of returning `Err`:
  - Refactor to wrap the failure path in `Err(...)`. Lifecycle code should
    not use exceptions for control flow.
- Hook accidentally captured plugin-local state:
  - Move shared state onto `PluginContext` so downstream hooks and rules
    can access it.
- `on_translate` invoked without a built `System`:
  - Ensure `on_build` runs first or that a previously built `System` is
    attached to the context.

## Output expectations

- Which hooks the plugin implements and why.
- Where the `PluginContext` carries shared state.
- How exposure / discovery is wired (decorator + entry point).
- How errors propagate through the `Result` chain.
