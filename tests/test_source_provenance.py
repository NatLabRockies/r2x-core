"""Tests for source-side provenance capture during translation.

Exercises the ``preserve_source`` flag on ``PluginContext``:

- Translated components get tagged with a ``SourceProvenance`` carrying the
  source UUID.
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
    assert tags[0].source_uuid == source_bus.uuid


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
    assert {c.uuid for c in ctx.target_system.iter_translated_components()} == {
        c.uuid for c in ctx.target_system.iter_all_components()
    }


def test_provenance_survives_json_round_trip(context_preserve_source: PluginContext) -> None:
    """to_json / from_json preserves SourceProvenance tags and ProvenanceInfo."""
    from fixtures.target_system import NodeComponent

    src = context_preserve_source.source_system
    tgt = context_preserve_source.target_system
    assert src is not None and tgt is not None

    unmapped = RoundTripUnmappedType(name="phantom", payload="x")
    src.add_component(unmapped)

    apply_rules_to_context(context_preserve_source)

    original_source_uuids = {tag.source_uuid for tag in tgt.get_supplemental_attributes(SourceProvenance)}

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sys.json"
        tgt.to_json(path)
        loaded = System.from_json(path)

    assert loaded.source_provenance_info is not None
    assert loaded.source_provenance_info.source_system_uuid == src.uuid

    loaded_source_uuids = {tag.source_uuid for tag in loaded.get_supplemental_attributes(SourceProvenance)}
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


def test_finalize_survives_missing_r2x_core_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ProvenanceBuilder.finalize()`` degrades gracefully when r2x_core has no dist metadata.

    Running from a source checkout without ``uv sync`` / ``pip install``
    makes ``importlib.metadata.version("r2x_core")`` raise
    ``PackageNotFoundError``. ``finalize`` must not blow up in that path;
    it should record a PEP 440 sentinel and let ``ProvenanceInfo`` validate.
    """
    import r2x_core.provenance as provenance_mod
    from r2x_core.provenance import ProvenanceBuilder

    # Simulate "package not installed" by making the lookup always return the
    # documented fallback string. If finalize forwarded that raw string, it
    # would raise on the PEP 440 validator; the fix uses a numeric sentinel.
    monkeypatch.setattr(
        provenance_mod,
        "get_package_version",
        lambda _name, fallback="unknown": fallback,
    )

    stub_source = System(system_base=100.0, name="stub")
    info = ProvenanceBuilder(stub_source).finalize()
    assert str(info.r2x_core_version) == "0.0.0"


def test_system_serialize_uses_same_version_sentinel_as_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """System-level and provenance-level r2x versions share the same no-metadata sentinel."""
    import r2x_core.system as system_mod

    monkeypatch.setattr(system_mod, "get_package_version", lambda _name, fallback="unknown": fallback)
    system = System(system_base=100.0, name="target")
    attrs = system.serialize_system_attributes()
    assert attrs["r2x_core_version"] == "0.0.0"


def test_provenance_info_rejects_wrong_version_type() -> None:
    """ProvenanceInfo refuses non-str non-Version inputs for r2x_core_version."""
    with pytest.raises(TypeError, match=r"expected str or packaging\.version\.Version"):
        ProvenanceInfo(
            r2x_core_version=12345,
            source_system_uuid="00000000-0000-0000-0000-000000000000",
        )


def test_record_edge_requires_at_least_one_source(source_system: System) -> None:
    """record_edge rejects an empty source list: an edge with no source is meaningless."""
    from r2x_core.provenance import ProvenanceBuilder

    builder = ProvenanceBuilder(source_system)
    with pytest.raises(ValueError, match="record_edge requires at least one source"):
        builder.record_edge(sources=[], targets=[], status="dropped")


def test_record_translation_sa_target_is_noop(source_system: System) -> None:
    """record_translation does nothing for a supplemental-attribute target.

    SAs cannot own SAs, so no SourceProvenance tag is attached; the
    correspondence is captured in the hop record instead.
    """
    from fixtures.source_system import BusComponent, BusGeographicInfo

    from r2x_core.provenance import ProvenanceBuilder, SourceProvenance

    tgt = System(system_base=100.0, name="target")
    builder = ProvenanceBuilder(source_system)
    src_bus = next(source_system.get_components(BusComponent))
    sa_target = BusGeographicInfo(latitude=1.0, longitude=2.0, location_name="x")

    # Must not raise and must not attach any tag.
    builder.record_translation(src_bus, sa_target, tgt)
    assert list(tgt.get_supplemental_attributes(SourceProvenance)) == []
