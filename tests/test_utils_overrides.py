"""Unit tests for ``r2x_core.utils.overrides.merge_with_overrides``."""

import pytest

from r2x_core.utils import merge_with_overrides

pytestmark = pytest.mark.plugin


def test_merge_with_overrides_adds_new_keys_without_mutating_base():
    base = {"a": 1}
    overrides = {"b": 2}
    result = merge_with_overrides(base, overrides=overrides)

    assert result == {"a": 1, "b": 2}
    assert base == {"a": 1}


def test_merge_with_overrides_replaces_scalars():
    base = {"a": 1}
    overrides = {"a": 3}
    result = merge_with_overrides(base, overrides=overrides)

    assert result["a"] == 3


def test_merge_with_overrides_merges_list_with_shorter_override():
    base = {"items": [1, 2, 3]}
    overrides = {"items": [9]}
    result = merge_with_overrides(base, overrides=overrides)

    assert result["items"] == [9, 2, 3]


def test_merge_with_overrides_merges_list_with_longer_override():
    base = {"items": [1]}
    overrides = {"items": [9, 10]}
    result = merge_with_overrides(base, overrides=overrides)

    assert result["items"] == [9, 10]


def test_merge_with_overrides_merges_nested_dicts_and_lists():
    base = {"nested": {"choices": ["a", "b"], "value": 1}}
    overrides = {"nested": {"choices": ["x"], "value": 2}}
    result = merge_with_overrides(base, overrides=overrides)

    assert result["nested"]["choices"] == ["x", "b"]
    assert result["nested"]["value"] == 2
