# Preserving Source Data Across Translations

Capture everything a translation would otherwise discard, so the original
source can be reconstructed later. This guide shows how to enable preservation,
what gets captured, and how to inspect it. For the design and semantics, see
{doc}`../explanations/lossless-translation`.

```{note}
This guide covers the **forward capture**, which is implemented. The **reverse
restoration** that consumes the captured data to rebuild the source is not yet
implemented; the captured history is built to support it as future work.
```

## Enable Preservation on the Translation

Set `preserve_source=True` on the context. Everything else about applying
rules stays the same (see {doc}`apply-rules`):

```python
from r2x_core import PluginContext, apply_rules_to_context

context = PluginContext(
    config=config,
    rules=forward_rules,          # X -> Y rules
    source_system=x_system,
    target_system=y_system,
    preserve_source=True,
)
result = apply_rules_to_context(context)
```

With preservation on, the executor does two things beyond the normal
translation:

- Tags every rule-produced target component with a
  {py:class}`~r2x_core.SourceProvenance` supplemental attribute recording its
  source UUID.
- Appends one hop record to `y_system.translation_history` holding a full
  snapshot of the source system, the source-to-target correspondence edges,
  and a mapped-field baseline.

## Inspect What Was Captured

The captured history lives on the target system:

```python
record = y_system.translation_history[-1]

record.source_system_uuid         # UUID of the source (X) system
record.from_model, record.to_model
len(record.snapshot.components)   # every source component, snapshotted
record.edges                      # source-to-target correspondence
```

Each edge tells you how a source mapped, with arity as data:

```python
for edge in record.edges:
    edge.source_uuids   # >1 for aggregation (many-to-one)
    edge.target_uuids   # >1 for fan-out (one-to-many); [] when nothing produced
    edge.status         # "translated", "dropped", or "unclaimed"
    edge.rule_name, edge.rule_version
```

- `translated`: the rule produced at least one target component.
- `dropped`: a rule matched the source but its filter excluded it.
- `unclaimed`: no rule ever named the source's type. These, plus `dropped`
  components, are the ones a reverse pass would resurrect.

Find everything a translation discarded:

```python
discarded = [e for e in record.edges if e.status in ("dropped", "unclaimed")]
```

## Identify Translated Components

Use {py:meth}`~r2x_core.System.iter_translated_components` to walk only the
rule-produced components on the target (skipping any pre-existing target
content):

```python
for component in y_system.iter_translated_components():
    ...
```

## The History Travels with the System

The history serializes inside the system JSON, so nothing extra needs to be
saved or shipped:

```python
y_system.to_json("y_system.json")

# Later, possibly in another process or tool
from r2x_core import System
y_system = System.from_json("y_system.json")
y_system.translation_history            # restored intact
```

Before relying on the history for recovery, check that every record loaded
cleanly. A record from a newer schema than the installed library is retained
inertly rather than dropped, so recovery code must refuse to proceed if any
record failed to parse:

```python
if y_system.has_unparsed_translation_history():
    raise RuntimeError(
        "translation history contains records this version cannot read; "
        "upgrade r2x-core before attempting recovery"
    )
```

## Declare Aggregation with `consumes`

The executor sees one source producing many targets automatically. It cannot
see aggregation, where a rule folds several source components into one target
(via a `system="target"` rule or a getter that reaches into the system).
Without help, the folded-in sources are recorded as `unclaimed`.

Declare what an aggregation rule consumes so its correspondence is recorded
correctly:

```python
from rust_ok import Ok

def fold_in_siblings(iterated, *, context):
    """Return the extra source components this rule aggregates."""
    return [c for c in context.source_system.get_components(Sibling) if ...]

rule = Rule(
    source_type="Primary",
    target_type="Aggregate",
    version=1,
    field_map={...},
    consumes=fold_in_siblings,     # or a registered getter name (str)
)
```

The producing edge then records `source_uuids = [iterated, *consumed]`.

## When Preservation Is Off

Without `preserve_source=True`, behavior is exactly as before: unmapped fields
and unmatched components are dropped, no history is captured, and serialization
output is byte-for-byte identical to a plain system. Existing translations are
unaffected by this feature.

## Limitations to Keep in Mind

- Reverse restoration (rebuilding X from Y and the history) is not yet
  implemented.
- Time series for dropped/unclaimed components are not yet carried into the
  target store, so a resurrected component would not find its series. Time
  series for translated components transfer normally.

See {doc}`../explanations/lossless-translation` for the full design.

## See Also

- {doc}`../explanations/lossless-translation` for design and semantics
- {doc}`apply-rules` for applying rules to a context
- {doc}`define-rule-mappings` for authoring rules
