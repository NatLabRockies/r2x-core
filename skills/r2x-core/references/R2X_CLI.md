# r2x CLI integration

Use this reference when developing an r2x-core plugin that will be installed,
discovered, validated, or executed by the Rust `r2x` CLI. The CLI repository is
[`NatLabRockies/r2x-cli`](https://github.com/NatLabRockies/r2x-cli). The binary is
called `r2x`, not `r2x-cli`.

## What the CLI does

`r2x` discovers installed Python plugins, builds a plugin manifest, manages the
Python environment, and executes plugins as direct commands or YAML pipeline
steps. It uses static analysis for discovery, so an entry point and decorated
function must be visible in the installed package metadata/source layout.

Keep the responsibilities separate:

- r2x-core defines the Python plugin API and runtime behavior.
- The plugin package defines `PluginConfig`, `Plugin`, components, rules, and
  entry points.
- `r2x` installs packages, discovers plugin metadata, resolves CLI arguments,
  and runs pipeline steps.

## Install and verify the published CLI

Install the latest released binary on macOS/Linux:

```bash
curl --proto '=https' --tlsv1.2 -LsSf \
  https://github.com/NatLabRockies/r2x-cli/releases/latest/download/r2x-installer.sh | sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://github.com/NatLabRockies/r2x-cli/releases/latest/download/r2x-installer.ps1 | iex"
```

Verify the command before installing plugins:

```bash
r2x --version
r2x --help
```

The published binary requires Python shared libraries at runtime. If the
binary reports a missing `libpython`, install a supported shared Python with
`uv`:

```bash
uv python install 3.12
```

Use the published installers or release binaries only. Do not build `r2x` from
source as part of the r2x-core plugin workflow. If the published binary is
unavailable for the platform, stop and report that limitation rather than
silently switching to a source build.

## Install a plugin package

Use the CLI to install the Python package into the r2x-managed environment:

```bash
r2x install r2x-reeds
r2x list
r2x sync
```

For a GitHub source or editable local package:

```bash
r2x install gh:NatLabRockies/r2x-reeds
r2x install -e /path/to/my-translator
r2x sync
```

Use `r2x install ... --branch`, `--tag`, or `--commit` when a non-default
revision is required. Run `r2x sync --upgrade` only when upgrading compatible
installed plugin packages is intended.

## Plugin package contract

A class-based r2x-core plugin package should expose its package/plugin metadata
through the `r2x_plugin` entry-point group:

```toml
[project.entry-points.r2x_plugin]
reeds = "r2x_reeds.plugins:ReEDSPlugin"
```

A function transform marked with `@expose_plugin` is discovered in the
`r2x.transforms` group:

```toml
[project.entry-points."r2x.transforms"]
scale_system = "r2x_reeds.transforms:scale_system"
```

Confirm the current consuming CLI behavior before changing metadata. The CLI
supports both groups, but the class package entry point and transform entry
point have different roles. A decorator alone does not install a package or
create an entry point.

## Validate discovery before running

Use the repository-local API probe first, then run the plugin probe from the
Python environment that contains the translator package:

```bash
uv run python skills/r2x-core/tools/check_api_symbols.py --repo src/r2x_core
uv run python skills/r2x-core/tools/inspect_plugins.py --group r2x_plugin
```

The plugin probe reads installed entry points from the active Python environment.
The r2x-core checkout itself does not define an `r2x_plugin` entry point, so
`No entry points found for group 'r2x_plugin'.` is expected when the probe is
run here without an installed translator. Run it from the translator checkout or
its r2x-managed environment to inspect actual plugins.

Then use the CLI to refresh its manifest and inspect installed plugins:

```bash
r2x sync
r2x list
r2x list r2x-reeds
r2x run plugin
```

For a specific plugin, ask the CLI to render the resolved argument contract:

```bash
r2x run plugin r2x-reeds.reeds-parser --show-help
```

If the CLI cannot see a plugin that Python can import, compare these layers:

1. The package is installed in the r2x-managed environment, not only the
   repository's development `.venv`.
2. The package metadata contains `[r2x_plugin]` or `[r2x.transforms]`.
3. The entry-point target has the correct import path.
4. `@expose_plugin` is applied directly to a function for transform discovery.
5. `r2x sync` has refreshed stale manifest metadata.
6. The plugin source is in the installed distribution files scanned by the CLI.

## Run a plugin directly

Use the short direct-plugin form:

```bash
r2x run r2x-reeds.reeds-parser \
  --path /path/to/reeds/run \
  --solve-year 2030 \
  --weather-year 2012
```

The legacy explicit form remains useful when disambiguating command modes:

```bash
r2x run plugin r2x-reeds.reeds-parser --show-help
```

Use idiomatic flags for automation. Existing `key=value` arguments are also
accepted by current CLI behavior, but do not mix both forms for the same field:

```bash
r2x run r2x-reeds.reeds-parser \
  path=/path/to/reeds/run \
  solve_year=2030 \
  weather_year=2012
```

A plugin that produces a `System` writes JSON to stdout when no output path is
provided. Diagnostics belong on stderr. Use `-o` for a durable JSON entrypoint
and its time-series sidecars:

```bash
r2x run r2x-reeds.reeds-parser \
  --path /path/to/reeds/run \
  --solve-year 2030 \
  --weather-year 2012 \
  -o artifacts/system.json

r2x run r2x-reeds.add-pcm-defaults \
  -i artifacts/system.json \
  --pcm-defaults-fpath config/pcm_defaults.json
```

Do not parse diagnostic text from stdout when a plugin is expected to produce a
System. Use stderr for logs and stdout for the pipeline artifact.

## Compose plugins as a Unix stream

Use `set -o pipefail` and keep the producer/consumer boundary clean:

```bash
set -o pipefail
r2x run r2x-reeds.reeds-parser \
  --path /path/to/reeds/run \
  --solve-year 2030 \
  --weather-year 2012 |
r2x run r2x-reeds.add-pcm-defaults \
  --pcm-defaults-fpath config/pcm_defaults.json
```

Use durable `-o` / `-i` boundaries when debugging, rerunning, or retaining
artifacts. A terminal exporter writes configured files and should not emit a
second JSON artifact into the stream.

## Run and validate a YAML pipeline

Create or inspect a pipeline file with `r2x init`, then list and preview before
execution:

```bash
r2x init
r2x run pipeline.yaml --list
r2x run pipeline.yaml --print reeds-to-plexos
r2x run pipeline.yaml reeds-to-plexos --dry-run
```

A pipeline must use the same plugin identifier under `pipelines` and `config`:

```yaml
variables:
  reeds_run: /data/reeds/run
  solve_year: 2030

pipelines:
  reeds-to-sienna:
    - r2x-reeds.reeds-parser
    - r2x-sienna.sienna-exporter

config:
  r2x-reeds.reeds-parser:
    path: ${reeds_run}
    solve_year: ${solve_year}
    weather_year: 2012
  r2x-sienna.sienna-exporter:
    output_path: output/system.json

output_folder: output
```

After the dry run succeeds, execute and retain the output:

```bash
r2x run pipeline.yaml reeds-to-sienna --output output/system.json
```

Use `--list` to validate the pipeline name and `--print` to inspect resolved
configuration without executing plugins. Use `--dry-run` to verify ordering and
configuration without touching translation inputs.

## CLI verbosity and logs

The CLI owns its Rust and process-level logging. Use:

```bash
r2x run pipeline.yaml reeds-to-sienna -q
r2x run pipeline.yaml reeds-to-sienna -v
r2x run pipeline.yaml reeds-to-sienna -vv
r2x log show
r2x log set log-python true
r2x log set no-stdout true
r2x log path
```

- `-q` suppresses informational status.
- `-qq` suppresses logs and plugin stdout capture.
- `-v` enables debug logging.
- `-vv` enables trace logging.
- `--log-python` shows Python/plugin logs on the console.
- `--no-stdout` keeps plugin stdout out of the log file.

This is separate from the Python Loguru policy in [LOGGING.md](./LOGGING.md).
The CLI controls what it captures and displays, while the application/plugin
controls its Loguru namespace and `r2x_core.logger.setup_logging(...)` sinks.

## Validation checklist

Before handing off an r2x-core plugin intended for `r2x`:

1. Run focused Python tests for the public plugin, config, reader, and rule
   behavior.
2. Run `uv run python skills/r2x-core/tools/check_api_symbols.py --repo src/r2x_core`.
3. Install the plugin into the r2x-managed environment with `r2x install -e .`.
4. Run `r2x sync` and confirm the package appears in `r2x list`.
5. Run `r2x run plugin <plugin-ref> --show-help`.
6. Preview every pipeline with `--list`, `--print`, and `--dry-run`.
7. Run one bounded real translation with `-o` and verify the output JSON and
   time-series sidecars.
8. Run a second step from the durable output with `-i` or a bounded pipe.
9. Check exit status and stderr separately from stdout. Use `pipefail` for
   pipelines.
10. If installation or discovery changed, repeat `r2x sync` after reinstalling
    rather than trusting stale manifest metadata.

## Failure triage

- **`r2x list` does not show the package:** reinstall it into the managed
  environment, run `r2x sync`, and inspect package metadata for the entry-point
  group.
- **Plugin help has missing or wrong flags:** inspect `PluginConfig` fields and
  annotations, then reinstall and sync so the manifest is regenerated.
- **Direct plugin works in Python but not through `r2x`:** verify the package
  distribution contains the module and that the entry-point target is valid.
- **Pipeline name not found:** run `r2x run pipeline.yaml --list`; check the
  YAML `pipelines` key and exact identifier spelling.
- **Dry run passes but execution fails:** validate real input paths, reader
  configuration, plugin dependencies, and the subprocess stderr. Dry run does
  not read or translate model data.
- **Piped output is corrupt:** keep diagnostics on stderr, avoid printing in
  plugin code, and use durable `-o` / `-i` boundaries to isolate the failing
  stage.
- **Python logs are missing:** enable the consuming application namespace,
  configure Loguru at the application boundary, then use `--log-python` or
  `r2x log set log-python true`.
