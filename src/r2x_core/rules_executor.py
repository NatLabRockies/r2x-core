"""Execute a set of rules for a given translation context."""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from infrasys import Component, SupplementalAttribute
from infrasys.exceptions import ISNotStored
from loguru import logger
from rust_ok import Err, Ok, Result

from .plugin_context import PluginContext
from .provenance import ProvenanceBuilder
from .result import RuleApplicationStats, RuleResult, TranslationResult
from .rules import Rule
from .time_series import transfer_time_series_metadata
from .utils import (
    RuleOutputs,
    build_target_fields,
    create_rule_outputs,
    create_target_component,
    evaluate_rule_filter,
    iter_components,
    resolve_component_type,
    sort_rules_by_dependencies,
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

    sorted_rules = sort_rules_by_dependencies(context.list_rules()).unwrap_or_raise(exc_type=ValueError)

    builder = _build_provenance_builder(context)

    rule_results: list[RuleResult] = []
    total_converted = 0
    successful_rules = 0
    failed_rules = 0

    for rule in sorted_rules:
        logger.debug("Applying rule: {}", rule)
        result = apply_single_rule(rule, context=context, builder=builder)

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

    if builder is not None and context.target_system is not None:
        builder.preserve_untranslated(context.target_system)

    ts_result = transfer_time_series_metadata(context)

    if builder is not None and context.target_system is not None:
        context.target_system.source_provenance_info = builder.finalize()

    return TranslationResult(
        total_rules=len(context.rules),
        successful_rules=successful_rules,
        failed_rules=failed_rules,
        total_converted=total_converted,
        rule_results=rule_results,
        time_series_transferred=ts_result.transferred,
        time_series_updated=ts_result.updated,
    )


def apply_single_rule(
    rule: Rule,
    *,
    context: PluginContext,
    builder: ProvenanceBuilder | None = None,
) -> Result[RuleApplicationStats, ValueError]:
    """Apply one transformation rule across matching components.

    Parameters
    ----------
    rule : Rule
        The rule to apply.
    context : PluginContext
        The plugin context containing rules and systems.
    builder : ProvenanceBuilder, optional
        When provided, each successfully translated target component is tagged
        with a :class:`SourceProvenance` supplemental attribute so a later
        reverse translation can restore the original source UUID.

    Returns
    -------
    Result[RuleApplicationStats, ValueError]
        Result containing application statistics or an error.
    """
    converted = 0
    target_types = rule.get_target_types()
    supplemental_rules = getattr(rule, "supplemental_attributes", ())
    if len(target_types) > 1 and supplemental_rules:
        return Err(ValueError("Rules with supplemental outputs must have exactly one primary target"))
    should_regenerate_uuid = len(target_types) > 1

    read_system = context.target_system if rule.system == "target" else context.source_system
    if read_system is None:
        return Err(ValueError(f"System '{rule.system}' is not set in context"))

    source_class_result = _resolve_source_class(rule, context=context)
    if source_class_result.is_err():
        return source_class_result.map(lambda _: RuleApplicationStats(converted=0, skipped=0))
    source_class = cast(type[Component], source_class_result.ok())

    resolved_targets: list[type[Component | SupplementalAttribute]] = []
    for target_type in target_types:
        target_class_result = _resolve_component_class(
            target_type, context=context, label="target", allow_supplemental=True
        )
        if target_class_result.is_err():
            return target_class_result.map(lambda _: RuleApplicationStats(converted=0, skipped=0))
        resolved_class = target_class_result.ok()
        assert resolved_class is not None
        resolved_targets.append(resolved_class)

    supplemental_classes: list[type[SupplementalAttribute]] = []
    for supplemental_rule in supplemental_rules:
        supplemental_class_result = resolve_supplemental_class(supplemental_rule.target_type, context=context)
        if supplemental_class_result.is_err():
            return Err(
                ValueError(
                    f"Rule '{rule.name or rule}', supplemental target "
                    f"'{supplemental_rule.target_type}': {supplemental_class_result.err()}"
                )
            )
        supplemental_class = supplemental_class_result.ok()
        assert supplemental_class is not None
        supplemental_classes.append(supplemental_class)

    if supplemental_rules:
        for target_class in resolved_targets:
            if issubclass(target_class, SupplementalAttribute):
                return Err(
                    ValueError("A rule with supplemental outputs must have a Component primary target")
                )

    found_component = False

    for src_component in iter_components(read_system, class_type=source_class):
        if rule.filter is not None:
            try:
                if not evaluate_rule_filter(src_component, rule_filter=rule.filter, context=context):
                    continue
            except ValueError as exc:
                return Err(ValueError(f"Failed to evaluate filter for {src_component.label}: {exc}"))
        found_component = True
        for target_class in resolved_targets:
            outputs_result = create_rule_outputs(
                src_component,
                rule=rule,
                target_class=cast(type[Component], target_class),
                supplemental_classes=supplemental_classes,
                context=context,
                regenerate_uuid=should_regenerate_uuid,
            ).map_err(
                lambda error, source_label=src_component.label: ValueError(
                    f"Rule '{rule.name or rule}', source '{source_label}': {error}"
                )
            )
            if outputs_result.is_err():
                return outputs_result.map(lambda _: RuleApplicationStats(converted=0, skipped=0))

            outputs = outputs_result.unwrap()
            attach_result = attach_rule_outputs(outputs, src_component, context)
            if attach_result.is_err():
                return attach_result.map_err(
                    lambda error, source_label=src_component.label: ValueError(
                        f"Rule '{rule.name or rule}', source '{source_label}': {error}"
                    )
                ).map(lambda _: RuleApplicationStats(converted=0, skipped=0))

            if builder is not None and rule.system == "source" and context.target_system is not None:
                builder.record_translation(src_component, outputs.primary, context.target_system)

            converted += 1

    if not found_component:
        logger.warning("No components found for source type '{}' in rule {}", rule.get_source_types(), rule)

    logger.debug("Rule {}: {} converted", rule, converted)
    return Ok(RuleApplicationStats(converted=converted, skipped=0))


def _build_provenance_builder(context: PluginContext) -> ProvenanceBuilder | None:
    """Return a provenance builder when the context opts into source preservation.

    Returns None when ``preserve_source`` is False or when the context is
    missing the source system that the builder needs to inspect.
    """
    if not context.preserve_source:
        return None
    if context.source_system is None:
        logger.warning("preserve_source=True but context has no source_system; skipping provenance capture")
        return None
    return ProvenanceBuilder(context.source_system)


def _convert_component_with_class(
    rule: Rule,
    source_component: Component,
    target_class: type[Component] | type[SupplementalAttribute],
    context: PluginContext,
    regenerate_uuid: bool,
) -> Result[Component | SupplementalAttribute, ValueError]:
    """Convert a single source component to a pre-resolved target class.

    Separated from type resolution so callers can resolve once and reuse.
    """
    fields_result = build_target_fields(source_component, rule=rule, context=context).map_err(
        lambda e: ValueError(f"Failed to build fields for {source_component.label}: {e}")
    )

    def create_component(kwargs: dict[str, Any]) -> Result[Component | SupplementalAttribute, ValueError]:
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
        return Ok(create_target_component(target_class, kwargs=kwargs))

    return fields_result.and_then(create_component)


def _convert_component(
    rule: Rule,
    source_component: Component,
    target_type: str,
    context: PluginContext,
    regenerate_uuid: bool,
) -> Result[Any, ValueError]:
    """Convert a single source component to a target type.

    Resolves the target class on every call. Prefer _convert_component_with_class
    when converting many components with the same rule to avoid repeated resolution.
    """
    target_class_result = _resolve_component_class(
        target_type, context=context, label="target", allow_supplemental=True
    )
    return target_class_result.and_then(
        lambda target_class: _convert_component_with_class(
            rule, source_component, target_class, context, regenerate_uuid
        )
    )


def _resolve_component_class(
    type_name: str,
    *,
    context: PluginContext,
    label: str,
    allow_supplemental: bool = False,
) -> Result[type[Component | SupplementalAttribute], ValueError]:
    """Resolve a named type and verify it is an infrasys component-compatible class."""
    class_result = resolve_component_type(type_name, context=context).map_err(
        lambda e: ValueError(f"Failed to resolve {label} type '{type_name}': {e}")
    )
    if class_result.is_err():
        return class_result.map(lambda _: Component)

    resolved_class = class_result.ok()
    is_component = isinstance(resolved_class, type) and issubclass(resolved_class, Component)
    is_supplemental = (
        allow_supplemental
        and isinstance(resolved_class, type)
        and issubclass(resolved_class, SupplementalAttribute)
    )
    if not (is_component or is_supplemental):
        expected = "Component or SupplementalAttribute" if allow_supplemental else "Component"
        return Err(ValueError(f"Resolved {label} type '{type_name}' is not a {expected} subclass"))

    assert resolved_class is not None
    return Ok(cast(type[Component] | type[SupplementalAttribute], resolved_class))


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

    return _resolve_component_class(source_type, context=context, label="source").map(
        lambda resolved_class: cast(type[Component], resolved_class)
    )


def resolve_supplemental_class(
    type_name: str, *, context: PluginContext
) -> Result[type[SupplementalAttribute], ValueError]:
    """Resolve and validate a supplemental-attribute output type."""
    class_result = _resolve_component_class(
        type_name, context=context, label="supplemental target", allow_supplemental=True
    )
    if class_result.is_err():
        return class_result.map(lambda _: SupplementalAttribute)
    resolved_class = class_result.ok()
    assert resolved_class is not None
    if not issubclass(resolved_class, SupplementalAttribute):
        return Err(
            ValueError(
                f"Resolved supplemental target type '{type_name}' is not a SupplementalAttribute subclass"
            )
        )
    return Ok(resolved_class)


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


def attach_rule_outputs(
    outputs: RuleOutputs,
    source_component: Component,
    context: PluginContext,
) -> Result[None, ValueError]:
    """Attach a primary output and its supplemental attributes as one operation."""
    target_system = context.target_system
    if target_system is None:
        return Err(ValueError("target_system must be set in context"))
    if outputs.supplemental_attributes and not isinstance(outputs.primary, Component):
        return Err(ValueError("A primary Component is required for supplemental outputs"))

    seen_supplemental_uuids = set()
    for supplemental_attribute in outputs.supplemental_attributes:
        if supplemental_attribute.uuid in seen_supplemental_uuids:
            return Err(
                ValueError(
                    f"Supplemental output UUID {supplemental_attribute.uuid} is duplicated in rule outputs"
                )
            )
        seen_supplemental_uuids.add(supplemental_attribute.uuid)
        try:
            target_system.get_supplemental_attribute_by_uuid(supplemental_attribute.uuid)
        except ISNotStored:
            continue
        except Exception as error:
            return Err(
                ValueError(
                    f"Failed to inspect supplemental output UUID {supplemental_attribute.uuid}: {error}"
                )
            )
        return Err(
            ValueError(
                f"Supplemental output UUID {supplemental_attribute.uuid} is already stored in target system"
            )
        )

    attached_supplemental: list[SupplementalAttribute] = []
    primary_attached = False

    def fail_with_rollback(error: ValueError) -> Result[None, ValueError]:
        """Return the attachment error after attempting to remove partial outputs."""
        rollback_result = _rollback_rule_outputs(outputs, attached_supplemental, primary_attached, context)
        if rollback_result.is_err():
            return Err(ValueError(f"{error}; {rollback_result.err()}"))
        return Err(error)

    try:
        attach_result = _attach_component(outputs.primary, source_component, context)
        if attach_result.is_err():
            return fail_with_rollback(attach_result.err())
        primary_attached = isinstance(outputs.primary, Component)

        for supplemental_attribute in outputs.supplemental_attributes:
            attach_result = _attach_component(supplemental_attribute, outputs.primary, context)
            if attach_result.is_err():
                return fail_with_rollback(attach_result.err())
            attached_supplemental.append(supplemental_attribute)
            logger.trace(
                "Attached supplemental attribute {} to {}",
                type(supplemental_attribute).__name__,
                outputs.primary.label,
            )
    except Exception as error:
        return fail_with_rollback(ValueError(f"Failed to attach rule outputs: {error}"))

    return Ok(None)


def _rollback_rule_outputs(
    outputs: RuleOutputs,
    supplemental_attributes: list[SupplementalAttribute],
    primary_attached: bool,
    context: PluginContext,
) -> Result[None, ValueError]:
    """Remove outputs already attached before a later attachment failed."""
    target_system = context.target_system
    if target_system is None:
        return Ok(None)

    rollback_errors: list[str] = []
    for supplemental_attribute in reversed(supplemental_attributes):
        try:
            target_system.remove_supplemental_attribute(supplemental_attribute)
        except Exception as error:
            rollback_errors.append(f"supplemental attribute: {error}")

    if primary_attached:
        try:
            target_system.remove_component(cast(Component, outputs.primary))
        except Exception as error:
            rollback_errors.append(f"primary component: {error}")

    if rollback_errors:
        return Err(ValueError(f"Failed to roll back rule outputs: {'; '.join(rollback_errors)}"))
    return Ok(None)


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
