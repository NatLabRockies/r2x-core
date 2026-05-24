# ADR 0001: CI Strategy

2026-05-24

## Status

Accepted

## Context

Our CI workflow needs to balance speed (fast PR feedback) with safety (comprehensive
gates on main). We evaluated the mdo4grid and arco CI workflows for patterns worth
adopting and made the following decisions:

## Decisions

### Trigger strategy

1. **Push triggers only on `main`** — PR `synchronize` events already cover
   feature branch pushes. Running both `push` + `pull_request` on every commit
   doubles CI jobs with no added value.

2. **Path filters** — CI only runs when relevant files change (`src/`, `tests/`,
   `pyproject.toml`, `uv.lock`, `.github/workflows/ci.yaml`). Docs-only or
   README changes skip the full pipeline. `docs.yaml` has its own trigger and
   is not affected.

### Python test matrix

3. **Inline dynamic matrix via `fromJSON`** — PRs test Python 3.12 and 3.14
   (the extremes of our support range). Full matrix (3.11–3.14) runs on pushes
   to `main`. Implemented as a one-liner in the matrix definition rather than
   a separate `define-matrix` job (pattern adopted from arco):

   ```yaml
   python: ${{ fromJSON(github.event_name == 'push' && '["3.11","3.12","3.13","3.14"]' || '["3.12","3.14"]') }}
   ```

### Pre-commit hooks

4. **`prek --fail-fast`** — Stops on first lint/type/spell failure instead of
   running every hook. Faster feedback; developers can run `just hooks` locally
   for the full report.

### Timeouts and concurrency

5. **`timeout-minutes` on all jobs** — Pre-commit: 10 min, Tests: 30 min,
   Package: 20 min, Docs: 20 min. Prevents hung jobs from burning CI minutes.

6. **`concurrency` on all workflows** — Commit lint, docs, and release workflows
   also get `concurrency` groups to cancel redundant runs. Already present on
   `ci.yaml`; extended to `commit.yaml`.

### Security hardening

7. **`permissions: contents: read`** on all workflows — Principle of least
   privilege. Only `release.yaml` needs `contents: write`.

8. **`persist-credentials: false`** on all `actions/checkout` steps — Prevents
   the GITHUB_TOKEN from persisting in the local git config beyond the checkout
   step.

### Workflow quality

9. **`workflow-quality.yaml`** — New workflow that runs `zizmor --pedantic`
   (GitHub Actions security linter) and `actionlint` (syntax/semantics checker)
   whenever `.github/**` files change. Triggers on both PRs and main pushes
   when the `.github/` path changes. Pattern adopted from arco.

## Consequences

- Faster PR feedback: reduced Python matrix + fail-fast prek
- Fewer CI jobs: no double runs on feature branch pushes
- No loss of safety: full matrix on main push, path filters, codecov still reports
- Cleaner ci.yaml: inline matrix avoids a dedicated `define-matrix` job
- Workflow quality is continuously linted for security and correctness
- All workflows follow consistent security hardening pattern
