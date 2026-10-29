"""Tests for translation result data structures."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from r2x_core.result import RuleResult, TranslationResult
from r2x_core.rules import Rule

pytestmark = pytest.mark.rules


@pytest.fixture
def sample_rule() -> Rule:
    """Return a simple rule instance for the tests."""
    return Rule(source_type="RuleA", target_type="RuleB", version=1)


@pytest.fixture
def rule_result_factory(sample_rule: Rule) -> Callable[..., RuleResult]:
    """Provide a helper for creating RuleResult instances."""

    def factory(
        *,
        converted: int = 0,
        skipped: int = 0,
        success: bool = True,
        error: str | None = None,
    ) -> RuleResult:
        return RuleResult(
            rule=sample_rule,
            converted=converted,
            skipped=skipped,
            success=success,
            error=error,
        )

    return factory


@pytest.fixture
def translation_result_factory(
    rule_result_factory: Callable[..., RuleResult],
) -> Callable[..., TranslationResult]:
    """Provide a helper for constructing TranslationResult instances."""

    def factory(
        *,
        total_rules: int = 1,
        successful_rules: int = 1,
        failed_rules: int = 0,
        total_converted: int = 0,
        rule_results: list[RuleResult] | None = None,
        time_series_transferred: int = 0,
        time_series_updated: int = 0,
    ) -> TranslationResult:
        if rule_results is None:
            rule_results = [rule_result_factory()]
        return TranslationResult(
            total_rules=total_rules,
            successful_rules=successful_rules,
            failed_rules=failed_rules,
            total_converted=total_converted,
            rule_results=rule_results,
            time_series_transferred=time_series_transferred,
            time_series_updated=time_series_updated,
        )

    return factory


def test_rule_result_creation(rule_result_factory: Callable[..., RuleResult], sample_rule: Rule) -> None:
    """RuleResult should store the provided values and rule reference."""
    result = rule_result_factory(converted=5, skipped=2, success=True)

    assert result.rule is sample_rule
    assert result.converted == 5
    assert result.skipped == 2
    assert result.success is True
    assert result.error is None


def test_rule_result_with_error(rule_result_factory: Callable[..., RuleResult]) -> None:
    """Errors provided to RuleResult should be preserved."""
    error_msg = "Rule execution failed"
    result = rule_result_factory(converted=0, skipped=0, success=False, error=error_msg)

    assert result.success is False
    assert result.error == error_msg


def test_rule_result_is_immutable(rule_result_factory: Callable[..., RuleResult]) -> None:
    """RuleResult is frozen, so attribute assignment should raise."""
    result = rule_result_factory()

    with pytest.raises(AttributeError):
        result.converted = 10  # type: ignore


def test_translation_result_creation(
    translation_result_factory: Callable[..., TranslationResult],
    rule_result_factory: Callable[..., RuleResult],
) -> None:
    """TranslationResult should aggregate statistics correctly."""
    rule_results = [
        rule_result_factory(converted=5, skipped=1, success=True),
        rule_result_factory(converted=3, skipped=2, success=True),
    ]
    result = translation_result_factory(
        total_rules=2,
        successful_rules=2,
        failed_rules=0,
        total_converted=8,
        rule_results=rule_results,
    )

    assert result.total_rules == 2
    assert result.successful_rules == 2
    assert result.failed_rules == 0
    assert result.total_converted == 8
    assert len(result.rule_results) == 2
    assert result.time_series_transferred == 0
    assert result.time_series_updated == 0


def test_translation_result_time_series_stats(
    translation_result_factory: Callable[..., TranslationResult],
) -> None:
    """Time series statistics should be accessible on the result."""
    result = translation_result_factory(
        time_series_transferred=10,
        time_series_updated=3,
    )

    assert result.time_series_transferred == 10
    assert result.time_series_updated == 3


@pytest.mark.parametrize("failed_rules,expected", [(0, True), (1, False)])
def test_translation_success_flag(
    translation_result_factory: Callable[..., TranslationResult],
    rule_result_factory: Callable[..., RuleResult],
    failed_rules: int,
    expected: bool,
) -> None:
    """success property is True only when no rules fail."""
    rule_results = [
        rule_result_factory(
            converted=1 if failed_rules == 0 else 0,
            success=failed_rules == 0,
            error=None if failed_rules == 0 else "failed",
        )
    ]
    result = translation_result_factory(
        total_rules=1,
        successful_rules=1 - failed_rules,
        failed_rules=failed_rules,
        total_converted=0,
        rule_results=rule_results,
    )

    assert result.success is expected


def test_translation_result_is_immutable(
    translation_result_factory: Callable[..., TranslationResult],
) -> None:
    """TranslationResult is frozen like RuleResult."""
    result = translation_result_factory()

    with pytest.raises(AttributeError):
        result.total_rules = 2  # type: ignore


def test_translation_summary_empty(
    translation_result_factory: Callable[..., TranslationResult],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """summary() should be no-op when there are no rule results."""
    result = translation_result_factory(
        total_rules=0,
        successful_rules=0,
        failed_rules=0,
        total_converted=0,
        rule_results=[],
    )

    result.summary()
    captured = capsys.readouterr()
    assert captured.out == ""


def test_translation_summary_with_results(
    translation_result_factory: Callable[..., TranslationResult],
    rule_result_factory: Callable[..., RuleResult],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """summary() should produce table headers when rule results exist."""
    rule_results = [
        rule_result_factory(converted=5, skipped=1, success=True),
        rule_result_factory(
            converted=0,
            skipped=1,
            success=False,
            error="Execution failed",
        ),
    ]
    result = translation_result_factory(
        total_rules=2,
        successful_rules=1,
        failed_rules=1,
        total_converted=5,
        rule_results=rule_results,
    )

    result.summary()
    captured = capsys.readouterr()
    for header in ("Status", "Rule", "Converted", "Details"):
        assert header in captured.out
