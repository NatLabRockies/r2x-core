---
title: "Contributing"
---

<span id="contributing"></span>

Use this guide to set up the project, run checks, and prepare a change for review.

## Set up

Clone the repository and install the project tools and dependencies:

```console
git clone https://github.com/NatLabRockies/r2x-core.git
cd r2x-core
mise run setup
mise run hooks-install
```

To build the docs, install Node.js 22.22 or newer and run:

```bash
npm ci --prefix docs
```

## Run checks

Use the project tasks defined in `mise.toml`:

```bash
mise run test
mise run hooks
mise run type
mise run lint
mise run format
```

`mise run test` runs pytest with coverage. The project requires at least 98% coverage.

## Write docs

Add guide pages under `docs/src/content/docs/`. API reference inputs live under `docs/source/references/`. Do not edit generated pages under `docs/src/content/docs/references/`.

Use standard Markdown with Starlight frontmatter. Write runnable Python examples in `python doctest` fences. Start input lines with `>>>` and prefix each expected output line with `# ` so it stays a comment when copied. Use an `assert` when output is not useful to show.

Update `docs/astro.config.mjs` when you add a section to the sidebar. Run the docs build and inspect the result:

```bash
mise run docs
cd docs
npm run preview
```

## Prepare a change

Create a branch from `main`, make one focused change, and run the relevant checks before opening a pull request. Update the docs when behavior changes.

Use a conventional commit message, such as:

```text
docs: clarify setup instructions
```

For a bug report or feature request, check the existing issues first. Include the steps to reproduce, the expected and actual behavior, and your Python version and operating system.
