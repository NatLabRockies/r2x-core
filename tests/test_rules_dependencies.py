"""Tests for rule dependencies, system field, and get_current_component."""

from __future__ import annotations

from rust_ok import Ok

from r2x_core.getters import getter


# Test helper getter (example of application-defined getter)
@getter(name="get_current_component")
def get_current_component(ctx, component):
    """Return the current component being processed.

    Example getter that applications can define to pass the current
    component being iterated over to a target field.
    """
    return Ok(component)


def test_rule_with_name_field():
    """Rule can have an optional name field."""
    from r2x_core import Rule

    rule = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        name="test_rule",
    )

    assert rule.name == "test_rule"


def test_rule_with_depends_on_field():
    """Rule can have an optional depends_on field."""
    from r2x_core import Rule

    rule = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        name="rule_b",
        depends_on=["rule_a"],
    )

    assert rule.depends_on == ["rule_a"]


def test_rule_with_system_field_default():
    """Rule system field defaults to 'source'."""
    from r2x_core import Rule

    rule = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
    )

    assert rule.system == "source"


def test_rule_with_system_field_target():
    """Rule can specify system='target'."""
    from r2x_core import Rule

    rule = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        system="target",
    )

    assert rule.system == "target"


def test_topological_sort_simple_dependency():
    """Rules are sorted by dependencies."""
    from r2x_core import Rule
    from r2x_core.rules_executor import sort_rules_by_dependencies

    rule_a = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        name="rule_a",
    )

    rule_b = Rule(
        source_type="B",
        target_type="C",
        version=1,
        field_map={"f": "f"},
        name="rule_b",
        depends_on=["rule_a"],
    )

    rules = [rule_b, rule_a]  # Intentionally out of order
    result = sort_rules_by_dependencies(rules)

    assert result.is_ok()
    sorted_rules = result.unwrap()
    assert sorted_rules[0].name == "rule_a"
    assert sorted_rules[1].name == "rule_b"


def test_topological_sort_unnamed_rules_follow_dependencies():
    """Unnamed rules respect dependencies on named rules."""
    from r2x_core import Rule
    from r2x_core.rules_executor import sort_rules_by_dependencies

    rule_a = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        name="rule_a",
    )

    unnamed_rule = Rule(
        source_type="B",
        target_type="C",
        version=1,
        field_map={"f": "f"},
        depends_on=["rule_a"],
    )

    rules = [unnamed_rule, rule_a]
    result = sort_rules_by_dependencies(rules)

    assert result.is_ok()
    sorted_rules = result.unwrap()
    assert sorted_rules[0].name == "rule_a"
    assert sorted_rules[1] is unnamed_rule


def test_topological_sort_complex_dependencies():
    """Rules are sorted with complex dependency graph."""
    from r2x_core import Rule
    from r2x_core.rules_executor import sort_rules_by_dependencies

    rule_a = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        name="rule_a",
    )

    rule_b = Rule(
        source_type="B",
        target_type="C",
        version=1,
        field_map={"f": "f"},
        name="rule_b",
        depends_on=["rule_a"],
    )

    rule_c = Rule(
        source_type="C",
        target_type="D",
        version=1,
        field_map={"f": "f"},
        name="rule_c",
        depends_on=["rule_a"],
    )

    rule_d = Rule(
        source_type="D",
        target_type="E",
        version=1,
        field_map={"f": "f"},
        name="rule_d",
        depends_on=["rule_b", "rule_c"],
    )

    rules = [rule_d, rule_c, rule_b, rule_a]  # Intentionally out of order
    result = sort_rules_by_dependencies(rules)

    assert result.is_ok()
    sorted_rules = result.unwrap()

    # rule_a must come first
    assert sorted_rules[0].name == "rule_a"
    # rule_b and rule_c must come after rule_a but before rule_d
    names = [r.name for r in sorted_rules]
    assert names.index("rule_b") < names.index("rule_d")
    assert names.index("rule_c") < names.index("rule_d")


def test_topological_sort_circular_dependency():
    """Circular dependencies are detected."""
    from r2x_core import Rule
    from r2x_core.rules_executor import sort_rules_by_dependencies

    rule_a = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        name="rule_a",
        depends_on=["rule_b"],
    )

    rule_b = Rule(
        source_type="B",
        target_type="C",
        version=1,
        field_map={"f": "f"},
        name="rule_b",
        depends_on=["rule_a"],
    )

    rules = [rule_a, rule_b]
    result = sort_rules_by_dependencies(rules)

    assert result.is_err()
    assert "Circular dependencies" in str(result.err())


def test_topological_sort_unknown_dependency():
    """Unknown dependencies are detected."""
    from r2x_core import Rule
    from r2x_core.rules_executor import sort_rules_by_dependencies

    rule_a = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        name="rule_a",
        depends_on=["unknown_rule"],
    )

    rules = [rule_a]
    result = sort_rules_by_dependencies(rules)

    assert result.is_err()
    assert "unknown rule" in str(result.err()).lower()


def test_topological_sort_duplicate_names():
    """Duplicate rule names are detected."""
    from r2x_core import Rule
    from r2x_core.rules_executor import sort_rules_by_dependencies

    rule_a = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
        name="duplicate",
    )

    rule_b = Rule(
        source_type="C",
        target_type="D",
        version=1,
        field_map={"f": "f"},
        name="duplicate",
    )

    rules = [rule_a, rule_b]
    result = sort_rules_by_dependencies(rules)

    assert result.is_err()
    assert "Duplicate rule name" in str(result.err())


def test_topological_sort_unnamed_rules():
    """Unnamed rules are placed at the beginning."""
    from r2x_core import Rule
    from r2x_core.rules_executor import sort_rules_by_dependencies

    unnamed_rule = Rule(
        source_type="A",
        target_type="B",
        version=1,
        field_map={"f": "f"},
    )

    named_rule = Rule(
        source_type="C",
        target_type="D",
        version=1,
        field_map={"f": "f"},
        name="named",
    )

    rules = [named_rule, unnamed_rule]
    result = sort_rules_by_dependencies(rules)

    assert result.is_ok()
    sorted_rules = result.unwrap()
    # Unnamed rule should come first
    assert sorted_rules[0].name is None
    assert sorted_rules[1].name == "named"


def test_get_current_component_getter():
    """get_current_component (application-defined) returns the component being processed."""
    from r2x_core import PluginConfig, PluginContext, System

    class MockComponent:
        def __init__(self, name):
            self.name = name

    component = MockComponent("test")
    source_system = System(name="source")
    target_system = System(name="target")
    config = PluginConfig(models=())
    ctx = PluginContext(
        source_system=source_system,
        target_system=target_system,
        config=config,
        rules=(),
        store=None,
    )

    # Use the application-defined getter from this module
    result = get_current_component(ctx, component)

    assert result.is_ok()
    assert result.unwrap() == component
    assert result.unwrap().name == "test"


def test_get_current_component_in_getter_registry():
    """get_current_component is registered in GETTER_REGISTRY."""
    from r2x_core.getters import GETTER_REGISTRY

    assert "get_current_component" in GETTER_REGISTRY
