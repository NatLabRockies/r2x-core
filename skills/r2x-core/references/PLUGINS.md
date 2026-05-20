# r2x-core Plugin System Reference

Use this when defining, running, exposing, or discovering r2x-core plugins and
function transforms.

## Contracts (source-verified)

- `Plugin.from_context(ctx: PluginContext[ConfigT]) -> Plugin[ConfigT]`
- `Plugin.run(*, ctx: PluginContext[ConfigT] | None = None) -> PluginContext[ConfigT]`
- `Plugin.get_implemented_hooks() -> set[str]`
- `Plugin.get_config_type() -> type[Any]`
- `@expose_plugin` marks function-based transform plugins by setting
  `__r2x_exposed__ = True`; it does not wrap, register, instantiate, or
  validate class plugins.

## Do

- Use class-based `Plugin[ConfigT]` for lifecycle translators.
- Use function-based transforms for small `System -> System` operations.
- Return `Ok(...)` / `Err(...)` from lifecycle hooks and function transforms.
- Keep shared plugin state in declared `PluginContext` fields: `store`,
  `system`, `source_system`, `target_system`, `rules`, and `metadata`.
- Use `metadata` for small cross-hook coordination values.
- Verify entry-point group names from current source/docs before editing
  `pyproject.toml`; docs have used multiple groups over time.

## Don't

- Do not decorate class plugins with `@expose_plugin` unless source has changed.
  It is for function transforms.
- Do not stash arbitrary attributes on `PluginContext`; it uses `__slots__`.
- Do not assume every hook return value is stored on the context.
- Do not catch and reformat Pydantic `PluginConfig` validation errors unless a
  user-facing boundary requires it.
- Do not add compatibility import fallbacks around `r2x_core` APIs unless the
  user explicitly asks for multi-version support.

## Class plugin lifecycle

A class plugin binds a translator to a typed `PluginConfig`.

```python
from r2x_core import Ok, Plugin, PluginConfig, System


class MyConfig(PluginConfig):
    input_folder: str
    model_year: int


class MyTranslator(Plugin[MyConfig]):
    def on_prepare(self):
        self.ctx.metadata["prepared"] = True
        return Ok(None)

    def on_build(self):
        return Ok(System(name=f"model_{self.config.model_year}"))
```

`Plugin.run()` calls only implemented hooks. The first hook `Err` becomes a
raised `PluginError` and execution stops.

Hook return handling:

- `on_upgrade`, `on_build`, and `on_transform` update `ctx.system` when they
  return `Ok(system)`.
- `on_translate` updates `ctx.target_system` when it returns `Ok(system)`.
- `on_validate`, `on_prepare`, `on_export`, and `on_cleanup` return values are
  only checked for `Err`; successful payloads are not automatically stored.

## PluginContext

`PluginContext` is the pipeline state object, not a free-form attribute bag.

Common fields:

- `config`: typed `PluginConfig`.
- `store`: optional `DataStore`.
- `system`: in-progress/primary `System`.
- `source_system`: source system for rules.
- `target_system`: target system populated by rules/transforms.
- `rules`: tuple of `Rule` objects.
- `metadata`: mutable dict for small cross-hook values.
- `skip_validation`, `auto_add_composed_components`: parser/build flags.

Use `context.evolve(...)` when creating an updated context value for a new
pipeline step. Use direct fields or `metadata` inside lifecycle hooks.

```python
from r2x_core import PluginContext

ctx = PluginContext(config=MyConfig(input_folder="/data", model_year=2030))
plugin = MyTranslator.from_context(ctx)
ctx = plugin.run()
```

Plugin properties such as `plugin.store`, `plugin.system`,
`plugin.source_system`, and `plugin.target_system` raise `PluginError` when the
required context field is missing. Check setup before relying on them.

## Capability introspection

```python
hooks = MyTranslator.get_implemented_hooks()
assert hooks == {"on_prepare", "on_build"}
config_type = MyTranslator.get_config_type()
```

`get_implemented_hooks()` returns a `set[str]`; sort it only for display.

## Function transform plugins

Function transforms are plain functions marked with `@expose_plugin`. They are
best for focused system transformations without a class lifecycle.

```python
from rust_ok import Err, Ok, Result
from r2x_core import PluginConfig, System, expose_plugin


class TransformConfig(PluginConfig):
    scale: float = 1.0


@expose_plugin
def scale_system(system: System, config: TransformConfig) -> Result[System, str]:
    if config.scale <= 0:
        return Err("scale must be positive")
    # mutate/copy system as appropriate for the transform
    return Ok(system)
```

Function transform guidance:

- Keep the signature explicit, usually `(system: System, config: Config)`.
- Return `Result[System, str]` or another source-confirmed `Result` contract.
- Prefer typed/nested Pydantic config over `**kwargs`.
- Surface validation or domain failures as `Err(...)`, not exceptions.
- Direct Python calls should work; entry-point discovery is an integration
  layer, not the only execution path.

## Entry points

Entry-point group names are easy to get stale. Verify against current source,
docs, and CLI behavior before editing packaging.

Typical split seen in repo docs/source:

```toml
# class plugin discovery in older/current docs
[project.entry-points.r2x_plugin]
my_translator = "my_pkg.plugins:MyTranslator"

# function transform discovery
[project.entry-points."r2x.transforms"]
scale_system = "my_pkg.transforms:scale_system"
```

If a doc mentions `r2x.plugins`, `r2x_plugin`, and `r2x.transforms` in nearby
places, treat that as a drift signal and inspect discovery source/tests before
shipping a package change. Yes, one string can waste a whole afternoon. Rude.

## Failure playbook

- Class plugin not discovered:
  - Confirm the package is installed in the active environment.
  - Inspect `importlib.metadata.entry_points(...)` for the expected group.
  - Confirm the entry-point target imports the class.
- Function transform not discovered:
  - Confirm the function has `__r2x_exposed__ = True` after decoration.
  - Confirm the entry-point group matches the current transform discovery path.
- Hook returns `Err` and translation halts:
  - `Plugin.run()` raises `PluginError`; map it only at an outer boundary.
- Context field missing:
  - Initialize `store`, systems, or rules before accessing plugin properties.
- Need to share cross-hook data:
  - Use `ctx.metadata[...]`, not arbitrary `ctx.foo` attributes.

## Output expectations

- Class plugin vs function transform choice.
- Hooks implemented and why.
- Context fields required and where they are populated.
- Entry-point group verified and source consulted.
- Result/error propagation decisions.
