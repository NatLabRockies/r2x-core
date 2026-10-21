"""Unit conversion and display formatting."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pint

if TYPE_CHECKING:
    from .specs import UnitSpec

__all__ = ["convert_to_internal", "format_for_display", "ureg"]

ureg = pint.UnitRegistry()


def convert_to_internal(
    value: Any,
    spec: UnitSpec,
    base_value: float | None = None,
    base_unit: str | None = None,
) -> float:
    """Convert an input value to its internal representation.

    Parameters
    ----------
    value : float, int, or dict
        Input value. Dict inputs contain ``value`` and ``unit`` keys.
    spec : UnitSpec
        Unit metadata for the field.
    base_value : float or None, optional
        Base quantity value used for per-unit conversion.
    base_unit : str or None, optional
        Unit string declared by the base field.

    Returns
    -------
    float
        Value in internal representation.

    Raises
    ------
    ValueError
        If a required base value or base unit is unavailable.
    """
    if isinstance(value, int | float):
        return float(value)

    if not isinstance(value, dict):
        return 0.0

    if "value" not in value or "unit" not in value:
        return 0.0

    input_value = float(cast(Any, value["value"]))
    input_unit_str = str(cast(Any, value["unit"]))

    if spec.base is None:
        return input_value

    if base_value is None:
        msg = f"Base field '{spec.base}' is required for unit conversion but was not provided or is None"
        raise ValueError(msg)

    if base_unit is None:
        msg = f"Base unit for field '{spec.base}' could not be determined - check field annotations"
        raise ValueError(msg)

    if input_unit_str == base_unit:
        return input_value / base_value

    try:
        input_quantity = input_value * ureg(input_unit_str)
        base_quantity = base_value * ureg(base_unit)
        ratio: pint.Quantity = input_quantity / base_quantity
        return float(ratio.magnitude)
    except (pint.UndefinedUnitError, pint.DimensionalityError):
        return input_value / base_value


def format_for_display(
    value: float,
    spec: UnitSpec,
    unit_system: Any,
    base_value: float | None = None,
    base_unit: str | None = None,
    system_base: float | None = None,
) -> str:
    """Format an internal value according to the selected display mode.

    Parameters
    ----------
    value : float
        Internal value, using per-unit storage for relative quantities.
    spec : UnitSpec
        Unit metadata for the field.
    unit_system : UnitSystem
        Active display mode.
    base_value : float or None, optional
        Base field value for natural-unit conversion.
    base_unit : str or None, optional
        Unit declared by the base field.
    system_base : float or None, optional
        System-wide base used for system-base display.

    Returns
    -------
    str
        Value formatted with its display unit.
    """
    from . import UnitSystem

    if spec.base is None:
        return f"{value} {spec.unit}"

    if unit_system == UnitSystem.DEVICE_BASE:
        return f"{value} pu"

    if unit_system == UnitSystem.NATURAL_UNITS:
        if base_value is None or base_unit is None:
            return f"{value} pu"
        natural_value = value * base_value
        return f"{natural_value:.4g} {base_unit}"

    if unit_system == UnitSystem.SYSTEM_BASE:
        if base_value is None:
            return f"{value} pu"
        natural_value = value * base_value
        if system_base is not None and isinstance(system_base, int | float):
            system_pu = natural_value / system_base
            return f"{system_pu:.4g} pu (system)"
        return f"{value} pu"

    return f"{value} pu"
