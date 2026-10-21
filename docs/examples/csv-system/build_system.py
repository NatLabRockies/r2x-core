"""Read active generators, apply a capacity scenario, and save a system."""

from pathlib import Path

from pydantic import Field
from rust_ok import Ok, Result
from tutorial_model import Generator

from r2x_core import (
    DataFile,
    DataStore,
    Plugin,
    PluginConfig,
    PluginContext,
    System,
    TabularProcessing,
)


class BuildConfig(PluginConfig):
    scale: float = Field(default=1.1, gt=0)
    output_path: Path = Path("output/system.json")


class BuildScenario(Plugin[BuildConfig]):
    def on_build(self) -> Result[System, str]:
        system = System(name="capacity-scenario")
        rows = self.store.read_data("generators").collect()
        for row in rows.iter_rows(named=True):
            system.add_component(Generator(name=row["name"], capacity_mw=row["capacity_mw"]))
        return Ok(system)

    def on_transform(self) -> Result[System, str]:
        for generator in self.system.get_components(Generator):
            generator.capacity_mw *= self.config.scale
        return Ok(self.system)

    def on_export(self) -> Result[None, str]:
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.system.to_json(self.config.output_path, overwrite=True)
        return Ok(None)


store = DataStore(Path("inputs"))
store.add_data(
    [
        DataFile(
            name="generators",
            relative_fpath="generators.csv",
            proc_spec=TabularProcessing(filter_by={"status": "active"}),
        ),
    ]
)
context = PluginContext(config=BuildConfig(), store=store)
result = BuildScenario.from_context(context).run()
assert result.system is not None
components = list(result.system.get_components(Generator))
assert len(components) == 2
print(f"{len(components)} active generators")
print(f"{sum(item.capacity_mw for item in components):.1f} MW after scaling")
print("Saved output/system.json")
