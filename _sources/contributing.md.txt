# Contributing

We welcome contributions to R2X Core! This guide will help you get started with contributing to the project.

## Development Setup

### How to set up a development environment

Set up a development environment for contributing to R2X Core:

```console
# Clone the repository
git clone https://github.com/NREL/r2x-core.git
cd r2x-core

# Install with development dependencies
uv sync --dev

# Install prek hooks
uv run prek install
```

### How to run tests

Execute the test suite:

```console
# Run all tests
uv run pytest

# Run tests with coverage
uv run pytest --cov --cov-report=xml

# Run tests with verbose output
uv run pytest -vvl
```

### How to run code quality checks

Ensure code quality and consistency:

```console
# Run prek checks on all files
uv run prek run --all-files

# Run type checking
uv run mypy --config-file=pyproject.toml src/

# Run linting and formatting
uv run ruff check src/
uv run ruff format src/
```

## Documentation

### How to build documentation locally

Build and preview the documentation:

```console
# Navigate to docs directory
cd docs

# Build HTML documentation
make html

# Serve documentation locally for live editing
make livehtml
```

### How to add new documentation

Add new content to the documentation:

1. Create or edit markdown files in `docs/source/`
2. Update `docs/source/index.md` if adding new sections
3. Build and preview locally:
   ```console
   make html
   ```
4. Check that links and references work correctly

## Contributing Guidelines

### How to contribute to R2X Core

Follow these steps to contribute:

1. **Fork the repository** on GitHub
2. **Create a feature branch**:
   ```console
   git switch -c feature/my-new-feature
   ```
3. **Make your changes** following the coding standards
4. **Run tests and checks**:
   ```console
   uv run pytest
   uv run prek run --all-files
   ```
5. **Commit your changes** using conventional commit format:
   ```console
   git commit -m "feat: add new file reader for XYZ format"
   ```
6. **Push to your fork** and create a pull request

### How to report issues

Report bugs or request features:

1. Check existing issues on GitHub
2. Create a new issue with:
   - Clear description of the problem/feature
   - Steps to reproduce (for bugs)
   - Expected vs actual behavior
   - Environment details (Python version, OS, etc.)

### How to write documentation

Follow documentation standards:

1. Use MyST Markdown format
2. Follow Diataxis principles:
   - **How-tos**: Goal-oriented guides
   - **Tutorials**: Learning-oriented lessons
   - **Reference**: Information-oriented details
   - **Explanation**: Understanding-oriented discussion
3. Include code examples where appropriate
4. Test documentation builds locally before submitting

## Git Conventions

### Branch Naming

Use descriptive branch names following this pattern:

```
<type>/<scope>
```

**Types:**

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `chore/` - Maintenance tasks
- `refactor/` - Code improvements

**Examples:**

- `feature/plexos-parser`
- `fix/data-validation`
- `docs/api-reference`

### Commit Message Format

Follow the [Angular/Karma](https://karma-runner.github.io/6.4/dev/git-commit-msg.html) convention:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Types:**

- `feat`: New features
- `fix`: Bug fixes
- `docs`: Documentation changes
- `style`: Code style changes (formatting, missing semicolons, etc.)
- `refactor`: Code changes that neither fix bugs nor add features
- `test`: Adding or modifying tests
- `chore`: Changes to build process or auxiliary tools

**Examples:**

```
feat(parser): add support for PLEXOS XML files
fix(validation): handle missing data columns
docs: update API reference for DataStore
```

### Pull Request Guidelines

1. **Create from feature branch**: Always branch from `main`
2. **Keep changes focused**: One feature or fix per PR
3. **Include tests**: All new code must have corresponding tests
4. **Update documentation**: Include relevant documentation updates
5. **Clean commit history**: Squash commits if necessary

### Git Workflow

We use a **trunk-based development** approach:

1. **Create feature branch** from `main`:

   ```bash
   git switch -c feature/your-feature-name
   ```

2. **Make changes** and commit regularly with clear messages

3. **Keep branch updated** with main:

   ```bash
   git fetch origin
   git rebase origin/main
   ```

4. **Push and create PR** when ready:

   ```bash
   git push origin feature/your-feature-name
   ```

5. **Delete branch** after merge:
   ```bash
   git branch -d feature/your-feature-name
   ```

## Development Practices

### Code Quality Tools

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check for issues
uv run ruff check

# Auto-fix issues
uv run ruff check --fix

# Format code
uv run ruff format
```

### Prek Hooks

Install prek hooks to automatically run checks:

```bash
uv run prek install
```

This will run linting and formatting before each commit.

### Type Checking

Use mypy for static type checking:

```bash
uv run mypy src/
```

### Testing Standards

- **Unit tests**: Test individual functions and classes
- **Integration tests**: Test component interactions
- **Coverage**: Maintain minimum 80% code coverage
- **Clear test names**: Use descriptive test function names
- **Isolated tests**: Each test should be independent

### Documentation Standards

We follow the [Diataxis](https://diataxis.fr/) framework:

- **How-to guides**: Problem-oriented practical steps
- **Tutorials**: Learning-oriented lessons
- **Reference**: Information-oriented technical descriptions
- **Explanation**: Understanding-oriented discussions

### Useful Python References

- [Python Enhancement Proposals (PEPs)](https://peps.python.org/)
- [Type Hints Cheat Sheet](https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html)
- [Testing Best Practices](https://docs.python-guide.org/writing/tests/)

## Code Standards

### Coding Conventions

We follow Python best practices:

- PEP 8 style guide (enforced by Ruff)
- Type hints for all function signatures
- Docstrings for all public functions and classes
- Clear, descriptive variable and function names

### Testing Requirements

- All new features must include tests
- Maintain minimum 80% code coverage
- Tests should be clear and maintainable
- Use pytest for all testing
