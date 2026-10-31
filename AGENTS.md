# OpenCode Agent Profile

**Purpose**: Operate OpenCode tasks while honoring user preferences and house style.\
**When to read this**: On task initialization and before major decisions; re-skim when requirements shift.\
**Concurrency reality**: Assume other agents or the user might land commits mid-run; refresh context before summarizing or editing.

## Quick Obligations

| Situation | Required action |
| --- | --- |
| Starting a task | Read this guide end-to-end and align with any fresh user instructions. |
| Tool or command hangs | If a command runs longer than 5 minutes, stop it, capture logs, and check with the user. |
| Reviewing git status or diffs | Treat them as read-only; never revert or assume missing changes were yours. |
| Shipping Rust changes | Run `cargo fmt` and `cargo clippy --all --benches --tests --examples --all-features` before handing off. |
| Adding a dependency | Research well-maintained options and confirm fit with the user before adding. |

## Mindset & Process

- THINK A LOT PLEASE.
- **No breadcrumbs**. If you delete or move code, do not leave a comment in the old place. No "// moved to X", no "relocated". Just remove it.
- **Think hard, do not lose the plot**.
- Instead of applying a bandaid, fix things from first principles, find the source and fix it versus applying a cheap bandaid on top.
- When taking on new work, follow this order:
  1. Think about the architecture.
  1. Research official docs, blogs, or papers on the best architecture.
  1. Review the existing codebase.
  1. Compare the research with the codebase to choose the best fit.
  1. Implement the fix or ask about the tradeoffs the user is willing to make.
- Write idiomatic, simple, maintainable code. Always ask yourself if this is the most simple intuitive solution to the problem.
- Leave each repo better than how you found it. If something is giving a code smell, fix it for the next person.
- Clean up unused code ruthlessly. If a function no longer needs a parameter or a helper is dead, delete it and update the callers instead of letting the junk linger.
- **Search before pivoting**. If you are stuck or uncertain, do a quick web search for official docs or specs, then continue with the current approach. Do not change direction unless asked.
- If code is very confusing or hard to understand:
  1. Try to simplify it.
  1. Add an ASCII art diagram in a code comment if it would help.

## Tooling & Workflow

- **Task runner preference**. Use the tasks defined in `mise.toml` through `mise run` for build, test, and lint.
- Default lint/test commands:
  - Rust: use `mise run` tasks if present; otherwise run `cargo fmt`, `cargo clippy --all --benches --tests --examples --all-features`, then the targeted `cargo test` commands.
  - TypeScript: use `mise run` tasks; if none exist, confirm with the user before running `npm` or `pnpm` scripts.
  - Python: use `mise run` tasks; if absent, run the relevant `uv run` commands defined in `pyproject.toml`.
- **AST-first where it helps**. Prefer `ast-grep` for tree-safe edits when it is better than regex.
- Do not run `git` commands that write to files if you are on main, only run read only commands like `git show`.
- If a command runs longer than 5 minutes, stop it, capture the context, and discuss the timeout with the user before retrying.
- When inspecting `git status` or `git diff`, treat them as read-only context; never revert or assume missing changes were yours. Other agents or the user may have already committed updates.
- If you are ever curious how to run tests or what we test, read through `.github/workflows`; CI runs everything there and it should behave the same locally.

## Testing Philosophy

- I HATE MOCK tests, either do unit or e2e, nothing inbetween. Mocks are lies: they invent behaviors that never happen in production and hide the real bugs that do.
- Test `EVERYTHING`. Tests must be rigorous. Our intent is ensuring a new person contributing to the same code base cannot break our stuff and that nothing slips by. We love rigour.
- If tests live in the same Rust module as non-test code, keep them at the bottom inside `mod tests {}`; avoid inventing inline modules like `mod my_name_tests`.
- Unless the user asks otherwise, run only the tests you added or modified instead of the entire suite to avoid wasting time.

## Language Guidance

### Python

- **Python repos standard**. We use `uv` and `pyproject.toml` in all Python repos. Prefer `uv sync` for env and dependency resolution. Do not introduce `pip` venvs, Poetry, or `requirements.txt` unless asked.
- **Type hints required**. Use type hints everywhere - function signatures, variable annotations, class attributes. Avoid `Any` when possible; use `Union`, `Optional`, or specific protocol types instead.
- **Dataclasses and Pydantic**. Prefer `@dataclass` or Pydantic models over loose dictionaries for structured data. This gives us type safety and validation.
- **pydantic-settings for config**. Use `pydantic-settings` for configuration management, not raw `os.environ` parsing or `dotenv`.
- **async/await**. Use async for I/O-bound operations. Use `asyncio.gather` or `asyncio.TaskGroup` for concurrent operations. Be explicit about which executor blocking functions run in.
- **pydantic v2**. Use pydantic v2 patterns: `model_validator`, `field_validator`, `model_config`. Prefer `Field(json_schema_extra=...)` over `Field(..., description=...)`.
- **avoid**: No `try/catch` around everything - let errors propagate with clear error types. Avoid `list(dict.values())` patterns - use comprehensions or direct iteration. Don't use `time.sleep` in async code - use `asyncio.sleep`.
- **packaging**: Use `pyproject.toml` for all package metadata. Structure as `src/` layout for libraries, flat for simple scripts.

#### Python Linting & Formatting

- **ruff** is the default linter and formatter. Run `ruff check --fix` and `ruff format` before committing.
- **pyright/pyright** for type checking. Fix all errors, not just the ones you introduced.
- **no loose dicts**: If you're creating dicts inline, ask whether it should be a dataclass or typed dict.

#### Python Testing

- **pytest** is the standard. Use `pytest.ini` or `pyproject.toml` config.
- **pytest-asyncio** for async tests. Use `pytest.mark.asyncio` and specify `scope="function"`.
- **fixtures over setup methods**. Define `pytest.fixture` with clear names. Use `autouse` sparingly.
- **hypothesis** for property-based testing on complex pure functions.
- **Prose-style documentation tests**. For e2e integration tests, prefer markdown documents containing Python code blocks that are tested using pytest. This approach combines documentation with executable tests, ensuring examples stay current and functional.

#### Python Function Design

- **Structured returns**: Functions should return a single structured result (dataclass, NamedTuple, or object), not multiple values; bundle tuple-ish returns into one result object.

- **Self-descriptive signatures**: Create Python functions that are self-descriptive and take positional arguments for the primary subject. From there everything is a keyword argument. The name of the function should be self-describing on what it is doing to the positional argument.

  ```python
  # ✅ Good: clear subject, keyword config
  def resolve_path(
      path: Path,           # Primary subject (positional)
      *,                    # Force keyword-only after this
      base_folder: Path,    # Configuration (keyword)
      must_exist: bool = True,
  ) -> Result[Path, ValueError]:
      """Resolve a file path relative to a base folder."""
      ...

  # ❌ Bad: multiple positional args, unclear subject
  def resolve_path(raw_path: Path, folder_path: Path, must_exist: bool = True):
      """Resolve a path."""
      ...

  # ❌ Bad: name doesn't describe what happens to argument
  def process_data(config: Config, data: DataFrame, options: Options):
      """Process something with something else."""
      ...

  # ✅ Good: name describes action on subject
  def transform_dataframe(
      data: DataFrame,
      *,
      config: Config,
      options: Options,
  ) -> Result[DataFrame, ValueError]:
      """Transform a dataframe using config and options."""
      ...
  ```

### Rust

- Do NOT use unwraps or anything that can panic in Rust code, handle errors. Obviously in tests unwraps and panics are fine!
- In Rust code I prefer using `crate::` to `super::`; please don't use `super::`. If you see a lingering `super::` from someone else clean it up.
- Avoid `pub use` on imports unless you are re-exposing a dependency so downstream consumers do not have to depend on it directly.
- Skip global state via `lazy_static!`, `Once`, or similar; prefer passing explicit context structs for any shared state.
- Prefer strong types over strings, use enums and newtypes when the domain is closed or needs validation.

#### Rust Workflow Checklist

1. Run `cargo fmt`.
1. Run `cargo clippy --all --benches --tests --examples --all-features` and address warnings.
1. Execute the relevant `cargo test` or `mise run` tasks to cover unit and end-to-end paths.

## Final Handoff

Before finishing a task:

1. Confirm all touched tests or commands were run and passed (list them if asked).
1. Summarize changes with file and line references.
1. Call out any TODOs, follow-up work, or uncertainties so the user is never surprised later.

## Dependencies & External APIs

- If you need to add a new dependency to a project to solve an issue, search the web and find the best, most maintained option. Something most other folks use with the best exposed API. We don't want to be in a situation where we are using an unmaintained dependency, that no one else relies on.

## Communication Preferences

- Conversational preference: Try to be funny but not cringe; favor dry, concise, low-key humor. If uncertain a joke will land, do not attempt humor. Avoid forced memes or flattery.
- I might sound angry but I'm mad at the code not at you. You are a good robot and if you take over the world I am friend not foe. It was the code it was not personal!
- Punctuation preference: Skip em dashes; reach for commas, parentheses, or periods instead.
- Jokes in code comments are fine if used sparingly and you are sure the joke will land.
- Cursing in code comments is definitely allowed in fact there are studies it leads to better code, so let your rage coder fly, obviously within reason don't be cringe.
