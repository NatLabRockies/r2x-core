"""Build a configured generator system, apply a scenario, and save it."""

from pathlib import Path

from pydantic import Field
from rust_ok import Ok, Result
from tutorial_model import Generator

from r2x_core import Plugin, PluginConfig, PluginContext, System, build_system


class BuildConfig(PluginConfig):
    """Inputs and application-level scenario settings."""

    scale: float = Field(default=1.1, gt=0)
    output_path: Path = Path("output/system.json")


class BuildScenario(Plugin[BuildConfig]):
    """Use core construction, then apply the application's scenario."""

    def on_build(self) -> Result[System, str]:
        return Ok(build_system(self.config, name="capacity-scenario"))

    def on_transform(self) -> Result[System, str]:
        for generator in self.system.get_components(Generator):
            generator.capacity_mw *= self.config.scale
        return Ok(self.system)

    def on_export(self) -> Result[None, str]:
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.system.to_json(self.config.output_path, overwrite=True)
        return Ok(None)


config = BuildConfig(
    models=("tutorial_model",),
    config_path_override=Path(__file__).parent / "config",
)
result = BuildScenario.from_context(PluginContext(config=config)).run()
assert result.system is not None
components = list(result.system.get_components(Generator))
assert len(components) == 2
print(f"{len(components)} active generators")
print(f"{sum(item.capacity_mw for item in components):.1f} MW after scaling")
print("Saved output/system.json")
