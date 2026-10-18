---
title: r2x-core
description: Python building blocks for developers who read, transform, and export power-system model data.
---

<span id="r2x-core-documentation"></span>
<span id="about-r2x-core"></span>
<span id="key-features"></span>

`r2x-core` is a Python library for developers building power-system model translators.
It supplies the shared pieces for reading input files, constructing typed components,
applying transformations, and exporting an inspectable system. Configuration,
plugin lifecycle hooks, rule mappings, and unit handling help model packages use
the same workflow instead of rebuilding that infrastructure.

<span id="plugin-discovery"></span>

Model plugins provide the knowledge of a particular model's files and conventions:
its parser reads that format, and its exporter writes the target format.
[r2x-cli](https://github.com/NatLabRockies/r2x-cli) is the separate Rust command-line tool
that installs those plugins and runs them in pipelines. Use core directly when
writing or testing a plugin; use the CLI when running installed translators.
Start with the [CSV capacity example](/r2x-core/tutorials/getting-started/) to see
these boundaries without external model datasets.

<span id="quick-start"></span>

## Get set up

[Install the published package](/r2x-core/install/), choose an [environment](/r2x-core/getting-started/environment/), and [verify first use](/r2x-core/getting-started/verify/).

## Start with a working example

[Read a CSV and build a system](/r2x-core/tutorials/getting-started/) without external model datasets.
Use the [generated API reference](/r2x-core/references/api/) to inspect signatures, types, defaults, return values, and pinned implementation source.

<span id="indices-and-tables"></span>

## Find your task

- [Tutorials](/r2x-core/tutorials/): learn through small examples.
- [How-to guides](/r2x-core/how-tos/): configure files, implement plugins, and apply rules.
- [Reference/API](/r2x-core/references/): public API and configuration contracts.
- [Explanation](/r2x-core/explanations/): architecture and data flow.
- [Troubleshooting](/r2x-core/troubleshooting/): imports, input lookup, and lifecycle errors.
- [Changelog](/r2x-core/release-notes/): release history.
- [Contributors](/r2x-core/contributing/): setup and checks.
