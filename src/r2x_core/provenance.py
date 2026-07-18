"""Source-side provenance for lossless round-trip translations.

When a translation runs with ``PluginContext.preserve_source=True``, every
translated target component is tagged with a :class:`SourceProvenance`
supplemental attribute pointing back at the source component's UUID. This is a
cheap 1:1 identity index ("which source did this target come from"); the full
lens complement (dropped components, per-hop snapshots, correspondence edges,
mapped-field baselines) lives in ``System.translation_history``.

Because ``SourceProvenance`` is a real ``SupplementalAttribute``, it rides
inside the standard infrasys serialization (JSON + sqlite associations) with
zero sidecar keys. Any tool that reads the system in the normal way sees the
tag; nothing is hidden in an r2x-only side channel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from infrasys import Component, SupplementalAttribute
from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from .translation_history import EdgeStatus, HopEdge, HopRecord, SystemSnapshot
from .utils import VersionField, coerce_version, get_package_version

if TYPE_CHECKING:
    from .system import System


class SourceProvenance(SupplementalAttribute):
    """Identity tag linking a translated target component to its source.

    Attached to every rule-produced target component when
    ``preserve_source=True``. It records the UUID of the source component the
    target was translated from, so a later reverse translation can remap the
    target's UUID back to its original source UUID (PutGet).

    This is deliberately a thin 1:1 index, not the lens complement. Everything
    needed to reconstruct the source (dropped components, per-hop snapshots,
    many-to-many correspondence edges, mapped-field baselines) lives in
    ``System.translation_history``.

    ``SourceProvenance`` itself is a supplemental attribute, so it participates
    in normal infrasys serialization (persisted in ``supplemental_attributes``
    and the associations sqlite table).
    """

    source_uuid: UUID = Field(description="UUID of the originating source component")


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
    """Captures the lens complement (a :class:`HopRecord`) during translation.

    Usage sits inside :func:`r2x_core.rules_executor.apply_rules_to_context`:

    1. Construct with the source system.
    2. Call :meth:`record_translation` per produced target (attaches the cheap
       1:1 identity tag).
    3. Call :meth:`record_edge` per rule application (accumulates the
       correspondence, with arity and mapped-field baseline).
    4. Call :meth:`build_hop_record` after the rules loop to produce the full
       hop record (snapshot + edges + unclaimed detection).
    5. Call :meth:`finalize` to produce a :class:`ProvenanceInfo` for the
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
        # Accumulated correspondence edges, one per rule application.
        self._edges: list[HopEdge] = []
        # Source UUIDs that at least one rule named (matched), whether it
        # produced a target or deliberately dropped. Anything left over after
        # all rules run is "unclaimed": no rule ever mentioned its type.
        self._claimed_source_uuids: set[UUID] = set()
        # target_uuid -> the mapped field names the producing rule declared, so
        # the baseline captures only rule-produced fields (not defaults or
        # computed fields the target happens to carry).
        self._mapped_fields_by_target: dict[UUID, set[str]] = {}

    def record_translation(
        self,
        source_component: Component | SupplementalAttribute,
        target_component: Component | SupplementalAttribute,
        target_system: System,
    ) -> None:
        """Tag a translated target component with its source-side UUID.

        When ``target_component`` is a plain :class:`Component`: attaches a
        fresh :class:`SourceProvenance` tag to the target pointing at
        ``source_component.uuid``. Fan-out rules that produce multiple targets
        from one source therefore end up with one distinct tag per target, all
        pointing at the same source uuid.

        When ``target_component`` is a :class:`SupplementalAttribute`: no-op,
        because SAs cannot own SAs. The correspondence for SA-producing rules
        is captured in ``System.translation_history`` instead.

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
            return

        provenance = SourceProvenance(source_uuid=source_component.uuid)
        target_system.add_supplemental_attribute(target_component, provenance)

    def record_edge(
        self,
        *,
        sources: list[Component | SupplementalAttribute],
        targets: list[Component | SupplementalAttribute],
        status: EdgeStatus,
        rule_name: str | None = None,
        rule_version: int | None = None,
        mapped_fields: set[str] | None = None,
    ) -> None:
        """Record one source-to-target correspondence edge for the current hop.

        Arity is data: pass multiple ``sources`` for aggregation (many-to-one),
        multiple ``targets`` for fan-out (one-to-many). All named sources are
        marked claimed so they are not later misclassified as ``unclaimed``.

        Parameters
        ----------
        sources : list of Component or SupplementalAttribute
            The source entities this edge consumed. Must be non-empty.
        targets : list of Component or SupplementalAttribute
            The target entities this edge produced. Empty for a drop.
        status : EdgeStatus
            ``"translated"`` when targets were produced, ``"dropped"`` when a
            rule matched but deliberately produced nothing.
        rule_name : str, optional
            Name of the rule that produced this edge, if named.
        rule_version : int, optional
            Version of the rule that produced this edge.
        mapped_fields : set of str, optional
            Names of the target fields this rule actually produced (its
            ``field_map`` and ``getters`` keys). Used to scope the baseline to
            rule-produced fields. When ``None``, no baseline is captured for
            these targets.
        """
        if not sources:
            raise ValueError("record_edge requires at least one source")
        source_uuids = [source.uuid for source in sources]
        self._claimed_source_uuids.update(source_uuids)
        if mapped_fields is not None:
            for target in targets:
                self._mapped_fields_by_target[target.uuid] = mapped_fields
        self._edges.append(
            HopEdge(
                source_uuids=source_uuids,
                target_uuids=[target.uuid for target in targets],
                rule_name=rule_name,
                rule_version=rule_version,
                status=status,
            )
        )

    def build_hop_record(self, target_system: System) -> HopRecord:
        """Assemble the hop record for this translation run.

        Snapshots the whole source system (the lens complement), appends the
        accumulated edges, adds one ``unclaimed`` edge per source component no
        rule ever named, and captures the mapped-field baseline off the
        constructed target components (post-validation).

        Parameters
        ----------
        target_system : System
            The target system the translation produced. Used to read final,
            validated target field values for the baseline.

        Returns
        -------
        HopRecord
            The self-contained complement for this hop.
        """
        edges = list(self._edges)
        edges.extend(
            HopEdge(source_uuids=[source.uuid], target_uuids=[], status="unclaimed")
            for source in self._source_system.iter_all_components()
            if source.uuid not in self._claimed_source_uuids
        )

        baseline = self._build_baseline(edges, target_system)

        return HopRecord(
            r2x_core_version=coerce_version(get_package_version("r2x_core", fallback="0.0.0")),
            source_system_uuid=self._source_system.uuid,
            from_model=self._source_system.name,
            to_model=target_system.name,
            snapshot=self._snapshot_source(),
            edges=edges,
            baseline=baseline,
            time_series_manifest=[],
        )

    def _snapshot_source(self) -> SystemSnapshot:
        """Serialize the source system into the infrasys record form.

        Uses ``model_dump_custom()`` (the exact form the system JSON emits,
        carrying the ``__metadata__`` type discriminator) so a reverse pass
        reconstructs through the same deserialization path ``from_json`` uses.
        """
        components = [
            component.model_dump_custom() for component in self._source_system.iter_all_components()
        ]
        supplemental_attributes = [
            sa.model_dump_custom()
            for sa in self._source_system.get_supplemental_attributes(SupplementalAttribute)
            if not isinstance(sa, SourceProvenance)
        ]
        return SystemSnapshot(
            components=components,
            supplemental_attributes=supplemental_attributes,
        )

    def _build_baseline(self, edges: list[HopEdge], target_system: System) -> dict[UUID, dict[str, Any]]:
        """Capture as-produced values of rule-mapped fields off constructed targets.

        Read after the whole hop has run and validated, so the values reflect
        pydantic coercion (and any later ``system="target"`` enrichment), not
        the raw kwargs that entered construction. Scoped to the fields the rule
        actually produced (recorded per target in ``record_edge``), so a
        reverse pass compares only rule-produced fields when telling a user
        edit from a lossy forward transform.
        """
        baseline: dict[UUID, dict[str, Any]] = {}
        target_uuids = {c.uuid for c in target_system.iter_all_components()}
        for edge in edges:
            for target_uuid in edge.target_uuids:
                mapped_fields = self._mapped_fields_by_target.get(target_uuid)
                # Skip targets with no recorded mapped fields (e.g. SA targets,
                # which are not components and carry no baseline).
                if not mapped_fields or target_uuid not in target_uuids:
                    continue
                target = target_system.get_component_by_uuid(target_uuid)
                dumped = target.model_dump(mode="json")
                baseline[target_uuid] = {field: dumped[field] for field in mapped_fields if field in dumped}
        return baseline

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
            r2x_core_version=coerce_version(get_package_version("r2x_core", fallback="0.0.0")),
            source_system_uuid=self._source_system.uuid,
            source_system_name=self._source_system.name,
        )
