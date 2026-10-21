"""Unit specification and annotation types."""

from __future__ import annotations

import types
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Union, cast, get_args, get_origin

from pydantic import BaseModel, GetCoreSchemaHandler
from pydantic_core import core_schema

from .conversion import convert_to_internal

if TYPE_CHECKING:
    from pydantic import GetJsonSchemaHandler
    from pydantic.json_schema import JsonSchemaValue

__all__ = ["Unit", "UnitSpec", "unit_spec"]


@dataclass(slots=True, eq=False)
class UnitSpec:
    """Metadata descriptor for unit-aware fields.

    ``base_unit`` is resolved from the owning model's declared fields when its
    class is created. A specification with ``base`` cannot be used for natural-
    unit conversion until that binding has been made.

    Attributes
    ----------
    unit : str
        Unit string, such as ``"MVA"``, ``"pu"``, or ``"kV"``.
    base : str or None
        Field name for device-base lookup.
    base_unit : str or None
        Resolved unit of the referenced base field.
    """

    unit: str
    base: str | None = None
    base_unit: str | None = field(default=None, init=False)

    def bind_base_unit(self, base_unit: str) -> None:
        """Bind the declared base field's unit once.

        Parameters
        ----------
        base_unit : str
            Unit declared by the referenced base field.

        Raises
        ------
        ValueError
            If this specification was already bound to a different unit.
        """
        if self.base_unit is not None and self.base_unit != base_unit:
            raise ValueError(f"Base unit is already bound as {self.base_unit!r}, not {base_unit!r}")
        self.base_unit = base_unit

    def validate_value(self, value: Any, info: core_schema.ValidationInfo) -> float | BaseModel | None:
        """Validate and convert one value carrying this unit specification."""
        if value is None:
            return None

        if isinstance(value, BaseModel):
            return self.convert_structured_value(value, info)

        if isinstance(value, int | float):
            return float(value)

        if isinstance(value, dict):
            if "value" in value and "unit" in value:
                input_value = float(cast(Any, value["value"]))

                if self.base is None:
                    return input_value

                base_value = info.data.get(self.base) if info.data is not None else None
                if base_value is None:
                    return input_value

                return convert_to_internal(value, self, base_value, self.base_unit)

            raise ValueError("Dict must contain 'value' and 'unit' keys for unit conversion")

        raise ValueError("Expected float, dict with 'value' and 'unit', or BaseModel instance")

    def convert_structured_value(
        self,
        value: BaseModel,
        info: core_schema.ValidationInfo,
    ) -> BaseModel:
        """Convert numeric fields of a structured value to per-unit form."""
        if self.base is None:
            return value

        base_value = info.data.get(self.base) if info.data is not None else None
        if base_value is None:
            return value

        from .mixins import HasUnits

        model_fields = type(value).model_fields
        structured_values = value.model_dump()
        converted_fields: dict[str, Any] = {}

        if isinstance(value, HasUnits):
            convertible_fields = {
                field_name
                for field_name, field_spec in type(value).unit_specs.items()
                if field_spec.base is None
            }
            for field_name, field_value in structured_values.items():
                if (
                    field_name in convertible_fields
                    and isinstance(field_value, int | float)
                    and not isinstance(field_value, bool)
                ):
                    converted_fields[field_name] = field_value / base_value
                else:
                    converted_fields[field_name] = field_value
            return type(value)(**converted_fields)

        for field_name, field_value in structured_values.items():
            field_info = model_fields.get(field_name)
            if field_info is None:
                converted_fields[field_name] = field_value
                continue

            field_type = field_info.annotation
            origin = get_origin(field_type)
            if origin in (Union, types.UnionType):
                args = get_args(field_type)
                non_none_types = [arg for arg in args if arg is not type(None)]
                if non_none_types:
                    field_type = non_none_types[0]

            is_numeric = field_type in (int, float) or (
                isinstance(field_type, type)
                and issubclass(field_type, int | float)
                and not issubclass(field_type, bool)
            )

            if is_numeric and isinstance(field_value, int | float) and not isinstance(field_value, bool):
                converted_fields[field_name] = field_value / base_value
            else:
                converted_fields[field_name] = field_value

        return type(value)(**converted_fields)

    def __get_pydantic_core_schema__(
        self,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """Build validation and serialization behavior for an annotated field."""
        actual_type = source_type
        origin = get_origin(source_type)
        if origin in (Union, types.UnionType):
            args = get_args(source_type)
            non_none_types = [arg for arg in args if arg is not type(None)]
            if non_none_types:
                actual_type = non_none_types[0]

        is_structured_type = isinstance(actual_type, type) and issubclass(actual_type, BaseModel)

        if is_structured_type:
            python_schema = core_schema.with_info_after_validator_function(
                self.validate_value,
                core_schema.union_schema([handler(actual_type), core_schema.none_schema()]),
            )

            def serialize_structured(value: Any) -> Any:
                """Serialize a structured unit value as a mapping."""
                if isinstance(value, BaseModel):
                    return value.model_dump()
                return value

            return core_schema.json_or_python_schema(
                json_schema=handler(actual_type),
                python_schema=python_schema,
                serialization=core_schema.plain_serializer_function_ser_schema(
                    serialize_structured,
                    return_schema=core_schema.dict_schema(),
                    when_used="json-unless-none",
                ),
            )

        python_schema = core_schema.with_info_after_validator_function(
            self.validate_value,
            core_schema.union_schema(
                [core_schema.float_schema(), core_schema.dict_schema(), core_schema.none_schema()]
            ),
        )

        return core_schema.json_or_python_schema(
            json_schema=core_schema.float_schema(),
            python_schema=python_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: float(value) if isinstance(value, int | float) else value,
                return_schema=core_schema.float_schema(),
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _core_schema: core_schema.CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        """Generate a numeric JSON Schema for unit-annotated fields."""
        return handler(core_schema.float_schema())


def unit_spec(
    unit: str,
    *,
    base: str | None = None,
) -> UnitSpec:
    """Create a unit specification for an annotated model field.

    Parameters
    ----------
    unit : str
        Unit string, such as ``"MVA"``, ``"kV"``, or ``"pu"``.
    base : str or None, optional
        Name of the field that provides the device base.

    Returns
    -------
    UnitSpec
        Unit metadata for use with ``typing.Annotated``.
    """
    return UnitSpec(unit=unit, base=base)


Unit = unit_spec
