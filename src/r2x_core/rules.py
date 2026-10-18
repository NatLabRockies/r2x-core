"""Typed Rule sources, targets, filters, and shared construction mappings."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, Literal, Protocol, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, field_validator, model_validator
from rust_ok import Result

from .plugin_context import PluginContext

RuleGetter: TypeAlias = Callable[..., Result[Any, ValueError]]


class RuleFilter(BaseModel):
    """Declarative predicate for selecting source components or data rows."""

    field: str | None = None
    getter: RuleGetter | str | None = None
    op: Literal["eq", "neq", "in", "not_in", "geq", "startswith", "not_startswith", "endswith"] | None = None
    values: list[Any] | None = None
    prefixes: list[str] | None = None
    any_of: list[RuleFilter] | None = None
    all_of: list[RuleFilter] | None = None
    casefold: bool = True
    on_missing: Literal["include", "exclude"] = "exclude"

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    @field_validator("getter", mode="before")
    @classmethod
    def validate_getter(cls, value: Any) -> Any:
        """Resolve string getter references into callables."""
        if value is None or callable(value):
            return value
        if not isinstance(value, str):
            raise TypeError(f"RuleFilter.getter must be callable or str, not {type(value).__name__}")

        from .getters import preprocess_rule_getters

        return preprocess_rule_getters({"filter": value}).unwrap_or_raise()["filter"]

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
            if not (self.values or self.prefixes):
                raise ValueError("RuleFilter.values must contain at least one value")
            if self.op == "geq" and len(self.values or []) != 1:
                raise ValueError("RuleFilter.geq expects exactly one comparison value")
            if self.op in {"startswith", "not_startswith"}:
                prefix_values = self.prefixes if self.prefixes is not None else self.values
                if prefix_values is None:
                    raise ValueError(
                        "RuleFilter.prefixes must provide at least one entry for prefix operations"
                    )
                if any(not isinstance(prefix, str) for prefix in prefix_values):
                    raise ValueError("RuleFilter.prefixes entries must be strings")
                object.__setattr__(self, "values", prefix_values)
        return self

    def matches(self, component: Any, *, context: PluginContext | None = None) -> bool:
        """Evaluate this filter against a component or mapping row."""
        from .utils import evaluate_rule_filter

        return evaluate_rule_filter(component, rule_filter=self, context=context)


class ComponentSource(BaseModel):
    """Select existing components from one explicitly named context System."""

    kind: Literal["component"] = "component"
    component_type: str = Field(min_length=1)
    system: Literal["source", "target"] = "source"

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("component_type")
    @classmethod
    def validate_component_type(cls, value: str) -> str:
        """Require a trimmed component type name."""
        if value != value.strip():
            raise ValueError("ComponentSource.component_type cannot contain surrounding whitespace")
        return value


class DatasetSource(BaseModel):
    """Select records from one named DataStore dataset."""

    kind: Literal["dataset"] = "dataset"
    dataset: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("dataset")
    @classmethod
    def validate_dataset(cls, value: str) -> str:
        """Require a trimmed dataset name."""
        if value != value.strip():
            raise ValueError("DatasetSource.dataset cannot contain surrounding whitespace")
        return value


RuleSource: TypeAlias = Annotated[ComponentSource | DatasetSource, Field(discriminator="kind")]


class ComponentTarget(BaseModel):
    """Construct one or more concrete Component types from the same source."""

    kind: Literal["component"] = "component"
    component_types: tuple[str, ...] = Field(min_length=1)
    duplicate_policy: Literal["error", "first"] = "error"

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("component_types")
    @classmethod
    def validate_component_types(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique, trimmed component type names."""
        if any(not name or name != name.strip() for name in names):
            raise ValueError("ComponentTarget type names must be non-empty and trimmed")
        if len(set(names)) != len(names):
            raise ValueError("ComponentTarget.component_types cannot contain duplicates")
        return names


class OwnedSupplementalTarget(BaseModel):
    """Construct SupplementalAttributes and associate them with explicitly matched owners."""

    kind: Literal["owned_supplemental_attribute"] = "owned_supplemental_attribute"
    attribute_type: str = Field(min_length=1)
    owner_type: str = Field(min_length=1)
    owner_field: str | None = None
    owner_match: dict[str, str] = Field(default_factory=dict)
    nulls_equal: StrictBool = False
    missing_owner: Literal["error", "skip"] = "error"
    ambiguous_owner: Literal["error", "first"] = "error"

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("attribute_type", "owner_type")
    @classmethod
    def validate_type_name(cls, value: str) -> str:
        """Require a trimmed attribute or owner type name."""
        if value != value.strip():
            raise ValueError("OwnedSupplementalTarget type names cannot contain surrounding whitespace")
        return value

    @model_validator(mode="after")
    def validate_owner_mapping(self) -> OwnedSupplementalTarget:
        """Require exactly one explicit owner matching strategy."""
        if (self.owner_field is None) == (not self.owner_match):
            raise ValueError("Configure exactly one of owner_field or owner_match")
        if self.owner_field is not None and (
            not self.owner_field or self.owner_field != self.owner_field.strip()
        ):
            raise ValueError("OwnedSupplementalTarget.owner_field must be a non-empty trimmed name")
        if any(
            not source or source != source.strip() or not target or target != target.strip()
            for source, target in self.owner_match.items()
        ):
            raise ValueError("OwnedSupplementalTarget owner-match fields must be non-empty and trimmed")
        return self


RuleTarget: TypeAlias = Annotated[ComponentTarget | OwnedSupplementalTarget, Field(discriminator="kind")]


class SupplementalAttributeRule(BaseModel):
    """Nested attribute output attached to the primary output from the same source."""

    target_type: str = Field(min_length=1)
    field_map: dict[str, str | list[str]] = Field(default_factory=dict)
    getters: dict[str, RuleGetter | str] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    optional: StrictBool = True

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    @field_validator("target_type")
    @classmethod
    def validate_target_type(cls, value: str) -> str:
        """Require a trimmed supplemental target type name."""
        if value != value.strip():
            raise ValueError("SupplementalAttributeRule.target_type cannot contain surrounding whitespace")
        return value

    @model_validator(mode="after")
    def validate_field_map(self) -> SupplementalAttributeRule:
        """Require getters for mappings that combine multiple source fields."""
        for target_field, source_fields in self.field_map.items():
            if not target_field:
                raise ValueError("SupplementalAttributeRule field names cannot be empty")
            if isinstance(source_fields, list) and target_field not in self.getters:
                raise ValueError(f"Multi-field mapping for '{target_field}' requires a getter function")
        return self


class RuleLike(Protocol):
    """Shared field mapping consumed by component construction."""

    @property
    def field_map(self) -> Mapping[str, str | list[str]]:
        """Map target fields to source attributes."""
        ...

    @property
    def getters(self) -> Mapping[str, RuleGetter | str]:
        """Provide getters for target fields."""
        ...

    @property
    def defaults(self) -> Mapping[str, object]:
        """Provide defaults for target fields."""
        ...


class RuleMapping(BaseModel):
    """Shared target and field construction contract for executable and computed records."""

    name: str | None = Field(default=None, min_length=1)
    version: int = Field(default=1, ge=1)
    target: RuleTarget
    field_map: dict[str, str | list[str]] = Field(default_factory=dict)
    getters: dict[str, RuleGetter | str] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    filter: RuleFilter | None = None
    supplemental_attributes: tuple[SupplementalAttributeRule, ...] = ()

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        """Require a trimmed optional mapping name."""
        if value is not None and value != value.strip():
            raise ValueError("RuleMapping.name cannot contain surrounding whitespace")
        return value

    @model_validator(mode="after")
    def validate_mapping(self) -> RuleMapping:
        """Validate field names and multi-field getter requirements."""
        for target_field, source_fields in self.field_map.items():
            if not target_field:
                raise ValueError("RuleMapping field_map target names cannot be empty")
            if isinstance(source_fields, list) and target_field not in self.getters:
                raise ValueError(f"Multi-field mapping for '{target_field}' requires a getter function")
        if any(not target_field for target_field in (*self.getters, *self.defaults)):
            raise ValueError("RuleMapping target field names cannot be empty")
        if isinstance(self.target, ComponentTarget):
            if len(self.target.component_types) > 1 and self.supplemental_attributes:
                raise ValueError("Rules with nested supplemental outputs require exactly one primary target")
        elif self.supplemental_attributes:
            raise ValueError("Owned supplemental targets cannot also declare nested supplemental outputs")
        return self

    @classmethod
    def from_records(cls, records: Sequence[Mapping[str, Any]]) -> list[Self]:
        """Create typed mappings from JSON-compatible records."""
        from .getters import preprocess_rule_getters

        mappings: list[Self] = []
        for record in records:
            values = dict(record)
            getter_data = values.get("getters", {})
            if getter_data:
                values["getters"] = preprocess_rule_getters(getter_data).unwrap_or_raise()
            nested_outputs = []
            for output_data in values.get("supplemental_attributes", ()):
                output = dict(output_data)
                if output.get("getters"):
                    output["getters"] = preprocess_rule_getters(output["getters"]).unwrap_or_raise()
                nested_outputs.append(output)
            values["supplemental_attributes"] = tuple(nested_outputs)
            mappings.append(cls.model_validate(values))
        return mappings


class MappingSelection(BaseModel):
    """Select named construction mappings by an explicit ordered key field."""

    name: str = Field(min_length=1)
    key_field: str = Field(min_length=1)
    priority: tuple[str, ...] = Field(min_length=1)
    by_key: dict[str, str] = Field(min_length=1)
    duplicate_policy: Literal["error", "first"] = "error"
    duplicate_identity: Literal["target_type_and_name", "name"] = "target_type_and_name"

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("name", "key_field")
    @classmethod
    def validate_required_names(cls, value: str) -> str:
        """Require trimmed selection and input-field names."""
        if value != value.strip():
            raise ValueError("MappingSelection names cannot contain surrounding whitespace")
        return value

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique, trimmed keys while preserving selection precedence."""
        if any(not value or value != value.strip() for value in values):
            raise ValueError("MappingSelection priority keys must be non-empty and trimmed")
        if len(set(values)) != len(values):
            raise ValueError("MappingSelection priority keys cannot contain duplicates")
        return values

    @field_validator("by_key")
    @classmethod
    def validate_key_mappings(cls, values: dict[str, str]) -> dict[str, str]:
        """Require every key and mapping name to be explicit and trimmed."""
        if any(
            not key or key != key.strip() or not name or name != name.strip() for key, name in values.items()
        ):
            raise ValueError("MappingSelection keys and mapping names must be non-empty and trimmed")
        return values

    @model_validator(mode="after")
    def validate_priority_references(self) -> MappingSelection:
        """Require every mapped key to have an explicit position in the priority list."""
        unknown_keys = sorted(set(self.by_key) - set(self.priority))
        if unknown_keys:
            raise ValueError(f"MappingSelection by_key contains keys absent from priority: {unknown_keys}")
        return self


class FixedMappingRoute(BaseModel):
    """Choose one named RuleMapping for every record in a batch."""

    kind: Literal["fixed"] = "fixed"
    name: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Require a trimmed mapping name."""
        if value != value.strip():
            raise ValueError("FixedMappingRoute.name cannot contain surrounding whitespace")
        return value


class SelectedMappingRoute(BaseModel):
    """Choose a named MappingSelection for every record in a batch."""

    kind: Literal["selected"] = "selected"
    name: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Require a trimmed selection name."""
        if value != value.strip():
            raise ValueError("SelectedMappingRoute.name cannot contain surrounding whitespace")
        return value


MappingRoute: TypeAlias = Annotated[FixedMappingRoute | SelectedMappingRoute, Field(discriminator="kind")]


class Rule(RuleMapping):
    """One mapping rule with an explicit source and output target."""

    source: RuleSource
    depends_on: tuple[str, ...] = ()

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    @field_validator("depends_on")
    @classmethod
    def validate_dependencies(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique, trimmed dependency names."""
        if any(not name or name != name.strip() for name in names):
            raise ValueError("Rule.depends_on names must be non-empty and trimmed")
        if len(set(names)) != len(names):
            raise ValueError("Rule.depends_on cannot contain duplicates")
        return names

    def __str__(self) -> str:
        """Represent the rule's declared source and target."""
        source_name = (
            self.source.component_type
            if isinstance(self.source, ComponentSource)
            else f"dataset:{self.source.dataset}"
        )
        target_name = (
            ",".join(self.target.component_types)
            if isinstance(self.target, ComponentTarget)
            else self.target.attribute_type
        )
        return f"{source_name}->{target_name}(v{self.version})"

    def __hash__(self) -> int:
        """Hash rules by their declared source, target, and version."""
        target_key = (
            ("component", self.target.component_types)
            if isinstance(self.target, ComponentTarget)
            else ("owned_supplemental", self.target.attribute_type, self.target.owner_type)
        )
        return hash((self.source.kind, self.source.model_dump_json(), target_key, self.version))

    def __eq__(self, other: object) -> bool:
        """Compare rules by their source, target, and version."""
        if not isinstance(other, Rule):
            return NotImplemented
        return self.source == other.source and self.target == other.target and self.version == other.version


class RuleStage(BaseModel):
    """An explicitly ordered set of named executable Rules."""

    name: str = Field(min_length=1)
    rules: tuple[str, ...] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Require a trimmed stage name."""
        if value != value.strip():
            raise ValueError("RuleStage.name cannot contain surrounding whitespace")
        return value

    @field_validator("rules")
    @classmethod
    def validate_rules(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique, trimmed rule names while preserving declared order."""
        if any(not value or value != value.strip() for value in values):
            raise ValueError("RuleStage rule names must be non-empty and trimmed")
        if len(set(values)) != len(values):
            raise ValueError("RuleStage cannot execute one Rule more than once")
        return values


class RulePlanDocument(BaseModel):
    """Typed configuration envelope for shared executable and detached Rules."""

    mappings: tuple[RuleMapping, ...] = ()
    rules: tuple[Rule, ...] = ()
    mapping_selections: tuple[MappingSelection, ...] = ()
    execution: tuple[RuleStage, ...] = ()
    required_stages: tuple[str, ...] = ()
    required_rules: tuple[str, ...] = ()
    required_datasets: tuple[str, ...] = ()

    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("mappings", mode="before")
    @classmethod
    def parse_mappings(cls, values: object) -> object:
        """Resolve configured getter names and validate each shared mapping."""
        if isinstance(values, Sequence) and not isinstance(values, str | bytes):
            mappings: list[RuleMapping] = []
            for value in values:
                if isinstance(value, RuleMapping):
                    mappings.append(value)
                    continue
                if not isinstance(value, Mapping):
                    return values
                record: dict[str, object] = {}
                for key, item in value.items():
                    if not isinstance(key, str):
                        return values
                    record[key] = item
                mappings.extend(RuleMapping.from_records([record]))
            return mappings
        return values

    @field_validator("rules", mode="before")
    @classmethod
    def parse_rules(cls, values: object) -> object:
        """Resolve configured getter names and validate each executable Rule."""
        if isinstance(values, Sequence) and not isinstance(values, str | bytes):
            rules: list[Rule] = []
            for value in values:
                if isinstance(value, Rule):
                    rules.append(value)
                    continue
                if not isinstance(value, Mapping):
                    return values
                record: dict[str, object] = {}
                for key, item in value.items():
                    if not isinstance(key, str):
                        return values
                    record[key] = item
                rules.extend(Rule.from_records([record]))
            return rules
        return values

    @field_validator("required_stages", "required_rules", "required_datasets")
    @classmethod
    def validate_requirements(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique, non-empty requirement names."""
        if any(not value or value != value.strip() for value in values):
            raise ValueError("RulePlan requirements must be non-empty and trimmed")
        if len(set(values)) != len(values):
            raise ValueError("RulePlan requirements cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def validate_references(self) -> RulePlanDocument:
        """Reject duplicate names and unresolved stage/rule requirements."""
        mapping_names = [mapping.name for mapping in self.mappings]
        rule_names = [rule.name for rule in self.rules]
        selection_names = [selection.name for selection in self.mapping_selections]
        if any(name is None for name in (*mapping_names, *rule_names)):
            raise ValueError("Every RulePlan mapping and Rule must have a name")
        names = [*mapping_names, *rule_names, *selection_names]
        if len(set(names)) != len(names):
            raise ValueError("RulePlan names must be unique across mappings and rules")
        stage_names = [stage.name for stage in self.execution]
        if len(set(stage_names)) != len(stage_names):
            raise ValueError("RulePlan stage names must be unique")
        mapping_name_set = set(mapping_names)
        rule_name_set = set(rule_names)
        unknown_mappings = sorted(
            {
                mapping_name
                for selection in self.mapping_selections
                for mapping_name in selection.by_key.values()
            }
            - mapping_name_set
        )
        if unknown_mappings:
            raise ValueError(f"RulePlan selections reference unknown mappings: {unknown_mappings}")
        unknown_rules = sorted({name for stage in self.execution for name in stage.rules} - rule_name_set)
        if unknown_rules:
            raise ValueError(f"RulePlan stages reference unknown executable Rules: {unknown_rules}")
        unknown_dependencies = sorted(
            {dependency for rule in self.rules for dependency in rule.depends_on} - rule_name_set
        )
        if unknown_dependencies:
            raise ValueError(f"RulePlan Rules reference unknown dependencies: {unknown_dependencies}")
        known_names = mapping_name_set | rule_name_set
        missing_rules = sorted(set(self.required_rules) - known_names)
        if missing_rules:
            raise ValueError(f"Required RulePlan rule(s) are missing: {missing_rules}")
        missing_stages = sorted(set(self.required_stages) - set(stage_names))
        if missing_stages:
            raise ValueError(f"Required RulePlan stage(s) are missing: {missing_stages}")
        return self


def parse_rule_source(value: object) -> RuleSource:
    """Validate one JSON-compatible explicit Rule source variant."""
    return TypeAdapter(RuleSource).validate_python(value)


def parse_rule_target(value: object) -> RuleTarget:
    """Validate one JSON-compatible explicit Rule target variant."""
    return TypeAdapter(RuleTarget).validate_python(value)


RuleFilter.model_rebuild()
