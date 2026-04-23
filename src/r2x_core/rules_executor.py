"""Execute a set of rules for a given translation context."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import uuid4

from infrasys import Component, SupplementalAttribute
from loguru import logger
from rust_ok import Err, Ok, Result

from .plugin_context import PluginContext
from .result import RuleApplicationStats, RuleResult, TranslationResult
from .rules import Rule
from .time_series import transfer_time_series_metadata
from .utils import (
    _build_target_fields,
    _create_target_component,
    _evaluate_rule_filter,
    _iter_system_components,
    _resolve_component_type,
    _sort_rules_by_dependencies,
)


def apply_rules_to_context(context: PluginContext) -> TranslationResult:
    """Apply all transformation rules defined in a PluginContext.

    Parameters
    ----------
    context : PluginContext
        The plugin context containing rules and systems

    Returns
    -------
    TranslationResult
        Rich result object with detailed statistics and per-rule results

    Raises
    ------
    ValueError
        If the context has no rules defined or if circular dependencies are detected
    """
    if not context.rules:
        raise ValueError(f"{type(context).__name__} has no rules. Use context.list_rules().")

    sorted_rules = _sort_rules_by_dependencies(context.list_rules()).unwrap_or_raise(exc_type=ValueError)

    rule_results: list[RuleResult] = []
    total_converted = 0
    successful_rules = 0
    failed_rules = 0

    for rule in sorted_rules:
        logger.debug("Applying rule: {}", rule)
        result = apply_single_rule(rule, context=context)

        match result:
            case Ok(stats):
                rule_results.append(
                    RuleResult(
                        rule=rule,
                        converted=stats.converted,
                        skipped=stats.skipped,
                        success=True,
                        error=None,
                    )
                )
                total_converted += stats.converted
                successful_rules += 1
            case Err(_):
                error = str(result.err())
                logger.error("Rule {} failed: {}", rule, error)
                rule_results.append(
                    RuleResult(
                        rule=rule,
                        converted=0,
                        skipped=0,
                        success=False,
                        error=error,
                    )
                )
                failed_rules += 1

    ts_result = transfer_time_series_metadata(context)

    return TranslationResult(
        total_rules=len(context.rules),
        successful_rules=successful_rules,
        failed_rules=failed_rules,
        total_converted=total_converted,
        rule_results=rule_results,
        time_series_transferred=ts_result.transferred,
        time_series_updated=ts_result.updated,
    )


def apply_single_rule(rule: Rule, *, context: PluginContext) -> Result[RuleApplicationStats, ValueError]:
    """Apply one transformation rule across matching components."""
    converted = 0
    target_types = rule.get_target_types()
    should_regenerate_uuid = len(target_types) > 1

    read_system = context.target_system if rule.system == "target" else context.source_system
    if read_system is None:
        return Err(ValueError(f"System '{rule.system}' is not set in context"))

    source_class_result = _resolve_source_class(rule, context=context)
    if source_class_result.is_err():
        return source_class_result.map(lambda _: RuleApplicationStats(converted=0, skipped=0))
    source_class = cast(type[Component], source_class_result.ok())

    resolved_targets: list[type] = []
    for target_type in target_types:
        target_class_result = _resolve_component_type(target_type, context=context).map_err(
            lambda e, tt=target_type: ValueError(f"Failed to resolve target type '{tt}': {e}")
        )
        if target_class_result.is_err():
            return target_class_result.map(lambda _: RuleApplicationStats(converted=0, skipped=0))
        resolved_targets.append(cast(type, target_class_result.ok()))

    filter_func: Callable[[Any], bool] | None = None
    if rule.filter is not None:
        rule_filter = rule.filter
        filter_func = lambda comp, rf=rule_filter: _evaluate_rule_filter(comp, rule_filter=rf)  # noqa: E731

    found_component = False

    for src_component in _iter_system_components(
        read_system, class_type=source_class, filter_func=filter_func
    ):
        found_component = True
        for target_class in resolved_targets:
            fields_result = _build_target_fields(src_component, rule=rule, context=context).map_err(
                lambda e: ValueError(f"Failed to build fields for {src_component.label}: {e}")  # noqa: B023
            )

            if fields_result.is_err():
                return fields_result.map(lambda _: RuleApplicationStats(converted=0, skipped=0))

            kwargs = cast(dict[str, Any], fields_result.ok())
            if should_regenerate_uuid and "uuid" in kwargs:
                kwargs = dict(kwargs)
                kwargs["uuid"] = str(uuid4())
            component = _create_target_component(target_class, kwargs=kwargs)

            attach_result = _attach_component(component, src_component, context)

            if attach_result.is_err():
                return attach_result.map(lambda _: RuleApplicationStats(converted=0, skipped=0))

            if _is_supplemental_attribute(component):
                logger.trace(
                    "Rule {}: attached SA {} to {}",
                    rule,
                    type(component).__name__,
                    src_component.label,
                )
            converted += 1

    if not found_component:
        logger.warning("No components found for source type '{}' in rule {}", rule.get_source_types(), rule)

    logger.debug("Rule {}: {} converted", rule, converted)
    return Ok(RuleApplicationStats(converted=converted, skipped=0))


def _convert_component_with_class(
    rule: Rule,
    source_component: Any,
    target_class: type,
    context: PluginContext,
    regenerate_uuid: bool,
) -> Result[Any, ValueError]:
    """Convert a single source component to a pre-resolved target class.

    Separated from type resolution so callers can resolve once and reuse.
    """
    fields_result = _build_target_fields(source_component, rule=rule, context=context).map_err(
        lambda e: ValueError(f"Failed to build fields for {source_component.label}: {e}")
    )

    def create_component(kwargs: dict[str, Any]) -> Result[Any, ValueError]:
        """
        Create a target component instance with the given keyword arguments.

        If `regenerate_uuid` is True and 'uuid' is present in kwargs, a new UUID is generated.
        Returns an Ok result with the created component, or an Err if creation fails.

        Parameters
        ----------
        kwargs : dict[str, Any]
            The keyword arguments to use for constructing the component.

        Returns
        -------
        Result[Any, ValueError]
            Ok(component) if successful, Err(ValueError) if creation fails.
        """
        if regenerate_uuid and "uuid" in kwargs:
            kwargs = dict(kwargs)
            kwargs["uuid"] = str(uuid4())
        return Ok(_create_target_component(target_class, kwargs=kwargs))

    return fields_result.and_then(create_component)


def _convert_component(
    rule: Rule,
    source_component: Any,
    target_type: str,
    context: PluginContext,
    regenerate_uuid: bool,
) -> Result[Any, ValueError]:
    """Convert a single source component to a target type.

    Resolves the target class on every call. Prefer _convert_component_with_class
    when converting many components with the same rule to avoid repeated resolution.
    """
    target_class_result = _resolve_component_type(target_type, context=context).map_err(
        lambda e: ValueError(f"Failed to resolve target type '{target_type}': {e}")
    )
    return target_class_result.and_then(
        lambda target_class: _convert_component_with_class(
            rule, source_component, target_class, context, regenerate_uuid
        )
    )


def _resolve_source_class(rule: Rule, *, context: PluginContext) -> Result[type[Component], ValueError]:
    """Resolve all source types for a rule into a single component class.

    Rules with multiple source types are not supported here; the caller
    is responsible for deciding how to handle that case.
    """
    source_types = rule.get_source_types()
    if not source_types:
        return Err(ValueError(f"Rule '{rule}' has no source types defined"))

    # For now rules only support a single source type
    source_type = source_types[0]
    if len(source_types) > 1:
        logger.warning("Rule '{}' defines multiple source types; only '{}' will be used", rule, source_type)

    return cast(
        "Result[type[Component], ValueError]",
        _resolve_component_type(source_type, context=context).map_err(
            lambda e: ValueError(f"Failed to resolve source type '{source_type}': {e}")
        ),
    )


def _is_supplemental_attribute(component: Component) -> bool:
    """Check if a component is a supplemental attribute.

    Parameters
    ----------
    component : Any
        The component to check

    Returns
    -------
    bool
        True if the component is a supplemental attribute, False otherwise
    """
    return isinstance(component, SupplementalAttribute)


def _attach_component(
    component: Any,
    source_component: Any,
    context: PluginContext,
) -> Result[None, ValueError]:
    """Attach a component to the target system.

    For regular components, adds them directly to the system.
    For supplemental attributes, finds the corresponding target component
    and attaches the supplemental attribute to it.

    Parameters
    ----------
    component : Any
        The component or supplemental attribute to attach
    source_component : Any
        The source component that was converted
    context : PluginContext
        The plugin context

    Returns
    -------
    Result[None, ValueError]
        Ok if attachment succeeds, Err otherwise
    """
    if context.target_system is None:
        return Err(ValueError("target_system must be set in context"))
    if not _is_supplemental_attribute(component):
        context.target_system.add_component(component)
        return Ok(None)

    # Find the target component that corresponds to the source component
    # We look for a component with the same UUID in the target system
    try:
        target_component = context.target_system.get_component_by_uuid(source_component.uuid)
    except Exception as e:
        logger.error(
            "Failed to find target component with UUID {} for supplemental attribute attachment: {}",
            source_component.uuid,
            e,
        )
        return Err(
            ValueError(
                f"Cannot attach supplemental attribute: target component with UUID "
                f"{source_component.uuid} not found in target system"
            )
        )

    context.target_system.add_supplemental_attribute(target_component, component)
    return Ok(None)
