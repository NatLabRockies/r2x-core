"""Rule definitions and helpers for the translation pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal, Protocol, TypeAlias

from pydantic import ConfigDict, Field, TypeAdapter, field_validator, model_validator
from rust_ok import Result

from .type_vocabulary import FilterOperator, StrictModel

if TYPE_CHECKING:
    from .plugin_context import PluginContext


RuleGetter: TypeAlias = Callable[..., Result[Any, ValueError]]


class RuleFilterBase(StrictModel):
    """Common behavior for one node in a component filter expression."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    def matches(self, component: Any, *, context: PluginContext | None = None) -> bool:
        """Evaluate this filter against a component instance."""
        from .utils.rules import evaluate_rule_filter

        return evaluate_rule_filter(component, rule_filter=self, context=context)


class LeafFilter(RuleFilterBase):
    """Comparison behavior shared by field-backed and getter-backed leaves."""

    op: FilterOperator
    values: Annotated[list[Any], Field(min_length=1)]
    casefold: bool = True
    on_missing: Literal["include", "exclude"] = "exclude"

    @model_validator(mode="after")
    def validate_values(self) -> LeafFilter:
        """Validate value shape for the selected operator."""
        if self.op == "geq" and len(self.values) != 1:
            msg = "geq expects exactly one comparison value"
            raise ValueError(msg)
        if self.op in {"startswith", "not_startswith", "endswith"} and any(
            not isinstance(value, str) for value in self.values
        ):
            msg = f"{self.op} filter values must be strings"
            raise ValueError(msg)
        return self

    @property
    def normalized_values(self) -> list[Any]:
        """Normalize comparison values without changing serialized input."""
        return [
            value.casefold() if self.casefold and isinstance(value, str) else value for value in self.values
        ]


class FieldFilter(LeafFilter):
    """Compare a named component field."""

    kind: Literal["field"] = "field"
    field: str


class GetterFilter(LeafFilter):
    """Compare a value returned by a registered getter."""

    kind: Literal["getter"] = "getter"
    getter: RuleGetter | str

    @field_validator("getter", mode="before")
    @classmethod
    def resolve_getter_name(cls, value: Any) -> Any:
        """Resolve registered getter names into callables."""
        if callable(value):
            return value
        if not isinstance(value, str):
            msg = f"getter must be callable or str, not {type(value).__name__}"
            raise ValueError(msg)
        from .getters import resolve_getter

        return resolve_getter(value).unwrap_or_raise()


class AnyOfFilter(RuleFilterBase):
    """Match when any child filter matches."""

    kind: Literal["any_of"] = "any_of"
    filters: Annotated[list[RuleFilter], Field(min_length=1)]


class AllOfFilter(RuleFilterBase):
    """Match when all child filters match."""

    kind: Literal["all_of"] = "all_of"
    filters: Annotated[list[RuleFilter], Field(min_length=1)]


RuleFilter: TypeAlias = Annotated[
    FieldFilter | GetterFilter | AnyOfFilter | AllOfFilter,
    Field(discriminator="kind"),
]
AnyOfFilter.model_rebuild(_types_namespace={"RuleFilter": RuleFilter})
AllOfFilter.model_rebuild(_types_namespace={"RuleFilter": RuleFilter})


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
            msg = "SupplementalAttributeRule.target_type must be a non-empty string"
            raise ValueError(msg)
        if self.optional is not True and self.optional is not False:
            msg = "SupplementalAttributeRule.optional must be a bool"
            raise TypeError(msg)
        for target_field, getter in self.getters.items():
            if not callable(getter):
                msg = f"Getter for {target_field!r} must be callable"
                raise TypeError(msg)
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
            msg = (
                f"Rule cannot have both multiple sources and multiple targets. "
                f"source_type={self.source_type}, target_type={self.target_type}"
            )
            raise NotImplementedError(msg)

        for target_field, getter in self.getters.items():
            if not callable(getter):
                msg = f"Getter for {target_field!r} must be callable"
                raise TypeError(msg)
        if any(not isinstance(output, SupplementalAttributeRule) for output in self.supplemental_attributes):
            msg = "Rule.supplemental_attributes must contain SupplementalAttributeRule instances"
            raise TypeError(msg)
        for target_field, source_fields in self.field_map.items():
            if isinstance(source_fields, list) and target_field not in self.getters:
                msg = f"Multi-field mapping for '{target_field}' requires a getter function"
                raise ValueError(msg)
        if self.filter is not None and not isinstance(
            self.filter, (FieldFilter, GetterFilter, AnyOfFilter, AllOfFilter)
        ):
            msg = f"Rule.filter must be a RuleFilter node, not {type(self.filter).__name__}"
            raise TypeError(msg)

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
                    TypeAdapter(RuleFilter).validate_python(rule["filter"])
                    if rule["filter"] is not None
                    else None
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
