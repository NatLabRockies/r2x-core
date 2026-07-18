"""R2X Core System class - subclass of infrasys.System with R2X-specific functionality."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import orjson
from infrasys.component import Component
from infrasys.system import System as InfrasysSystem
from infrasys.utils.sqlite import backup
from loguru import logger
from pydantic import ValidationError

from . import units
from .provenance import ProvenanceInfo, SourceProvenance
from .translation_history import HopRecord
from .utils import (
    filter_kwargs_by_signatures,
    get_package_version,
    warn_if_persisted_version_newer_than_installed,
)
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
        # Provenance metadata describing which source system produced this one.
        # Populated by the rules executor when PluginContext.preserve_source is
        # True; None otherwise. Per-component provenance lives in
        # SourceProvenance supplemental attributes on the components themselves.
        self.source_provenance_info: ProvenanceInfo | None = None

        # Append-only stack of translation hops (the lens complement). Populated
        # by the rules executor when PluginContext.preserve_source is True.
        # Empty otherwise, in which case serialization output is unchanged.
        self.translation_history: list[HopRecord] = []
        # Raw hop-record payloads that failed to validate on load (schema newer
        # than this library, or corrupt), each with its original stack position.
        # Kept inert so the system still loads (C4: downstream tools must open
        # the file) and so re-serialization restores the exact original order
        # (the stack is an append-only chain history; reordering corrupts it).
        self._unparsed_translation_history: list[tuple[int, dict[str, Any]]] = []

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

    def iter_translated_components(self) -> Iterator[Component]:
        """Iterate components tagged as rule-produced translations.

        If this system contains any :class:`SourceProvenance` tags, this yields
        only components carrying one. Untagged components in a provenance-bearing
        system are not rule-produced translations; they may be pre-existing
        target content.

        If no components in this system carry provenance tags, this yields
        every component (i.e. systems that were not built with
        ``preserve_source=True`` behave the same as :meth:`iter_all_components`).

        Yields
        ------
        Component
            Every component tagged as a rule-produced translation, or every
            component when no provenance tags exist.
        """
        translated = self._translated_component_uuids()
        if not translated:
            yield from self.iter_all_components()
            return

        for component in self.iter_all_components():
            if component.uuid in translated:
                yield component

    def _translated_component_uuids(self) -> set[UUID]:
        """Return component UUIDs carrying a :class:`SourceProvenance` tag.

        Two sqlite scans (one to iterate all ``SourceProvenance`` SAs, one
        association-table lookup per SA) instead of one per component. For a
        system with N components and K provenance SAs, this is ``1 + K``
        queries versus ``N`` for the naive per-component approach; K is
        typically much smaller than N.
        """
        result: set[UUID] = set()
        for tag in self.get_supplemental_attributes(SourceProvenance):
            for owner in self.get_components_with_supplemental_attribute(tag):
                result.add(owner.uuid)
        return result

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
            Dictionary containing ``system_base_power``, ``r2x_core_version``,
            ``source_provenance_info`` when set, and ``translation_history``
            when non-empty. When no provenance was captured, output is
            identical to a plain system: no extra keys are emitted.
        """
        attrs: dict[str, Any] = {
            "system_base_power": self.base_power,
            "r2x_core_version": get_package_version("r2x_core", fallback="0.0.0"),
        }
        if self.source_provenance_info is not None:
            attrs["source_provenance_info"] = self.source_provenance_info.model_dump(mode="json")
        history = self._serialize_translation_history()
        if history:
            attrs["translation_history"] = history
        return attrs

    def _serialize_translation_history(self) -> list[dict[str, Any]]:
        """Serialize the hop stack, restoring unparsed records to their positions.

        Parsed records are dumped in order; unparsed records (retained from a
        load under schema skew) are spliced back at their original indices so a
        round trip preserves the exact append-only order.
        """
        parsed = [record.model_dump(mode="json") for record in self.translation_history]
        if not self._unparsed_translation_history:
            return parsed
        total = len(parsed) + len(self._unparsed_translation_history)
        unparsed_by_index = dict(self._unparsed_translation_history)
        result: list[dict[str, Any]] = []
        parsed_iter = iter(parsed)
        for index in range(total):
            if index in unparsed_by_index:
                result.append(unparsed_by_index[index])
            else:
                result.append(next(parsed_iter))
        return result

    def deserialize_system_attributes(self, data: dict[str, Any]) -> None:
        """Deserialize R2X-specific system attributes.

        Parameters
        ----------
        data : dict[str, Any]
            Dictionary containing serialized system attributes.
        """
        if "system_base_power" in data:
            self.base_power = data["system_base_power"]

        raw_provenance = data.get("source_provenance_info")
        if raw_provenance is not None:
            try:
                self.source_provenance_info = ProvenanceInfo.model_validate(raw_provenance)
            except ValidationError as exc:
                # Do not fail the whole system load just because provenance metadata
                # is malformed; it is informational, not required for correctness.
                logger.warning("Ignoring malformed source_provenance_info: {}", exc)
                self.source_provenance_info = None
            else:
                warn_if_persisted_version_newer_than_installed(
                    self.source_provenance_info.r2x_core_version, package_name="r2x_core"
                )

        self._deserialize_translation_history(data.get("translation_history"))

    def _deserialize_translation_history(self, raw_history: Any) -> None:
        """Load the translation-history stack leniently.

        Records that validate become :class:`HopRecord` instances. Records that
        do not (a newer schema than this library, or corruption) are retained
        as raw payloads in ``_unparsed_translation_history`` so they survive a
        round trip and so the system still loads. Code that relies on the
        history for recovery must fail loudly on unparsed records rather than
        silently proceed with a truncated stack.
        """
        self.translation_history = []
        self._unparsed_translation_history = []
        if not raw_history:
            return
        if not isinstance(raw_history, list):
            logger.warning("Ignoring malformed translation_history: expected a list")
            return
        for index, raw_record in enumerate(raw_history):
            try:
                self.translation_history.append(HopRecord.model_validate(raw_record))
            except ValidationError as exc:
                logger.warning(
                    "Retaining unparsable translation-history record inertly (schema drift?): {}", exc
                )
                self._unparsed_translation_history.append((index, raw_record))

    def has_unparsed_translation_history(self) -> bool:
        """Return True if any hop record on this system failed to validate on load.

        A reverse/recovery pass must check this and refuse to proceed when True:
        a record we could not parse may be exactly the one holding the data
        needed to reconstruct an ancestor, and silently ignoring it would
        convert losslessness into silent loss.
        """
        return bool(self._unparsed_translation_history)
