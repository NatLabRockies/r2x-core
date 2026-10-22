"""Translation execution result data structures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rules import Rule


@dataclass(frozen=True, slots=True)
class RuleApplicationStats:
    """Statistics from applying a single transformation rule."""

    converted: int
    skipped: int


@dataclass(frozen=True, slots=True)
class ConversionOption:
    """A possible type conversion with version."""

    target_type: str
    version: int


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Result of applying a single transformation rule."""

    rule: Rule
    converted: int
    skipped: int
    success: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Aggregated statistics for a translation run."""

    total_rules: int
    successful_rules: int
    failed_rules: int
    total_converted: int
    rule_results: list[RuleResult]
    time_series_transferred: int = 0
    time_series_updated: int = 0

    @property
    def success(self) -> bool:
        """Return True if the translation completed without failures."""
        return self.failed_rules == 0

    def summary(self) -> None:
        """Display a simple summary table using rich."""
        from rich.console import Console
        from rich.table import Table

        console = Console()

        if not self.rule_results:
            return

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Status", justify="center", style="white", width=6)
        table.add_column("Rule", style="cyan")
        table.add_column("Converted", justify="right", style="yellow")
        table.add_column("Details", style="white")

        for result in self.rule_results:
            status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
            converted = str(result.converted) if result.converted > 0 else "[dim]0[/dim]"
            details = "[dim]success[/dim]" if result.success else f"[red]{result.error}[/red]"
            table.add_row(status, str(result.rule), converted, details)

        console.print(table)
