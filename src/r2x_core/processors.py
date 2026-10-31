"""Shared placeholder substitution for input paths, options, and operations."""

from __future__ import annotations

from collections.abc import Mapping

from rust_ok import Err, Ok, Result, is_ok

from .types import PLACEHOLDER_PATTERN, JSONValue


def substitute_placeholders(
    value: object,
    *,
    placeholders: Mapping[str, JSONValue] | None = None,
) -> Result[object, ValueError]:
    """Replace placeholders recursively without changing non-string mapping keys."""
    if isinstance(value, str):
        whole = PLACEHOLDER_PATTERN.fullmatch(value)
        if whole:
            name = whole.group(1)
            if placeholders is None or name not in placeholders:
                return Err(ValueError(f"Placeholder {{{name}}} has no configured value"))
            return Ok(placeholders[name])
        matches = tuple(PLACEHOLDER_PATTERN.finditer(value))
        if not matches:
            return Ok(value)
        if placeholders is None:
            return Err(ValueError(f"Placeholder {{{matches[0].group(1)}}} has no configured value"))
        missing = next((match.group(1) for match in matches if match.group(1) not in placeholders), None)
        if missing is not None:
            return Err(ValueError(f"Placeholder {{{missing}}} has no configured value"))
        return Ok(PLACEHOLDER_PATTERN.sub(lambda match: str(placeholders[match.group(1)]), value))

    if isinstance(value, list):
        result: list[object] = []
        for item in value:
            substituted = substitute_placeholders(item, placeholders=placeholders)
            if is_ok(substituted):
                result.append(substituted.value)
            else:
                return Err(substituted.err())
        return Ok(result)

    if isinstance(value, dict):
        result: dict[object, object] = {}
        for key, item in value.items():
            substituted = substitute_placeholders(item, placeholders=placeholders)
            if is_ok(substituted):
                result[key] = substituted.value
            else:
                return Err(substituted.err())
        return Ok(result)

    return Ok(value)
