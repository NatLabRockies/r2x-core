from collections.abc import Generator
from pathlib import Path

import pytest
from loguru import logger

from r2x_core.logger import setup_logging

pytest_plugins = [
    "fixtures.rules",
    "fixtures.context",
    "fixtures.source_system",
    "fixtures.target_system",
]


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers for documentation tests."""
    config.addinivalue_line(
        "markers",
        "doctest: tests for documentation examples",
    )
    config.addinivalue_line(
        "markers",
        "doc_coverage: tests for API documentation coverage",
    )


@pytest.fixture(scope="function")
def empty_file(tmp_path) -> Generator[Path, None, None]:
    empty_fpath = tmp_path / "test.csv"
    empty_fpath.write_text("")
    yield empty_fpath
    empty_fpath.unlink()


@pytest.fixture
def caplog(caplog):
    # verbosity=2 enables TRACE level
    setup_logging(verbosity=2)
    handler_id = logger.add(caplog.handler, format="{message}")
    yield caplog
    logger.remove(handler_id)
