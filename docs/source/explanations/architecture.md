# Architecture

r2x-core is three layers with one model each. The config layer describes inputs
and rules as Pydantic models. The execution layer reads files, processes frames,
and applies rules. The seams are the two abstract classes an application
implements to plug in its own file formats or frame engine.

## Layers

```{mermaid}
flowchart TB
    subgraph config["Config layer (pure Pydantic, no infrasys, no Polars)"]
        direction LR
        types["types<br/>FileFormat markers<br/>EXTENSION_MAPPING<br/>PLACEHOLDER_PATTERN"]
        datafile["datafile<br/>DataFile · FileInfo · ReaderConfig<br/>TabularProcessing · JSONProcessing"]
        models["models<br/>MappingStep · Expression"]
        rules["rules<br/>Rule · RuleFilter<br/>SupplementalAttributeRule"]
        plugin_config["plugin_config<br/>PluginConfig<br/>active_versions · upgrade_handler"]
    end

    subgraph seams["Seams (abstract, two adapters or more each)"]
        direction LR
        file_reader["file_reader<br/>FileReader[OutputT]"]
        tabular_backend["tabular_backend<br/>TabularBackend[FrameT]<br/>apply_mapping_steps"]
        json_processor["json_adapter<br/>JSONProcessor protocol"]
    end

    subgraph adapters["Adapters"]
        direction LR
        polars["polars_adapter<br/>PolarsTabularFileReader<br/>PolarsTabularBackend<br/>(optional extra)"]
        h5["h5_adapter<br/>H5PyFileReader → H5Result"]
        json["json_adapter<br/>JSONFileReader<br/>JSONProcessingBackend"]
        xml["file_readers<br/>XMLFileReader"]
    end

    subgraph exec["Execution layer"]
        direction LR
        reader["reader<br/>DataReader"]
        processors["processors<br/>apply_processing<br/>substitute_placeholders"]
        store["store<br/>DataStore"]
        rules_executor["rules_executor<br/>apply_rules_to_context<br/>apply_single_rule"]
        time_series["time_series"]
        provenance["provenance<br/>ProvenanceBuilder"]
    end

    subgraph plugin["Plugin layer"]
        direction LR
        plugin_context["plugin_context<br/>PluginContext"]
        plugin_base["plugin_base<br/>Plugin · HOOK_SPECS"]
        system["system<br/>System(infrasys.System)"]
        units["units<br/>HasUnits · HasPerUnit · Unit"]
    end

    datafile --> types
    models --> types
    rules --> types
    file_reader --> datafile
    tabular_backend --> datafile
    tabular_backend --> models
    json_processor --> datafile
    polars -.->|implements| file_reader
    polars -.->|implements| tabular_backend
    polars --> h5
    h5 -.->|implements| file_reader
    json -.->|implements| file_reader
    json -.->|implements| json_processor
    xml -.->|implements| file_reader
    reader --> file_reader
    reader --> processors
    processors --> tabular_backend
    processors --> json_processor
    store --> reader
    store --> plugin_config
    rules_executor --> rules
    rules_executor --> plugin_context
    rules_executor --> time_series
    rules_executor --> provenance
    plugin_base --> plugin_context
    system --> units
    system --> provenance
    plugin_context -.->|holds| store
    plugin_context -.->|holds| system
    plugin_context -.->|holds| rules
```

Solid arrows are runtime imports. Dotted arrows are "implements" or
"holds a reference to". The config layer imports nothing below it, which is
what keeps `from r2x_core import DataFile` at about 0.2 seconds: infrasys,
pandas, and Polars load only when an execution-layer or plugin-layer module is
touched.

## Reading one file

```{mermaid}
sequenceDiagram
    participant App
    participant DataStore
    participant DataReader
    participant FileReader
    participant apply_processing
    participant TabularBackend

    App->>DataStore: read_data("generators", placeholders=...)
    DataStore->>DataReader: read_data_file(DataFile, folder_path, placeholders)
    DataReader->>DataReader: substitute_path_placeholders · get_fpath
    DataReader->>DataReader: select_file_reader(file_type)
    Note over DataReader: first configured FileReader that supports the format,<br/>else the lazily created default Polars reader
    DataReader->>FileReader: read_file(file_type, file_path, reader_config)
    FileReader-->>DataReader: raw data (LazyFrame · JSONValue · Element)
    DataReader->>apply_processing: (raw, data_file, proc_spec, placeholders, tabular_backend, json_processor)
    apply_processing->>apply_processing: substitute placeholders in proc_spec
    alt proc_spec is TabularProcessing
        apply_processing->>TabularBackend: process(frame, data_file, proc_spec)
    else proc_spec is JSONProcessing
        apply_processing->>apply_processing: json_processor.process(...)
    end
    apply_processing-->>DataReader: Result[data, ValueError]
    DataReader-->>DataStore: data (or raise ReaderError)
    DataStore-->>App: data
```

`DataReader` is stateless across reads. Its default Polars reader and backend
are `cached_property` values created on first tabular use, so a JSON-only
application never imports Polars. `apply_processing` resolves the same default
through `default_tabular_backend()` when called directly without a backend,
which is the pattern translator parsers use for frames they read themselves.

## Translating a system

```{mermaid}
sequenceDiagram
    participant Plugin
    participant apply_rules_to_context
    participant apply_single_rule
    participant utils.rules
    participant target as target System
    participant ProvenanceBuilder
    participant time_series

    Plugin->>apply_rules_to_context: context (rules, source_system, target_system)
    apply_rules_to_context->>utils.rules: sort_rules_by_dependencies(rules)
    loop each Rule in dependency order
        apply_rules_to_context->>apply_single_rule: rule, context, builder
        apply_single_rule->>utils.rules: resolve_component_type(source, target, supplemental)
        loop each source component matching rule.filter
            apply_single_rule->>utils.rules: create_rule_outputs(component, rule, ...)
            Note over utils.rules: build_component_kwargs: field_map → getters → defaults
            apply_single_rule->>target: attach_rule_outputs(primary + supplemental)
            apply_single_rule->>ProvenanceBuilder: record_translation (if preserve_source)
        end
        apply_single_rule-->>apply_rules_to_context: Result[RuleApplicationStats]
    end
    apply_rules_to_context->>ProvenanceBuilder: preserve_untranslated(target)
    apply_rules_to_context->>time_series: transfer_time_series_metadata(context)
    apply_rules_to_context-->>Plugin: TranslationResult
```

Rules are declared as `Rule` dataclasses holding resolved callables. JSON rule
files go through `Rule.from_records`, the one place where getter strings become
callables and supplemental-attribute dicts become `SupplementalAttributeRule`
instances. Downstream code never sees a string where a callable belongs.

## Plugin lifecycle

```{mermaid}
flowchart LR
    ctx["PluginContext<br/>config · store · system<br/>source_system · target_system<br/>rules · metadata"]
    run["Plugin.run()"]
    ctx --> run
    run --> v[on_validate] --> p[on_prepare] --> u[on_upgrade] --> b[on_build] --> t[on_transform] --> tr[on_translate] --> e[on_export] --> c[on_cleanup]
    u -.->|Ok(system)| ctx
    b -.->|Ok(system)| ctx
    t -.->|Ok(system)| ctx
    tr -.->|Ok(target_system)| ctx
```

The eight hooks and which context attribute each one writes are defined once in
`plugin_base.HOOK_SPECS`. `Plugin.run` iterates that table; hooks a subclass does
not define are skipped. A hook returning `Err` raises `PluginError` and stops the
run.

## Unit binding

```{mermaid}
flowchart LR
    decl["class Gen(HasPerUnit, Component):<br/>base_power: Annotated[float, Unit('MVA')]<br/>rating: Annotated[float, Unit('pu', base='base_power')]"]
    hook["HasUnits.__pydantic_init_subclass__"]
    specs["Gen.unit_specs<br/>{base_power: Unit(MVA), rating: Unit(pu, base_unit=MVA)}"]
    validate["UnitSpec.validate_value<br/>{'value': 80, 'unit': 'MVA'} → 0.8"]
    decl -->|class creation| hook --> specs
    specs -->|instance validation| validate
```

Base units are resolved once when the class is created, from the class's own
`model_fields`. A `base=` that names a field without a `Unit` fails at import
time with a `TypeError`. There is no validation context and no subclass walk, so
two classes with the same name in different modules cannot collide.

## Module inventory

| Module | Role | Root exports |
| --- | --- | --- |
| `types` | Format markers, extension map, shared regex and type aliases | `FileFormat`, `H5Format` |
| `datafile` | Input file configuration and processing specs | `DataFile`, `FileInfo`, `ReaderConfig`, `TabularProcessing`, `JSONProcessing`, `SplitColumnSpec` |
| `models` | Ordered mapping steps and expressions (future `proc_spec`) | none |
| `rules` | Translation rule declarations | `Rule`, `RuleFilter`, `SupplementalAttributeRule` |
| `plugin_config` | Typed plugin configuration and asset paths | `PluginConfig` |
| `file_reader` | File-format seam and default tabular reader resolver | `FileReader` |
| `tabular_backend` | Frame-engine seam, step runner, default backend resolver | `TabularBackend` |
| `json_adapter` | JSON reader, `JSONProcessor` protocol, default processor | none at root |
| `h5_adapter` | Configuration-driven HDF5 reader producing neutral columns | `H5Reader`, `H5PyFileReader` |
| `polars_adapter` | Polars reader, backend, expressions, processing (extra) | none at root |
| `file_readers` | XML reader | none |
| `reader` | Read-then-process pipeline | `DataReader` |
| `processors` | Placeholder substitution and spec-type dispatch | none at root |
| `store` | Named `DataFile` collection, mapping JSON loading, upgrade retry | `DataStore` |
| `rules_executor` | Rule application, output attachment, rollback | `apply_rules_to_context`, `apply_single_rule`, `attach_rule_outputs`, `resolve_supplemental_class` |
| `time_series` | Time series metadata transfer between systems | `transfer_time_series_metadata`, `replace_single_time_series` |
| `provenance` | Source provenance tags and preservation | none at root |
| `plugin_context` | Shared mutable execution state | `PluginContext` |
| `plugin_base` | Lifecycle hooks and `HOOK_SPECS` | `Plugin` |
| `plugin_expose` | Marker decorator for function plugins | `expose_plugin` |
| `system` | `infrasys.System` subclass with units and provenance | `System` |
| `units` | Unit-aware fields, class-creation binding, display modes | `HasUnits`, `HasPerUnit`, `Unit`, `UnitSystem`, `get_unit_system`, `set_unit_system` |
| `versioning` | Version strategies, `VersionReader`, `UpgradeHandler` | `VersionStrategy`, `SemanticVersioningStrategy`, `GitVersioningStrategy`, `VersionReader` |
| `utils` | Lazy barrel over `files`, `rules`, `upgrade`, `validation`, `version`, `export`, `parser`, `iteration`, `overrides` | `UpgradeStep`, `UpgradeType`, `run_upgrade_step`, `create_component`, `components_to_records`, `export_components_to_csv` |
| `getters` | Named getter registry for rule JSON | `getter`, `resolve_getter` |
| `result` | Translation result dataclasses | `RuleResult`, `TranslationResult` |
| `exceptions` | Error hierarchy | `PluginError`, `ValidationError`, `UpgradeError`, `ComponentCreationError`, `CLIError` |
| `logger` | Loguru setup for applications | none at root |

## Design rules this layout enforces

- One schema per concept. `DataFile` describes an input, `Rule` describes a
  translation. The step-list `MappingStep` form replaces `TabularProcessing`
  only when it reaches parity; see
  {doc}`tabular-processing-roadmap`.
- A seam needs two adapters. `FileReader` has four, `TabularBackend` has one
  with the contract exercised by tests. `JSONProcessor` is a single injection
  point, not a registry.
- The config layer never imports the execution layer. Guarded by a subprocess
  test in `tests/test_public_imports.py`.
- No private helpers. Module-level functions carry descriptive public names;
  `__all__` and the root `_LAZY_IMPORTS` decide what is exported.
- No undeclared fields. Configuration is read through declared Pydantic fields.
  `getattr` is reserved for names that come from user rule JSON, importlib
  module probing, and generic introspection.
