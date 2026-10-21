"""Adapter-neutral processing dispatch and placeholder substitution."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError
from rust_ok import Err, Ok, Result, is_err

from .datafile import DataFile
from .exceptions import ValidationError
from .json_adapter import JSONProcessor, default_json_processor
from .models import JSONProcessing, TabularProcessing
from .tabular_backend import TabularBackend, default_tabular_backend
from .types import PLACEHOLDER_PATTERN, FileProcessing


def substitute_placeholders(
    value: Any, *, placeholders: dict[str, Any] | None = None
) -> Result[Any, ValueError]:
    """Replace {variable} placeholders in values using provided mapping.

    Recursively substitutes placeholders in strings, lists, and dictionaries.
    Complete placeholders preserve their replacement type; embedded placeholders
    are converted to strings.

    Parameters
    ----------
    value : Any
        String, list, dict, or scalar value potentially containing placeholders.
    placeholders : dict[str, Any] | None
        Mapping from placeholder names to replacement values. Required if
        placeholders are found in value.

    Returns
    -------
    Result[Any, ValueError]
        Ok(substituted_value) on success, Err(ValueError) if placeholders found
        without mapping or placeholder name not in mapping dictionary.

    Examples
    --------
    >>> result = substitute_placeholders("{year}", placeholders={"year": 2030})
    >>> result.unwrap()
    2030

    >>> result = substitute_placeholders({"year": "{y}"}, placeholders={"y": 2030})
    >>> result.unwrap()
    {'year': 2030}
    """

    def substitute_value(val: Any) -> Result[Any, ValueError]:
        """Recursively substitute placeholders in a value."""
        if isinstance(val, str):
            if "{" not in val:
                return Ok(val)

            match = PLACEHOLDER_PATTERN.fullmatch(val)
            if match:
                var_name = match.group(1)
                if placeholders is None:
                    return Err(
                        ValueError(
                            f"Found placeholder '{{{var_name}}}' but no placeholders provided.\n"
                            "Hint: Pass placeholders parameter when calling read_data_file(), "
                            "or use literal values instead of placeholders."
                        )
                    )
                if var_name not in placeholders:
                    available = ", ".join(placeholders.keys())
                    return Err(
                        ValueError(
                            f"Placeholder '{{{var_name}}}' not found in placeholders.\n"
                            f"Available placeholders: {available}"
                        )
                    )
                return Ok(placeholders[var_name])

            matches = list(PLACEHOLDER_PATTERN.finditer(val))
            if matches:
                if placeholders is None:
                    name = matches[0].group(1)
                    return Err(ValueError(f"Found placeholder '{{{name}}}' but no placeholders provided."))
                missing = [match.group(1) for match in matches if match.group(1) not in placeholders]
                if missing:
                    available = ", ".join(placeholders)
                    return Err(
                        ValueError(
                            f"Placeholder '{{{missing[0]}}}' not found in placeholders.\n"
                            f"Available placeholders: {available}"
                        )
                    )
                return Ok(
                    PLACEHOLDER_PATTERN.sub(
                        lambda match: str(placeholders[match.group(1)]),
                        val,
                    )
                )
            return Ok(val)

        if isinstance(val, list):
            new_list = []
            local_changed = False
            for item in val:
                result = substitute_value(item)
                if is_err(result):
                    return result
                result_value = result.unwrap()
                new_list.append(result_value)
                if result_value is not item:
                    local_changed = True
            if not local_changed:
                return Ok(val)
            return Ok(new_list)

        if isinstance(val, dict):
            new_dict = {}
            local_changed = False
            for key, item in val.items():
                result = substitute_value(item)
                if is_err(result):
                    return result
                result_value = result.unwrap()
                new_dict[key] = result_value
                if result_value is not item:
                    local_changed = True
            if not local_changed:
                return Ok(val)
            return Ok(new_dict)

        return Ok(val)

    return substitute_value(value)


def apply_processing(
    data: Any,
    *,
    data_file: DataFile,
    proc_spec: FileProcessing | None,
    placeholders: dict[str, Any] | None = None,
    processor: TabularBackend[Any] | JSONProcessor | None = None,
) -> Result[Any, ValueError | ValidationError]:
    """Apply the processor selected by the configured processing specification."""
    if proc_spec is None:
        return Ok(data)

    spec_dict = proc_spec.model_dump()
    result_substitution = substitute_placeholders(spec_dict, placeholders=placeholders)
    if is_err(result_substitution):
        return Err(result_substitution.err())
    substituted = result_substitution.unwrap()
    if substituted is not spec_dict:
        try:
            new_proc = type(proc_spec).model_validate(substituted)
        except PydanticValidationError as error:
            return Err(
                ValueError(f"Invalid processing specification after placeholder substitution: {error}")
            )
        data_file = data_file.model_copy(update={"proc_spec": new_proc})
        proc_spec = new_proc

    match proc_spec:
        case TabularProcessing():
            selected = processor if processor is not None else default_tabular_backend()
            if not isinstance(selected, TabularBackend):
                return Err(ValueError("TabularProcessing requires a TabularBackend"))
            if not selected.supports_data(data):
                return Err(
                    ValueError(f"{type(selected).__name__} does not support data type {type(data).__name__}")
                )
            return selected.process(data, data_file=data_file, proc_spec=proc_spec)
        case JSONProcessing():
            if isinstance(processor, TabularBackend):
                return Err(ValueError("JSONProcessing requires a JSONProcessor"))
            selected = processor if processor is not None else default_json_processor()
            return selected.process(data, data_file=data_file, proc_spec=proc_spec)
