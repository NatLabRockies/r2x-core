"""Execute shared construction rules against Systems or named datasets."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType, UnionType
from typing import Annotated, Literal, Union, get_args, get_origin

import numpy as np
import polars as pl
from infrasys import Component, SingleTimeSeries, SupplementalAttribute
from infrasys.exceptions import ISBaseException, ISNotStored
from loguru import logger
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from rust_ok import Err, Ok, Result

from .exceptions import ReaderError
from .plugin_context import PluginContext
from .provenance import ProvenanceBuilder
from .result import RuleApplicationStats, RuleIssue, RuleResult, TranslationResult
from .rules import (
    ComponentSource,
    ComponentTarget,
    DatasetSource,
    FixedMappingRoute,
    MappingRoute,
    MappingSelection,
    OwnedSupplementalTarget,
    OwnerTarget,
    Rule,
    RuleLike,
    RuleMapping,
    RulePlanDocument,
    TimeSeriesTarget,
)
from .time_series import transfer_time_series_metadata
from .utils import (
    RuleOutputs,
    create_rule_outputs,
    evaluate_rule_filter,
    iter_components,
    resolve_component_type,
    to_attr_source,
)
from .utils import (
    sort_rules_by_dependencies as sort_rule_dependencies,
)


@dataclass(frozen=True, slots=True)
class ResolvedRuleMapping:
    """One shared mapping with output and owner models resolved against a PluginContext."""

    mapping: RuleMapping
    target_types: tuple[type[Component | SupplementalAttribute], ...]
    nested_types: tuple[type[SupplementalAttribute], ...]
    owner_type: type[Component] | None


@dataclass(frozen=True, slots=True)
class ResolvedMappingSelection:
    """One mapping selection with every named output resolved during plan validation."""

    selection: MappingSelection
    mappings_by_key: Mapping[str, ResolvedRuleMapping]


@dataclass(frozen=True, slots=True)
class ResolvedRule:
    """Executable Rule with source and shared mapping models resolved once."""

    rule: Rule
    source_type: type[Component] | None
    mapping: ResolvedRuleMapping

    @property
    def target_types(self) -> tuple[type[Component | SupplementalAttribute], ...]:
        """Return the resolved output models from the shared mapping."""
        return self.mapping.target_types

    @property
    def nested_types(self) -> tuple[type[SupplementalAttribute], ...]:
        """Return the resolved same-source supplemental models."""
        return self.mapping.nested_types

    @property
    def owner_type(self) -> type[Component] | None:
        """Return the resolved owner model for independently attached attributes."""
        return self.mapping.owner_type


@dataclass(frozen=True, slots=True)
class RulePlan:
    """Validated shared mappings, executable Rules, and explicit stage indexes."""

    mappings_by_name: Mapping[str, ResolvedRuleMapping]
    rules_by_name: Mapping[str, ResolvedRule]
    selections_by_name: Mapping[str, ResolvedMappingSelection]
    stages_by_name: Mapping[str, tuple[ResolvedRule, ...]]
    mapping_names_by_target: Mapping[str, tuple[str, ...]]

    @classmethod
    def from_mapping(
        cls,
        source: object,
        *,
        context: PluginContext,
    ) -> Result[RulePlan, ValueError]:
        """Validate a RulePlan envelope, resolving every target and named input once."""
        try:
            document = RulePlanDocument.model_validate(source)
        except (PydanticValidationError, TypeError, ValueError) as error:
            return Err(ValueError(f"Invalid RulePlan configuration: {error}"))

        if document.required_datasets:
            if context.store is None:
                return Err(
                    ValueError("RulePlan declares required datasets but PluginContext has no DataStore")
                )
            for dataset in document.required_datasets:
                if dataset not in context.store:
                    return Err(ValueError(f"Required RulePlan dataset {dataset!r} is not registered"))
                if context.store.is_optional(dataset):
                    return Err(ValueError(f"Required RulePlan dataset {dataset!r} is marked optional"))

        mappings_by_name: dict[str, ResolvedRuleMapping] = {}
        mapping_names_by_target: dict[str, list[str]] = {}
        for mapping in document.mappings:
            if mapping.name is None:
                return Err(ValueError("Every RulePlan mapping must have a name"))
            match resolve_rule_mapping(mapping, context=context):
                case Err(error):
                    return Err(ValueError(f"Invalid mapping {mapping.name!r}: {error}"))
                case Ok(resolved_mapping):
                    mappings_by_name[mapping.name] = resolved_mapping
                    for target_name in (
                        mapping.target.component_types
                        if isinstance(mapping.target, ComponentTarget)
                        else (mapping.target.owner_type,)
                        if isinstance(mapping.target, TimeSeriesTarget)
                        else (mapping.target.attribute_type,)
                    ):
                        mapping_names_by_target.setdefault(target_name, []).append(mapping.name)

        selections_by_name: dict[str, ResolvedMappingSelection] = {}
        for selection in document.mapping_selections:
            mappings_for_key: dict[str, ResolvedRuleMapping] = {}
            for key, mapping_name in selection.by_key.items():
                resolved_mapping = mappings_by_name[mapping_name]
                if not isinstance(resolved_mapping.mapping.target, ComponentTarget):
                    return Err(
                        ValueError(
                            f"Selection {selection.name!r} mapping {mapping_name!r} must target Components"
                        )
                    )
                if len(resolved_mapping.target_types) != 1:
                    return Err(
                        ValueError(
                            f"Selection {selection.name!r} mapping {mapping_name!r} must have one Component target"
                        )
                    )
                mappings_for_key[key] = resolved_mapping
            selections_by_name[selection.name] = ResolvedMappingSelection(
                selection=selection,
                mappings_by_key=MappingProxyType(mappings_for_key),
            )

        rules_by_name: dict[str, ResolvedRule] = {}
        for rule in document.rules:
            if rule.name is None:
                return Err(ValueError("Every RulePlan Rule must have a name"))
            if rule.mapping_ref is not None:
                shared_mapping = mappings_by_name.get(rule.mapping_ref)
                if shared_mapping is None:
                    return Err(
                        ValueError(f"Rule {rule.name!r} references unknown mapping {rule.mapping_ref!r}")
                    )
                if rule.target != shared_mapping.mapping.target:
                    return Err(
                        ValueError(f"Rule {rule.name!r} target does not match mapping {rule.mapping_ref!r}")
                    )
                source_type = resolve_rule_source(rule, context=context)
                if source_type.is_err():
                    return Err(ValueError(f"Invalid Rule {rule.name!r}: {source_type.err()}"))
                source_class = source_type.unwrap()
                if isinstance(rule.target, OwnedSupplementalTarget) and isinstance(
                    rule.source, ComponentSource
                ):
                    source_fields = set(source_class.model_fields) if source_class is not None else set()
                    missing_fields = sorted(set(owner_source_fields(rule.target)) - source_fields)
                    if missing_fields:
                        return Err(
                            ValueError(
                                f"Invalid Rule {rule.name!r}: owner-match source fields are missing: "
                                f"{missing_fields}"
                            )
                        )
                rules_by_name[rule.name] = ResolvedRule(
                    rule=rule,
                    source_type=source_class,
                    mapping=shared_mapping,
                )
            else:
                match resolve_rule(rule, context=context):
                    case Err(error):
                        return Err(ValueError(f"Invalid Rule {rule.name!r}: {error}"))
                    case Ok(resolved_rule):
                        rules_by_name[rule.name] = resolved_rule

        stages_by_name: dict[str, tuple[ResolvedRule, ...]] = {}
        rule_positions: dict[str, tuple[int, int]] = {}
        for stage_index, stage in enumerate(document.execution):
            staged_rules = tuple(rules_by_name[name] for name in stage.rules)
            stages_by_name[stage.name] = staged_rules
            for rule_index, rule in enumerate(staged_rules):
                rule_positions[rule.rule.name or ""] = (stage_index, rule_index)
        for rule_name, resolved_rule in rules_by_name.items():
            position = rule_positions.get(rule_name)
            if position is None and resolved_rule.rule.depends_on:
                return Err(ValueError(f"Rule {rule_name!r} has dependencies but is not assigned to a stage"))
            for dependency in resolved_rule.rule.depends_on:
                dependency_position = rule_positions.get(dependency)
                if dependency_position is None:
                    return Err(
                        ValueError(f"Rule {rule_name!r} dependency {dependency!r} is not assigned to a stage")
                    )
                if position is not None and dependency_position >= position:
                    return Err(
                        ValueError(
                            f"RulePlan stage order places dependency {dependency!r} after {rule_name!r}"
                        )
                    )

        return Ok(
            cls(
                mappings_by_name=MappingProxyType(mappings_by_name),
                rules_by_name=MappingProxyType(rules_by_name),
                selections_by_name=MappingProxyType(selections_by_name),
                stages_by_name=MappingProxyType(stages_by_name),
                mapping_names_by_target=MappingProxyType(
                    {name: tuple(mapping_names) for name, mapping_names in mapping_names_by_target.items()}
                ),
            )
        )

    def get_mapping(self, name: str) -> Result[ResolvedRuleMapping, ValueError]:
        """Return one named construction mapping, including an executable Rule mapping."""
        mapping = self.mappings_by_name.get(name)
        if mapping is not None:
            return Ok(mapping)
        rule = self.rules_by_name.get(name)
        if rule is not None:
            return Ok(rule.mapping)
        return Err(ValueError(f"No RulePlan mapping named {name!r}"))

    def get_selection(self, name: str) -> Result[ResolvedMappingSelection, ValueError]:
        """Return one uniquely named, prevalidated mapping selection."""
        try:
            return Ok(self.selections_by_name[name])
        except KeyError:
            return Err(ValueError(f"No RulePlan mapping selection named {name!r}"))

    def get_rule(self, name: str) -> Result[ResolvedRule, ValueError]:
        """Return one uniquely named, prevalidated executable Rule."""
        try:
            return Ok(self.rules_by_name[name])
        except KeyError:
            return Err(ValueError(f"No RulePlan Rule named {name!r}"))

    def mapping_for_target(
        self, target_type: str, *, name: str | None = None
    ) -> Result[ResolvedRuleMapping, ValueError]:
        """Resolve an explicit mapping name or one unambiguous target mapping."""
        candidates = self.mapping_names_by_target.get(target_type, ())
        if name is not None:
            if name not in candidates:
                return Err(ValueError(f"No mapping named {name!r} targets {target_type!r}"))
            return self.get_mapping(name)
        if not candidates:
            return Err(ValueError(f"No mapping targets {target_type!r}"))
        if len(candidates) > 1:
            return Err(ValueError(f"Multiple mappings target {target_type!r}: {candidates}"))
        return self.get_mapping(candidates[0])

    def stage(self, name: str) -> Result[tuple[ResolvedRule, ...], ValueError]:
        """Return one explicitly ordered, prevalidated stage."""
        try:
            return Ok(self.stages_by_name[name])
        except KeyError:
            return Err(ValueError(f"No RulePlan stage named {name!r}"))


@dataclass(frozen=True, slots=True)
class PreparedRuleOutputs:
    """Constructed output group and its independently resolved owner, if any."""

    outputs: tuple[RuleOutputs, ...]
    owner: Component | None


@dataclass(frozen=True, slots=True)
class OwnerMatchIndex:
    """Typed owner lookup built once for one rule execution against one System."""

    target: OwnerTarget
    owners_by_key: Mapping[tuple[object, ...], tuple[Component, ...]]


class RuleExecutionError(ValueError):
    """Structured rule failure retaining row issues and completed output counts."""

    def __init__(
        self,
        message: str,
        *,
        rule: str | None = None,
        mapping: str | None = None,
        dataset: str | None = None,
        converted: int = 0,
        skipped: int = 0,
        issues: Iterable[RuleIssue] = (),
    ) -> None:
        self.rule = rule
        self.mapping = mapping
        self.dataset = dataset
        self.converted = converted
        self.skipped = skipped
        self.issues = tuple(issues)
        details = "; ".join(
            f"row {issue.row}: {issue.message}" if issue.row is not None else issue.message
            for issue in self.issues
        )
        label = (
            f"Rule {rule!r}"
            if rule is not None
            else f"Mapping {mapping!r}"
            if mapping is not None
            else "Rule"
        )
        if dataset is not None:
            label += f" on dataset {dataset!r}"
        super().__init__(f"{label}: {message}" + (f" ({details})" if details else ""))


def apply_rules_to_context(
    context: PluginContext,
    /,
    *,
    on_error: Literal["stop", "continue"],
    plan: RulePlan | None = None,
    stage: str | None = None,
) -> TranslationResult:
    """Execute context Rules or one explicitly named stage from a validated RulePlan.

    Configuration, source-System requirements, target types, and mapped target
    fields are validated before the first System mutation. ``continue`` proceeds
    after a runtime rule failure; ``stop`` returns after the first failure.
    Dependency edges order rules but do not gate dependents under ``continue``.
    Successful earlier outputs remain attached when a later rule fails.
    """
    if on_error not in {"stop", "continue"}:
        raise ValueError("on_error must be 'stop' or 'continue'")
    if context.target_system is None:
        raise ValueError("target_system must be set in context")

    if plan is not None:
        if stage is None:
            raise ValueError("A RulePlan invocation must select an explicit stage")
        if context.rules:
            raise ValueError("Use either context.rules or a RulePlan stage, not both")
        match plan.stage(stage):
            case Err(error):
                raise error
            case Ok(selected_rules):
                resolved_rules = list(selected_rules)
    else:
        if stage is not None:
            raise ValueError("stage requires a validated RulePlan")
        if not context.rules:
            raise ValueError(f"{type(context).__name__} has no rules. Use context.list_rules().")
        sorted_rules = sort_rule_dependencies(list(context.rules)).unwrap_or_raise(exc_type=ValueError)
        resolved_rules = []
        for rule in sorted_rules:
            match resolve_rule(rule, context=context):
                case Ok(resolved):
                    resolved_rules.append(resolved)
                case Err(error):
                    raise ValueError(f"Invalid rule '{rule.name or rule}': {error}") from error

    for resolved in resolved_rules:
        source = resolved.rule.source
        if isinstance(source, ComponentSource):
            source_system = context.source_system if source.system == "source" else context.target_system
            if source_system is None:
                raise ValueError(f"Required {source.system} source System is not set in context")

    selected_rule_values = [resolved.rule for resolved in resolved_rules]
    has_translation_sources = any(
        isinstance(rule.source, ComponentSource) and rule.source.system == "source"
        for rule in selected_rule_values
    )
    provenance_builder = build_provenance_builder(context) if has_translation_sources else None
    rule_results: list[RuleResult] = []
    total_converted = 0
    successful_rules = 0
    failed_rules = 0

    for resolved in resolved_rules:
        rule = resolved.rule
        logger.debug("Applying rule: {}", rule)
        result = execute_rule(resolved, context=context, builder=provenance_builder)
        match result:
            case Ok(stats):
                rule_results.append(
                    RuleResult(
                        rule=rule,
                        converted=stats.converted,
                        skipped=stats.skipped,
                        success=True,
                    )
                )
                total_converted += stats.converted
                successful_rules += 1
            case Err(error):
                logger.error("Rule {} failed: {}", rule, error)
                converted = error.converted if isinstance(error, RuleExecutionError) else 0
                skipped = error.skipped if isinstance(error, RuleExecutionError) else 0
                issues = error.issues if isinstance(error, RuleExecutionError) else ()
                rule_results.append(
                    RuleResult(
                        rule=rule,
                        converted=converted,
                        skipped=skipped,
                        success=False,
                        error=str(error),
                        issues=issues,
                    )
                )
                total_converted += converted
                failed_rules += 1
                if on_error == "stop":
                    break

    if has_translation_sources:
        if provenance_builder is not None:
            provenance_builder.preserve_untranslated(context.target_system)
        time_series_result = transfer_time_series_metadata(context)
        if provenance_builder is not None:
            context.target_system.source_provenance_info = provenance_builder.finalize()
    else:
        time_series_result = None

    return TranslationResult(
        total_rules=len(resolved_rules),
        successful_rules=successful_rules,
        failed_rules=failed_rules,
        total_converted=total_converted,
        rule_results=rule_results,
        time_series_transferred=0 if time_series_result is None else time_series_result.transferred,
        time_series_updated=0 if time_series_result is None else time_series_result.updated,
    )


def resolve_rule(rule: Rule, *, context: PluginContext) -> Result[ResolvedRule, ValueError]:
    """Resolve one standalone Rule with its inline mapping against a context."""
    if rule.mapping_ref is not None:
        return Err(
            ValueError(
                f"Rule {rule.name!r} references shared mapping {rule.mapping_ref!r}; "
                "resolve it through a RulePlan"
            )
        )
    source_result = resolve_rule_source(rule, context=context)
    if source_result.is_err():
        return Err(source_result.err())
    source_type = source_result.unwrap()

    mapping_result = resolve_rule_mapping(rule, context=context)
    if mapping_result.is_err():
        return Err(mapping_result.err())
    resolved_mapping = mapping_result.unwrap()
    if isinstance(rule.target, OwnedSupplementalTarget) and isinstance(rule.source, ComponentSource):
        source_fields = set(source_type.model_fields) if source_type is not None else set()
        required_owner_fields = set(owner_source_fields(rule.target))
        missing_fields = sorted(required_owner_fields - source_fields)
        if missing_fields:
            return Err(
                ValueError(f"Owner-match source field(s) are missing from the Component: {missing_fields}")
            )
    return Ok(ResolvedRule(rule=rule, source_type=source_type, mapping=resolved_mapping))


def resolve_rule_source(rule: Rule, *, context: PluginContext) -> Result[type[Component] | None, ValueError]:
    """Resolve a Rule's explicitly declared source independently of its mapping."""
    if isinstance(rule.source, ComponentSource):
        source_result = resolve_component_type(rule.source.component_type, context=context)
        if source_result.is_err():
            return Err(
                ValueError(
                    f"Could not resolve source type {rule.source.component_type!r}: {source_result.err()}"
                )
            )
        source_class = source_result.ok()
        if not isinstance(source_class, type) or not issubclass(source_class, Component):
            return Err(ValueError(f"Source type {rule.source.component_type!r} is not a Component"))
        return Ok(source_class)
    if context.store is None:
        return Err(ValueError("DatasetSource requires a DataStore"))
    if rule.source.dataset not in context.store:
        return Err(ValueError(f"Dataset {rule.source.dataset!r} is not registered in the DataStore"))
    return Ok(None)


def resolve_rule_mapping(
    mapping: RuleMapping, *, context: PluginContext
) -> Result[ResolvedRuleMapping, ValueError]:
    """Resolve target, nested attribute, owner models, and all mapped fields once."""
    target_types: list[type[Component | SupplementalAttribute]] = []
    nested_types: list[type[SupplementalAttribute]] = []
    owner_type: type[Component] | None = None
    if isinstance(mapping.target, ComponentTarget):
        for type_name in mapping.target.component_types:
            match resolve_output_type(type_name, context=context):
                case Err(error):
                    return Err(error)
                case Ok(target_class) if issubclass(target_class, Component):
                    fields_error = mapping_fields_error(target_class, mapping)
                    if fields_error is not None:
                        return Err(fields_error)
                    target_types.append(target_class)
                case Ok(_):
                    return Err(ValueError(f"Target type {type_name!r} is not a Component"))
        for nested_rule in mapping.supplemental_attributes:
            match resolve_output_type(nested_rule.target_type, context=context):
                case Err(error):
                    return Err(error)
                case Ok(nested_class) if issubclass(nested_class, SupplementalAttribute):
                    fields_error = mapping_fields_error(nested_class, nested_rule)
                    if fields_error is not None:
                        return Err(fields_error)
                    nested_types.append(nested_class)
                case Ok(_):
                    return Err(
                        ValueError(
                            f"Nested target {nested_rule.target_type!r} is not a SupplementalAttribute"
                        )
                    )
    elif isinstance(mapping.target, TimeSeriesTarget):
        match resolve_output_type(mapping.target.owner_type, context=context):
            case Err(error):
                return Err(error)
            case Ok(owner_class) if issubclass(owner_class, Component):
                owner_type = owner_class
                for owner_path in mapping.target.owner_match.values():
                    path_error = validate_owner_path(owner_class, owner_path)
                    if path_error is not None:
                        return Err(path_error)
            case Ok(_):
                return Err(ValueError(f"Owner type {mapping.target.owner_type!r} is not a Component"))
    else:
        match resolve_output_type(mapping.target.attribute_type, context=context):
            case Err(error):
                return Err(error)
            case Ok(attribute_class) if issubclass(attribute_class, SupplementalAttribute):
                fields_error = mapping_fields_error(attribute_class, mapping)
                if fields_error is not None:
                    return Err(fields_error)
                target_types.append(attribute_class)
            case Ok(_):
                return Err(
                    ValueError(
                        f"Owned target {mapping.target.attribute_type!r} is not a SupplementalAttribute"
                    )
                )
        match resolve_output_type(mapping.target.owner_type, context=context):
            case Err(error):
                return Err(error)
            case Ok(owner_class) if issubclass(owner_class, Component):
                owner_type = owner_class
                for owner_path in mapping.target.owner_match.values():
                    path_error = validate_owner_path(owner_class, owner_path)
                    if path_error is not None:
                        return Err(path_error)
            case Ok(_):
                return Err(ValueError(f"Owner type {mapping.target.owner_type!r} is not a Component"))
    return Ok(
        ResolvedRuleMapping(
            mapping=mapping,
            target_types=tuple(target_types),
            nested_types=tuple(nested_types),
            owner_type=owner_type,
        )
    )


def resolve_output_type(
    type_name: str, *, context: PluginContext
) -> Result[type[Component | SupplementalAttribute], ValueError]:
    """Resolve one Component or SupplementalAttribute output type."""
    resolution = resolve_component_type(type_name, context=context)
    if resolution.is_err():
        return Err(ValueError(f"Could not resolve output type {type_name!r}: {resolution.err()}"))
    model_type = resolution.unwrap()
    if not isinstance(model_type, type) or not issubclass(model_type, (Component, SupplementalAttribute)):
        return Err(
            ValueError(f"Resolved output type {type_name!r} is not a Component or SupplementalAttribute")
        )
    return Ok(model_type)


def mapping_fields_error(target_type: type[BaseModel], mapping: RuleLike) -> ValueError | None:
    """Reject mapping, getter, or default names absent from a target model."""
    known_fields = set(target_type.model_fields)
    configured_fields = set(mapping.field_map) | set(mapping.getters) | set(mapping.defaults)
    unknown_fields = sorted(configured_fields - known_fields)
    if unknown_fields:
        return ValueError(f"Rule maps unknown target field(s) for {target_type.__name__}: {unknown_fields}")
    return None


def build_rule_outputs(
    source: Component | Mapping[str, object],
    /,
    *,
    mapping: RuleMapping,
    context: PluginContext,
) -> Result[tuple[RuleOutputs, ...], ValueError]:
    """Build detached outputs from a record using the shared Rule mapping contract."""
    resolution = resolve_rule_mapping(mapping, context=context)
    if resolution.is_err():
        return Err(resolution.err())
    resolved = resolution.unwrap()
    if not isinstance(mapping.target, ComponentTarget):
        return Err(ValueError("Detached component construction requires a ComponentTarget"))
    outputs: list[RuleOutputs] = []
    for target_class in resolved.target_types:
        if not isinstance(target_class, type) or not issubclass(target_class, Component):
            return Err(ValueError(f"Resolved target {target_class.__name__} is not a Component"))
        output_result = create_rule_outputs(
            source,
            rule=mapping,
            target_class=target_class,
            supplemental_classes=resolved.nested_types,
            context=context,
            regenerate_uuid=len(resolved.target_types) > 1,
        )
        if output_result.is_err():
            return Err(output_result.err())
        outputs.append(output_result.unwrap())
    return Ok(tuple(outputs))


def execute_rule(
    resolved: ResolvedRule,
    *,
    context: PluginContext,
    builder: ProvenanceBuilder | None,
) -> Result[RuleApplicationStats, RuleExecutionError]:
    """Read or select source records, then use one preparation and attachment path."""
    rule = resolved.rule
    owner_index: OwnerMatchIndex | None = None
    if isinstance(rule.target, OwnerTarget):
        if resolved.owner_type is None:
            return Err(RuleExecutionError("Owner target has no resolved owner type", rule=rule.name))
        match build_owner_match_index(rule.target, resolved.owner_type, context=context):
            case Err(error):
                return Err(RuleExecutionError(str(error), rule=rule.name))
            case Ok(index):
                owner_index = index
    if isinstance(rule.source, ComponentSource):
        if resolved.source_type is None:
            return Err(RuleExecutionError("ComponentSource has no resolved type", rule=rule.name))
        source_system = context.source_system if rule.source.system == "source" else context.target_system
        if source_system is None:
            return Err(RuleExecutionError("Required source System is not set", rule=rule.name))
        records: Iterable[Component | Mapping[str, object]] = iter_components(
            source_system,
            class_type=resolved.source_type,
        )
        return execute_rule_records(
            records,
            resolved=resolved,
            context=context,
            builder=builder,
            prevalidate_batch=False,
            owner_index=owner_index,
        )

    if not isinstance(rule.source, DatasetSource) or context.store is None:
        return Err(RuleExecutionError("DatasetSource requires a DataStore", rule=rule.name))
    try:
        data = context.store.read_data(
            rule.source.dataset,
            placeholders={**context.metadata, **context.config.model_dump()},
            context=context,
        )
    except (OSError, ValueError, KeyError, ReaderError, pl.exceptions.PolarsError) as error:
        return Err(
            RuleExecutionError(
                f"Could not read source dataset: {error}",
                rule=rule.name,
                dataset=rule.source.dataset,
            )
        )
    if data is None:
        if context.store.is_optional(rule.source.dataset):
            logger.info("Optional dataset '{}' is absent, skipping rule {}", rule.source.dataset, rule)
            return Ok(RuleApplicationStats(converted=0, skipped=1))
        return Err(
            RuleExecutionError(
                "Required dataset returned no data",
                rule=rule.name,
                dataset=rule.source.dataset,
            )
        )
    if not isinstance(data, (pl.DataFrame, pl.LazyFrame)):
        return Err(
            RuleExecutionError(
                f"Source returned {type(data).__name__}, expected a Polars frame",
                rule=rule.name,
                dataset=rule.source.dataset,
            )
        )
    try:
        frame = data.collect() if isinstance(data, pl.LazyFrame) else data
    except (OSError, ValueError, pl.exceptions.PolarsError) as error:
        return Err(
            RuleExecutionError(
                f"Could not collect source dataset: {error}",
                rule=rule.name,
                dataset=rule.source.dataset,
            )
        )
    if isinstance(rule.target, TimeSeriesTarget):
        if owner_index is None:
            return Err(RuleExecutionError("TimeSeriesTarget has no owner index", rule=rule.name))
        return execute_time_series_frame(
            frame,
            target=rule.target,
            owner_index=owner_index,
            context=context,
            rule_name=rule.name,
            dataset_name=rule.source.dataset,
        )
    if isinstance(rule.target, OwnedSupplementalTarget):
        missing_fields = sorted(set(owner_source_fields(rule.target)) - set(frame.columns))
        if missing_fields:
            return Err(
                RuleExecutionError(
                    f"Owner-match source field(s) are missing from dataset: {missing_fields}",
                    rule=rule.name,
                    dataset=rule.source.dataset,
                )
            )
    return execute_rule_records(
        frame.iter_rows(named=True),
        resolved=resolved,
        context=context,
        builder=None,
        prevalidate_batch=True,
        owner_index=owner_index,
    )


def execute_time_series_frame(
    frame: pl.DataFrame,
    /,
    *,
    target: TimeSeriesTarget,
    owner_index: OwnerMatchIndex,
    context: PluginContext,
    rule_name: str | None,
    dataset_name: str,
) -> Result[RuleApplicationStats, RuleExecutionError]:
    """Validate grouped profile rows and attach declared SingleTimeSeries outputs."""
    target_system = context.target_system
    if target_system is None:
        return Err(RuleExecutionError("target_system is not set", rule=rule_name, dataset=dataset_name))
    required_columns = {
        *owner_source_fields(target),
        *target.metadata_columns.values(),
        target.hour_column,
        target.value_column,
    }
    if target.initial_timestamp_column is not None:
        required_columns.add(target.initial_timestamp_column)
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        return Err(
            RuleExecutionError(
                f"Time-series source is missing required columns: {missing_columns}",
                rule=rule_name,
                dataset=dataset_name,
            )
        )
    if frame.is_empty():
        return Ok(RuleApplicationStats(converted=0, skipped=0))

    group_columns = list(dict.fromkeys([*owner_source_fields(target), *target.metadata_columns.values()]))
    groups = frame.partition_by(group_columns, maintain_order=True)
    pending: list[tuple[Component, SingleTimeSeries, dict[str, object]]] = []
    skipped = 0
    for group in groups:
        ordered = group.sort(target.hour_column, maintain_order=True)
        hours = ordered[target.hour_column].to_list()
        if hours != list(range(len(hours))):
            return Err(
                RuleExecutionError(
                    f"Time-series hour column {target.hour_column!r} must be unique and contiguous from zero",
                    rule=rule_name,
                    dataset=dataset_name,
                )
            )
        if target.expected_samples is not None and len(hours) != target.expected_samples:
            return Err(
                RuleExecutionError(
                    f"Time-series group has {len(hours)} samples, expected {target.expected_samples}",
                    rule=rule_name,
                    dataset=dataset_name,
                )
            )
        values = ordered[target.value_column].to_list()
        if any(value is None for value in values):
            return Err(
                RuleExecutionError(
                    f"Time-series value column {target.value_column!r} contains null samples",
                    rule=rule_name,
                    dataset=dataset_name,
                )
            )
        try:
            data = np.asarray(values, dtype=np.float32 if target.value_dtype == "float32" else np.float64)
        except (TypeError, ValueError) as error:
            return Err(
                RuleExecutionError(
                    f"Time-series values cannot be cast to {target.value_dtype}: {error}",
                    rule=rule_name,
                    dataset=dataset_name,
                )
            )

        if target.initial_timestamp_column is None:
            initial_timestamp = target.initial_timestamp
        else:
            timestamps = ordered[target.initial_timestamp_column].to_list()
            initial_timestamp = timestamps[0]
            if not isinstance(initial_timestamp, datetime):
                return Err(
                    RuleExecutionError(
                        f"Initial timestamp column {target.initial_timestamp_column!r} must contain datetimes",
                        rule=rule_name,
                        dataset=dataset_name,
                    )
                )
            expected_timestamps = [
                initial_timestamp + timedelta(seconds=index * target.resolution_seconds)
                for index in range(len(timestamps))
            ]
            if timestamps != expected_timestamps:
                return Err(
                    RuleExecutionError(
                        f"Time-series timestamps in {target.initial_timestamp_column!r} do not match "
                        "the configured hour order and resolution",
                        rule=rule_name,
                        dataset=dataset_name,
                    )
                )
        if initial_timestamp is None:
            return Err(
                RuleExecutionError(
                    "TimeSeriesTarget has no initial timestamp", rule=rule_name, dataset=dataset_name
                )
            )

        owner_result = resolve_record_owner(ordered.row(0, named=True), owner_index)
        if owner_result.is_err():
            return Err(RuleExecutionError(str(owner_result.err()), rule=rule_name, dataset=dataset_name))
        owner = owner_result.unwrap()
        if owner is None:
            skipped += 1
            continue

        features: dict[str, object] = {}
        for feature, column in target.metadata_columns.items():
            feature_values = ordered[column].unique().to_list()
            if len(feature_values) != 1 or feature_values[0] is None:
                return Err(
                    RuleExecutionError(
                        f"Time-series metadata column {column!r} must have one non-null value per group",
                        rule=rule_name,
                        dataset=dataset_name,
                    )
                )
            features[feature] = feature_values[0]
        try:
            series = SingleTimeSeries.from_array(
                data=data,
                name=target.name,
                initial_timestamp=initial_timestamp,
                resolution=timedelta(seconds=target.resolution_seconds),
            )
        except (ISBaseException, PydanticValidationError, TypeError, ValueError) as error:
            return Err(
                RuleExecutionError(
                    f"Could not construct time series {target.name!r}: {error}",
                    rule=rule_name,
                    dataset=dataset_name,
                )
            )
        pending.append((owner, series, features))

    for owner, _, features in pending:
        try:
            existing = target_system.list_time_series_keys(
                owner,
                name=target.name,
                time_series_type=SingleTimeSeries,
                **features,
            )
        except (ISBaseException, TypeError, ValueError) as error:
            return Err(
                RuleExecutionError(
                    f"Could not inspect existing time series {target.name!r}: {error}",
                    rule=rule_name,
                    dataset=dataset_name,
                )
            )
        if existing:
            return Err(
                RuleExecutionError(
                    f"Owner {owner.name!r} already has time series {target.name!r} with features {features}",
                    rule=rule_name,
                    dataset=dataset_name,
                )
            )

    converted = 0
    for owner, series, features in pending:
        try:
            target_system.add_time_series(series, owner, context=None, **features)
        except (ISBaseException, PydanticValidationError, TypeError, ValueError) as error:
            return Err(
                RuleExecutionError(
                    f"Could not attach time series {target.name!r}: {error}",
                    rule=rule_name,
                    dataset=dataset_name,
                    converted=converted,
                )
            )
        converted += 1
    return Ok(RuleApplicationStats(converted=converted, skipped=skipped))


def execute_rule_records(
    records: Iterable[Component | Mapping[str, object]],
    /,
    *,
    resolved: ResolvedRule,
    context: PluginContext,
    builder: ProvenanceBuilder | None,
    prevalidate_batch: bool,
    owner_index: OwnerMatchIndex | None,
) -> Result[RuleApplicationStats, RuleExecutionError]:
    """Run executable Rule records through the shared mapping executor."""
    rule = resolved.rule
    dataset_name = rule.source.dataset if isinstance(rule.source, DatasetSource) else None
    return execute_mapped_records(
        records,
        mapping_for_record=lambda record: Ok(resolved.mapping),
        context=context,
        builder=builder,
        prevalidate_batch=prevalidate_batch,
        rule_name=rule.name,
        mapping_name=None,
        dataset_name=dataset_name,
        owner_indexes={id(resolved.mapping): owner_index} if owner_index is not None else {},
    )


def execute_mapped_records(
    records: Iterable[Component | Mapping[str, object]],
    /,
    *,
    mapping_for_record: Callable[[Component | Mapping[str, object]], Result[ResolvedRuleMapping, ValueError]],
    context: PluginContext,
    builder: ProvenanceBuilder | None,
    prevalidate_batch: bool,
    rule_name: str | None,
    mapping_name: str | None,
    dataset_name: str | None,
    duplicate_policy: Literal["error", "first"] | None = None,
    duplicate_identity: Literal["target_type_and_name", "name"] = "target_type_and_name",
    owner_indexes: Mapping[int, OwnerMatchIndex | None] | None = None,
) -> Result[RuleApplicationStats, RuleExecutionError]:
    """Prepare, validate, de-duplicate, and attach records through one Rule path."""
    staged: list[tuple[int, Component | Mapping[str, object], PreparedRuleOutputs]] = []
    issues: list[RuleIssue] = []
    converted = 0
    skipped = 0
    seen_identities: set[tuple[object, ...]] = set()
    resolved_owner_indexes: dict[int, OwnerMatchIndex | None] = dict(owner_indexes or {})

    def owner_index_for(resolved_mapping: ResolvedRuleMapping) -> Result[OwnerMatchIndex | None, ValueError]:
        key = id(resolved_mapping)
        if key in resolved_owner_indexes:
            return Ok(resolved_owner_indexes[key])
        if not isinstance(resolved_mapping.mapping.target, OwnerTarget):
            resolved_owner_indexes[key] = None
            return Ok(None)
        if resolved_mapping.owner_type is None:
            return Err(ValueError("Owned target has no resolved owner type"))
        result = build_owner_match_index(
            resolved_mapping.mapping.target,
            resolved_mapping.owner_type,
            context=context,
        )
        if result.is_err():
            return Err(result.err())
        index = result.unwrap()
        resolved_owner_indexes[key] = index
        return Ok(index)

    def execution_error(
        message: str,
        *,
        count: int,
        issues_override: tuple[RuleIssue, ...] | None = None,
    ) -> RuleExecutionError:
        return RuleExecutionError(
            message,
            rule=rule_name,
            mapping=mapping_name,
            dataset=dataset_name,
            converted=count,
            skipped=skipped,
            issues=issues if issues_override is None else issues_override,
        )

    for row_number, record in enumerate(records, start=1):
        match mapping_for_record(record):
            case Err(error):
                issues.append(RuleIssue(row=row_number, message=str(error)))
                if not prevalidate_batch:
                    return Err(execution_error("Mapping selection failed", count=converted))
                continue
            case Ok(resolved_mapping):
                owner_index_result = owner_index_for(resolved_mapping)
                if owner_index_result.is_err():
                    issues.append(RuleIssue(row=row_number, message=str(owner_index_result.err())))
                    if not prevalidate_batch:
                        return Err(execution_error("Owner indexing failed", count=converted))
                    continue
                match prepare_rule_record(
                    record,
                    resolved=resolved_mapping,
                    context=context,
                    owner_index=owner_index_result.unwrap(),
                ):
                    case Err(error):
                        issues.append(RuleIssue(row=row_number, message=str(error)))
                        if not prevalidate_batch:
                            return Err(execution_error("Output preparation failed", count=converted))
                        continue
                    case Ok(None):
                        skipped += 1
                        continue
                    case Ok(prepared):
                        selected_duplicate_policy = duplicate_policy
                        selected_duplicate_identity = duplicate_identity
                        if isinstance(resolved_mapping.mapping.target, ComponentTarget):
                            if selected_duplicate_policy is None:
                                selected_duplicate_policy = resolved_mapping.mapping.target.duplicate_policy
                            identities = component_identities(
                                prepared.outputs,
                                duplicate_identity=selected_duplicate_identity,
                            )
                            repeated = [identity for identity in identities if identity in seen_identities]
                            if repeated:
                                if selected_duplicate_policy == "first":
                                    skipped += 1
                                    continue
                                duplicate_names = sorted({str(identity[-1]) for identity in repeated})
                                issues.append(
                                    RuleIssue(
                                        row=row_number,
                                        message=f"duplicate component identity {duplicate_names}",
                                    )
                                )
                                if not prevalidate_batch:
                                    return Err(execution_error("Duplicate output identity", count=converted))
                                continue
                            seen_identities.update(identities)
                        if prevalidate_batch:
                            staged.append((row_number, record, prepared))
                            continue
                        match attach_prepared_outputs(
                            prepared,
                            record=record,
                            builder=builder,
                            rule_name=rule_name,
                            mapping_name=mapping_name,
                            row_number=row_number,
                            dataset=dataset_name,
                            context=context,
                        ):
                            case Err(error):
                                return Err(
                                    execution_error(
                                        "Output attachment failed",
                                        count=converted + error.converted,
                                        issues_override=error.issues,
                                    )
                                )
                            case Ok(attached):
                                converted += attached

    if issues:
        return Err(execution_error("Output preparation failed", count=converted))
    for row_number, record, prepared in staged:
        match attach_prepared_outputs(
            prepared,
            record=record,
            builder=builder,
            rule_name=rule_name,
            mapping_name=mapping_name,
            row_number=row_number,
            dataset=dataset_name,
            context=context,
        ):
            case Err(error):
                return Err(
                    execution_error(
                        "Output attachment failed",
                        count=converted + error.converted,
                        issues_override=error.issues,
                    )
                )
            case Ok(attached):
                converted += attached
    return Ok(RuleApplicationStats(converted=converted, skipped=skipped))


def apply_mapping_records(
    records: Iterable[Mapping[str, object]],
    /,
    *,
    plan: RulePlan,
    route: MappingRoute,
    context: PluginContext,
) -> Result[RuleApplicationStats, RuleExecutionError]:
    """Build and attach one fully prevalidated batch through the shared Rule path."""
    if context.target_system is None:
        return Err(RuleExecutionError("target_system must be set in context"))

    if isinstance(route, FixedMappingRoute):
        match plan.get_mapping(route.name):
            case Err(error):
                return Err(RuleExecutionError(str(error), mapping=route.name))
            case Ok(resolved_mapping):
                return execute_mapped_records(
                    records,
                    mapping_for_record=lambda record: Ok(resolved_mapping),
                    context=context,
                    builder=None,
                    prevalidate_batch=True,
                    rule_name=None,
                    mapping_name=route.name,
                    dataset_name=None,
                )

    selection_result = plan.get_selection(route.name)
    if selection_result.is_err():
        return Err(RuleExecutionError(str(selection_result.err()), mapping=route.name))
    resolved_selection = selection_result.unwrap()
    selection = resolved_selection.selection

    def mapping_for_record(
        record: Component | Mapping[str, object],
    ) -> Result[ResolvedRuleMapping, ValueError]:
        if not isinstance(record, Mapping):
            return Err(ValueError("Mapping selection requires mapping records"))
        if selection.key_field not in record:
            return Err(ValueError(f"Selection field {selection.key_field!r} is missing"))
        raw_keys = record[selection.key_field]
        if isinstance(raw_keys, str):
            keys: tuple[str, ...] = (raw_keys,)
        elif isinstance(raw_keys, list | tuple):
            if not all(isinstance(key, str) for key in raw_keys):
                return Err(ValueError(f"Selection field {selection.key_field!r} must contain only strings"))
            keys = tuple(key for key in raw_keys if isinstance(key, str))
        else:
            return Err(
                ValueError(f"Selection field {selection.key_field!r} must be a string or sequence of strings")
            )
        unknown_keys = sorted(set(keys) - set(selection.priority))
        if unknown_keys:
            return Err(
                ValueError(
                    f"Selection field {selection.key_field!r} contains unconfigured keys {unknown_keys}"
                )
            )
        selected_key = next(
            (key for key in selection.priority if key in keys and key in resolved_selection.mappings_by_key),
            None,
        )
        if selected_key is None:
            return Err(ValueError(f"No mapping selected by {selection.key_field!r} values {list(keys)}"))
        return Ok(resolved_selection.mappings_by_key[selected_key])

    return execute_mapped_records(
        records,
        mapping_for_record=mapping_for_record,
        context=context,
        builder=None,
        prevalidate_batch=True,
        rule_name=None,
        mapping_name=route.name,
        dataset_name=None,
        duplicate_policy=selection.duplicate_policy,
        duplicate_identity=selection.duplicate_identity,
    )


def prepare_rule_record(
    record: Component | Mapping[str, object],
    /,
    *,
    resolved: ResolvedRuleMapping,
    context: PluginContext,
    owner_index: OwnerMatchIndex | None,
) -> Result[PreparedRuleOutputs | None, ValueError]:
    """Filter, map, validate, and owner-resolve one source record."""
    mapping = resolved.mapping
    if mapping.filter is not None:
        try:
            if not evaluate_rule_filter(to_attr_source(record), rule_filter=mapping.filter, context=context):
                return Ok(None)
        except ValueError as error:
            return Err(ValueError(f"Filter failed: {error}"))

    if isinstance(mapping.target, ComponentTarget):
        outputs: list[RuleOutputs] = []
        for target_class in resolved.target_types:
            if not issubclass(target_class, Component):
                return Err(ValueError(f"Target {target_class.__name__} is not a Component"))
            match create_rule_outputs(
                record,
                rule=mapping,
                target_class=target_class,
                supplemental_classes=resolved.nested_types,
                context=context,
                regenerate_uuid=len(resolved.target_types) > 1,
            ):
                case Err(error):
                    return Err(error)
                case Ok(output):
                    outputs.append(output)
        return Ok(PreparedRuleOutputs(outputs=tuple(outputs), owner=None))

    if resolved.owner_type is None:
        return Err(ValueError("Owned SupplementalAttribute target has no resolved owner type"))
    if owner_index is None:
        return Err(ValueError("Owned target has no execution-scoped owner index"))
    owner_result = resolve_record_owner(record, owner_index)
    if owner_result.is_err():
        return Err(owner_result.err())
    owner = owner_result.unwrap()
    if owner is None:
        return Ok(None)

    attribute_class = resolved.target_types[0]
    if not issubclass(attribute_class, SupplementalAttribute):
        return Err(ValueError(f"Target {attribute_class.__name__} is not a SupplementalAttribute"))
    output_result = create_rule_outputs(
        record,
        rule=mapping,
        target_class=attribute_class,
        supplemental_classes=(),
        context=context,
    )
    if output_result.is_err():
        return Err(output_result.err())
    output = output_result.unwrap()
    if not isinstance(output.primary, SupplementalAttribute):
        return Err(ValueError("Owned target output is not a SupplementalAttribute"))
    return Ok(PreparedRuleOutputs(outputs=(output,), owner=owner))


def component_identities(
    outputs: tuple[RuleOutputs, ...],
    *,
    duplicate_identity: Literal["target_type_and_name", "name"],
) -> list[tuple[object, ...]]:
    """Return configured identities from constructed Component outputs."""
    if duplicate_identity == "name":
        return [(output.primary.name,) for output in outputs if isinstance(output.primary, Component)]
    return [
        (type(output.primary), output.primary.name)
        for output in outputs
        if isinstance(output.primary, Component)
    ]


def build_owner_match_index(
    target: OwnerTarget,
    owner_type: type[Component],
    *,
    context: PluginContext,
) -> Result[OwnerMatchIndex, ValueError]:
    """Index matching owners once in their System insertion order for one rule run."""
    target_system = context.target_system
    if target_system is None:
        return Err(ValueError("target_system must be set in context"))
    mutable_index: dict[tuple[object, ...], list[Component]] = {}
    for owner in target_system.get_components(owner_type):
        match owner_key_for_component(owner, target):
            case Err(error):
                return Err(error)
            case Ok(None):
                continue
            case Ok(key):
                try:
                    hash(key)
                except TypeError:
                    return Err(
                        ValueError(f"Owner key for {target.owner_type} must contain only hashable values")
                    )
                mutable_index.setdefault(key, []).append(owner)
    return Ok(
        OwnerMatchIndex(
            target=target,
            owners_by_key=MappingProxyType({key: tuple(owners) for key, owners in mutable_index.items()}),
        )
    )


def owner_key_for_component(
    owner: Component, target: OwnerTarget
) -> Result[tuple[object, ...] | None, ValueError]:
    """Read an owner's typed key in the configured field order."""
    if target.owner_field is not None:
        return Ok((owner.name,))
    values: list[object] = []
    for owner_path in target.owner_match.values():
        match owner_field_path(owner, owner_path):
            case Err(error):
                return Err(error)
            case Ok(value):
                if value is None and not target.nulls_equal:
                    return Ok(None)
                values.append(value)
    return Ok(tuple(values))


def resolve_record_owner(
    record: Component | Mapping[str, object],
    index: OwnerMatchIndex,
) -> Result[Component | None, ValueError]:
    """Resolve one record by its prebuilt typed key and explicit owner policies."""
    target = index.target
    values: list[object] = []
    for source_field in owner_source_fields(target):
        match record_field_value(record, source_field):
            case Err(error):
                return Err(error)
            case Ok(value):
                if target.owner_field is not None and (
                    not isinstance(value, str) or not value.strip() or value != value.strip()
                ):
                    return Err(
                        ValueError(f"Owner key field {source_field!r} must be a non-empty trimmed string")
                    )
                if target.owner_field is None and value is None and not target.nulls_equal:
                    return Err(
                        ValueError(
                            f"Owner-match source field {source_field!r} is null but nulls_equal is false"
                        )
                    )
                values.append(value)
    key = tuple(values)
    try:
        hash(key)
    except TypeError:
        return Err(ValueError("Owner-match source key must contain only hashable values"))
    matches = index.owners_by_key.get(key, ())
    if not matches:
        if target.missing_owner == "skip":
            return Ok(None)
        return Err(ValueError(f"No {target.owner_type} owner matched the configured keys"))
    if len(matches) > 1:
        if target.ambiguous_owner == "error":
            return Err(ValueError(f"Multiple {target.owner_type} owners matched the configured keys"))
        logger.warning("Multiple {} owners matched, selecting the first configured match", target.owner_type)
    return Ok(matches[0])


def owner_source_fields(target: OwnerTarget) -> tuple[str, ...]:
    """Return all source fields used to identify an owner."""
    if target.owner_field is not None:
        return (target.owner_field,)
    return tuple(target.owner_match)


def record_field_value(
    record: Component | Mapping[str, object], field_name: str
) -> Result[object, ValueError]:
    """Read one named source field from a mapping row or Component."""
    if isinstance(record, Mapping):
        if field_name not in record:
            return Err(ValueError(f"Owner-match source field {field_name!r} is missing"))
        return Ok(record[field_name])
    if field_name not in type(record).model_fields:
        return Err(ValueError(f"Owner-match source field {field_name!r} is not a Component field"))
    return Ok(getattr(record, field_name))


def validate_owner_path(owner_type: type[Component], path: str) -> ValueError | None:
    """Validate every segment of a configured owner path against model types."""
    current_type: type[BaseModel] = owner_type
    parts = path.split(".")
    for index, part in enumerate(parts):
        field_info = current_type.model_fields.get(part)
        if field_info is None:
            return ValueError(f"Owner {current_type.__name__} has no configured field path {path!r}")
        if index == len(parts) - 1:
            return None
        field_type = field_info.annotation
        origin = get_origin(field_type)
        if origin is Annotated:
            field_type = get_args(field_type)[0]
            origin = get_origin(field_type)
        if origin in (Union, UnionType):
            field_type = next(
                (
                    candidate
                    for candidate in get_args(field_type)
                    if isinstance(candidate, type) and issubclass(candidate, BaseModel)
                ),
                object,
            )
        if not isinstance(field_type, type) or not issubclass(field_type, BaseModel):
            return ValueError(f"Owner field path {path!r} cannot continue through {part!r}")
        current_type = field_type
    return None


def owner_field_path(owner: Component, path: str) -> Result[object, ValueError]:
    """Resolve an explicitly configured dotted path on a prevalidated owner model."""
    value: object = owner
    for path_part in path.split("."):
        if value is None:
            return Ok(None)
        try:
            value = getattr(value, path_part)
        except AttributeError:
            return Err(ValueError(f"Owner {type(owner).__name__} has no configured field path {path!r}"))
    return Ok(value)


def attach_prepared_outputs(
    prepared: PreparedRuleOutputs,
    *,
    record: Component | Mapping[str, object],
    builder: ProvenanceBuilder | None,
    rule_name: str | None,
    mapping_name: str | None,
    row_number: int,
    dataset: str | None,
    context: PluginContext,
) -> Result[int, RuleExecutionError]:
    """Attach output groups independently and preserve progress and provenance."""
    converted = 0
    for outputs in prepared.outputs:
        match attach_rule_outputs(outputs, context=context, owner=prepared.owner):
            case Err(error):
                return Err(
                    RuleExecutionError(
                        "Output attachment failed",
                        rule=rule_name,
                        mapping=mapping_name,
                        dataset=dataset,
                        converted=converted,
                        issues=[RuleIssue(row=row_number, message=str(error))],
                    )
                )
            case Ok():
                converted += 1
                if builder is not None and isinstance(record, Component):
                    target_system = context.target_system
                    if target_system is None:
                        return Err(
                            RuleExecutionError(
                                "target_system is not set after output attachment",
                                rule=rule_name,
                                mapping=mapping_name,
                                dataset=dataset,
                                converted=converted,
                                issues=[RuleIssue(row=row_number, message="target_system is missing")],
                            )
                        )
                    builder.record_translation(record, outputs.primary, target_system)
    return Ok(converted)


def attach_rule_outputs(
    outputs: RuleOutputs,
    *,
    context: PluginContext,
    owner: Component | None = None,
) -> Result[None, ValueError]:
    """Attach one output group safely, removing only objects added by this call."""
    target_system = context.target_system
    if target_system is None:
        return Err(ValueError("target_system must be set in context"))
    if isinstance(outputs.primary, SupplementalAttribute) and owner is None:
        return Err(ValueError("An explicit owner is required for SupplementalAttribute outputs"))
    if outputs.supplemental_attributes and not isinstance(outputs.primary, Component):
        return Err(ValueError("Nested supplemental outputs require a primary Component"))

    attributes = (
        (outputs.primary, *outputs.supplemental_attributes)
        if isinstance(outputs.primary, SupplementalAttribute)
        else outputs.supplemental_attributes
    )
    seen_uuids: set[object] = set()
    for attribute in attributes:
        if attribute.uuid in seen_uuids:
            return Err(ValueError(f"Supplemental output UUID {attribute.uuid} is duplicated in rule outputs"))
        seen_uuids.add(attribute.uuid)
        try:
            target_system.get_supplemental_attribute_by_uuid(attribute.uuid)
        except ISNotStored:
            continue
        except ISBaseException as error:
            return Err(ValueError(f"Could not inspect SupplementalAttribute UUID {attribute.uuid}: {error}"))
        return Err(
            ValueError(f"Supplemental output UUID {attribute.uuid} is already stored in target system")
        )

    attached_primary = False
    attached_attributes: list[SupplementalAttribute] = []
    try:
        if isinstance(outputs.primary, Component):
            target_system.add_component(outputs.primary)
            attached_primary = True
            attribute_owner = outputs.primary
        else:
            if owner is None:
                return Err(ValueError("An explicit owner is required for SupplementalAttribute outputs"))
            target_system.add_supplemental_attribute(owner, outputs.primary)
            attached_attributes.append(outputs.primary)
            attribute_owner = None
        if attribute_owner is not None:
            for attribute in outputs.supplemental_attributes:
                target_system.add_supplemental_attribute(attribute_owner, attribute)
                attached_attributes.append(attribute)
    except ISBaseException as error:
        rollback_errors: list[str] = []
        for attribute in reversed(attached_attributes):
            try:
                target_system.remove_supplemental_attribute(attribute)
            except ISBaseException as rollback_error:
                rollback_errors.append(str(rollback_error))
        if attached_primary and isinstance(outputs.primary, Component):
            try:
                target_system.remove_component(outputs.primary)
            except ISBaseException as rollback_error:
                rollback_errors.append(str(rollback_error))
        detail = f"Failed to attach rule output group: {error}"
        if rollback_errors:
            detail += f"; rollback failures: {rollback_errors}"
        return Err(ValueError(detail))
    return Ok(None)


def build_provenance_builder(context: PluginContext) -> ProvenanceBuilder | None:
    """Return a provenance builder when source preservation is configured."""
    if not context.preserve_source:
        return None
    if context.source_system is None:
        logger.warning("preserve_source=True but context has no source_system; skipping provenance capture")
        return None
    return ProvenanceBuilder(context.source_system)


def apply_single_rule(
    rule: Rule,
    *,
    context: PluginContext,
    builder: ProvenanceBuilder | None = None,
) -> Result[RuleApplicationStats, ValueError]:
    """Apply one rule without finalizing whole-translation metadata or carry-over."""
    if context.target_system is None:
        return Err(ValueError("target_system must be set in context"))
    resolution = resolve_rule(rule, context=context)
    if resolution.is_err():
        return Err(resolution.err())
    return execute_rule(resolution.unwrap(), context=context, builder=builder)


def resolve_supplemental_class(
    type_name: str, *, context: PluginContext
) -> Result[type[SupplementalAttribute], ValueError]:
    """Resolve and validate one SupplementalAttribute class."""
    resolution = resolve_output_type(type_name, context=context)
    if resolution.is_err():
        return Err(resolution.err())
    model_type = resolution.unwrap()
    if not issubclass(model_type, SupplementalAttribute):
        return Err(
            ValueError(f"Resolved supplemental target type {type_name!r} is not a SupplementalAttribute")
        )
    return Ok(model_type)
