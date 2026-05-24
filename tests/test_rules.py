import pytest


def test_simple_rule_creation(rules_simple):
    """Create and verify simple rule with single-field mapping."""
    rule_simple = rules_simple[0]
    assert rule_simple.source_type == "BusComponent"
    assert rule_simple.target_type == "NodeComponent"
    assert rule_simple.version == 1
    assert rule_simple.field_map == {
        "name": "name",
        "uuid": "uuid",
        "kv_rating": "voltage_kv",
        "demand_mw": "load_mw",
        "area": "zone",
    }
    assert rule_simple.getters == {}
    assert rule_simple.defaults == {"area": "unspecified"}


def test_multifield_rule_requires_getter():
    """Multi-field mapping without getter raises ValueError."""
    from r2x_core import Rule

    with pytest.raises(ValueError, match=r"Multi-field mapping .* requires a getter"):
        Rule(
            source_type="Gen",
            target_type="PGen",
            version=1,
            field_map={
                "rating": ["power_a", "power_b"],  # Multi-field without getter
            },
            getters={},  # Missing getter for rating
        )


def test_validation_with_multiple_multifield_mappings():
    """Validation checks all multi-field mappings."""
    from rust_ok import Ok, Result

    from r2x_core import Rule

    def field_getter(_src: object, *, context: object) -> Result[int, ValueError]:
        _ = context
        return Ok(0)

    with pytest.raises(ValueError, match=r"Multi-field mapping .* requires a getter"):
        Rule(
            source_type="Multi",
            target_type="PMulti",
            version=1,
            field_map={
                "field1": ["src_a", "src_b"],
                "field2": ["src_c", "src_d"],
            },
            getters={
                "field1": field_getter,  # Only field1 has getter
            },
        )


def test_rule_is_frozen(rules_simple):
    """Verify rule is frozen (immutable)."""
    from dataclasses import FrozenInstanceError

    rule_simple = rules_simple[0]
    with pytest.raises(FrozenInstanceError):
        rule_simple.version = 2


@pytest.mark.parametrize(
    "defaults,expected",
    [
        ({}, {}),
        ({"field": "default"}, {"field": "default"}),
        ({"f1": 1, "f2": "default"}, {"f1": 1, "f2": "default"}),
    ],
    ids=["no_defaults", "single_default", "multiple_defaults"],
)
def test_defaults_are_optional(defaults, expected):
    """Defaults are optional and default to empty dict."""
    from r2x_core import Rule

    rule = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        defaults=defaults,
    )

    assert rule.defaults == expected


def test_rule_hash_and_equality():
    """Two rules with the same identity hash equal each other."""
    from r2x_core import Rule

    rule_a = Rule(source_type="A", target_type="B", version=1)
    rule_b = Rule(source_type="A", target_type="B", version=1)
    rule_c = Rule(source_type=["A"], target_type="B", version=2)

    assert hash(rule_a) == hash(rule_b)
    assert rule_a == rule_b
    assert rule_a != rule_c
    assert (rule_a == "not a rule") is False


def test_rule_get_source_target_types_and_lists():
    """Source/target helpers should normalize to lists."""
    from r2x_core import Rule

    rule = Rule(source_type="A", target_type=["B", "C"], version=1)
    assert rule.get_source_types() == ["A"]
    assert rule.get_target_types() == ["B", "C"]
    assert rule.has_multiple_targets()
    assert not rule.has_multiple_sources()


def test_rule_rejects_multi_source_and_multi_target():
    """Rules cannot declare both multiple sources and targets."""
    from r2x_core import Rule

    with pytest.raises(NotImplementedError):
        Rule(source_type=["A", "B"], target_type=["C", "D"], version=1)


def test_rule_from_records_processes_string_getters_and_filters():
    """from_records resolves string getter specs and filters."""
    from types import SimpleNamespace

    from rust_ok import Ok

    from r2x_core import Rule, RuleFilter

    records = [
        {
            "source_type": "Source",
            "target_type": "Target",
            "version": 1,
            "field_map": {"name": "name"},
            "getters": {"nested_name": "child.name"},
            "filter": {"field": "status", "op": "eq", "values": ["ok"]},
        }
    ]

    rules = Rule.from_records(records)
    assert len(rules) == 1
    rule = rules[0]
    assert isinstance(rule.filter, RuleFilter)
    getter_fn = rule.getters["nested_name"]
    if callable(getter_fn):
        result = getter_fn(SimpleNamespace(child=SimpleNamespace(name="x")), context=None)
        assert isinstance(result, Ok)


def test_rule_filter_pattern_variants():
    """RuleFilter should validate structure and evaluate operations."""
    from types import SimpleNamespace

    from r2x_core import RuleFilter

    base = SimpleNamespace(name="Alpha", status="ok", count=5)

    leaf = RuleFilter(field="name", op="eq", values=["alpha"])
    assert leaf.matches(base)

    assert RuleFilter(field="name", op="neq", values=["beta"]).matches(base)

    assert RuleFilter(field="name", op="in", values=["alpha", "beta"]).matches(base)

    assert not RuleFilter(field="name", op="not_in", values=["alpha", "beta"]).matches(base)

    geq_filter = RuleFilter(field="count", op="geq", values=[3])
    assert geq_filter.matches(base)

    missing_filter = RuleFilter(field="missing", op="eq", values=["foo"], on_missing="include")
    assert missing_filter.matches(base)

    with pytest.raises(ValueError):
        RuleFilter(field="name", values=["x"], op=None)

    with pytest.raises(ValueError):
        RuleFilter(field="name", op="eq", values=["x"], any_of=[{"field": "x"}])  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        RuleFilter(field="value", op="geq", values=[1, 2])
