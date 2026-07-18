"""Tests for the translation-history stack (the lens complement).

Covers the capture-and-persistence half of lossless round-trip translation:

- Serialization output is byte-identical when no history is captured (C6).
- Hop records survive a JSON round trip, and snapshots reconstruct through the
  same infrasys path ``from_json`` uses (even under ``extra="forbid"`` with a
  computed-field discriminator).
- Records that fail to validate on load are retained inertly, not dropped.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import orjson
import pytest
from infrasys import Component
from pydantic import ConfigDict, Field, ValidationError, computed_field

from r2x_core import System
from r2x_core.translation_history import (
    TRANSLATION_HISTORY_SCHEMA_VERSION,
    HopEdge,
    HopRecord,
    SystemSnapshot,
)


class SnapshotProbe(Component):
    """Module-level component so infrasys can re-import it on deserialization."""

    payload: str = Field(default="")


class ForbidComputedProbe(Component):
    """Component with a computed-field discriminator under ``extra='forbid'``.

    Mirrors downstream model packages (r2x-sienna) whose ``model_dump()`` emits
    a ``class_type`` that a naive ``model_validate`` would reject. The snapshot
    must round-trip through the infrasys serialization form instead.
    """

    model_config = ConfigDict(extra="forbid")

    payload: str = Field(default="")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def class_type(self) -> str:
        """Serialization-only discriminator."""
        return type(self).__name__


def _json_body(path: Path) -> dict:
    """Return the parsed system JSON body (excludes sqlite/arrow sidecars)."""
    return orjson.loads(path.read_bytes())


def _snapshot_of(system: System) -> SystemSnapshot:
    """Build a SystemSnapshot from a system in the infrasys serialization form."""
    return SystemSnapshot(
        components=[c.model_dump_custom() for c in system.iter_all_components()],
        supplemental_attributes=[],
    )


def _hop_record_for(system: System) -> HopRecord:
    """Build a minimal valid HopRecord snapshotting ``system``."""
    return HopRecord(
        r2x_core_version="1.2.3",
        source_system_uuid=system.uuid,
        from_model="X",
        to_model="Y",
        snapshot=_snapshot_of(system),
        edges=[
            HopEdge(
                source_uuids=[c.uuid for c in system.iter_all_components()],
                target_uuids=[],
                status="unclaimed",
            )
        ],
    )


def test_serialization_omits_history_key_when_empty() -> None:
    """With no history captured, the system JSON carries no ``translation_history``.

    This is the C6 zero-cost-when-off contract: a system that never opted into
    preservation serializes exactly like a plain system, with no extra keys.
    Asserted before any history is wired into the executor. (The only field
    that legitimately varies between dumps is ``time_series.directory``, which
    is derived from the output filename, not from preservation.)
    """
    system = System(system_base=100.0, name="plain")
    system.add_component(SnapshotProbe(name="a", payload="x"))

    assert system.translation_history == []

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sys.json"
        system.to_json(path)
        body = _json_body(path)

    assert "translation_history" not in body
    # The serialize hook must not inject any preservation key when off.
    assert "source_provenance_info" not in body


def test_serialization_adds_only_history_key_when_present() -> None:
    """Capturing history adds exactly the ``translation_history`` key, nothing else.

    Compares the JSON body with and without a captured record (same in-memory
    system, same output path stem), so the diff isolates precisely what
    preservation adds: one key, and no mutation of any other field.
    """
    system = System(system_base=100.0, name="plain")
    system.add_component(SnapshotProbe(name="a", payload="x"))

    with tempfile.TemporaryDirectory() as td:
        off_path = Path(td) / "sys.json"
        system.to_json(off_path, overwrite=True)
        off_body = _json_body(off_path)

        system.translation_history.append(_hop_record_for(system))
        on_path = Path(td) / "sys.json"
        system.to_json(on_path, overwrite=True)
        on_body = _json_body(on_path)

    assert set(on_body) - set(off_body) == {"translation_history"}
    # Every other field is untouched by preservation.
    for key in off_body:
        assert on_body[key] == off_body[key], f"preservation mutated unrelated key {key!r}"


def test_hop_record_survives_json_round_trip() -> None:
    """A captured hop record round-trips through to_json / from_json intact."""
    system = System(system_base=100.0, name="src")
    probe = SnapshotProbe(name="thing", payload="data")
    system.add_component(probe)

    system.translation_history.append(_hop_record_for(system))

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sys.json"
        system.to_json(path)
        body = _json_body(path)
        assert "translation_history" in body
        loaded = System.from_json(path)

    assert len(loaded.translation_history) == 1
    record = loaded.translation_history[0]
    assert record.schema_version == TRANSLATION_HISTORY_SCHEMA_VERSION
    assert record.from_model == "X"
    assert record.to_model == "Y"
    assert record.source_system_uuid == system.uuid
    assert len(record.snapshot.components) == 1
    assert record.edges[0].status == "unclaimed"
    assert probe.uuid in record.edges[0].source_uuids
    assert not loaded.has_unparsed_translation_history()


def test_snapshot_reconstructs_component_via_infrasys_path() -> None:
    """A snapshot record instantiates the original component through infrasys.

    Uses the same first-pass deserialization the system loader uses, so the
    ``extra="forbid"`` + computed-field case that breaks naive model_validate
    is handled by construction.
    """
    from infrasys.serialization import CachedTypeHelper

    system = System(system_base=100.0, name="src")
    original = ForbidComputedProbe(name="widget", payload="keepme")
    system.add_component(original)

    record = _hop_record_for(system)
    (component_record,) = record.snapshot.components

    # Recovery reconstructs into a *fresh* system (the source no longer exists),
    # via the same path System.from_json uses internally.
    restored_system = System(system_base=100.0, name="restored")
    restored = restored_system._try_deserialize_component(component_record, CachedTypeHelper())
    assert restored is not None
    assert restored.uuid == original.uuid
    assert restored.payload == "keepme"


def test_unparsable_record_retained_inertly_not_dropped() -> None:
    """A hop record too new to validate is kept as raw payload and flagged.

    Losslessness must not silently degrade: the record survives the round trip
    and ``has_unparsed_translation_history`` reports it so a recovery pass can
    refuse to proceed.
    """
    system = System(system_base=100.0, name="src")
    system.add_component(SnapshotProbe(name="a"))

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sys.json"
        system.to_json(path)
        body = _json_body(path)
        # Inject a record from a hypothetical future schema the loader cannot parse.
        body["translation_history"] = [{"schema_version": 9999, "totally": "unknown-shape"}]
        path.write_bytes(orjson.dumps(body))

        loaded = System.from_json(path)

    assert loaded.translation_history == []
    assert loaded.has_unparsed_translation_history()

    # The unparsed record must survive re-serialization (no silent data loss).
    with tempfile.TemporaryDirectory() as td:
        path2 = Path(td) / "sys2.json"
        loaded.to_json(path2)
        body2 = _json_body(path2)

    assert body2["translation_history"] == [{"schema_version": 9999, "totally": "unknown-shape"}]


def test_unparsed_records_keep_stack_order_across_round_trip() -> None:
    """A future-schema record interleaved with valid ones keeps its position.

    The stack is an append-only chain history, so order is significant. An
    unparsable record spliced back at the wrong index would corrupt the chain.
    """
    system = System(system_base=100.0, name="src")
    system.add_component(SnapshotProbe(name="a"))

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sys.json"
        system.to_json(path)
        body = _json_body(path)
        valid = HopRecord(
            r2x_core_version="1.0.0",
            source_system_uuid=system.uuid,
            snapshot=SystemSnapshot(components=[], supplemental_attributes=[]),
        ).model_dump(mode="json")
        future = {"schema_version": 9999, "marker": "future"}
        # Order: valid, future, valid  -> the future record sits at index 1.
        valid_b = dict(valid)
        valid_b["to_model"] = "second"
        body["translation_history"] = [valid, future, valid_b]
        path.write_bytes(orjson.dumps(body))

        loaded = System.from_json(path)

    assert loaded.has_unparsed_translation_history()
    assert len(loaded.translation_history) == 2

    with tempfile.TemporaryDirectory() as td:
        path2 = Path(td) / "sys2.json"
        loaded.to_json(path2)
        history = _json_body(path2)["translation_history"]

    assert len(history) == 3
    assert history[1] == future, "future-schema record must stay at its original index"
    assert history[2]["to_model"] == "second"


def test_hop_edge_rejects_unknown_fields() -> None:
    """HopEdge forbids extra fields so schema drift is caught, not swallowed."""
    with pytest.raises(ValidationError):
        HopEdge(source_uuids=[uuid4()], status="translated", bogus="nope")  # type: ignore[call-arg]


def test_hop_record_rejects_newer_schema_version() -> None:
    """A record from a newer schema is rejected, so the loader retains it inertly.

    Without this, a structurally-compatible future record would validate, get
    parsed into a partial view, and lose any fields this library does not know
    about on the next dump: silent data loss in a losslessness feature.
    """
    with pytest.raises(ValidationError):
        HopRecord(
            schema_version=TRANSLATION_HISTORY_SCHEMA_VERSION + 1,
            r2x_core_version="1.0.0",
            source_system_uuid=uuid4(),
            snapshot=SystemSnapshot(components=[], supplemental_attributes=[]),
        )


def test_hop_record_rejects_unknown_fields() -> None:
    """An unknown field means a newer schema; forbid it so it is retained inertly."""
    with pytest.raises(ValidationError):
        HopRecord(
            r2x_core_version="1.0.0",
            source_system_uuid=uuid4(),
            snapshot=SystemSnapshot(components=[], supplemental_attributes=[]),
            future_field="surprise",  # type: ignore[call-arg]
        )


# --- end-to-end capture through the executor ---------------------------------


def _preserve_context(rules, source_system, target_system):
    """Build a preserve_source=True PluginContext for the fixture systems."""
    from r2x_core import PluginConfig, PluginContext

    return PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        rules=rules,
        preserve_source=True,
    )


def test_executor_appends_one_hop_record(rules_simple, source_system, target_system) -> None:
    """A preserve_source translation appends exactly one hop record to the target."""
    from r2x_core import apply_rules_to_context

    ctx = _preserve_context(rules_simple, source_system, target_system)
    apply_rules_to_context(ctx)

    assert ctx.target_system is not None
    assert len(ctx.target_system.translation_history) == 1
    record = ctx.target_system.translation_history[0]
    assert record.source_system_uuid == source_system.uuid
    assert record.from_model == source_system.name
    assert record.to_model == target_system.name
    # The snapshot holds every source component.
    assert len(record.snapshot.components) == len(list(source_system.iter_all_components()))


def test_executor_records_one_to_one_edges_with_baseline(rules_simple, source_system, target_system) -> None:
    """1:1 rules produce translated edges with single source/target and a baseline."""
    from fixtures.source_system import BusComponent

    from r2x_core import apply_rules_to_context

    src_bus = next(source_system.get_components(BusComponent))
    ctx = _preserve_context(rules_simple, source_system, target_system)
    apply_rules_to_context(ctx)

    record = ctx.target_system.translation_history[0]
    bus_edges = [e for e in record.edges if src_bus.uuid in e.source_uuids]
    assert len(bus_edges) == 1
    edge = bus_edges[0]
    assert edge.status == "translated"
    assert len(edge.source_uuids) == 1
    assert len(edge.target_uuids) == 1
    # Baseline captured off the constructed target, post-validation.
    (target_uuid,) = edge.target_uuids
    assert target_uuid in record.baseline
    assert record.baseline[target_uuid]["name"] == src_bus.name


def test_executor_marks_unnamed_source_type_unclaimed(rules_simple, source_system, target_system) -> None:
    """A source component whose type no rule names is recorded as ``unclaimed``."""
    from r2x_core import apply_rules_to_context

    phantom = SnapshotProbe(name="orphan", payload="z")
    source_system.add_component(phantom)

    ctx = _preserve_context(rules_simple, source_system, target_system)
    apply_rules_to_context(ctx)

    record = ctx.target_system.translation_history[0]
    phantom_edges = [e for e in record.edges if phantom.uuid in e.source_uuids]
    assert len(phantom_edges) == 1
    assert phantom_edges[0].status == "unclaimed"
    assert phantom_edges[0].target_uuids == []
    # The phantom still rides in the snapshot for later recovery.
    snapshot_uuids = {c["uuid"] for c in record.snapshot.components}
    assert str(phantom.uuid) in snapshot_uuids


def test_executor_filtered_out_source_is_dropped_not_unclaimed(source_system, target_system) -> None:
    """A source the rule names but its filter excludes is ``dropped``, not ``unclaimed``.

    The distinction matters for a reverse pass: ``dropped`` is a rule-asserted
    exclusion, ``unclaimed`` means no rule ever named the type. Conflating them
    is the silent-misclassification risk the design calls out.
    """
    from fixtures.source_system import BusComponent

    from r2x_core import Rule, apply_rules_to_context

    # A rule that names BusComponent but filters to a zone no bus has.
    rule = Rule.from_records(
        [
            {
                "source_type": "BusComponent",
                "target_type": "NodeComponent",
                "version": 1,
                "field_map": {"name": "name", "uuid": "uuid"},
                "filter": {"field": "zone", "op": "eq", "values": ["nonexistent-zone"]},
            }
        ]
    )
    src_bus = next(source_system.get_components(BusComponent))

    ctx = _preserve_context(rule, source_system, target_system)
    apply_rules_to_context(ctx)

    record = ctx.target_system.translation_history[0]
    bus_edges = [e for e in record.edges if src_bus.uuid in e.source_uuids]
    assert len(bus_edges) == 1
    assert bus_edges[0].status == "dropped"
    assert bus_edges[0].rule_version == 1


def test_executor_history_survives_round_trip(rules_simple, source_system, target_system) -> None:
    """A captured hop record survives to_json / from_json on the translated system."""
    from r2x_core import apply_rules_to_context

    ctx = _preserve_context(rules_simple, source_system, target_system)
    apply_rules_to_context(ctx)

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "translated.json"
        ctx.target_system.to_json(path)
        loaded = System.from_json(path)

    assert len(loaded.translation_history) == 1
    assert loaded.translation_history[0].source_system_uuid == source_system.uuid
    assert not loaded.has_unparsed_translation_history()


def test_consumes_records_aggregated_sources_on_one_edge(source_system, target_system) -> None:
    """A rule's ``consumes`` hook folds extra sources into a single edge.

    The iterated source plus every consumed source share one translated edge,
    and all of them are marked claimed (none fall through to ``unclaimed``).
    """
    from fixtures.source_system import BusComponent, LineComponent

    from r2x_core import Rule, apply_rules_to_context

    src_bus = next(source_system.get_components(BusComponent))
    src_lines = list(source_system.get_components(LineComponent))

    def fold_in_lines(iterated, *, context):
        """Aggregate all lines into the bus's target node."""
        return list(context.source_system.get_components(LineComponent))

    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=3,
        field_map={"name": "name", "uuid": "uuid"},
        consumes=fold_in_lines,
    )

    ctx = _preserve_context([rule], source_system, target_system)
    apply_rules_to_context(ctx)

    record = ctx.target_system.translation_history[0]
    bus_edges = [e for e in record.edges if src_bus.uuid in e.source_uuids]
    assert len(bus_edges) == 1
    edge = bus_edges[0]
    assert edge.status == "translated"
    # Iterated bus + all consumed lines on one edge.
    for line in src_lines:
        assert line.uuid in edge.source_uuids
    # Consumed lines are claimed, so they are not separately unclaimed.
    line_only_edges = [
        e for e in record.edges if any(line.uuid in e.source_uuids for line in src_lines) and e is not edge
    ]
    assert line_only_edges == []


def test_consumes_hook_failure_surfaces_as_rule_error(source_system, target_system) -> None:
    """A raising ``consumes`` hook fails the rule rather than corrupting the ledger."""
    from r2x_core import Rule, apply_rules_to_context

    def boom(iterated, *, context):
        raise RuntimeError("kaboom")

    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        consumes=boom,
    )
    ctx = _preserve_context([rule], source_system, target_system)
    result = apply_rules_to_context(ctx)
    assert result.failed_rules == 1


def test_consumes_hook_non_list_return_is_rule_error(source_system, target_system) -> None:
    """A ``consumes`` hook that returns a non-list is rejected."""
    from r2x_core import Rule, apply_rules_to_context

    def bad(iterated, *, context):
        return "not-a-list"

    rule = Rule(
        source_type="BusComponent",
        target_type="NodeComponent",
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
        consumes=bad,
    )
    ctx = _preserve_context([rule], source_system, target_system)
    result = apply_rules_to_context(ctx)
    assert result.failed_rules == 1


def test_fan_out_produces_one_edge_with_multiple_targets(source_system, target_system) -> None:
    """A one-to-many rule records a single edge listing all produced targets."""
    from fixtures.source_system import BusComponent

    from r2x_core import Rule, apply_rules_to_context

    src_bus = next(source_system.get_components(BusComponent))
    # One source bus fans out into a NodeComponent and a CircuitComponent.
    rule = Rule(
        source_type="BusComponent",
        target_type=["NodeComponent", "CircuitComponent"],
        version=1,
        field_map={"name": "name", "uuid": "uuid"},
    )
    ctx = _preserve_context([rule], source_system, target_system)
    apply_rules_to_context(ctx)

    record = ctx.target_system.translation_history[0]
    bus_edges = [e for e in record.edges if src_bus.uuid in e.source_uuids]
    assert len(bus_edges) == 1
    assert bus_edges[0].status == "translated"
    # Two targets, both with fresh (regenerated) UUIDs, on one edge.
    assert len(bus_edges[0].target_uuids) == 2
    assert src_bus.uuid not in bus_edges[0].target_uuids


def test_iter_translated_components_yields_tagged_targets(rules_simple, source_system, target_system) -> None:
    """iter_translated_components yields exactly the rule-produced components."""
    from r2x_core import apply_rules_to_context

    ctx = _preserve_context(rules_simple, source_system, target_system)
    apply_rules_to_context(ctx)

    translated = list(ctx.target_system.iter_translated_components())
    assert translated
    # Every yielded component carries a SourceProvenance tag.
    from r2x_core.provenance import SourceProvenance

    for component in translated:
        tags = ctx.target_system.get_supplemental_attributes_with_component(
            component, supplemental_attribute_type=SourceProvenance
        )
        assert len(tags) == 1


def test_malformed_history_non_list_is_ignored() -> None:
    """A non-list translation_history payload is ignored, not fatal."""
    system = System(system_base=100.0, name="src")
    system.add_component(SnapshotProbe(name="a"))

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sys.json"
        system.to_json(path)
        body = _json_body(path)
        body["translation_history"] = {"not": "a list"}
        path.write_bytes(orjson.dumps(body))
        loaded = System.from_json(path)

    assert loaded.translation_history == []
    assert not loaded.has_unparsed_translation_history()


def test_preserve_source_off_captures_no_history(rules_simple, source_system, target_system) -> None:
    """Without preserve_source, no hop record is captured (C6)."""
    from r2x_core import PluginConfig, PluginContext, apply_rules_to_context

    ctx = PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        rules=rules_simple,
        preserve_source=False,
    )
    apply_rules_to_context(ctx)

    assert ctx.target_system.translation_history == []
