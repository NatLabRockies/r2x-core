# r2x-core automation tasks.

set dotenv-load := false

default:
    @just --list

alias sync := setup

# Install dev dependencies.
setup:
    uv sync --all-groups --locked

# Update uv.lock.
lock:
    uv lock

# Install git hooks.
hooks-install:
    uv run --locked prek install

# Format code.
format *ARGS:
    uv run --locked ruff format {{ARGS}}

# Lint code.
lint *ARGS:
    uv run --locked ruff check --config=pyproject.toml {{ARGS}}

# Type check.
type:
    uv run --locked ty check

# Check docstring coverage.
docstrings:
    uv run --locked docstr-coverage src --badge docs/source/_static --percentage-only

# Run tests.
test *ARGS:
    uv run --locked pytest -q --cov-report=term-missing:skip-covered {{ARGS}}

# Build documentation.
docs:
    uv run --locked sphinx-build -M html docs/source docs/build

# Run prek hooks (format, lint, type check, file hygiene).
hooks:
    uv run --locked prek run --all-files --stage pre-commit --show-diff-on-failure

# Comprehensive verification: hooks + tests + docstring coverage.
verify: hooks docstrings
    uv run --locked pytest --tb=short --cov-report=term-missing:skip-covered
