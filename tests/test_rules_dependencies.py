"""Tests for rule dependencies, system field, and get_current_component."""

from __future__ import annotations

from graphlib import CycleError

import pytest
from rust_ok import Ok

from r2x_core import PluginConfig, PluginContext, Rule, System
from r2x_core.getters import GETTER_REGISTRY, getter
from r2x_core.rules_executor import sort_rules_by_dependencies


def make_rule(
    source_type: str,
    target_type: str,
    *,
    name: str | None = None,
    depends_on: list[str] | None = None,
) -> Rule:
    """Build a rule with the shared test mapping fields."""
    return Rule(
        source_type=source_type,
        target_type=target_type,
        version=1,
        field_map={"f": "f"},
        name=name,
        depends_on=depends_on,
    )


pytestmark = pytest.mark.rules


@getter(name="get_current_component")
def get_current_component(ctx, component):
    """Return the current component being processed."""
    return Ok(component)


@pytest.mark.parametrize(
    ("name", "depends_on"),
    [
        pytest.param("test_rule", None, id="name"),
        pytest.param("rule_b", ["rule_a"], id="dependency"),
    ],
)
def test_rule_preserves_optional_name_and_dependencies(name: str, depends_on: list[str] | None) -> None:
    rule = make_rule("A", "B", name=name, depends_on=depends_on)

    assert rule.name == name
    assert rule.depends_on == depends_on


def test_rule_system_field_defaults_to_source() -> None:
    rule = Rule(source_type="A", target_type="B", version=1, field_map={"f": "f"})

    assert rule.system == "source"


def test_rule_system_field_can_select_target() -> None:
    rule = Rule(source_type="A", target_type="B", version=1, field_map={"f": "f"}, system="target")

    assert rule.system == "target"


def test_topological_sort_simple_dependency() -> None:
    """Rules are sorted by dependencies."""
    rule_a = make_rule("A", "B", name="rule_a")
    rule_b = make_rule("B", "C", name="rule_b", depends_on=["rule_a"])

    result = sort_rules_by_dependencies([rule_b, rule_a])

    assert result.is_ok()
    sorted_rules = result.unwrap()
    assert sorted_rules[0].name == "rule_a"
    assert sorted_rules[1].name == "rule_b"


def test_topological_sort_unnamed_rules_follow_dependencies() -> None:
    """Unnamed rules respect dependencies on named rules."""
    rule_a = make_rule("A", "B", name="rule_a")
    unnamed_rule = make_rule("B", "C", depends_on=["rule_a"])

    result = sort_rules_by_dependencies([unnamed_rule, rule_a])

    assert result.is_ok()
    sorted_rules = result.unwrap()
    assert sorted_rules[0].name == "rule_a"
    assert sorted_rules[1] is unnamed_rule


def test_topological_sort_complex_dependencies() -> None:
    """Rules are sorted with a complex dependency graph."""
    rule_a = make_rule("A", "B", name="rule_a")
    rule_b = make_rule("B", "C", name="rule_b", depends_on=["rule_a"])
    rule_c = make_rule("C", "D", name="rule_c", depends_on=["rule_a"])
    rule_d = make_rule("D", "E", name="rule_d", depends_on=["rule_b", "rule_c"])

    result = sort_rules_by_dependencies([rule_d, rule_c, rule_b, rule_a])

    assert result.is_ok()
    sorted_rules = result.unwrap()
    assert sorted_rules[0].name == "rule_a"
    names = [rule.name for rule in sorted_rules]
    assert names.index("rule_b") < names.index("rule_d")
    assert names.index("rule_c") < names.index("rule_d")


def test_topological_sort_reports_cycle_without_unrelated_rules() -> None:
    """Cycle errors identify only the cycle and retain the graphlib cause."""
    rule_a = make_rule("A", "B", name="rule_a", depends_on=["rule_b"])
    rule_b = make_rule("B", "C", name="rule_b", depends_on=["rule_a"])
    unrelated = make_rule("C", "D", name="unrelated")

    result = sort_rules_by_dependencies([rule_a, rule_b, unrelated])

    assert result.is_err()
    assert "Circular dependencies" in str(result.err())
    assert "rule_a" in str(result.err())
    assert "rule_b" in str(result.err())
    assert "unrelated" not in str(result.err())
    assert isinstance(result.err().__cause__, CycleError)


@pytest.mark.parametrize(
    ("name", "dependency"),
    [
        pytest.param("named", "unknown_rule", id="named"),
        pytest.param(None, "missing_named_rule", id="unnamed"),
    ],
)
def test_topological_sort_rejects_unknown_dependencies(name: str | None, dependency: str) -> None:
    rule = make_rule("A", "B", name=name, depends_on=[dependency])

    result = sort_rules_by_dependencies([rule])

    assert result.is_err()
    assert "unknown rule" in str(result.err()).lower()


def test_topological_sort_rejects_duplicate_names() -> None:
    rule_a = make_rule("A", "B", name="duplicate")
    rule_b = make_rule("C", "D", name="duplicate")

    result = sort_rules_by_dependencies([rule_a, rule_b])

    assert result.is_err()
    assert "Duplicate rule name" in str(result.err())


def test_topological_sort_places_unnamed_rules_first() -> None:
    """Unnamed rules without dependencies are placed before named rules."""
    unnamed_rule = make_rule("A", "B")
    named_rule = make_rule("C", "D", name="named")

    result = sort_rules_by_dependencies([named_rule, unnamed_rule])

    assert result.is_ok()
    sorted_rules = result.unwrap()
    assert sorted_rules[0] is unnamed_rule
    assert sorted_rules[1] is named_rule


def test_get_current_component_getter():
    """The application-defined getter returns the component being processed."""

    class ExampleComponent:
        def __init__(self, name: str) -> None:
            self.name = name

    component = ExampleComponent("test")
    context = PluginContext(
        source_system=System(name="source"),
        target_system=System(name="target"),
        config=PluginConfig(models=()),
        rules=(),
        store=None,
    )

    result = get_current_component(context, component)

    assert result.is_ok()
    assert result.unwrap() is component
    assert result.unwrap().name == "test"


def test_get_current_component_in_getter_registry():
    """The application-defined getter is registered by its configured name."""
    assert GETTER_REGISTRY["get_current_component"] is get_current_component


def test_rule_sort_preserves_stable_named_and_unnamed_positions() -> None:
    """Keep named topological order and place unnamed rules at their defined positions."""
    first = make_rule("A", "B", name="first")
    dependent = make_rule("B", "C", name="dependent", depends_on=["first"])
    unrelated = make_rule("C", "D", name="unrelated")
    independent = make_rule("D", "E")
    after_dependencies = make_rule("E", "F", depends_on=["first", "dependent"])

    result = sort_rules_by_dependencies([unrelated, dependent, after_dependencies, first, independent])

    assert result.is_ok()
    assert all(
        actual is expected
        for actual, expected in zip(
            result.unwrap(),
            [independent, unrelated, first, dependent, after_dependencies],
            strict=True,
        )
    )


def test_unnamed_rule_depends_on_named_rule_with_equal_rule_value():
    """Dependencies locate named rules by identity rather than Rule equality."""
    first = make_rule("A", "B", name="first")
    dependency = make_rule("A", "B", name="dependency")
    unnamed = make_rule("B", "C", depends_on=["dependency"])

    result = sort_rules_by_dependencies([first, dependency, unnamed])

    assert result.is_ok()
    sorted_rules = result.unwrap()
    assert sorted_rules[0] is first
    assert sorted_rules[1] is dependency
    assert sorted_rules[2] is unnamed
