"""Utility functions for rules management."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from rust_ok import Err, Ok, Result

from ..plugin_context import PluginContext
from ..rules import RuleGetter

if TYPE_CHECKING:
    from ..rules import Rule, RuleFilter, RuleLike


_COMPONENT_TYPE_CACHE: dict[str, type] = {}


def _resolve_component_type(type_name: str, *, context: PluginContext) -> Result[type, TypeError]:
    """Resolve a component type name to a class.

    Uses cache to avoid repeated module imports for the same type.
    Searches modules specified in config.models (defaults to r2x_sienna.models, r2x_plexos.models).

    Parameters
    ----------
    type_name : str
        Name of the component type to resolve
    context : PluginContext
        Plugin context to get models from config

    Returns
    -------
    Result[type, TypeError]
        Ok with the resolved class, or Err if not found

    Notes
    -----
    Uses a module-level cache dict to optimize repeated type lookups.
    Modules to search are configured via config.models.
    """
    if type_name in _COMPONENT_TYPE_CACHE:
        return Ok(_COMPONENT_TYPE_CACHE[type_name])

    modules_to_search: list[str] = list(context.config.models)

    for module_name in modules_to_search:
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, type_name):
                component_type = getattr(module, type_name)
                _COMPONENT_TYPE_CACHE[type_name] = component_type
                return Ok(component_type)
        except ImportError:
            continue

    return Err(TypeError(f"Component type '{type_name}' not found in modules: {modules_to_search}"))


def _create_target_component(target_class: type, *, kwargs: dict[str, Any]) -> Any:
    """Instantiate a target component safely."""
    return target_class(**kwargs)


def _make_attr_getter(chain: list[str]) -> RuleGetter:
    """Create a getter that safely walks nested attributes and returns a Result."""

    def _getter(src: Any, *, context: PluginContext) -> Result[Any, ValueError]:
        """Extract attributes."""
        _ = context
        val = src
        for attr in chain:
            val = getattr(val, attr, None)
            if val is None:
                break
        return Ok(val)

    return _getter


def _build_target_fields(
    source_component: Any,
    *,
    rule: Rule,
    context: PluginContext,
) -> Result[dict[str, Any], ValueError]:
    """Build field map for the target component."""
    return build_component_kwargs(source_component, rule=rule, context=context)


def _as_attr_source(source_component: Any) -> Any:
    """Return an object that supports attribute access for the provided record."""
    if isinstance(source_component, Mapping):
        return SimpleNamespace(**source_component)
    return source_component


def build_component_kwargs(
    source_component: Any, *, rule: RuleLike, context: PluginContext
) -> Result[dict[str, Any], ValueError]:
    """Construct kwargs for instantiating a target component.

    Parameters
    ----------
    source_component : Any
        Source object or parser record providing attributes referenced by the rule.
    rule : RuleLike
        Object exposing field_map, getters, and defaults.
    context : PluginContext
        Active context passed to getters.
    """
    source_obj = _as_attr_source(source_component)
    field_map = getattr(rule, "field_map", {})
    getters = getattr(rule, "getters", {})
    defaults = getattr(rule, "defaults", {})
    kwargs: dict[str, Any] = {}

    for target_field, source_field in field_map.items():
        if isinstance(source_field, list):
            # Multi-field mappings must be handled by a getter; skip direct assignment.
            continue
        value = getattr(source_obj, source_field, None)
        if value is not None:
            kwargs[target_field] = value
        elif target_field in defaults:
            kwargs[target_field] = defaults[target_field]
        else:
            return Err(
                ValueError(
                    f"No attribute '{source_field}' on source component and no default for '{target_field}'"
                )
            )

    for target_field, getter_func in getters.items():
        if not callable(getter_func):
            return Err(ValueError(f"Getter for '{target_field}' is not callable: {getter_func}"))
        result = getter_func(source_obj, context=context)
        match result:
            case Ok(value):
                if value is not None:
                    kwargs[target_field] = value
                elif target_field in defaults:
                    kwargs[target_field] = defaults[target_field]
            case Err(e):
                if target_field in defaults:
                    kwargs[target_field] = defaults[target_field]
                else:
                    return Err(ValueError(f"Getter for '{target_field}' failed: {e}"))

    for target_field, default_value in defaults.items():
        if target_field not in kwargs:
            kwargs[target_field] = default_value

    return Ok(kwargs)


def _evaluate_rule_filter(component: Any, *, rule_filter: RuleFilter) -> bool:
    """Return True if the component satisfies the rule filter."""
    if rule_filter.any_of is not None:
        return any(_evaluate_rule_filter(component, rule_filter=child) for child in rule_filter.any_of)
    if rule_filter.all_of is not None:
        return all(_evaluate_rule_filter(component, rule_filter=child) for child in rule_filter.all_of)

    if rule_filter.field is None or rule_filter.op is None or rule_filter.values is None:
        raise ValueError("RuleFilter must have field, op, and values for leaf filters")

    attr = getattr(component, rule_filter.field, None)
    if attr is None:
        return rule_filter.on_missing == "include"

    candidate = str(attr).casefold() if rule_filter.casefold and isinstance(attr, str) else attr
    values = [
        str(val).casefold() if rule_filter.casefold and isinstance(val, str) else val
        for val in rule_filter.values
    ]

    if rule_filter.op == "eq":
        return candidate == values[0]
    if rule_filter.op == "neq":
        return candidate != values[0]
    if rule_filter.op == "in":
        return candidate in values
    if rule_filter.op == "not_in":
        return candidate not in values
    if rule_filter.op == "geq":
        try:
            cand_num = float(candidate)
            threshold = float(values[0])
        except (TypeError, ValueError):
            return False
        return cand_num >= threshold
    if rule_filter.op == "startswith":
        return any(str(candidate).startswith(val) for val in values)
    if rule_filter.op == "not_startswith":
        return all(not str(candidate).startswith(val) for val in values)
    if rule_filter.op == "endswith":
        return any(str(candidate).endswith(val) for val in values)
    return False


def _sort_rules_by_dependencies(rules: list[Rule]) -> Result[list[Rule], ValueError]:
    """Sort rules by dependencies using topological sort.

    Parameters
    ----------
    rules : list[Rule]
        Rules to sort

    Returns
    -------
    Result[list[Rule], ValueError]
        Ok with sorted rules, or Err if circular dependencies detected

    Notes
    -----
    Rules without names or dependencies are placed at the beginning.
    Uses Kahn's algorithm for topological sorting.
    """
    named_rules: dict[str, Rule] = {}
    unnamed_rules: list[Rule] = []

    for rule in rules:
        if rule.name:
            if rule.name in named_rules:
                return Err(ValueError(f"Duplicate rule name: {rule.name}"))
            named_rules[rule.name] = rule
        else:
            unnamed_rules.append(rule)

    # Dependency graph
    in_degree: dict[str, int] = dict.fromkeys(named_rules, 0)
    adjacency: dict[str, list[str]] = {name: [] for name in named_rules}

    for name, rule in named_rules.items():
        if rule.depends_on:
            for dep in rule.depends_on:
                if dep not in named_rules:
                    return Err(ValueError(f"Rule '{name}' depends on unknown rule '{dep}'"))
                adjacency[dep].append(name)
                in_degree[name] += 1

    # Kahn's algorithm
    queue = [name for name, degree in in_degree.items() if degree == 0]
    sorted_names: list[str] = []

    while queue:
        current = queue.pop(0)
        sorted_names.append(current)

        for neighbor in adjacency[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(sorted_names) != len(named_rules):
        unsorted = set(named_rules.keys()) - set(sorted_names)
        return Err(ValueError(f"Circular dependencies detected in rules: {', '.join(unsorted)}"))

    unnamed_no_deps = [rule for rule in unnamed_rules if not rule.depends_on]
    unnamed_with_deps = [rule for rule in unnamed_rules if rule.depends_on]

    sorted_rules: list[Rule] = unnamed_no_deps + [named_rules[name] for name in sorted_names]

    for rule in unnamed_with_deps:
        deps = rule.depends_on or []
        for dep in deps:
            if dep not in named_rules:
                return Err(ValueError(f"Rule depends on unknown rule '{dep}'"))
        dep_indices = [sorted_rules.index(named_rules[dep]) for dep in deps]
        insert_index = max(dep_indices, default=-1) + 1
        sorted_rules.insert(insert_index, rule)

    return Ok(sorted_rules)
