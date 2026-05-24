"""Parser utils."""

from typing import Any, TypeVar

from infrasys import Component
from pydantic import ValidationError as PydanticValidationError
from rust_ok import Err, Ok, Result

T = TypeVar("T", bound=Component)


def create_component(
    component_class: type[T],
    *,
    skip_none: bool = True,
    skip_validation: bool = False,
    **field_values: Any,
) -> Result[T, PydanticValidationError]:
    """Create and validate a component instance with optional validation skipping.

    This utility function returns a Result to allow recovery from validation errors
    (e.g., skipping invalid components, logging warnings, etc.).

    Parameters
    ----------
    component_class : type[T]
        The component class to instantiate.
    skip_none : bool, default True
        Whether to skip fields with None values when creating the component.
    skip_validation : bool, default False
        Skip Pydantic validation when creating components (faster but less safe).
    **field_values : Any
        Field values to pass to the component constructor.

    Returns
    -------
    Result[T, PydanticValidationError]
        ``Ok(component)`` if validation succeeds, or ``Err(validation_error)``
        if validation fails. Returns the specific component type T.

    Examples
    --------
    >>> from infrasys import Generator
    >>> result = create_component(Generator, name="Gen1", capacity=100.0)
    >>> if result.is_ok():
    ...     gen = result.value
    ...     print(gen.name)
    >>> else:
    ...     print(f"Error: {result.error}")
    """
    valid_fields = {
        k: v
        for k, v in field_values.items()
        if k in component_class.model_fields and (v is not None or not skip_none)
    }

    try:
        # Both paths return the same type T - either via model_construct or model_validate
        # model_construct bypasses __init__ and all validators for 2-3x speedup
        # on large batch component creation.
        if skip_validation:
            component = component_class.model_construct(**valid_fields)
        else:
            component = component_class.model_validate(valid_fields)
        return Ok(component)
    except PydanticValidationError as e:
        return Err(e)
