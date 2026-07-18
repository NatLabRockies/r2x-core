"""The translation history: the lens complement for lossless round-trips.

A translation from model X to model Y is lossy (see
:doc:`../explanations/lossless-translation`). To make the round trip X->Y->X
recoverable, each hop run with ``PluginContext.preserve_source=True`` appends a
self-contained :class:`HopRecord` to ``System.translation_history``. The stack
is append-only: no hop ever mutates or forgets a prior record, so an arbitrary
chain ``X -> Y -> X -> Z -> Y`` never destroys information a later hop needs.

The complement is the *whole source* (a full snapshot per hop), so GetPut for
an unedited round-trip is identity by construction, with no residue accounting
to get wrong. This is forced by two facts: getters are opaque callables (we
cannot compute which source fields they consumed), and the record must be
self-contained to survive a cross-tool JSON handoff.

Layout::

    System (active model, pristine)
      translation_history: list[HopRecord]      # serialized in system JSON
        HopRecord
          from_model / to_model / versions / source_system_uuid
          snapshot: SystemSnapshot              # full source image (infrasys form)
          edges: list[HopEdge]                  # correspondence, arity as data
          baseline: {target_uuid: {field: value}}   # as-produced mapped values
          time_series_manifest: [...]           # array files the snapshot relies on

Everything a reverse ("put") pass needs is a query over this data; the reverse
pass itself is intentionally *not* implemented here. This module is capture and
persistence only.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from .utils import VersionField

# Bump when the serialized shape of HopRecord/HopEdge/SystemSnapshot changes in
# a way older readers cannot understand. This is deliberately separate from the
# r2x_core library version: a component's schema can drift (a renamed field)
# without the library version telling us anything, and the library version can
# bump without the on-disk format changing at all.
TRANSLATION_HISTORY_SCHEMA_VERSION = 1


EdgeStatus = Literal["translated", "dropped", "unclaimed"]
"""Why a source appears (or does not) in the target.

- ``translated``: at least one target component was produced from the source(s).
- ``dropped``: a rule matched the source but deliberately produced nothing
  (a rule-asserted intent, e.g. a filter excluded it).
- ``unclaimed``: no rule ever named the source's type. The executor discovers
  this after all rules run; it is distinct from ``dropped`` because a
  reverse-pass policy may treat "nobody claimed this" more conservatively than
  "a rule chose to drop this" (see the known-risks discussion in the design).
"""


class HopEdge(BaseModel):
    """One correspondence between source and target components in a hop.

    Arity is data on the edge, not a shape of the type: ``source_uuids`` has
    more than one entry for many-to-one aggregation, ``target_uuids`` has more
    than one for one-to-many fan-out, and both may be plural for many-to-many.
    ``target_uuids`` is empty when ``status`` is ``dropped`` or ``unclaimed``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_uuids: Annotated[
        list[UUID], Field(description="UUIDs of the source components this edge consumed")
    ]
    target_uuids: Annotated[
        list[UUID],
        Field(default_factory=list, description="UUIDs of the target components this edge produced"),
    ]
    rule_name: Annotated[
        str | None, Field(default=None, description="Name of the rule that produced this edge, if named")
    ] = None
    rule_version: Annotated[
        int | None,
        Field(default=None, description="Version of the rule that produced this edge, if a rule ran"),
    ] = None
    status: Annotated[EdgeStatus, Field(description="Why the source(s) appear or do not in the target")]

    @field_serializer("source_uuids", "target_uuids")
    def _serialize_uuid_list(self, value: list[UUID]) -> list[str]:
        """Render UUID lists as canonical strings for JSON output."""
        return [str(item) for item in value]


class SystemSnapshot(BaseModel):
    """A full, self-contained image of a source system in infrasys form.

    ``components`` and ``supplemental_attributes`` are the exact records the
    infrasys system JSON emits (``model_dump_custom()`` output, carrying the
    ``__metadata__`` type discriminator), so a reverse pass reconstructs them
    through the same deserialization path :meth:`System.from_json` uses. This
    is why the snapshot survives ``extra="forbid"`` models with computed-field
    discriminators: it never round-trips through a plain ``model_validate``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    components: Annotated[
        list[dict[str, Any]],
        Field(description="Source components as infrasys serialization records (with __metadata__)"),
    ]
    supplemental_attributes: Annotated[
        list[dict[str, Any]],
        Field(
            default_factory=list,
            description="Source supplemental attributes as infrasys serialization records",
        ),
    ]


class HopRecord(BaseModel):
    """One translation hop: the source image plus the correspondence it produced.

    Self-contained by construction (full snapshot, no external references), so
    it survives a cross-tool JSON handoff and lets a later reverse pass
    reconstruct the source without the original system on disk.
    """

    # extra="forbid" (not "allow") on purpose: an unknown field means the record
    # came from a newer schema this library does not understand. We want that to
    # raise so the loader can retain the raw payload inertly with full fidelity,
    # rather than silently parsing a partial view and dropping the unknown
    # fields on the next dump.
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    schema_version: Annotated[
        int,
        Field(
            default=TRANSLATION_HISTORY_SCHEMA_VERSION,
            description="Serialized-format version of this hop record",
            le=TRANSLATION_HISTORY_SCHEMA_VERSION,
        ),
    ] = TRANSLATION_HISTORY_SCHEMA_VERSION
    r2x_core_version: Annotated[VersionField, Field(description="r2x-core version that produced this hop")]
    source_system_uuid: Annotated[UUID, Field(description="UUID of the source system for this hop")]
    from_model: Annotated[
        str | None, Field(default=None, description="Name of the model translated from, if known")
    ] = None
    to_model: Annotated[
        str | None, Field(default=None, description="Name of the model translated to, if known")
    ] = None
    snapshot: Annotated[SystemSnapshot, Field(description="Full image of the source system")]
    edges: Annotated[
        list[HopEdge], Field(default_factory=list, description="Source-to-target correspondence edges")
    ]
    baseline: Annotated[
        dict[UUID, dict[str, Any]],
        Field(
            default_factory=dict,
            description=(
                "Per target component, the as-produced values of its mapped fields, captured after "
                "validation. Lets a reverse pass tell a user edit (current != baseline) from a "
                "lossy forward transform (current == baseline)."
            ),
        ),
    ]
    time_series_manifest: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "Time-series array file identifiers the snapshot relies on. Lets serialization "
                "assert every referenced array is present instead of discovering a dangling "
                "reference at recovery time."
            ),
        ),
    ]

    @field_serializer("r2x_core_version")
    def _serialize_version(self, value: Any) -> str:
        """Render the version as its PEP 440 string form for JSON output."""
        return str(value)

    @field_serializer("source_system_uuid")
    def _serialize_uuid(self, value: UUID) -> str:
        """Render the UUID as its canonical string form for JSON output."""
        return str(value)

    @field_serializer("baseline")
    def _serialize_baseline(self, value: dict[UUID, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Render baseline keys (target UUIDs) as strings for JSON output."""
        return {str(key): fields for key, fields in value.items()}
