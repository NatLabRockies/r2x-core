# Documentation development

The public docs use Astro, Starlight, and Pagefind. Their base path is `/r2x-core/`.
Use Node.js 22.22 or newer and the locked Python documentation environment:

```bash
uv sync --locked --group docs --group dev
npm ci --prefix docs
mise run docs
```

The deployable static output is `docs/dist/`.
`cd docs && npm run dev` regenerates the API and starts a local development server.
No hosting or repository settings are changed by these commands.

## Authoring

Edit pages under `src/content/docs/` in standard Markdown with Starlight frontmatter.
Links start at `/r2x-core/`. Old `.html` links redirect to current pages and keep query strings and member anchors.
Use `python doctest` fences with `>>>` prompts and checked output or assertions for runnable examples. Each block runs in a fresh namespace. Mark examples that depend on outside context as illustrative. Do not treat their imports or commented calls as tested behavior.
The version guide links to Git tags. It does not claim that separate snapshots are hosted.

## API contracts

Sphinx extracts the API for the site. The directives under `source/references/` define which APIs appear in the reference.
Autodoc, Napoleon, and autodoc-pydantic preserve Python signatures, field types and defaults, returns, errors, inherited contracts, and examples.
Handwritten contracts would repeat the source and miss details.

`../scripts/generate_api.py` builds JSON in `build/api-json/` and creates Starlight pages under `src/content/docs/references/`.
Its PEP 723 dependencies and lockfile keep Sphinx tools separate from the docs environment. It installs this checkout in editable mode so the API reflects the code being built.
The script converts relative links to Astro routes and keeps API anchor IDs. Sphinx also builds `src/generated/api-toc.json`. Starlight uses that file for the desktop sidebar and mobile contents menu, so do not maintain a second list.
Implementation links point to the Git commit used for the build. Generated files are ignored by Git. Do not edit them by hand.
The site builds release notes from the root `CHANGELOG.md`, so there is no second copy to maintain. Astro builds the public site. We do not publish a Sphinx site.

## Validation and publishing

Run `mise run docs`, then run `npm run preview` from this directory to inspect the built site.
Check guide and API links, signatures, configuration tables, source links, and Pagefind search. Run the repository hooks on changed files.
GitHub Actions publishes `docs/dist/` to GitHub Pages. A local build does not deploy the site.

## Executable examples and branding

The root `examples/csv-system/` directory contains the CSV to artifact example used by the getting started tutorial.
Run its build and inspection scripts from that directory with the root project environment. The invalid input example should fail validation before export.
The SVGs in `src/assets/` are the shared R2X marks for light and dark themes and square layouts. The header keeps the package title visible and uses R2X colors and sizing.

## Examples for newer Python versions

An example that needs newer Python syntax declares the version in its fence, for example `python doctest requires-python=3.12`.
When the host uses an older version, the docs runners use the version declared in the fence. They run it with `uv run --isolated` and the locked docs dependencies, without changing the host environment.
The runner checks every block and its expected output. If it cannot download or run the required Python version, the check fails.
The first run on Python 3.11 may need network access to download Python 3.12 and its isolated dependencies.
