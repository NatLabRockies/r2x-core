# Documentation development

The public documentation is an Astro/Starlight site with Pagefind search and basepath `/r2x-core/`.
Use Node.js 22.22 or newer and the locked Python documentation environment:

```bash
uv sync --locked --group docs --group dev
npm ci --prefix docs
just docs
```

The deployable static output is `docs/dist/`.
`cd docs && npm run dev` regenerates the API and starts a local development server.
No hosting or repository settings are changed by these commands.

## Authoring

Edit task-focused pages under `src/content/docs/` using standard Markdown and Starlight frontmatter.
Links are rooted at `/r2x-core/`.
Historical `.html` page paths redirect to current pages.
The version guide links to actual Git tags without claiming separately hosted snapshots.

## API contracts

Sphinx is an internal API extraction step only.
Existing directives under `source/references/` remain the source of truth for API coverage.
Autodoc, Napoleon, and autodoc-pydantic preserve Python signatures, field types and defaults, returns, errors, inherited contracts, and examples.
Replacing these with hand-maintained contracts would duplicate source and lose coverage.

`generate_api.py` builds JSON in `build/api-json/`, then wraps each reference body in generated Starlight content under `src/content/docs/references/`.
It resolves relative links into Astro routes and retains API anchor IDs.
Implementation links are pinned to the build checkout's Git commit.
Generated content is ignored by Git and must not be edited.
Root `CHANGELOG.md` similarly generates the release-notes page without a maintained duplicate.
The public build uses Astro; no Sphinx theme or standalone Sphinx site is published.

## Validation and publishing

Run `just docs`, then use `npm run preview` from this directory to inspect the production output.
Verify guide and API links, signatures, configuration tables, source links, and Pagefind search.
Run the repository hooks on changed source files.
The existing GitHub documentation workflow builds this Astro output and publishes `docs/dist/` through the unchanged gh-pages provider.
Its deployment condition, branch, token, and permissions are preserved; running a local build does not deploy anything.

## Executable examples and branding

`examples/csv-system/` is the small input-to-artifact workflow used by the getting-started tutorial.
Run its build and inspection scripts from that directory with the root project environment.
The negative-input case is expected to fail validation before export.
The source SVGs under `src/assets/` are the shared R2X light/dark and square marks; the header keeps the package title visible and uses R2X's sizing and theme colors.
