"""Rule definitions and helpers for the translation pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol, TypeAlias

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator
from rust_ok import Result

from .types import FilterOperator

if TYPE_CHECKING:
    from .plugin_context import PluginContext


class RuleFilter(BaseModel):
    """Declarative predicate for selecting source components."""

    field: str | None = None
    getter: RuleGetter | None = None
    op: FilterOperator | None = None
    values: list[Any] | None = None
    prefixes: list[str] | None = None
    any_of: list[RuleFilter] | None = None
    all_of: list[RuleFilter] | None = None
    casefold: bool = True
    on_missing: Annotated[
        Literal["include", "exclude"],
        Field(description="Action when a field is missing or has a None value."),
    ] = "exclude"
    _normalized_values: list[Any] = PrivateAttr(default_factory=list)

    @field_validator("getter", mode="before")
    @classmethod
    def validate_getter(cls, value: Any) -> Any:
        """Resolve string getter references into callables."""
        if value is None or callable(value):
            return value
        if not isinstance(value, str):
            raise TypeError(f"RuleFilter.getter must be callable or str, not {type(value).__name__}")

        from .getters import resolve_getter

        getter = resolve_getter(value).unwrap_or_raise()
        return getter

    @model_validator(mode="after")
    def validate_structure(self) -> RuleFilter:
        """Ensure the filter is either a leaf or a composition."""
        is_leaf = (
            self.field is not None
            or self.getter is not None
            or self.op is not None
            or self.values is not None
            or self.prefixes is not None
        )
        has_children = bool(self.any_of) or bool(self.all_of)

        if is_leaf and has_children:
            raise ValueError("RuleFilter cannot mix field/op/values with any_of/all_of")
        if not is_leaf and not has_children:
            raise ValueError("RuleFilter requires field/op/values or any_of/all_of")
        if self.any_of and self.all_of:
            raise ValueError("RuleFilter cannot set both any_of and all_of")

        if is_leaf:
            if self.field and self.getter:
                raise ValueError("RuleFilter cannot set both field and getter")
            if not self.field and self.getter is None:
                raise ValueError("RuleFilter.field is required for leaf filters")
            if self.op is None:
                raise ValueError("RuleFilter.op is required for leaf filters")
            if self.op in {"startswith", "not_startswith"}:
                prefix_values = self.prefixes if self.prefixes is not None else self.values
                if not prefix_values:
                    raise ValueError("RuleFilter prefix operations require at least one prefix")
                if any(not isinstance(prefix, str) for prefix in prefix_values):
                    raise ValueError("RuleFilter prefix values must be strings")
                object.__setattr__(self, "values", prefix_values)
            else:
                if self.prefixes is not None:
                    raise ValueError("RuleFilter.prefixes is only supported for prefix operations")
                if not self.values:
                    raise ValueError("RuleFilter.values must contain at least one value")
                if self.op == "geq" and len(self.values) != 1:
                    raise ValueError("RuleFilter.geq expects exactly one comparison value")
                if self.op == "endswith" and any(not isinstance(value, str) for value in self.values):
                    raise ValueError("RuleFilter endswith values must be strings")

            # Precompute casefolded values once so evaluate_rule_filter does not
            # recompute them per component.
            normalized = [
                str(val).casefold() if self.casefold and isinstance(val, str) else val
                for val in self.values or []
            ]
            object.__setattr__(self, "_normalized_values", normalized)

        return self

    def matches(self, component: Any, *, context: PluginContext | None = None) -> bool:
        """Evaluate this filter against a component instance."""
        from .utils.rules import evaluate_rule_filter

        return evaluate_rule_filter(component, rule_filter=self, context=context)


RuleGetter: TypeAlias = Callable[..., Result[Any, ValueError]]


@dataclass(frozen=True, slots=True)
class SupplementalAttributeRule:
    """Declarative output specification for a supplemental attribute.

    Supplemental attributes are built from the same source object as their
    primary component. Optional outputs are omitted when their mapping produces
    no values, while provided values are always validated by the target model.
    """

    target_type: str
    field_map: dict[str, str | list[str]] = field(default_factory=dict)
    getters: dict[str, RuleGetter] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    optional: bool = True

    def __post_init__(self) -> None:
        """Validate getter functions, multi-field mappings, and the target type."""
        if not isinstance(self.target_type, str) or not self.target_type:
            raise ValueError("SupplementalAttributeRule.target_type must be a non-empty string")
        if self.optional is not True and self.optional is not False:
            raise TypeError("SupplementalAttributeRule.optional must be a bool")
        for target_field, getter in self.getters.items():
            if not callable(getter):
                raise TypeError(f"Getter for {target_field!r} must be callable")
        for target_field, source_fields in self.field_map.items():
            if isinstance(source_fields, list) and target_field not in self.getters:
                msg = f"Multi-field mapping for '{target_field}' requires a getter function"
                raise ValueError(msg)


class RuleLike(Protocol):
    """Minimal interface required to build kwargs for a target component."""

    @property
    def field_map(self) -> Mapping[str, str | list[str]]:
        """Mapping of target field names to source field names."""
        ...

    @property
    def getters(self) -> Mapping[str, RuleGetter]:
        """Mapping of target field names to getter callables."""
        ...

    @property
    def defaults(self) -> Mapping[str, Any]:
        """Default values for target fields."""
        ...


@dataclass(frozen=True, slots=True)
class Rule:
    """Declarative rule for converting one component type to another."""

    source_type: str | list[str]
    target_type: str | list[str]
    version: int
    field_map: dict[str, str | list[str]] = field(default_factory=dict)
    getters: dict[str, RuleGetter] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    filter: RuleFilter | None = field(default=None)
    system: Literal["source", "target"] = "source"
    name: str | None = None
    depends_on: list[str] | None = None
    supplemental_attributes: list[SupplementalAttributeRule] = field(default_factory=list)

    def __str__(self) -> str:
        """Represent string."""
        return f"{self.source_type}->{self.target_type}(v{self.version})"

    def __post_init__(self) -> Any:
        """Validate init."""
        if self.has_multiple_sources() and self.has_multiple_targets():
            raise NotImplementedError(
                f"Rule cannot have both multiple sources and multiple targets. "
                f"source_type={self.source_type}, target_type={self.target_type}"
            )

        for target_field, getter in self.getters.items():
            if not callable(getter):
                raise TypeError(f"Getter for {target_field!r} must be callable")
        if any(not isinstance(output, SupplementalAttributeRule) for output in self.supplemental_attributes):
            raise TypeError("Rule.supplemental_attributes must contain SupplementalAttributeRule instances")
        for target_field, source_fields in self.field_map.items():
            if isinstance(source_fields, list) and target_field not in self.getters:
                msg = f"Multi-field mapping for '{target_field}' requires a getter function"
                raise ValueError(msg)
        if self.filter is not None and not isinstance(self.filter, RuleFilter):
            raise TypeError(f"Rule.filter must be a RuleFilter, not {type(self.filter).__name__}")

    def __hash__(self) -> int:
        """Hash based on rule's unique identifier."""
        source_key = tuple(self.source_type) if isinstance(self.source_type, list) else self.source_type
        target_key = tuple(self.target_type) if isinstance(self.target_type, list) else self.target_type
        return hash((source_key, target_key, self.version))

    def __eq__(self, other: object) -> bool:
        """Equality based on rule's unique identifier."""
        if not isinstance(other, Rule):
            return NotImplemented
        return (
            self.source_type == other.source_type
            and self.target_type == other.target_type
            and self.version == other.version
        )

    def has_multiple_sources(self) -> bool:
        """Check if rule applies to multiple source types."""
        return isinstance(self.source_type, list)

    def has_multiple_targets(self) -> bool:
        """Check if rule creates multiple target types."""
        return isinstance(self.target_type, list)

    def get_source_types(self) -> list[str]:
        """Return source types as list."""
        return self.source_type if isinstance(self.source_type, list) else [self.source_type]

    def get_target_types(self) -> list[str]:
        """Return target types as list."""
        return self.target_type if isinstance(self.target_type, list) else [self.target_type]

    @classmethod
    def from_records(cls, records: list[dict[str, Any]]) -> list[Rule]:
        """Create rules from json objects."""
        from .getters import resolve_rule_getters

        rules_list: list[Rule] = []
        for record in records:
            rule = dict(record)
            if getters := rule.get("getters"):
                rule["getters"] = resolve_rule_getters(getters).unwrap_or_raise()
            if "filter" in rule:
                rule["filter"] = (
                    RuleFilter.model_validate(rule["filter"]) if rule["filter"] is not None else None
                )
            outputs: list[SupplementalAttributeRule] = []
            for output_record in rule.get("supplemental_attributes", []):
                output = dict(output_record)
                if getters := output.get("getters"):
                    output["getters"] = resolve_rule_getters(getters).unwrap_or_raise()
                outputs.append(SupplementalAttributeRule(**output))
            rule["supplemental_attributes"] = outputs
            rules_list.append(cls(**rule))
        return rules_list


RuleFilter.model_rebuild()
