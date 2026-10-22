"""Rule construction, field mapping, filter evaluation, and topological sort."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from infrasys import Component, SupplementalAttribute
from rust_ok import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class RuleOutputs:
    """Primary output and supplemental attributes built from one rule."""

    primary: Component | SupplementalAttribute
    supplemental_attributes: tuple[SupplementalAttribute, ...] = ()


if TYPE_CHECKING:
    from ..plugin_context import PluginContext
    from ..rules import Rule, RuleFilterBase, RuleGetter, RuleLike


COMPONENT_TYPE_CACHE: dict[tuple[tuple[str, ...], str], type] = {}


def value_error_from(message: str, cause: BaseException) -> ValueError:
    """Build contextual error text while retaining its originating exception."""
    error = ValueError(message)
    error.__cause__ = cause
    return error


def resolve_component_type(type_name: str, *, context: PluginContext) -> Result[type, TypeError]:
    """Resolve a component type name to a class.

    Caches successful lookups by ordered module search scope and type name.
    Searches modules specified in config.models.
    """
    cache_key = (context.config.models, type_name)
    if cache_key in COMPONENT_TYPE_CACHE:
        return Ok(COMPONENT_TYPE_CACHE[cache_key])

    modules_to_search: list[str] = list(context.config.models)

    for module_name in modules_to_search:
        try:
            module = importlib.import_module(module_name)
            component_type = getattr(module, type_name, None)
            if component_type is not None:
                COMPONENT_TYPE_CACHE[cache_key] = component_type
                return Ok(component_type)
        except ImportError:
            continue

    return Err(TypeError(f"Component type '{type_name}' not found in modules: {modules_to_search}"))


def build_attr_getter(chain: list[str]) -> RuleGetter:
    """Create a getter that walks nested attributes and returns a Result."""

    def attribute_chain_getter(src: Any, *, context: PluginContext) -> Result[Any, ValueError]:
        """Walk the attribute chain returning the leaf value or None."""
        _ = context
        val = src
        for attr in chain:
            val = getattr(val, attr, None)
            if val is None:
                break
        return Ok(val)

    return attribute_chain_getter


def to_attr_source(source_component: Component | Mapping[str, Any]) -> Component | SimpleNamespace:
    """Return an object that supports attribute access for the provided record.

    When source_component is a Mapping, wraps it in a SimpleNamespace so
    field_map can use dotted attribute access. Otherwise returns unchanged.
    """
    if isinstance(source_component, Mapping):
        return SimpleNamespace(**dict(source_component))
    return source_component


def build_component_kwargs(
    source_component: Component | Mapping[str, Any],
    *,
    rule: RuleLike,
    context: PluginContext,
    allow_missing: bool = False,
) -> Result[dict[str, Any], ValueError]:
    """Construct kwargs for instantiating a target component.

    Parameters
    ----------
    source_component : Any
        Source object or parser record providing attributes.
    rule : RuleLike
        Object exposing field_map, getters, and defaults.
    context : PluginContext
        Active context passed to getters.
    allow_missing : bool, default False
        Skip missing fields and failed getters instead of returning an error.
        This is used for optional supplemental outputs.
    """
    source_obj = to_attr_source(source_component)
    field_map = rule.field_map
    getters = rule.getters
    defaults = rule.defaults
    kwargs: dict[str, Any] = {}
    missing = object()

    for target_field, source_field in field_map.items():
        if isinstance(source_field, list):
            continue
        value = getattr(source_obj, source_field, missing)
        if value is not missing and value is not None:
            kwargs[target_field] = value
        elif target_field in defaults:
            kwargs[target_field] = defaults[target_field]
        elif not allow_missing:
            if value is missing:
                return Err(
                    ValueError(f"Source {type(source_obj).__name__} has no attribute {source_field!r}")
                )
            return Err(
                ValueError(
                    f"Source attribute {source_field!r} is None and no default exists for {target_field!r}"
                )
            )

    for target_field, getter_func in getters.items():
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
                elif not allow_missing:
                    error = ValueError(f"Getter for '{target_field}' failed: {e}")
                    if isinstance(e, BaseException):
                        error.__cause__ = e
                    return Err(error)
            case _:
                msg = f"Getter for '{target_field}' must return Ok or Err, got {type(result).__name__}"
                raise TypeError(msg)

    for target_field, default_value in defaults.items():
        if target_field not in kwargs:
            kwargs[target_field] = default_value

    return Ok(kwargs)


def create_rule_outputs(
    source_component: Component,
    *,
    rule: Rule,
    target_class: type[Component] | type[SupplementalAttribute],
    supplemental_classes: Sequence[type[SupplementalAttribute]],
    context: PluginContext,
    regenerate_uuid: bool = False,
) -> Result[RuleOutputs, ValueError]:
    """Construct a primary target and all supplemental outputs for a rule."""
    supplemental_rules = rule.supplemental_attributes
    if len(supplemental_rules) != len(supplemental_classes):
        return Err(
            ValueError(
                f"Rule '{rule}' has {len(supplemental_rules)} supplemental outputs but "
                f"{len(supplemental_classes)} resolved supplemental target types"
            )
        )

    fields_result = build_component_kwargs(source_component, rule=rule, context=context)
    if fields_result.is_err():
        error = fields_result.err()
        return Err(value_error_from(f"primary target: {error}", error))

    primary_kwargs = fields_result.unwrap()
    if regenerate_uuid and "uuid" in primary_kwargs:
        primary_kwargs = dict(primary_kwargs)
        primary_kwargs["uuid"] = str(uuid4())

    try:
        primary = target_class(**primary_kwargs)
    except ValueError as error:
        return Err(value_error_from(f"primary target '{target_class.__name__}': {error}", error))

    supplemental_attributes: list[SupplementalAttribute] = []
    for supplemental_rule, supplemental_class in zip(supplemental_rules, supplemental_classes, strict=True):
        fields_result = build_component_kwargs(
            source_component,
            rule=supplemental_rule,
            context=context,
            allow_missing=supplemental_rule.optional,
        )
        if fields_result.is_err():
            error = fields_result.err()
            return Err(
                value_error_from(f"supplemental target '{supplemental_rule.target_type}': {error}", error)
            )

        supplemental_kwargs = fields_result.unwrap()
        if supplemental_rule.optional and not any(
            value is not None and value != "" for value in supplemental_kwargs.values()
        ):
            continue

        try:
            supplemental_attributes.append(supplemental_class(**supplemental_kwargs))
        except ValueError as error:
            return Err(
                value_error_from(f"supplemental target '{supplemental_rule.target_type}': {error}", error)
            )

    return Ok(RuleOutputs(primary=primary, supplemental_attributes=tuple(supplemental_attributes)))


def evaluate_rule_filter(
    component: Any, *, rule_filter: RuleFilterBase, context: PluginContext | None = None
) -> bool:
    """Return whether the component satisfies a tagged filter expression."""
    from ..rules import AllOfFilter, AnyOfFilter, FieldFilter, GetterFilter, LeafFilter

    if isinstance(rule_filter, AnyOfFilter):
        return any(
            evaluate_rule_filter(component, rule_filter=child, context=context)
            for child in rule_filter.filters
        )
    if isinstance(rule_filter, AllOfFilter):
        return all(
            evaluate_rule_filter(component, rule_filter=child, context=context)
            for child in rule_filter.filters
        )

    if not isinstance(rule_filter, LeafFilter):
        msg = f"Unsupported filter node: {type(rule_filter).__name__}"
        raise TypeError(msg)
    if isinstance(rule_filter, GetterFilter):
        if context is None:
            msg = "Getter-backed filters require PluginContext"
            raise ValueError(msg)
        getter = rule_filter.getter
        if not callable(getter):
            msg = "Filter getter reference was not resolved"
            raise ValueError(msg)
        result = getter(component, context=context)
        match result:
            case Ok(value):
                candidate = value
            case Err(error):
                msg = f"Filter getter failed: {error}"
                if isinstance(error, BaseException):
                    raise ValueError(msg) from error
                raise ValueError(msg)
            case _:
                msg = f"Filter getter must return Ok or Err, got {type(result).__name__}"
                raise TypeError(msg)
    elif isinstance(rule_filter, FieldFilter):
        candidate = getattr(component, rule_filter.field, None)
    else:
        msg = f"Unsupported filter node: {type(rule_filter).__name__}"
        raise TypeError(msg)

    leaf_filter = rule_filter
    if candidate is None:
        return leaf_filter.on_missing == "include"
    if leaf_filter.casefold and isinstance(candidate, str):
        candidate = candidate.casefold()
    values = leaf_filter.normalized_values

    if leaf_filter.op == "eq":
        return candidate == values[0]
    if leaf_filter.op == "neq":
        return candidate != values[0]
    if leaf_filter.op == "in":
        return candidate in values
    if leaf_filter.op == "not_in":
        return candidate not in values
    if leaf_filter.op == "geq":
        try:
            return float(candidate) >= float(values[0])
        except (TypeError, ValueError):
            return False
    if leaf_filter.op == "startswith":
        return any(str(candidate).startswith(value) for value in values)
    if leaf_filter.op == "not_startswith":
        return all(not str(candidate).startswith(value) for value in values)
    if leaf_filter.op == "endswith":
        return any(str(candidate).endswith(value) for value in values)
    return False


def sort_rules_by_dependencies(rules: list[Rule]) -> Result[list[Rule], ValueError]:
    """Sort rules by dependencies using topological sort (Kahn's algorithm).

    Parameters
    ----------
    rules : list[Rule]
        Rules to sort

    Returns
    -------
    Result[list[Rule], ValueError]
        Ok with sorted rules, or Err if circular dependencies detected
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

    sorter = TopologicalSorter()
    for name in named_rules:
        sorter.add(name)
    for name, rule in named_rules.items():
        dependencies = rule.depends_on or ()
        for dep in dependencies:
            if dep not in named_rules:
                return Err(ValueError(f"Rule '{name}' depends on unknown rule '{dep}'"))
        sorter.add(name, *dependencies)

    sorted_names: list[str] = []
    try:
        sorted_names.extend(sorter.static_order())
    except CycleError as error:
        cycle = error.args[1][:-1]
        return Err(value_error_from(f"Circular dependencies detected in rules: {', '.join(cycle)}", error))

    unnamed_no_deps = [rule for rule in unnamed_rules if not rule.depends_on]
    unnamed_with_deps = [rule for rule in unnamed_rules if rule.depends_on]

    sorted_rules: list[Rule] = unnamed_no_deps + [named_rules[name] for name in sorted_names]

    for rule in unnamed_with_deps:
        deps = rule.depends_on or []
        for dep in deps:
            if dep not in named_rules:
                return Err(ValueError(f"Rule depends on unknown rule '{dep}'"))
        dep_indices = [
            next(index for index, candidate in enumerate(sorted_rules) if candidate is named_rules[dep])
            for dep in deps
        ]
        insert_index = max(dep_indices, default=-1) + 1
        sorted_rules.insert(insert_index, rule)

    return Ok(sorted_rules)
