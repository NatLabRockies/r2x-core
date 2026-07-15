"""Tests for source-side provenance capture during translation.

Exercises the ``preserve_source`` flag on ``PluginContext``:

- Translated components get tagged with ``SourceProvenance(preserved=False)``
  carrying the source UUID.
- Untranslated source components are copied into the target and tagged with
  ``SourceProvenance(preserved=True)`` while keeping their original UUID.
- Source supplemental attributes riding on preserved components are carried
  over and re-attached.
- ``System.source_provenance_info`` records source-side identity.
- Everything above survives a JSON round-trip.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from infrasys import Component
from pydantic import Field

from r2x_core import PluginContext, Rule, System, apply_rules_to_context
from r2x_core.provenance import ProvenanceInfo, SourceProvenance


class RoundTripUnmappedType(Component):
    """Module-level unmapped source type for JSON round-trip tests.

    Must be defined at module scope so infrasys can re-import it during
    deserialization; locally-defined test classes are unreachable.
    """

    payload: str = Field(default="")


@pytest.fixture
def context_preserve_source(
    rules_simple: list[Rule],
    source_system: System,
    target_system: System,
) -> PluginContext:
    """PluginContext identical to context_example but with preserve_source=True."""
    from r2x_core import PluginConfig

    return PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        rules=rules_simple,
        preserve_source=True,
    )


def test_preserve_source_sets_provenance_info(context_preserve_source: PluginContext) -> None:
    """After translation, target system carries ProvenanceInfo pointing at the source."""
    result = apply_rules_to_context(context_preserve_source)
    assert result.total_converted > 0

    tgt = context_preserve_source.target_system
    src = context_preserve_source.source_system
    assert tgt is not None and src is not None
    info = tgt.source_provenance_info
    assert isinstance(info, ProvenanceInfo)
    assert info.source_system_uuid == src.uuid
    assert info.source_system_name == src.name
    assert info.r2x_core_version  # non-empty


def test_translated_components_get_source_provenance_tag(
    context_preserve_source: PluginContext,
) -> None:
    """Every rule-produced target component carries SourceProvenance(preserved=False)."""
    from fixtures.source_system import BusComponent
    from fixtures.target_system import NodeComponent

    apply_rules_to_context(context_preserve_source)

    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None

    source_bus = next(src.get_components(BusComponent))
    # The target fixture may pre-seed components; only the rule-produced
    # NodeComponent (matching source bus uuid) should carry provenance.
    translated = [
        n
        for n in tgt.get_components(NodeComponent)
        if tgt.get_supplemental_attributes_with_component(n, supplemental_attribute_type=SourceProvenance)
    ]
    assert len(translated) == 1

    tags = tgt.get_supplemental_attributes_with_component(
        translated[0], supplemental_attribute_type=SourceProvenance
    )
    assert len(tags) == 1
    assert tags[0].preserved is False
    assert tags[0].source_uuid == source_bus.uuid


def test_untranslated_source_component_is_preserved_with_uuid(
    context_preserve_source: PluginContext,
) -> None:
    """A source component with no matching rule shows up in the target under its source UUID."""
    from infrasys import Component
    from pydantic import Field

    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None

    # A brand-new source type that no fixture rule matches (not a subtype of
    # anything the rules already handle).
    class UnmappedSourceType(Component):
        """Source-only type with no translation rule."""

        payload: str = Field(default="")

    phantom = UnmappedSourceType(name="phantom", payload="data")
    src.add_component(phantom)

    apply_rules_to_context(context_preserve_source)

    preserved = list(tgt.iter_preserved_components())
    preserved_uuids = {c.uuid for c in preserved}
    assert phantom.uuid in preserved_uuids

    carried = next(c for c in preserved if c.uuid == phantom.uuid)
    tags = tgt.get_supplemental_attributes_with_component(
        carried, supplemental_attribute_type=SourceProvenance
    )
    assert len(tags) == 1
    assert tags[0].preserved is True
    assert tags[0].source_uuid == phantom.uuid


def test_iter_translated_excludes_preserved(context_preserve_source: PluginContext) -> None:
    """iter_translated_components yields only rule-produced components; iter_preserved yields carry-overs."""
    from infrasys import Component
    from pydantic import Field

    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None

    class UnmappedSource(Component):
        payload: str = Field(default="")

    src.add_component(UnmappedSource(name="drop_me"))
    apply_rules_to_context(context_preserve_source)

    translated_uuids = {c.uuid for c in tgt.iter_translated_components()}
    preserved_uuids = {c.uuid for c in tgt.iter_preserved_components()}
    assert translated_uuids.isdisjoint(preserved_uuids)
    assert translated_uuids | preserved_uuids == {c.uuid for c in tgt.iter_all_components()}


def test_preserved_supplemental_attributes_are_carried_over(
    context_preserve_source: PluginContext,
) -> None:
    """Source SAs attached to untranslated components ride into the target and re-attach."""
    from fixtures.source_system import BusGeographicInfo
    from infrasys import Component
    from pydantic import Field

    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None

    class UnmappedType(Component):
        payload: str = Field(default="")

    unmapped = UnmappedType(name="preserved_thing", payload="x")
    src.add_component(unmapped)
    geo = BusGeographicInfo(latitude=40.7, longitude=-74.0, location_name="somewhere")
    src.add_supplemental_attribute(unmapped, geo)

    apply_rules_to_context(context_preserve_source)

    carried = next(c for c in tgt.iter_preserved_components() if c.uuid == unmapped.uuid)
    carried_sas = tgt.get_supplemental_attributes_with_component(
        carried, supplemental_attribute_type=BusGeographicInfo
    )
    assert len(carried_sas) == 1
    assert carried_sas[0].location_name == "somewhere"
    assert carried_sas[0].latitude == pytest.approx(40.7)


def test_preserve_source_off_produces_no_provenance(
    rules_simple: list[Rule],
    source_system: System,
    target_system: System,
) -> None:
    """Without preserve_source=True, nothing about provenance leaks into the target."""
    from r2x_core import PluginConfig

    ctx = PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=PluginConfig(models=("fixtures.source_system", "fixtures.target_system")),
        rules=rules_simple,
        preserve_source=False,
    )
    apply_rules_to_context(ctx)

    assert ctx.target_system is not None
    assert ctx.target_system.source_provenance_info is None
    tags = list(ctx.target_system.get_supplemental_attributes(SourceProvenance))
    assert tags == []
    assert list(ctx.target_system.iter_preserved_components()) == []


def test_provenance_survives_json_round_trip(context_preserve_source: PluginContext) -> None:
    """to_json / from_json preserves SourceProvenance tags and ProvenanceInfo."""
    from fixtures.target_system import NodeComponent

    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None

    unmapped = RoundTripUnmappedType(name="phantom", payload="x")
    src.add_component(unmapped)

    apply_rules_to_context(context_preserve_source)

    original_source_uuids = {
        unmapped.uuid,
        *{tag.source_uuid for tag in tgt.get_supplemental_attributes(SourceProvenance)},
    }

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sys.json"
        tgt.to_json(path)
        loaded = System.from_json(path)

    assert loaded.source_provenance_info is not None
    assert loaded.source_provenance_info.source_system_uuid == src.uuid

    loaded_source_uuids = {c.uuid for c in loaded.iter_preserved_components()} | {
        tag.source_uuid for tag in loaded.get_supplemental_attributes(SourceProvenance)
    }
    assert loaded_source_uuids == original_source_uuids

    loaded_nodes = list(loaded.get_components(NodeComponent))
    assert loaded_nodes
    tagged_nodes = [
        n
        for n in loaded_nodes
        if loaded.get_supplemental_attributes_with_component(n, supplemental_attribute_type=SourceProvenance)
    ]
    assert tagged_nodes, "at least one loaded node should carry SourceProvenance"
    for node in tagged_nodes:
        tags = loaded.get_supplemental_attributes_with_component(
            node, supplemental_attribute_type=SourceProvenance
        )
        assert len(tags) == 1
        assert tags[0].preserved is False


def test_is_preserved_public_wrapper(context_preserve_source: PluginContext) -> None:
    """System.is_preserved returns True for carry-overs, False for translations."""
    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None
    unmapped = RoundTripUnmappedType(name="is_preserved_probe", payload="y")
    src.add_component(unmapped)

    apply_rules_to_context(context_preserve_source)

    preserved = next(c for c in tgt.iter_preserved_components() if c.uuid == unmapped.uuid)
    assert tgt.is_preserved(preserved) is True

    translated = next(iter(tgt.iter_translated_components()))
    assert tgt.is_preserved(translated) is False


def test_malformed_provenance_info_ignored_not_fatal(
    context_preserve_source: PluginContext,
) -> None:
    """deserialize_system_attributes tolerates malformed provenance metadata."""
    apply_rules_to_context(context_preserve_source)
    tgt = context_preserve_source.target_system
    assert tgt is not None

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sys.json"
        tgt.to_json(path)

        # Corrupt the persisted provenance blob so ProvenanceInfo.model_validate fails.
        import orjson

        raw = orjson.loads(path.read_bytes())
        raw["source_provenance_info"] = {"totally": "bogus"}
        path.write_bytes(orjson.dumps(raw))

        loaded = System.from_json(path)

    assert loaded.source_provenance_info is None


def test_provenance_info_rejects_unparseable_version() -> None:
    """ProvenanceInfo refuses to construct with a non-PEP440 version string."""
    with pytest.raises(ValueError, match="not a valid PEP 440 version"):
        ProvenanceInfo(
            r2x_core_version="not-a-version",
            source_system_uuid="00000000-0000-0000-0000-000000000000",
        )


def test_provenance_info_rejects_wrong_version_type() -> None:
    """ProvenanceInfo refuses non-str non-Version inputs for r2x_core_version."""
    with pytest.raises(TypeError, match=r"expected str or packaging\.version\.Version"):
        ProvenanceInfo(
            r2x_core_version=12345,
            source_system_uuid="00000000-0000-0000-0000-000000000000",
        )


def test_supplemental_attribute_with_no_preserved_owners_is_skipped(
    context_preserve_source: PluginContext,
) -> None:
    """SAs whose every owner was translated do not ride into the target."""
    from fixtures.source_system import BusComponent, BusGeographicInfo

    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None

    # Attach an SA to a bus that WILL be translated (rules_simple maps BusComponent).
    # That means the SA's only owner is translated, so preserve_untranslated should skip it.
    translated_bus = next(src.get_components(BusComponent))
    only_translated_sa = BusGeographicInfo(latitude=1.0, longitude=2.0, location_name="only_on_translated")
    src.add_supplemental_attribute(translated_bus, only_translated_sa)

    # Force at least one preserved component so the SA loop actually runs.
    src.add_component(RoundTripUnmappedType(name="forces_sa_loop", payload="x"))

    apply_rules_to_context(context_preserve_source)

    carried_geo = list(tgt.get_supplemental_attributes(BusGeographicInfo))
    # Only the SAs attached to preserved components should appear; the translated-only one is filtered out.
    for sa in carried_geo:
        assert sa.location_name != "only_on_translated"


def test_record_translation_skips_supplemental_attribute_target(
    source_system: System,
) -> None:
    """record_translation returns without tagging when the target is a SupplementalAttribute."""
    from fixtures.source_system import BusComponent, BusGeographicInfo

    from r2x_core.provenance import ProvenanceBuilder

    tgt = System(system_base=100.0, name="target")
    builder = ProvenanceBuilder(source_system)
    src_bus = next(source_system.get_components(BusComponent))
    sa_target = BusGeographicInfo(latitude=1.0, longitude=2.0, location_name="test")

    # Passing an SA as target must not attempt to attach a SourceProvenance to it.
    builder.record_translation(src_bus, sa_target, tgt)

    # Source uuid still marked as translated so it will not be preserved later.
    builder.preserve_untranslated(tgt)
    preserved_uuids = {c.uuid for c in tgt.iter_preserved_components()}
    assert src_bus.uuid not in preserved_uuids


def test_preserve_untranslated_no_op_when_everything_translated(
    context_preserve_source: PluginContext,
) -> None:
    """When every source component has a rule, no carry-overs are produced and the SA loop is skipped."""
    from r2x_core.provenance import ProvenanceBuilder

    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None

    # Mark every source component as translated by feeding record_translation
    # a synthetic target component per source. We reuse the source components
    # themselves as the "target" argument since we only care about the uuid
    # bookkeeping side of the call, and the SA branch short-circuits attach.
    builder = ProvenanceBuilder(src)
    scratch_target = System(system_base=100.0, name="scratch")
    for comp in src.iter_all_components():
        clone = src.deepcopy_component(comp)
        scratch_target.add_component(clone)
        builder.record_translation(comp, clone, scratch_target)

    builder.preserve_untranslated(tgt)
    assert list(tgt.iter_preserved_components()) == []


def test_source_provenance_tags_are_not_carried_across(
    context_preserve_source: PluginContext,
) -> None:
    """SourceProvenance SAs on the source system are not re-copied to the target."""

    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None

    # Pre-tag a source component with a SourceProvenance (simulating a system
    # that already went through a translation earlier).
    unmapped = RoundTripUnmappedType(name="already_tagged", payload="x")
    src.add_component(unmapped)
    stray_tag = SourceProvenance(source_uuid=unmapped.uuid, preserved=True)
    src.add_supplemental_attribute(unmapped, stray_tag)

    apply_rules_to_context(context_preserve_source)

    carried = next(c for c in tgt.iter_preserved_components() if c.uuid == unmapped.uuid)
    tags = tgt.get_supplemental_attributes_with_component(
        carried, supplemental_attribute_type=SourceProvenance
    )
    # Exactly one tag: the fresh one this translation produced, not the stray.
    assert len(tags) == 1
    assert tags[0].uuid != stray_tag.uuid
