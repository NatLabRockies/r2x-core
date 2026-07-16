"""Source-side provenance for lossless round-trip translations.

When a translation runs with ``PluginContext.preserve_source=True``, we want a
later reverse translation to reproduce the original source system. Two things
have to survive the trip:

1. The identity of every source component that was translated, so the reverse
   pass can restore the original source UUIDs (needed for PutGet).
2. Every source component (and supplemental attribute) that had no matching
   translation rule, so the reverse pass can put them back.

We record both by attaching a :class:`SourceProvenance` supplemental attribute
to the relevant target-side entities:

- Translated components get a ``SourceProvenance(preserved=False, source_uuid=...)``
  pointing back at the source UUID they came from.
- Untranslated source components (and their SAs) are copied into the target as
  first-class components, tagged with ``SourceProvenance(preserved=True, ...)``.

Because ``SourceProvenance`` is a real ``SupplementalAttribute``, it rides
inside the standard infrasys serialization (JSON + sqlite associations) with
zero sidecar keys. Any tool that reads the system in the normal way sees the
tag; nothing is hidden in an r2x-only side channel.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from infrasys import Component, SupplementalAttribute
from loguru import logger
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_serializer

from .utils import get_package_version

if TYPE_CHECKING:
    from .system import System


class SourceProvenance(SupplementalAttribute):
    """Marks a target-side entity with its source-side provenance.

    Two modes:

    - ``preserved=False`` (translated): the tagged component was produced by a
      translation rule from a source component with UUID ``source_uuid``. Used
      on the reverse trip to remap Y-side UUIDs back to their original X-side
      UUIDs (PutGet).
    - ``preserved=True`` (carry-over): the tagged component is a copy of a
      source component that no translation rule matched. It exists in the
      target system solely so the reverse pass can put it back. The tagged
      component's UUID equals ``source_uuid``.

    ``SourceProvenance`` itself is a supplemental attribute, so it participates
    in normal infrasys serialization (persisted in ``supplemental_attributes``
    and the associations sqlite table).
    """

    source_uuid: UUID = Field(description="UUID of the originating source component")
    preserved: Annotated[
        bool,
        Field(
            description=(
                "True if the tagged component is a carry-over from source that no rule translated. "
                "False if the tagged component is a rule-produced translation of the source component."
            )
        ),
    ]


def _coerce_version(value: Any) -> Version:
    """Accept a Version or PEP 440 string; raise a clear ValueError otherwise."""
    if isinstance(value, Version):
        return value
    if isinstance(value, str):
        try:
            return Version(value)
        except InvalidVersion as exc:
            raise ValueError(f"{value!r} is not a valid PEP 440 version") from exc
    raise TypeError(f"expected str or packaging.version.Version, got {type(value).__name__}")


VersionField = Annotated[Version, BeforeValidator(_coerce_version)]


class ProvenanceInfo(BaseModel):
    """System-level metadata describing the translation that produced this system.

    Persisted via ``System.serialize_system_attributes``. Purely informational:
    losing it does not prevent round-trip because per-component provenance
    lives in :class:`SourceProvenance` tags.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    r2x_core_version: VersionField = Field(description="r2x-core version that produced this system")
    source_system_uuid: UUID = Field(description="UUID of the source system")
    source_system_name: str | None = Field(default=None, description="name of the source system if set")

    @field_serializer("r2x_core_version")
    def _serialize_version(self, value: Version) -> str:
        """Render the version as its PEP 440 string form for JSON output."""
        return str(value)

    @field_serializer("source_system_uuid")
    def _serialize_uuid(self, value: UUID) -> str:
        """Render the UUID as its canonical hex-with-dashes string for JSON output."""
        return str(value)


class ProvenanceBuilder:
    """Records source-to-target mappings during translation and preserves untranslated state.

    Usage sits inside :func:`r2x_core.rules_executor.apply_rules_to_context`:

    1. Construct with the source system.
    2. Call :meth:`record_translation` after each successful rule application.
    3. Call :meth:`preserve_untranslated` after the rules loop to copy every
       untranslated source component (and its SAs) into the target.
    4. Call :meth:`finalize` to produce a :class:`ProvenanceInfo` for the
       target system's metadata.
    """

    def __init__(self, source_system: System) -> None:
        """Initialize with the source system to capture.

        Parameters
        ----------
        source_system : System
            The source system being translated from.
        """
        self._source_system = source_system
        self._translated_source_uuids: set[UUID] = set()

    def record_translation(
        self,
        source_component: Component | SupplementalAttribute,
        target_component: Component | SupplementalAttribute,
        target_system: System,
    ) -> None:
        """Tag a translated target component with its source-side UUID.

        When ``target_component`` is a plain :class:`Component`: marks
        ``source_component.uuid`` as translated (safe to repeat; the
        underlying set is idempotent on membership) and attaches a fresh
        :class:`SourceProvenance` tag to the target. Fan-out rules that
        produce multiple targets from one source therefore end up with one
        distinct tag per target, all pointing at the same source uuid.

        When ``target_component`` is a :class:`SupplementalAttribute`: no-op.
        The source is deliberately NOT marked as translated so that a
        source consumed only by SA-producing rules (no Component target)
        still flows through the preservation pass and survives the reverse
        trip. Any Component-producing rule that later consumes the same
        source will still mark it via its own call to this method.

        Parameters
        ----------
        source_component : Component or SupplementalAttribute
            The source entity that a rule just consumed. Today the rules
            executor only feeds components here (SAs cannot be sources); the
            wider type keeps the door open for the reverse direction where
            an SA-source rule would call this helper with an SA.
        target_component : Component or SupplementalAttribute
            The target entity the rule produced. See behavior notes above.
        target_system : System
            The target system receiving the tag.
        """
        if isinstance(target_component, SupplementalAttribute):
            # SAs can't own SAs. Do NOT mark the source as translated here:
            # if the only rule that consumed this source produced an SA (no
            # Component target), we still want the source itself to survive
            # via the preservation pass so a reverse translation can put it
            # back. Sources that also have Component-producing rules get
            # marked by those rules' record_translation calls.
            return

        self._translated_source_uuids.add(source_component.uuid)

        provenance = SourceProvenance(
            source_uuid=source_component.uuid,
            preserved=False,
        )
        target_system.add_supplemental_attribute(target_component, provenance)

    def preserve_untranslated(self, target_system: System) -> None:
        """Copy untranslated source components (and their SAs) into the target.

        Every source component whose UUID was not recorded via
        :meth:`record_translation` is deep-copied into ``target_system`` (which
        preserves its original UUID) and tagged with
        ``SourceProvenance(preserved=True)``.

        Every source SA that references at least one preserved component is
        also deep-copied and re-attached, but only to owners that made it into
        the target. Owners that were translated are skipped for that SA (their
        translated counterparts get whatever SA the rules decided to produce).

        Time series metadata for preserved components flows through the normal
        :func:`transfer_time_series_metadata` path: preserved components live
        in the target's ``_components_by_uuid`` under their original UUID, so
        the sqlite transfer picks them up with no orphan-owner special case.

        Parameters
        ----------
        target_system : System
            The target system to preserve into.
        """
        preserved_uuids: set[UUID] = set()
        for source_component in self._iter_untranslated_source_components():
            # deepcopy_component uses model_dump() then re-instantiates, so
            # composed sub-components on `copy` are fresh instances that hold
            # the same uuid as their source counterparts but do not point at
            # the target-side canonical instance. Reverse translation will
            # need to re-link composed refs by uuid; the executor's normal
            # auto_add_composed_components path already de-duplicates by uuid
            # so this does not corrupt the target's component graph.
            copy = self._source_system.deepcopy_component(source_component)
            target_system.add_component(copy)
            provenance = SourceProvenance(
                source_uuid=source_component.uuid,
                preserved=True,
            )
            target_system.add_supplemental_attribute(copy, provenance)
            preserved_uuids.add(source_component.uuid)

        if preserved_uuids:
            logger.debug("Preserved {} untranslated source component(s)", len(preserved_uuids))

        self._preserve_source_supplemental_attributes(target_system, preserved_uuids)

    def finalize(self) -> ProvenanceInfo:
        """Return system-level provenance metadata for the target system.

        Returns
        -------
        ProvenanceInfo
            Metadata describing which source system produced this target.
        """
        # Use a PEP 440 sentinel when r2x_core has no distribution metadata
        # (source checkout). "unknown" would raise here; "0.0.0" is a
        # deliberately-old marker that a downstream compat check will flag as
        # "produced by an ancient version" rather than silently accept.
        return ProvenanceInfo(
            r2x_core_version=_coerce_version(get_package_version("r2x_core", fallback="0.0.0")),
            source_system_uuid=self._source_system.uuid,
            source_system_name=self._source_system.name,
        )

    def _iter_untranslated_source_components(self) -> Iterator[Component]:
        """Yield source components no rule consumed during translation."""
        for component in self._source_system.iter_all_components():
            if component.uuid not in self._translated_source_uuids:
                yield component

    def _preserve_source_supplemental_attributes(
        self, target_system: System, preserved_uuids: set[UUID]
    ) -> None:
        """Copy source SAs touching preserved components into the target.

        For each source SA:

        - Find its source-side owner components.
        - Keep only owners whose UUIDs are in ``preserved_uuids`` (i.e. owners
          that were preserved, not translated). Translated owners already
          received rule-driven SAs on the target and don't get the source SA
          re-attached.
        - If at least one preserved owner remains, deepcopy the SA into the
          target and attach it to each preserved owner (which exists there
          under its source UUID).
        """
        if not preserved_uuids:
            return

        # get_supplemental_attributes() with no type arg yields nothing (infrasys
        # iterates only requested types); pass the base to iterate all subtypes.
        for source_sa in self._source_system.get_supplemental_attributes(SupplementalAttribute):
            if isinstance(source_sa, SourceProvenance):
                # Never carry provenance tags across systems; each translation
                # produces its own provenance for the target.
                continue
            source_owners = self._source_system.get_components_with_supplemental_attribute(source_sa)
            preserved_owner_uuids = [owner.uuid for owner in source_owners if owner.uuid in preserved_uuids]
            if not preserved_owner_uuids:
                continue

            sa_copy = source_sa.model_copy(deep=True)
            for owner_uuid in preserved_owner_uuids:
                target_owner = target_system.get_component_by_uuid(owner_uuid)
                target_system.add_supplemental_attribute(target_owner, sa_copy)
