"""Rule definitions and helpers for the translation pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeAlias

from pydantic import BaseModel, PrivateAttr, model_validator
from rust_ok import Result

if TYPE_CHECKING:
    pass


class RuleFilter(BaseModel):
    """Declarative predicate for selecting source components."""

    field: str | None = None
    op: Literal["eq", "neq", "in", "not_in", "geq", "startswith", "not_startswith", "endswith"] | None = None
    values: list[Any] | None = None
    prefixes: list[str] | None = None
    any_of: list[RuleFilter] | None = None
    all_of: list[RuleFilter] | None = None
    casefold: bool = True
    on_missing: Literal["include", "exclude"] = "exclude"
    _normalized_values: list[Any] | None = PrivateAttr(None)

    @model_validator(mode="after")
    def _validate_structure(self) -> RuleFilter:
        """Ensure the filter is either a leaf or a composition."""
        is_leaf = (
            self.field is not None
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
            if not self.field:
                raise ValueError("RuleFilter.field is required for leaf filters")
            if self.op is None:
                raise ValueError("RuleFilter.op is required for leaf filters")
            if not (self.values or self.prefixes):
                raise ValueError("RuleFilter.values must contain at least one value")
            if self.op == "geq" and len(self.values or []) != 1:
                raise ValueError("RuleFilter.geq expects exactly one comparison value")
            if self.op in {"startswith", "not_startswith"}:
                prefix_values = self.prefixes if self.prefixes else self.values
                if not prefix_values:
                    raise ValueError(
                        "RuleFilter.prefixes must provide at least one entry for prefix operations"
                    )
                if any(not isinstance(prefix, str) for prefix in prefix_values):
                    raise ValueError("RuleFilter.prefixes entries must be strings")
                object.__setattr__(self, "values", prefix_values)

            # Precompute casefolded values once so _evaluate_rule_filter does not
            # recompute them per component.
            normalized = [
                str(val).casefold() if self.casefold and isinstance(val, str) else val
                for val in self.values or []
            ]
            object.__setattr__(self, "_normalized_values", normalized)

        return self

    def matches(self, component: Any) -> bool:
        """Evaluate this filter against a component instance."""
        from .utils import _evaluate_rule_filter

        return _evaluate_rule_filter(component, rule_filter=self)


RuleGetter: TypeAlias = Callable[..., Result[Any, ValueError]]


class RuleLike(Protocol):
    """Minimal interface required to build kwargs for a target component."""

    @property
    def field_map(self) -> Mapping[str, str | list[str]]:
        """Mapping of target field names to source field names."""
        ...

    @property
    def getters(self) -> Mapping[str, RuleGetter | str]:
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
    getters: dict[str, RuleGetter | str] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    filter: RuleFilter | None = field(default=None)
    system: Literal["source", "target"] = "source"
    name: str | None = None
    depends_on: list[str] | None = None

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
        from .getters import _preprocess_rule_getters

        rules_list = []
        for rule in records:
            if getters := rule.get("getters"):
                rule["getters"] = _preprocess_rule_getters(getters).unwrap_or_raise()
            if "filter" in rule:
                rule["filter"] = (
                    RuleFilter.model_validate(rule["filter"]) if rule["filter"] is not None else None
                )
            rules_list.append(cls(**rule))
        return rules_list


RuleFilter.model_rebuild()
