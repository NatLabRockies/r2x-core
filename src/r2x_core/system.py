"""R2X Core System class - subclass of infrasys.System with R2X-specific functionality."""

from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import orjson
from infrasys.component import Component
from infrasys.system import System as InfrasysSystem
from infrasys.utils.sqlite import backup
from loguru import logger

from . import units
from .utils import filter_kwargs_by_signatures
from .utils.files import get_r2x_cache_path


class System(InfrasysSystem):
    """R2X Core System class extending infrasys.System.

    Extends infrasys.System to provide R2X-specific functionality for data
    model translation and system construction. Adds convenience methods for
    component export and system manipulation.

    Parameters
    ----------
    system_base : float | None, optional
        System base power in MVA for per-unit calculations. Default is None.
    name : str | None, optional
        Unique identifier for the system. Default is None.
    **kwargs
        Additional keyword arguments passed to infrasys.System (e.g.,
        description, auto_add_composed_components).

    Attributes
    ----------
    name : str
        System identifier.
    description : str
        System description.
    base_power : float | None
        System base power in MVA.

    See Also
    --------
    :class:`infrasys.system.System` : Parent class with core system functionality.
    :class:`BaseParser` : Parser framework for building systems.
    """

    def __init__(
        self,
        system_base: float | None = None,
        *,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize R2X Core System.

        This method defines the 'system_base' unit in the global Pint registry.
        If you create multiple System instances, the last one's system_base will
        be used for all unit conversions. Existing components will detect the
        change and issue a warning if they access system_base conversions.

        Parameters
        ----------
        base_power : float, optional (defaults: 100.0)
            System base power in MVA for per-unit calculations.
            Can be provided as first positional argument or as keyword argument.
        name : str, optional
            Name of the system. If not provided, a default name will be assigned.
        **kwargs
            Additional keyword arguments passed to infrasys.System (e.g., description,
            auto_add_composed_components).
        """
        merged_kwargs = dict(kwargs)
        if name is not None:
            merged_kwargs["name"] = name

        super_kwargs = filter_kwargs_by_signatures(merged_kwargs, callables=[InfrasysSystem])
        super().__init__(**super_kwargs)

        self.base_power = system_base

        # Define the system base for pint unit conversion.
        # This allows components to convert: device_pu.to('system_base')
        units.ureg.define(f"system_base = {system_base} * MVA")  # overwrite
        logger.debug("Setting system base to {}", system_base)

    def __str__(self) -> str:
        """Return string representation of the system.

        Returns
        -------
        str
            String showing system name and component count.
        """
        system_str = f"System(name={self.name}"
        num_components = self._components.get_num_components()
        if num_components:
            system_str += f", components={num_components}"
        if self.base_power:
            system_str += f", system_base={self.base_power}"
        return system_str + ")"

    def __repr__(self) -> str:
        """Return detailed string representation.

        Returns
        -------
        str
            Same as __str__().
        """
        return str(self)

    def add_components(self, *components: Component, **kwargs: Any) -> None:
        """Add one or more components to the system and set their _system_base.

        Parameters
        ----------
        *components : Component
            Component(s) to add to the system.
        **kwargs
            Additional keyword arguments passed to parent's add_components.

        Notes
        -----
        If any component is a HasPerUnit model, this method automatically sets
        the component's _system_base attribute for use in system-base per-unit
        display mode.

        Raises
        ------
        ValueError
            If a component already has a different _system_base set.
        """
        super().add_components(*components, **kwargs)

        for component in components:
            if isinstance(component, units.HasPerUnit):
                existing_base = component._get_system_base()
                if existing_base is not None and existing_base != self.base_power:
                    comp_name = component.name if hasattr(component, "name") else type(component).__name__
                    msg = (
                        f"Component '{comp_name}' already has _system_base={existing_base} MVA "
                        f"but is being added to system with base={self.base_power} MVA. "
                        f"This may indicate the component was previously added to a different system."
                    )
                    raise ValueError(msg)

                component._system_base = self.base_power
                logger.trace(
                    "Set _system_base = {} MVA on component '{}'",
                    self.base_power,
                    component.name if hasattr(component, "name") else type(component).__name__,
                )

    def to_json(  # type: ignore
        self,
        fname: Path | str | None = None,
        overwrite: bool = False,
        indent: int | None = None,
        data: Any = None,
    ) -> bytes | None:
        """Serialize system to JSON file or return bytes.

        Parameters
        ----------
        fname : Path or str, optional
            Output JSON file path. If None, prints JSON to stdout.
            Note: When writing to stdout, time series are serialized to a temporary
            directory that will be cleaned up automatically.
        overwrite : bool, default False
            If True, overwrite existing file. If False, raise error if file exists.
        indent : int, optional
            JSON indentation level. If None, uses compact format.
        data : optional
            Additional data to include in serialization.

        Returns
        -------
        None

        Raises
        ------
        FileExistsError
            If file exists and overwrite=False.

        See Also
        --------
        :meth:`from_json` : Load system from JSON file
        """
        if fname:
            return super().to_json(fname, overwrite=overwrite, indent=indent, data=data)
        logger.info("Serializing system '{}'", self.name)

        cache_folder = get_r2x_cache_path()
        time_series_dir = cache_folder / f"{self.uuid}_time_series"
        time_series_dir.mkdir(exist_ok=True, parents=True)

        system_data: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "uuid": str(self.uuid),
            "data_format_version": self.data_format_version,
            "components": [x.model_dump_custom() for x in self._component_mgr.iter_all()],
            "supplemental_attributes": [
                x.model_dump_custom() for x in self._supplemental_attr_mgr.iter_all()
            ],
            "time_series": {
                "directory": str(time_series_dir),
            },
        }
        extra = self.serialize_system_attributes()
        system_data.update(extra)

        if data is None:
            data = system_data
        else:
            if "system" not in data:
                data["system"] = system_data

        backup(self._con, time_series_dir / self.DB_FILENAME)
        self._time_series_mgr.serialize(system_data["time_series"], time_series_dir, db_name=self.DB_FILENAME)

        json_bytes = orjson.dumps(data)

        return json_bytes

    @classmethod
    def from_json(  # type: ignore
        cls,
        source: Path | str | bytes,
        /,
        *,
        upgrade_handler: Callable[..., Any] | None = None,
        **kwargs: Any,
    ) -> "System":
        """Deserialize system from JSON file.

        Parameters
        ----------
        source : Path, str, or bytes
            Input JSON source.
        upgrade_handler : Callable, optional
            Function to handle data model version upgrades.
        **kwargs
            Additional keyword arguments passed to infrasys deserialization.

        Returns
        -------
        System
            Deserialized system instance.

        Raises
        ------
        FileNotFoundError
            If file does not exist.
        ValueError
            If JSON format is invalid.

        See Also
        --------
        :meth:`to_json` : Serialize system to JSON file.
        :func:`upgrade_data` : Phase 1 upgrades for parser workflow.
        """
        match source:
            case Path() | str():
                system = super().from_json(source, upgrade_handler=upgrade_handler, **kwargs)
            case bytes():
                logger.debug("Deserializing system from bytes.")
                json_data = orjson.loads(source.decode("utf-8"))
                ts_info = json_data.get("time_series")
                if not ts_info:
                    msg = "Data is missing time series information. Check source."
                    raise KeyError(msg)

                if "directory" not in ts_info:
                    msg = "Data is missing time series directory."
                    raise KeyError(msg)
                system = super().from_dict(
                    json_data, ts_info["directory"], upgrade_handler=upgrade_handler, **kwargs
                )
            case _:
                msg = f"{type(source)=} for function from_json. Valid types are: Path, str, bytes"
                raise NotImplementedError(msg)

        for component in system.get_components(Component):
            if isinstance(component, units.HasPerUnit):
                # NOTE: mypy does not know that we deserialize the system attributes.
                component._system_base = system.base_power  # type:ignore

        return system  # type: ignore

    def serialize_system_attributes(self) -> dict[str, Any]:
        """Serialize R2X-specific system attributes.

        Returns
        -------
        dict[str, Any]
            Dictionary containing system_base_power.
        """
        return {"system_base_power": self.base_power, "r2x_core_version": version("r2x_core")}

    def deserialize_system_attributes(self, data: dict[str, Any]) -> None:
        """Deserialize R2X-specific system attributes.

        Parameters
        ----------
        data : dict[str, Any]
            Dictionary containing serialized system attributes.
        """
        if "system_base_power" in data:
            self.base_power = data["system_base_power"]
