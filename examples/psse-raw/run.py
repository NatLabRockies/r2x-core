"""Build an in-memory example system with the production ingestion API."""

from pathlib import Path

from psse_models import PSSEBus, PSSEGenerator
from psse_reader import DummyPSSEReader

from r2x_core import PluginConfig, build_system


def main() -> None:
    """Build from configuration, registering only application models and reader."""
    example = Path(__file__).parent
    config = PluginConfig(models=("psse_models",), config_path_override=example / "config")
    system = build_system(
        config,
        name="illustrative-case",
        input_folder=example,
        readers={"dummy_raw": DummyPSSEReader()},
    )
    buses = tuple(system.get_components(PSSEBus))
    generators = tuple(system.get_components(PSSEGenerator))
    print(f"{len(buses)} buses")
    print(f"{len(generators)} in-service generators")
    print(f"{sum(generator.active_power_mw for generator in generators):.1f} MW")


if __name__ == "__main__":
    main()
