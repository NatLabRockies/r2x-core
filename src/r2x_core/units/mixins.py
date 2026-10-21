"""Mixins for unit-aware Pydantic models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from pydantic import PrivateAttr

from .specs import UnitSpec

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

__all__ = ["HasPerUnit", "HasUnits"]


class HasUnits:
    """Add unit metadata and display formatting to a Pydantic model.

    Unit specifications are collected from Pydantic field metadata when each
    model class is created. Specifications that reference a base field are
    bound to that field's unit at the same time.
    """

    unit_specs: ClassVar[dict[str, UnitSpec]] = {}

    if TYPE_CHECKING:
        model_fields: ClassVar[dict[str, FieldInfo]]

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Collect unit metadata and bind each declared base unit."""
        cast(Any, super()).__pydantic_init_subclass__(**kwargs)

        specs: dict[str, UnitSpec] = {}
        for field_name, field_info in cls.model_fields.items():
            for metadata in field_info.metadata:
                if isinstance(metadata, UnitSpec):
                    specs[field_name] = metadata

        for field_name, spec in specs.items():
            if spec.base is None:
                continue
            base_spec = specs.get(spec.base)
            if base_spec is None:
                msg = (
                    f"{cls.__name__}.{field_name} references base field {spec.base!r}, which has no UnitSpec"
                )
                raise TypeError(msg)
            spec.bind_base_unit(base_spec.unit)

        cls.unit_specs = specs

    @property
    def system_base(self) -> float | None:
        """Return the system base when this model supports it."""
        return None

    def __repr_args__(self) -> list[tuple[str | None, Any]]:
        """Format model fields using the active unit display mode.

        Returns
        -------
        list[tuple[str | None, Any]]
            Field names and display-formatted values used by ``repr``.
        """
        from . import get_unit_system
        from .conversion import format_for_display

        repr_args: list[tuple[str | None, Any]] = []
        unit_system = get_unit_system()

        for field_name in type(self).model_fields:
            if field_name.startswith("_"):
                continue

            value = getattr(self, field_name)
            spec = type(self).unit_specs.get(field_name)
            if spec is None:
                repr_args.append((field_name, value))
                continue

            base_value = getattr(self, spec.base) if spec.base is not None else None
            formatted = format_for_display(
                value,
                spec,
                unit_system,
                base_value,
                spec.base_unit,
                self.system_base,
            )
            repr_args.append((field_name, formatted))

        return repr_args


class HasPerUnit(HasUnits):
    """Add system-base display state to a unit-aware model."""

    _system_base: float | None = PrivateAttr(default=None)

    @property
    def system_base(self) -> float | None:
        """Return the system base power bound to this model."""
        return self.__dict__.get("_system_base")

    def bind_system_base(self, base_power: float | None) -> None:
        """Set the system base used for per-unit display.

        Parameters
        ----------
        base_power : float or None
            System base power to bind to this model.
        """
        self.__dict__["_system_base"] = base_power
