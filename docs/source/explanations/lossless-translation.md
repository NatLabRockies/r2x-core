# Lossless Round-Trip Translation

Translating a system from model X to model Y is inherently lossy. This
document explains how R2X Core captures everything a forward translation
discards, through an opt-in *translation history*, and the lens semantics that
govern what a future reverse translation can restore.

For the task-oriented guide, see {doc}`../how-tos/round-trip-translations`.

```{note}
The **forward capture** described here (the "get" half) is implemented: with
`preserve_source=True`, a translation records a self-contained
`translation_history` on the target system. The **reverse restoration** (the
"put" half) is not yet implemented. The history carries everything a reverse
pass needs; consuming it to reconstruct the source is future work. Where this
document describes restoration, it describes the design the captured data is
built to support, not current behavior.
```

## What Gets Lost in Translation

A translation applies {py:class}`~r2x_core.Rule` objects that copy or compute
target fields from source components (see {doc}`./rules-system`). Anything the
rules do not name is discarded. Loss falls into three distinct categories:

1. **Unmapped fields.** The target model has no home for a source field (a
   ReEDS-specific attribute with no PLEXOS equivalent). The component
   translates, the field vanishes.
2. **Dropped components.** No rule matches a component's type, or a rule
   filter excludes it. The entire component vanishes, along with its
   supplemental attributes and time series.
3. **Lossy transformations.** A getter collapses two fields into one, rounds a
   unit conversion, or coarsens an enum. The value arrives in the target, but
   the original cannot be computed back from it.

Without extra bookkeeping, a later Y→X translation cannot reconstruct the
original system: the information simply is not in Y.

## Lens Semantics

The design follows the bidirectional-transformation ("lens") literature from
programming language and database research. A lens is a pair of functions
between a rich "source" and a reduced "view", designed together so that the
pair is lossless even though the forward direction alone is lossy:

- `get : S → V`, the forward transform. Allowed to discard information.
- `put : (V, S) → S`, the backward transform. Takes the edited view **and the
  original source**, and produces an updated source.

The signature of `put` is the whole trick. A naive reverse function `V → S` is
impossible to write correctly because the discarded information is not in V.
The lens move is to stop pretending and hand `put` access to what `get` threw
away.

### The Laws

What makes a lens a lens, rather than two arbitrary functions, is a pair of
round-trip laws:

- **GetPut**: `put(get(s), s) = s`. Translate forward, edit nothing, translate
  back, and you get the original, exactly. This is the lossless-conversion
  requirement stated as an equation.
- **PutGet**: `get(put(v, s)) = v`. Whatever edits you made in the view
  survive the trip back; the restore step is not allowed to clobber them by
  "helpfully" restoring stale originals.

These two laws are in tension (GetPut says "restore the original values",
PutGet says "respect the view's edits"), and resolving that tension fixes the
merge policy with no freedom left over: on the way back, **fields the target
carried and the user edited take their current target values**, **fields the
target carried but the user left untouched restore their original source
value** (undoing a lossy transform), and **fields the target never carried
restore from the captured snapshot**.

### The Complement Formulation

An equivalent phrasing maps directly onto the captured history. Instead of
`put` taking the whole original source, factor `get` into two outputs:

```text
get(s)      = (v, c)    # the view, plus a "complement" c holding everything discarded
put(v', c)  = s'        # reconstruct from the edited view and the complement
```

The complement `c` is precisely "the stuff X cared about that Y doesn't". In
R2X Core terms: the rules engine is `get`, the translation history is the
complement `c`, and a reverse translation is `put`. A worked example:

```text
BusComponent (X)                 NodeComponent (Y)          snapshot (complement)
  name: "bus1"       --get-->      name: "bus1"               zone: "west"
  voltage_kv: 230.0                kv_rating: 230.0           owner: "PSCo"
  zone: "west"
  owner: "PSCo"
                     user edits Y:  kv_rating = 345.0

put(Y', c):  name        <- Y   (mapped)
             voltage_kv  <- 345.0  (mapped; the edit survives, PutGet)
             zone, owner <- snapshot (restored, GetPut)
```

This idea comes from database view-update theory (Bancilhon and Spyratos,
1981, the "constant complement" approach); Foster, Pierce, and colleagues
turned it into a compositional programming model ("Combinators for
Bidirectional Tree Transformations", TOPLAS 2007, and the Boomerang language).

### Two Refinements That Shape the Design

**Symmetric lenses.** Classic lenses are asymmetric: the source is strictly
richer and the view is a projection. Model translation is not like that; a
PLEXOS model has fields Sienna lacks *and vice versa*, so neither side is "the
source". The generalization (Hofmann, Pierce, and Wagner, 2011) keeps a
complement on **both** sides. Practically, the mechanism is
direction-agnostic: one hop record per translation run, produced the same way
whether you are going X→Y or Y→X.

**Chains, not just round trips.** Real usage is a chain,
`X → Y → X → Z → Y`, with no privileged "original" model. Because each hop is
one-shot (a model is not independently edited and merged back later), the
history is a *line*: an append-only stack of hop records where no hop ever
mutates or forgets a prior record. Returning to a model many hops later can
still consult the earlier record that captured it. This is why the history is
a `list` of records, not a single overwrite-per-hop blob.

**Delta lenses and deletions.** State-based lenses make absence ambiguous: is
a component missing from Y because it was deleted, or because it was never
mapped? Each edge in a hop record carries a `status` that resolves this:
`translated` (a target was produced), `dropped` (a rule matched but excluded
it), or `unclaimed` (no rule ever named its type). A future reverse pass can
resurrect `unclaimed`/`dropped` components while letting user deletions of
`translated` components propagate.

## The Translation History

When a translation runs with `preserve_source=True` on the
{py:class}`~r2x_core.PluginContext`, the executor appends one
`HopRecord` to the target system's `translation_history`. A hop record is the
lens complement for that hop. It holds:

- **A full snapshot** of the source system, in the exact infrasys
  serialization form the system JSON uses (each component and supplemental
  attribute carries its `__metadata__` type discriminator). This means a
  reverse pass reconstructs components through the same path
  {py:meth}`~r2x_core.System.from_json` uses, so even models with computed-field
  discriminators under `extra="forbid"` round-trip correctly.
- **Correspondence edges.** Each `HopEdge` records `source_uuids` and
  `target_uuids`, with arity as data: one-to-many (fan-out), many-to-one
  (aggregation), and many-to-many are all just edges with plural sides. Each
  edge carries the producing rule's name and version, and a `status`.
- **A mapped-field baseline.** Per produced target, the as-produced values of
  the fields the rule mapped, captured *after* validation. A reverse pass
  compares a target's current value against this baseline to tell a user edit
  (current ≠ baseline) from a lossy forward transform (current == baseline).

Snapshots are full images rather than "just the leftover fields" deliberately.
Getters are opaque callables that may read any source field, so the set of
consumed fields cannot be computed reliably; and a full snapshot is
self-contained, which is what makes it survive a cross-tool JSON handoff.

### The Identity Tag

Alongside the history, every translated target component gets a lightweight
{py:class}`~r2x_core.SourceProvenance` supplemental attribute recording the
UUID of the source component it came from. This is a cheap 1:1 identity index
for "which source did this target come from"; it is *not* the complement. It
rides in normal infrasys serialization with no sidecar keys.
{py:meth}`~r2x_core.System.iter_translated_components` uses it to distinguish
rule-produced components from pre-existing target content.

### Where the History Lives

The history is system-level state, serialized inside the system JSON under a
`translation_history` key via
{py:meth}`~r2x_core.System.serialize_system_attributes`, so it travels with the
Y system through `to_json`/`from_json` and survives handoffs between tools.

It is *not* stored as components inside the system on purpose: dropped
components live only in the snapshot, never in the active model's component
graph. This keeps the active model pristine, so exporters, component
iteration, and the next translation's own bookkeeping see only the model they
expect, never a smuggled-in foreign component.

Systems without a history deserialize exactly as before, and serialization
output is byte-for-byte unchanged whenever the feature is off (no extra keys
are emitted).

### Forward Compatibility

Each hop record carries a `schema_version`. A record from a newer schema than
the installed library (an unknown field, or a higher `schema_version`) fails
validation on load and is retained *inertly*: the raw payload is kept so it
survives a round trip at its original stack position, and the system still
loads (a downstream tool must be able to open the file). Code that relies on
the history for recovery must check
{py:meth}`~r2x_core.System.has_unparsed_translation_history` and refuse to
proceed when it returns `True`, rather than silently operating on a truncated
stack. This is deliberate: silently dropping a record we cannot parse would
turn a losslessness guarantee into silent loss.

## Aggregation and the `consumes` Hook

The executor observes one source component producing N target components
(fan-out). It cannot see aggregation: a `system="target"` rule, or a getter
that reaches into the system to fold in sibling components, consumes sources
the executor's per-component loop never iterated. Those sources would be
misclassified as `unclaimed`.

To make aggregation visible, an aggregation rule declares what it folds in via
{py:attr}`~r2x_core.Rule.consumes`: given the iterated component, it returns
the additional source components consumed. The edge then records
`source_uuids = [iterated, *consumed]`. This keeps arity as data on the edge
while putting the knowledge where it lives, in the rule.

## Known Limitations

- **Reverse restoration is not implemented yet.** The history captures
  everything a `put` pass needs, but the pass itself is future work.
- **Time series for dropped components** are not yet carried into the target
  store, so a resurrected dropped component would not find its series. (Time
  series for *translated* components transfer normally by UUID.) This is a
  known gap in the current capture.
- **Fan-out edits merge back from one sibling.** When one source produced
  several targets, a future reverse pass drives the restore from the first
  surviving sibling; edits on the other siblings do not merge.
- **Supplemental attributes cannot be rule sources**, so edits made to a
  target's supplemental attributes would not flow back through reverse rules.

## See Also

- {doc}`../how-tos/round-trip-translations` for the task-oriented guide
- {doc}`./rules-system` for the rule system this builds on
- {py:class}`~r2x_core.PluginContext` API reference
- {py:class}`~r2x_core.SourceProvenance` API reference
