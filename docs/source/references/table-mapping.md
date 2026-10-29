# Table mapping

`table_mapping.json` defines named tables through ordered operations and final
column projections. It describes table assembly, not file reading or component
construction.

Availability: the twenty-six operation tags, final `columns` projection, and
optional record-level `materialize` flag are available through
`r2x_core.assemble_tables`, `r2x_core.assemble_table_records`, and the opt-in
`build_system(..., table_mapping_path=...)` path. Schema-bearing optional inputs
preserve absence separately from present-empty data. Table-mapping records are
not the `TabularProcessing.steps` schema. See [ReEDS composition patterns](#reeds-composition-patterns)
for examples of combining generic operations without application-specific
handlers or expression trees.

For a guided example, see [Assemble hourly reserve requirements](/r2x-core/tutorials/assemble-reserve-requirements/).
For task-specific variations, see [Adapt table mappings](/r2x-core/how-tos/adapt-table-mappings/).

## Conformance contract

This reference defines the target format. MUST and MUST NOT identify requirements,
not suggestions. Examples illustrate those requirements and do not add operations
or defaults. These rules apply equally to handwritten and generated mappings.

| Rule | Requirement |
| --- | --- |
| TM-01 | Each mapping file MUST contain one JSON array of table records. No wrapper, comments, Markdown fences, SQL, or executable code belongs inside that file. |
| TM-02 | Each JSON object MUST have unique member names. Duplicate members are errors, even when their values agree. A later member MUST NOT replace an earlier one. |
| TM-03 | Every table MUST have one exact `name`. Names requested by a consumer are an interface contract, not suggestions to replace with descriptive alternatives. Intermediate names may be chosen by the author. |
| TM-04 | A table MUST start from exactly one `source` or one first-position constructor. `rows`, `concat`, `first_present`, and `first_nonempty` MUST NOT appear later in its operations. |
| TM-05 | Sources MUST be declared inputs or earlier table records. References MUST NOT introduce files, inline tables, forward dependencies, or undeclared optional inputs. |
| TM-06 | Operations MUST execute in array order, followed by the table-level `columns` projection and optional materialization. Object-member order MUST NOT change the result. |
| TM-07 | Records MUST contain only their documented fields and value forms. An optional field is omitted when unused, not supplied as `null`. `materialize`, when supplied, MUST be a JSON boolean. |
| TM-08 | Column references MUST identify existing columns at that stage. New output names MUST NOT be used before the operation or projection that creates them. |
| TM-09 | Joins, grouping, null filling, sorting, and row selection MUST be explicit. No inferred keys, implicit deduplication, or business defaults are permitted. |
| TM-10 | A mapping MUST satisfy the consumer's exact output name, fields, types, rows, and required ordering. Syntactically valid JSON alone is not conformance. |

For example, when a consumer requests `annual_cost_rows`, use that exact name
once on its table record. To change a record's name, replace its existing `name`
value. Do not append another `name` member, rely on last-value-wins parsing, or
wrap the record in an object keyed by the requested name. The names used in this
reference are examples, not reserved names.

## Document structure

The top-level value is a JSON list of table records in dependency order.

| Field | Required | Value |
| --- | --- | --- |
| `name` | Yes | Unique, nonempty table name. |
| `source` | For a source-based table | Name of an earlier prepared table. |
| `operations` | Yes | Ordered list of operation records. An empty list preserves the source. |
| `columns` | No | Final output-column map. Omission preserves the operation result. |
| `materialize` | No | Strict boolean, default `false`. When `true`, snapshot the final projected output in memory before dependent records run. |

A record starts from either `source` or a constructor operation. A constructor
record omits `source` and starts its operation list with `rows`, `concat`,
`first_present`, or `first_nonempty`.
A source-based record MUST NOT contain a constructor. Subsequent operations
consume the preceding result. A source-only projection still includes
`"operations": []`.

Evaluation order is source resolution, operations in array order, final
projection, then optional materialization. JSON object-member order does not
control evaluation. Table and column names are exact and case-sensitive.
References are names, not paths, patterns, SQL, or inline table definitions.

Dependencies must already be declared, including any upstream tables supplied
to this part of the mapping. Forward references, duplicate names, duplicate JSON
keys, unknown operations, and unknown fields are configuration errors.

```json
[
  {
    "name": "selected_generators",
    "source": "generator_inputs",
    "operations": [
      {"operation": "filter", "column": "year", "comparison": "equals", "value": "{selected_year}"}
    ],
    "columns": {
      "capacity_mw": "capacity",
      "name": "name",
      "solve_year": "year"
    }
  }
]
```

This record requires a prepared `generator_inputs` table with `year`, `capacity`,
and `name`, plus a configured integer `selected_year`.

### Consumer table identity

The consumer selects a table by name, not by its position in the array. A last
record with a different name is not an alias for the requested output. This also
applies when a mapping contains only one record.

Establish the requested output name before writing the operations. For example,
if the consumer requests `component_rows`, the record above MUST use
`"name": "component_rows"` instead of `"name": "selected_generators"`.
The operations and projection can stay unchanged. Do not add a second `name`
member or invent another mapping field to declare the output.

When delivering several independent mappings, check the final name in every
mapping, including the first. A correctly named output in one mapping does not
satisfy another mapping's consumer.

## Final column map

A final `columns` object defines exactly the output fields.

| Value form | Meaning |
| --- | --- |
| `"output_name": "input_name"` | Copy the incoming column, optionally under a different name. |
| `"output_name": {"value": "text"}` | Add literal text to every incoming row. |
| `"output_name": {"value": scalar, "dtype": logical_type}` | Add a scalar literal with an explicit type. |
| `"output_name": {"optional_column": "input_name", "dtype": logical_type}` | Strictly cast that source column when present, otherwise add a typed null. |

The map reads the result of all preceding operations. It MUST NOT reference a
sibling output, contain calculations, or perform aggregation. Bare strings name
input columns, not literal text. The `value` wrapper without `dtype` accepts
literal text only. The typed form requires `dtype` from `bool`, `int64`,
`float64`, `string`, or `datetime`, including when `value` is null. Integer and
boolean literal values must match their declared types; finite integers or floats
may supply `float64`; datetime literals are timezone-naive ISO-8601 strings.
Typed projection values are literals, not configuration bindings. An explicit
typed null creates an all-null column with that schema, while an omitted output
field is not present. If a typed literal uses the same output name as an input
column, the final projection replaces that input field. Use an ordered operation
to calculate a field before projecting it.

An optional-column value reads and casts its named source column when present.
When the source column is absent, it creates a null column with the declared
type. Present values follow the `cast` operation's strict rules, including
rejecting floating-point to integer conversion and parsing ISO datetime strings.
Use a bare string when the source column must exist. Optional fields in the
source schema are not inferred from data values.

Projection preserves row count, including empty and absent tables. It emits
output columns in sorted-name order and does not sort rows. Missing bare column
references are errors. Literal and optional-column dtypes are carried to the
backend explicitly and are not inferred from row data.

```json
{"name":"resource_rows","source":"native_rows","operations":[],"columns":{"capacity":{"value":null,"dtype":"float64"}}}
{"name":"resource_rows","source":"native_rows","operations":[],"columns":{"capacity_factor":{"optional_column":"capacity_factor","dtype":"float64"}}}
```

## Materialize a shared output

Set `"materialize": true` on a named table to evaluate its ordered operations
and final projection immediately, then retain that result as an in-memory source
for dependent records. The backend snapshot preserves columns, dtypes, row order,
duplicates, nulls, availability, and absent-input provenance. It is an explicit
eager boundary, not a persistent cache or automatic optimization. Downstream
records still evaluate their own operations lazily, and repeated downstream
collections can still recompute those downstream plans.

Materialization changes error timing: failures that would otherwise appear when
a lazy table is collected can surface while the marked record is assembled,
before its dependents run. The complete projected output is held in memory, so
opt in only when the result is bounded and reused enough to justify that cost.
The flag is strict: use JSON `true` or `false`, not a string or number.

```json
{
  "name": "small_shared_rows",
  "source": "prepared_rows",
  "operations": [{"operation": "filter", "column": "supported", "comparison": "equals", "value": true}],
  "columns": {"name": "name", "technology": "technology"},
  "materialize": true
}
```

A later table may use `small_shared_rows` as its source. `first_present` and
other constructors still select their source according to their documented
semantics, but a marked record then produces a new snapshot source rather than
retaining the selected `TabularSource` object's identity. When a caller supplies
that record's name in `initial_tables`, the preassembled source is returned as-is:
its operations, projection, and `materialize` flag are not run again.

## Configuration bindings

A whole-value placeholder such as `{selected_year}` or `{solve_year_rows}`
receives a value from application configuration and retains that value's type.

| Example binding | Type |
| --- | --- |
| `selected_year = 2032` | Integer |
| `solve_year_rows = [{"solve_year": 2032}]` | List of records |

Bindings are accepted in `filter.value`, `choose.value`, the `value` inside a
`choose.then` or `choose.otherwise` literal, `fill_null.value`, and `rows.values`.
The receiving argument determines the required type. A list of records is not a
string containing JSON. A scalar comparison MUST NOT receive a list. A
`fill_null.value` binding may be a flat scalar list only when filling a list
column.

A placeholder MUST occupy the whole value. An unresolved binding is an error.
Partial interpolation such as `"year_{selected_year}"` is not supported. Names,
column references, and final literal-text projections are not binding positions.
This format does not evaluate expressions from strings or infer table names,
join keys, or units from a binding.

## Operations

Each operation has an `operation` tag and the arguments listed below. Arguments
not listed as optional are required. These twenty-six tags are the complete operation vocabulary: `join`,
`match_patterns`, `match_source_patterns`, `filter`, `choose`, `group_by`, `unpivot`, `concat`,
`first_present`, `first_nonempty`, `multiply`, `add`, `divide`, `absolute`, `casefold`, `datetime_part`, `concat_strings`,
`split`, `rows`, `fill_null`, `head`, `sort`, `unique`, `cast`, `object`, and `list`. `sum`, `max`,
`mean`, `count`, `first`, `last`, and `list` are aggregate tags inside
`group_by`, not standalone table operations.

Names MUST be nonempty strings. Lists of keys or selected columns MUST have
unique entries. Join keys, aggregate lists, concat sources, sort keys, unique
keys, fill targets, object fields, list columns, and column-cast targets MUST be
nonempty. Grouping keys may be empty only to request one global aggregate row.
`unpivot.index` and `join.columns` may be empty lists. A final column map and
an explicitly supplied unpivot value map MUST be nonempty. If `unpivot.columns`
is omitted, at least one input column must remain outside `index`. The two
operands of `multiply`, `add`, or `divide` may name the same column.

### join

| Argument | Value |
| --- | --- |
| `source` | Earlier named right-side table. |
| `how` | `inner`, `left`, or `cross`. |
| `on` | List of same-named keys on both sides. Required for `inner` and `left`, omitted for `cross`. |
| `columns` | Optional list of right-side payload columns. Omission includes all right non-key columns. |

| Kind | Row behavior |
| --- | --- |
| `inner` | Keep matching rows only. |
| `left` | Keep every left row, using null payloads for unmatched rows. |
| `cross` | Form every left/right row combination. |

Key types must agree without implicit conversion. Null keys never match.
Matching keys are not duplicated as right-side payloads and MUST NOT be listed
in `columns`. For a cross join, all right columns are payload candidates. An
explicit empty `columns` list retains no payload but still performs the join's
row matching or expansion. A payload-name collision is an error, not an automatic
suffix or overwrite. Rename a conflicting payload in an earlier named table.

All right-side matches are retained. Duplicate keys can therefore increase the
number of rows. Joins preserve left-row order and right-match order within each
left row. There is no implicit first-match or deduplication policy.

### first_present

This source-free constructor selects the first present named source in the declared
order. It returns the selected `TabularSource` unchanged, including when it has
zero rows, and preserves its availability and absent-input provenance. It does not
append or combine rows. Sources must be declared before the table. The scheduler
may skip an exact optional physical input name only when reading confirmed that
the input was absent and no schema-bearing `TabularSource` was produced. A
present file whose reader emits namespaced outputs does not make other names in
that namespace optional. For example, output `catalog.item` does not permit
selecting `catalog` or `catalog.missing`. Schema-bearing absent sources are
represented by their `ABSENT` availability instead of `absent_source_names`.
Direct callers of `assemble_table_records` may pass exact omitted names through
`absent_source_names`; those names cannot also have decoded sources. Unknown
names and forward references remain errors. Malformed present data is not
treated as absent. Errors may occur while reading or when a lazy table is
collected. If every candidate is absent, the constructor raises an error, so
include a separately declared typed empty `rows` table last when an empty
fallback is intended.

```json
{"operation":"first_present","sources":["preferred_input","empty_fallback"]}
```

### first_nonempty

This source-free constructor selects the first present, nonempty named source in
priority order and returns it unchanged, preserving its schema, availability,
and absent-input provenance. Present-empty and absent candidates are skipped.
An omitted optional file may be skipped only when the scheduler confirmed that
exact physical input absent and no schema-bearing `TabularSource` was produced.
A present namespaced reader output does not make other names in its namespace
optional. Schema-bearing absent sources are skipped by their `ABSENT`
availability. Direct callers may pass exact omitted names in
`absent_source_names`, which cannot also have decoded sources. Unknown and
forward references remain errors. Malformed present data is not treated as
absent. Errors may occur while reading or when a lazy table is collected.
`fallback` names an ordinary previously declared table source returned
unchanged when no candidate has rows. Its availability and absent-input
provenance are preserved, so an explicitly absent fallback remains absent. A
typed, present-empty `rows` table is a suitable fallback. The fallback is not
tested for nonemptiness. If `fallback` is omitted and all candidates are absent
or empty, assembly raises an error.

| Argument | Value |
| --- | --- |
| `sources` | Nonempty, unique candidate source names in precedence order. |
| `fallback` | Optional earlier table output returned only when all candidates are absent or empty. |

```json
{"operation":"first_nonempty","sources":["candidate_input"],"fallback":"empty_fallback"}
```

### match_patterns

This operation applies static groups of literal exact values and prefixes. It
reuses the same generic matcher as file processing and intentionally differs
from `match_source_patterns`: every matching group emits a row, unmatched rows
are dropped, and groups do not have precedence.

| Argument | Value |
| --- | --- |
| `column` | Existing string column to match. |
| `label_column` | New string column containing the matching group label. |
| `groups` | Ordered list of exact and/or literal-prefix groups. |
| `defaults` | Optional typed output attributes supplied by each group. |
| `case_sensitive` | Optional boolean. Defaults to `true`. |

Each group has a `label` and at least one of `exact` or `prefixes`. Prefixes
match the literal beginning of a value, with no boundary requirement. Group
`attributes` override the declared `defaults` for that output row. Attribute
names must be declared in `defaults`, and values must keep one scalar type per
attribute. Exact values and prefixes are case-sensitive by default. When
`case_sensitive` is false, the shared matcher compares Unicode lowercase
values. Null input values do not match. Each input row may produce several
output rows, in group order and then source-row order. Repeated labels or
matching groups are retained. Unmatched rows are omitted. Empty inputs retain
the schema declared by the label and default attributes. Missing/non-string
inputs and output-column collisions are errors.

```json
{
  "operation": "match_patterns",
  "column": "technology",
  "label_column": "category",
  "defaults": {"priority": 90},
  "case_sensitive": false,
  "groups": [
    {"label": "storage", "exact": ["CAES"], "attributes": {"priority": 80}},
    {"label": "storage", "prefixes": ["battery_"]}
  ]
}
```

### match_source_patterns

| Argument | Value |
| --- | --- |
| `column` | Existing string column on the current table. |
| `source` | Earlier named pattern table. |
| `pattern_column` | Existing string column in the pattern table. |
| `range_separator` | Nonempty literal separator for numeric-suffix ranges. |
| `prefix_separator` | Nonempty literal boundary after a prefix. |
| `precedence` | Each of `exact`, `range`, and `prefix` once, in priority order. |
| `prefix_policy` | `longest` or `first` among matching prefixes. |
| `duplicate_policy` | `first` or `last` among otherwise tied pattern rows. |
| `unmatched` | `keep` left rows with null pattern payload, or `drop` them. |
| `case_sensitive` | Optional boolean. Defaults to `true`. |

```json
{
  "operation": "match_source_patterns",
  "column": "technology",
  "source": "technology_subsets",
  "pattern_column": "subset_technology",
  "range_separator": "*",
  "prefix_separator": "_",
  "precedence": ["exact", "range", "prefix"],
  "prefix_policy": "longest",
  "duplicate_policy": "first",
  "unmatched": "keep",
  "case_sensitive": false
}
```

An exact pattern equals the input. A numeric range has the form
`prefix<digits><range_separator>prefix<digits>`. Both endpoints must have the
same prefix and the lower bound must not exceed the upper bound. The input must
have that prefix followed by a numeric suffix within the inclusive range. A
prefix pattern matches only when the input continues with the configured
`prefix_separator` boundary. The Polars backend collects distinct pattern values
during assembly to validate range declarations, even when the current input has
no rows. Null patterns are ignored, and null input values do not match.

The configured `precedence` resolves matches across kinds. `longest` chooses the
longest matching prefix; `first` keeps pattern-source order. `duplicate_policy`
selects the first or last source row when remaining matches tie. The result keeps
all left columns and adds the selected pattern row's payload columns, excluding
`pattern_column`. Left row order is retained. `keep` emits null payloads for
unmatched rows; `drop` removes them. Output-name collisions are errors.

With `case_sensitive: false`, strings and separators use full Unicode casefold,
not lowercase. The range and prefix separators must remain distinct after
casefolding. This includes equivalence such as `straße` and `STRASSE`, while
keeping dotless `ı` distinct from `i`. The current Polars backend applies
`str.casefold` through a Python callback to each input-side string column before
candidate matching. This preserves Unicode semantics but can add CPU cost for
large columns. The callback runs before the candidate cross join, not once per
candidate pair. The result remains lazy after pattern validation, so collecting
it can evaluate the pattern source and other upstream plans again.

An absent schema-bearing pattern source behaves as a typed empty pattern table.
`keep` retains every left row with null payloads and `drop` removes unmatched
rows. The output keeps the left source's availability and unions absence
provenance from both inputs. A present-empty pattern source has the same row
matching behavior but does not add absent-input provenance. Empty outputs retain
the left and pattern payload schema.

### filter

| Argument | Value |
| --- | --- |
| `column` | Existing left-side column. |
| `comparison` | `equals`, `not_equal`, `less_than`, `greater_than`, `greater_than_or_equal`, `less_than_or_equal`, `starts_with`, `is_null`, or `is_not_null`. |
| `value` | Literal scalar or whole-value binding for a binary comparison. |
| `other_column` | Existing right-side column for a binary comparison instead of `value`. |

Binary comparisons require exactly one of `value` or `other_column`. A null
literal or binding is rejected. To select null or non-null rows, use unary
`is_null` or `is_not_null` and omit both operand fields. Binary column
comparisons require identical declared dtypes and do not cast either side.

Only rows for which the comparison is true remain. Null results from binary
comparisons do not pass. String equality and `starts_with` are case-sensitive.
`starts_with` requires string columns and a string literal. It compares literal
prefixes, not regular expressions. A list is not an implicit membership
test. Missing columns and incompatible comparison types are
errors. Filtering does not lowercase, convert, or fill input values. Sequential
filter operations express conjunction without an expression tree.

### choose

Choose one of two existing columns or scalar values for each input row using one
flat comparison predicate. `choose` is separate from `fill_null`: filling only
replaces nulls, while a final projection only selects or renames columns. Use
`choose` for row-dependent values that neither operation can express. It accepts
one predicate and two operands, not nested conditions or calculations.

| Argument | Value |
| --- | --- |
| `column` | Existing column tested by the predicate. |
| `comparison` | Any comparison documented for `filter`. |
| `value` | Scalar value or whole-value binding for a binary predicate. |
| `other_column` | Existing comparison column instead of `value`. |
| `then` | A bare column name or an object containing scalar `value`, selected when the predicate is true. |
| `otherwise` | A bare column name or an object containing scalar `value`, selected otherwise. |
| `output` | New output-column name. |

Binary predicates require exactly one of `value` or `other_column`, and reject
null literals or bindings. Unary `is_null` and `is_not_null` omit both operand
fields. Null comparison results select `otherwise`. Column comparisons require
identical dtypes. Literal predicates use the same type rules as `filter`.

A bare string in `then` or `otherwise` names a column. An object of the form
`{"value": ...}` supplies a scalar literal or whole-value binding, including
explicit null. No other object fields are allowed. Lists, objects, and nested
calculations are not operands. Branch columns must have identical dtypes, except
that `int64` and `float64` widen to `float64`. A null literal or null-typed
branch takes the other branch's dtype. Other incompatible types are errors.
When both branches are null and no dtype can be determined, the operation is an
error. Literal values must be representable by the selected output type. A string
literal remains text, even when it resembles an ISO datetime. The output type is
retained for empty inputs.

The operation preserves every input field, row count, and row order. `output`
MUST be a new column. Conditions and branch values refer only to existing input
columns, not to the new output. Apply multiple decisions as ordered operations
with separate outputs instead of embedding a nested decision tree.

```json
{
  "operation": "choose",
  "column": "component_family",
  "comparison": "equals",
  "value": "thermal",
  "then": "thermal_heat_rate",
  "otherwise": "heat_rate",
  "output": "prepared_heat_rate"
}
```

### group_by

| Argument | Value |
| --- | --- |
| `columns` | Grouping-key column names, or an empty list for a global aggregate. |
| `aggregate` | List of aggregate records. |

Each aggregate record contains:

| Field | Value |
| --- | --- |
| `operation` | `sum`, `max`, `mean`, `count`, `first`, `last`, or `list`. |
| `column` | Input column to aggregate. |
| `output` | Name of the aggregate result. |

```json
{
  "operation": "group_by",
  "columns": ["region", "solve_year"],
  "aggregate": [
    {"operation": "sum", "column": "contribution", "output": "total"},
    {"operation": "max", "column": "contribution", "output": "largest"}
  ]
}
```

The result contains only grouping columns and aggregate outputs. Aggregate
outputs MUST be distinct from each other and the grouping keys. An aggregate may
reuse its own input name when that name is not a grouping key. Each existing
group produces one row. Groups retain first-seen order, and null keys group
together. With nonempty keys, an empty input produces no groups. An empty
`columns` list requests one global aggregate row for a present input, including
a present-empty input. Aggregate expressions define empty-input values. Mean is
null, count and sum are zero, and list is empty. An absent optional input stays
absent and yields a typed zero-row result with its missing-input provenance,
not a synthesized summary row.

`sum` ignores null values and returns zero for an all-null existing group. `max`
ignores null values and returns null for an all-null group. Their numeric input
type is preserved. `mean` requires a numeric column, ignores null values,
returns float64, and returns null for an all-null group. `count` accepts any
column, counts non-null values, and returns int64, including zero for an
all-null group. `first` and `last` retain the input type and the selected value,
including null. They use the current row order within each group. `list`
collects every input value in current row order, including nulls, and returns a
list of the input type. Sort explicitly before grouping when first or last has a
priority meaning. Group order remains first-seen. Calculate row-level values
before grouping and operate on group results afterward. Aggregate records do
not contain nested expressions. For grouped aggregation, an empty input produces
no groups, with a list output retaining its declared element type. A global
aggregate over a present-empty input produces one row and a typed empty list
value.

### unpivot

| Argument | Value |
| --- | --- |
| `index` | Identifier columns retained on each output row. |
| `columns` | Optional map from output labels to input value-column names. If omitted, every input column outside `index` is selected and its exact name is the output label. |
| `variable_name` | Name of the output label column. |
| `value_name` | Name of the output value column. |
| `value_type_name` | Optional output column containing each source value's logical scalar type. |

```json
{
  "operation": "unpivot",
  "index": ["region"],
  "columns": {"base": "base_mw", "high": "high_mw"},
  "variable_name": "scenario",
  "value_name": "load_mw"
}
```

For each `columns` entry, the key is the exact text written into the
`variable_name` column. The value is the input column read into `value_name`.
In this example, `scenario` contains `base` and `high`, never `base_mw` or
`high_mw`. Given region `North`, `base_mw = 10.0`, and `high_mw = 12.0`, the
output is:

| region | scenario | load_mw |
| --- | --- | ---: |
| North | base | 10.0 |
| North | high | 12.0 |

Requested labels are part of the output contract. To use `ordinary` instead of
`base`, change the key to `"ordinary": "base_mw"`. Do not replace a requested
label with its input column name or expect a later join to correct it.

With an explicit `columns` map, only listed value columns are unpivoted, and
unlisted columns are excluded unless retained by `index`. If `columns` is
omitted, every other input column is unpivoted and its exact header becomes its
label. Explicit null and empty maps are invalid. There is no prefix or suffix
interpretation. Omitted-column mode requires at least one non-index input
column, including on an empty input.

Labels are strings and are processed in sorted order. Input row order is
preserved within each label. Identifier types are preserved. Without
`value_type_name`, value columns need compatible types, including on empty
input. Numeric widening from int64 to float64 is compatible, but numeric values
and text do not silently become one string column. Null values remain rows with
null values. Unlike this table operation, file-processing `unpivot` uses Polars'
common-supertype conversion when `value_type_name` is omitted.

When `value_type_name` is provided, each selected source type must be one of
`bool`, `int64`, `float64`, `string`, or `datetime`. `value_name` then contains
string representations of source values, while `value_type_name` contains the
backend-neutral logical source type for each label. Null values stay null, and
the type label still describes the declared source column. This mode allows
mixed supported scalar columns without losing their original type information.
Unsupported list, object, or other backend-specific types are errors, including
on empty inputs. The optional field is omitted when unused, not set to null.

Labels are exact data values, not output-column names. A label may equal an
input column name, and arbitrary exact input column names are supported. The
backend performs one native unpivot and maps its generated source-name values
to the requested labels, avoiding a separate upstream lazy branch per selected
column.

### concat

| Argument | Value |
| --- | --- |
| `sources` | Ordered list of earlier table names. |

This constructor appends rows in source order. Present sources must have the
same column names, regardless of their input order, and compatible types. The
first present source defines output column order. Matching columns are aligned
by exact name. Equal types are retained; int64 and float64 widen to float64.
Other type combinations and missing or extra fields are errors. Absent optional
sources are skipped and do not constrain a schema when a present source
contributes. If every source is absent, their declared schemas must agree and
the first absent source defines output order. The result is a typed empty table.
Malformed present sources remain errors. This operation does not join rows,
aggregate them, infer a union schema, or fill undeclared missing fields.

Use final column maps on source tables to establish a common schema.

### multiply

| Argument | Value |
| --- | --- |
| `columns` | The two numeric input-column names. |
| `output` | Name of the new calculated column. |

Multiply the two values for each row, preserving the other columns and the row
count. Null input produces null. Numeric widening from int64 to float64 is
compatible. Text-to-number conversion and unit conversion are not implicit.
The output MUST be a new column name. Inputs remain available for later operations.

```json
{
  "operation": "multiply",
  "columns": ["quantity_mw", "fraction"],
  "output": "contribution"
}
```

The strings identify columns. They are not arithmetic expressions. Supply a
coefficient as a column in a prepared factor table rather than embedding a
formula string in this operation.

### add and divide

Both operations use the same arguments as `multiply`:

| Argument | Value |
| --- | --- |
| `columns` | Exactly two existing numeric input-column names, in operand order. |
| `output` | Name of a new calculated column. |

They preserve all existing columns, row count, and row order. Null operands
produce null. `add` preserves int64 when both operands are int64 and otherwise
returns float64. `divide` returns float64. A zero denominator produces null,
not infinity or a business default. Neither operation converts text or changes
units. The output name MUST NOT already exist.

```json
[
  {"operation": "add", "columns": ["base_cost", "adjustment"], "output": "total_cost"},
  {"operation": "divide", "columns": ["cost", "distance"], "output": "cost_per_distance"}
]
```

### absolute

| Argument | Value |
| --- | --- |
| `column` | Existing numeric input column. |
| `output` | Name of a new output column. |

Take the absolute value of each numeric input. The operation retains the input
numeric dtype, preserves nulls, other columns, row count, and row order. An empty
input retains the declared output dtype. Text columns, missing inputs, and an
output name that already exists are errors. Numeric overflow and non-finite
behavior are outside this contract.

```json
{"operation":"absolute","column":"capacity","output":"absolute_capacity"}
```

### casefold

| Argument | Value |
| --- | --- |
| `column` | Existing string input column. |
| `output` | New string column for the normalized key. |

Apply full Unicode `str.casefold` to each non-null value. Nulls remain null,
and the operation preserves every input column, row count, row order, and the
original display value. An empty input retains a string output column. Missing
columns, non-string inputs, and an existing output name are errors. The
normalization is useful before an exact column-to-column join when the original
name must remain available for display. It does not parse patterns, alter the
source value, or trim punctuation. The current Polars backend uses a Python
callback to preserve full Unicode casefold semantics, which can add CPU cost on
large columns.

```json
{"operation":"casefold","column":"technology","output":"technology_key"}
```

### concat_strings

| Argument | Value |
| --- | --- |
| `columns` | Ordered, unique existing string or integer column names. |
| `separator` | Optional literal text between values. Defaults to the empty string. |
| `output` | Name of the new string column. |

Convert each selected value to text and join them in the declared order. A null
input produces a null output. All other columns, row count, and row order are
preserved. An empty input retains a string output type. Missing columns,
non-string/non-integer values, repeated input names, and an existing output name
are errors. This operation accepts no format pattern or expression string.

```json
{
  "operation": "concat_strings",
  "columns": ["region", "solve_year"],
  "separator": "_load_",
  "output": "owner_name"
}
```

### split

| Argument | Value |
| --- | --- |
| `column` | Existing string input column. |
| `separator` | Nonempty literal text separator, not a regular expression. |
| `index` | Zero-based result part to select. |
| `output` | New string column. |

Split each non-null input value on the exact separator and select the part at
`index`. Empty parts are retained. If that part does not exist, the output is
null. Null inputs remain null. All other columns, row count, and row order are
preserved. The output name MUST be new. An empty input retains a string output
column. Missing columns, non-string inputs, empty separators, and negative
indexes are errors.

```json
{"operation":"split","column":"technology","separator":"_","index":0,"output":"technology_base"}
```

### rows

| Argument | Value |
| --- | --- |
| `schema` | List of records containing `name` and `dtype`. |
| `values` | Literal records or a whole-value binding to records. |

`dtype` is one of `bool`, `int64`, `float64`, `string`, or `datetime`. Datetime
values are ISO-8601 strings and are parsed into the declared type. Explicit nulls
are retained, and an empty `values` list still produces the complete schema.

```json
{
  "operation": "rows",
  "schema": [{"name": "solve_year", "dtype": "int64"}],
  "values": "{solve_year_rows}"
}
```

This constructor declares the column shape and types even when `values` is an
empty list. Schema names MUST be unique. Each value record MUST supply exactly
the declared fields with compatible values, including explicit nulls where
needed. Extra or missing fields are errors, not inferred schema changes. It does not infer years or categories from other sources, and it does
not define business validation for input-file contents.

### fill_null

| Argument | Value |
| --- | --- |
| `columns` | Existing columns whose nulls are replaced. |
| `value` | Compatible replacement scalar, flat scalar-list literal, or whole-value binding. |
| `from_columns` | Ordered backup columns, as an alternative to `value`. |

Exactly one of `value` or `from_columns` is required. `from_columns` must be a
nonempty list of unique names. For each target, use its original incoming value
when non-null, otherwise the first non-null value among the backup columns in
the listed order. Every target and backup must have the same dtype. All targets
read the original input row, not another target's already-filled result. Zero is
non-null and is preserved. If every candidate is null, the result remains null.

With a scalar `value`, non-null values are preserved. An explicit null scalar
is a no-op and retains the selected columns' values and dtypes. Filling a
float64 column with integer zero keeps it float64. A flat list `value` fills a list-typed
column, with elements checked against its declared scalar element type. Null
list elements are preserved. Nested arrays and objects are not accepted. Missing
columns, invalid values, and NaN are not nulls and are not repaired by this
operation. The application owns the decision that a particular missing value
means zero, an empty list, or another default.

### head

| Argument | Value |
| --- | --- |
| `n` | Nonnegative integer number of rows to retain. |

Retain the first `n` rows in the source's current order. The operation preserves
column names, types, row order, availability, and missing-input provenance. A
zero count produces a typed empty table. It does not sort before selecting.

```json
{"operation": "head", "n": 8760}
```

### sort

| Argument | Value |
| --- | --- |
| `columns` | Sort keys in priority order. |
| `descending` | Optional strict boolean, defaults to `false`, applied to all keys. |

Sort is stable on ties and places nulls last in either direction. Sorting
changes rows, while a final column map changes fields. Perform sorting
explicitly when the consumer requires ordered samples.

```json
{"operation": "sort", "columns": ["technology_full"], "descending": true}
```

### unique

| Argument | Value |
| --- | --- |
| `columns` | Nonempty key columns. |
| `keep` | Required `first` or `last` row to retain for each key. |

Select complete rows, retaining all fields and their source order. Null keys
belong to the same key group. `keep` refers to current row order, so priority
selection MUST use an explicit stable `sort` immediately before `unique`. Sort
ascending by priority and use `keep: "first"` for the lowest priority value, or
`keep: "last"` for the highest. Ties are resolved by stable source order. An
empty input retains its schema.

```json
[
  {"operation": "sort", "columns": ["priority"]},
  {"operation": "unique", "columns": ["technology"], "keep": "first"}
]
```

### cast

| Argument | Value |
| --- | --- |
| `column` | Existing column to convert in place. |
| `dtype` | `bool`, `int64`, `float64`, `string`, or `datetime`. |

Cast preserves row count, order, and nulls. Use strict conversion. A non-null
value that cannot be represented by the target type is an error, not a null or a
filtered row. Floating-point to `int64` casts are unsupported and rejected
rather than truncated. Datetime text uses ISO-8601. Cast does not validate
application content or create a new output column. File-processing
`cast_columns` has a separate `float_to_int` policy for intentional truncation.

### datetime_part

| Argument | Value |
| --- | --- |
| `column` | Existing datetime-typed column. |
| `part` | `year`, `month`, `day`, `hour`, `minute`, or `second`. |
| `output` | New output-column name. |

Extract one datetime component as an `int64` value. Null timestamps remain null.
The operation preserves input rows, order, availability, and other columns. Empty
inputs retain an `int64` output schema. Missing columns, non-datetime inputs, and
output-name collisions are errors.

```json
{"operation": "datetime_part", "column": "timestamp", "part": "year", "output": "weather_year"}
```

### object

| Argument | Value |
| --- | --- |
| `columns` | Nonempty map from object-field names to existing columns or literal text. |
| `output` | New output-column name. |

A string value in `columns` is an exact input-column reference. An object of the
form `{"value": "text"}` supplies literal text. No other value forms or nested
calculations are allowed. The operation creates one plain object value per input
row, with fields in sorted-name order, retains all input columns, and preserves
row count and order. Existing source values may themselves be objects or lists.
The output name MUST be new. On empty input, the output retains its typed object
schema with zero rows.

```json
{"operation":"object","columns":{"from_to":"forward_capacity","to_from":"reverse_capacity"},"output":"max_active_power"}
```

### list

| Argument | Value |
| --- | --- |
| `columns` | Ordered nonempty list of existing column names. |
| `output` | New output-column name. |

The operation creates one list value per input row using the selected column
values in the declared order. Each input cell contributes one element, so a
list-valued cell remains nested as one element. Element dtypes must be identical,
or be `int64` and `float64`, in which case elements widen to `float64`. Nulls
are retained, rows and their order are preserved, and no values are deduplicated
or sorted.
All input columns remain available. The output name MUST be new. Empty input
retains the typed list schema.

```json
{"operation":"list","columns":["longitude","latitude"],"output":"coordinates"}
```

## Create a mapping from Python

The public models also support programmatic mapping construction. This example
creates two sets of units, joins their regions, calculates available capacity,
and groups two capacity metrics. The `TableOperation` adapter validates an
individual tagged operation. `exclude_unset=True` preserves the distinction
between omitted fields and explicitly supplied nulls when saving the models.

```python doctest
>>> import json
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from pydantic import TypeAdapter
>>> from r2x_core import TableAddOperation, TableAggregate, TableCastOperation
>>> from r2x_core import TableMatchSourcePatternsOperation, TableFirstPresentOperation
>>> from r2x_core import TableFirstNonEmptyOperation
>>> from r2x_core import TableChooseOperation, TableConcatOperation, TableDivideOperation
>>> from r2x_core import TableFillNullOperation, TableFilterOperation, TableGroupByOperation
>>> from r2x_core import TableJoinOperation, TableLiteral, TableMappingBackend, TableMappingRecord
>>> from r2x_core import TableMultiplyOperation, TableOperation, TableRowsColumn, TableRowsOperation
>>> from r2x_core import TableScalarLiteral, TableSortOperation, TableSplitOperation
>>> from r2x_core import SourceAvailability, TabularSource
>>> from r2x_core import TableUniqueOperation, TableUnpivotOperation, assemble_table_records, assemble_tables
>>> from r2x_core.polars_adapter import PolarsTabularBackend
>>> import polars as pl
>>> schema = [
...     TableRowsColumn(name=name, dtype=dtype) for name, dtype in [
...         ("plant", "string"), ("region", "string"), ("capacity", "float64"),
...         ("factor", "float64"), ("backup", "float64"), ("reserve", "float64"),
...         ("year", "int64"),
...     ]
... ]
>>> base = TableRowsOperation(operation="rows", schema=schema, values=[{
...     "plant": "wind_1", "region": "west", "capacity": 10.0, "factor": None,
...     "backup": 0.5, "reserve": 2.0, "year": 2032,
... }])
>>> new = TableRowsOperation(operation="rows", schema=schema, values=[{
...     "plant": "solar_2", "region": "east", "capacity": 20.0, "factor": 0.8,
...     "backup": 0.4, "reserve": 1.0, "year": 2032,
... }])
>>> regions = TableRowsOperation(operation="rows", schema=[
...     TableRowsColumn(name="region", dtype="string"),
...     TableRowsColumn(name="network", dtype="string"),
... ], values=[{"region": "west", "network": "W"}, {"region": "east", "network": "E"}])
>>> positive = TypeAdapter(TableOperation).validate_python({
...     "operation": "filter", "column": "capacity", "comparison": "greater_than", "value": 0.0,
... })
>>> isinstance(positive, TableFilterOperation)
# True
>>> source_match = TypeAdapter(TableOperation).validate_python({
...     "operation": "match_source_patterns", "column": "technology",
...     "source": "subsets", "pattern_column": "subset",
...     "range_separator": "*", "prefix_separator": "_",
...     "precedence": ["exact", "range", "prefix"],
...     "prefix_policy": "longest", "duplicate_policy": "first",
...     "unmatched": "keep", "case_sensitive": False,
... })
>>> isinstance(source_match, TableMatchSourcePatternsOperation)
# True
>>> records = [
...     TableMappingRecord(name="base", operations=[base]),
...     TableMappingRecord(name="new", operations=[new]),
...     TableMappingRecord(name="regions", operations=[regions]),
...     TableMappingRecord(name="units", operations=[
...         TableConcatOperation(operation="concat", sources=["base", "new"]),
...     ]),
...     TableMappingRecord(name="energy", source="units", operations=[
...         TableJoinOperation(operation="join", source="regions", how="left",
...                            on=["region"], columns=["network"]),
...         TableSortOperation(operation="sort", columns=["plant"]),
...         TableUniqueOperation(operation="unique", columns=["plant"], keep="first"),
...         positive,
...         TableFillNullOperation(operation="fill_null", columns=["factor"], from_columns=["backup"]),
...         TableMultiplyOperation(operation="multiply", columns=["capacity", "factor"], output="available"),
...         TableAddOperation(operation="add", columns=["available", "reserve"], output="with_reserve"),
...         TableDivideOperation(operation="divide", columns=["with_reserve", "capacity"], output="ratio"),
...         TableChooseOperation(operation="choose", column="ratio", comparison="less_than_or_equal",
...                              value=1.0, then="ratio", otherwise=TableScalarLiteral(value=1.0),
...                              output="bounded_ratio"),
...         TableSplitOperation(operation="split", column="plant", separator="_", index=0, output="resource"),
...         TableUnpivotOperation(operation="unpivot", index=["region", "network", "resource", "year", "bounded_ratio"],
...                               columns={"capacity": "capacity", "available": "available"},
...                               variable_name="metric", value_name="mw"),
...         TableGroupByOperation(operation="group_by", columns=["region", "network", "resource", "year", "bounded_ratio", "metric"],
...                               aggregate=[TableAggregate(operation="sum", column="mw", output="total")]),
...         TableSortOperation(operation="sort", columns=["region", "metric"]),
...         TableCastOperation(operation="cast", column="year", dtype="string"),
...     ], columns={"region": "region", "network": "network", "resource": "resource", "year": "year",
...                 "metric": "metric", "amount": "total", "ratio": "bounded_ratio", "unit": TableLiteral(value="MW")}),
... ]
>>> backend: TableMappingBackend = PolarsTabularBackend()
>>> absent_input = TabularSource(
...     pl.DataFrame(schema={"value": pl.Int64}).lazy(), backend,
...     availability=SourceAvailability.ABSENT,
... )
>>> present_empty = TabularSource(pl.DataFrame(schema={"value": pl.Int64}).lazy(), backend)
>>> fallback = TableMappingRecord(name="empty_fallback", operations=[
...     TableRowsOperation(operation="rows", schema=[TableRowsColumn(name="value", dtype="int64")], values=[]),
... ])
>>> selected_record = TableMappingRecord(name="selected", operations=[
...     TableFirstPresentOperation(operation="first_present", sources=["absent", "empty", "empty_fallback"]),
... ])
>>> selected = assemble_table_records(
...     {"absent": absent_input, "empty": present_empty}, [fallback, selected_record], backend=backend
... )
>>> selected["selected"] is present_empty
# True
>>> nonempty_input = TabularSource(pl.DataFrame({"value": [8]}, schema={"value": pl.Int64}).lazy(), backend)
>>> nonempty_selection = TableFirstNonEmptyOperation(
...     operation="first_nonempty", sources=["empty", "nonempty_input"], fallback="empty_fallback",
... )
>>> nonempty_tables = assemble_table_records(
...     {"empty": present_empty, "nonempty_input": nonempty_input},
...     [fallback, TableMappingRecord(name="selected_nonempty", operations=[nonempty_selection])],
...     backend=backend,
... )
>>> nonempty_tables["selected_nonempty"] is nonempty_input
# True
>>> with TemporaryDirectory() as folder:
...     path = Path(folder) / "table_mapping.json"
...     payload = [record.model_dump(mode="json", by_alias=True, exclude_unset=True) for record in records]
...     path.write_text(json.dumps(payload), encoding="utf-8") > 0
...     tables = assemble_tables({}, mapping_path=path, backend=backend)
# True
>>> rows = list(tables["energy"].iter_rows())
>>> [(row["resource"], row["metric"], row["amount"], row["unit"]) for row in rows]
# [('solar', 'available', 16.0, 'MW'), ('solar', 'capacity', 20.0, 'MW'), ('wind', 'available', 5.0, 'MW'), ('wind', 'capacity', 10.0, 'MW')]
>>> [row["ratio"] for row in rows]
# [0.85, 0.85, 0.7, 0.7]
>>> copied = assemble_table_records(
...     tables,
...     [TableMappingRecord(name="copied_base", source="base", operations=[])],
...     backend=backend,
... )
>>> list(copied["copied_base"].iter_rows())
# [{'plant': 'wind_1', 'region': 'west', 'capacity': 10.0, 'factor': None, 'backup': 0.5, 'reserve': 2.0, 'year': 2032}]
```

`assemble_tables` loads one JSON mapping file. `assemble_table_records` accepts
already-validated typed records so callers can retain one mapping snapshot across
an interleaved file/table schedule or input-upgrade retry. Both return named
`TabularSource` values. Any `initial_tables` entries must name records in the
mapping; selected seeded records are reused without recomputing their operations.
Undeclared seeded outputs are rejected, matching the cross-boundary scheduler.
Input columns and sources are described in the
[data and serialization reference](/r2x-core/references/data-workflow/).

## ReEDS composition patterns

These generic operations cover arithmetic, aggregate policies, comparisons,
column defaults, and stable row selection without adding application-specific
handlers or expression trees. Compose ordered operations and named intermediate
tables. Application configuration owns technology categories, eligibility,
component naming, and cost-source priority.

A weighted rate can multiply quantity by rate, group by the required identity,
summarize the numerator and denominator, then divide. Because `sum` ignores
nulls, a mapping that must retain an unknown rate needs an explicit missing-rate
candidate table and stable priority selection, rather than silently computing a
partial weighted mean. A zero or negative denominator follows the declared
arithmetic semantics and must not be replaced with a business default.

Conditional cost precedence can normalize eligible candidate rows to shared
key, priority, and value fields, concatenate them, sort by explicit priority,
and select the first complete row with `unique`. An earlier-record lookup
filters strictly earlier and nonzero candidates, sorts by year, then keeps the
last row per key. `first` and `last` retain complete aggregate field values, but
`unique` is the row-selection operation when related fields must come from one
source record.

### Worked acceptance cases

The values below specify observable outcomes, not a proposed JSON syntax.
Policies such as treating an unknown rate as unknown belong to the application
and must remain explicit in its mapping.

| Case | Inputs | Expected outcome |
| --- | --- | --- |
| Add an adjustment | Base cost 45,000 and adjustment 1,000. | 46,000. |
| Divide measurements | Cost 200 and distance 40. | Cost per distance 5. |
| Divide by zero | Cost 200 and distance 0. | Null, not infinity or a business default. |
| Capacity-weighted rate | Capacities 100 and 300, with rates 20 and 40. | Rate 35, not the unweighted mean 30. |
| Unknown weighted rate | A positive-capacity row has a null rate. | The ReEDS aggregate rate remains null, not a partial average. |
| Nonpositive total capacity | Group capacity sums to zero or less. | The ReEDS aggregate rate remains null. Do not divide by zero or manufacture a zero rate. |
| Conditional value | An eligible row has base rate 20 and target rate 40. | Select 40 when eligible and 20 otherwise. |
| Column default | Primary values `null`, `0`, `null`, with backup values `80`, `80`, `null`. | Results `80`, `0`, `null`, preserving all three rows. |
| Priority selection | One key has bin 1 with cost 40 and bin 2 with cost 30. | Selecting the lowest bin returns the entire bin-1 row, not the lowest cost. |
| Earlier nonzero rate | Eligible history contains 2020:66, 2025:0, 2030:88, and 2035:55. The requested solve year is 2030. | The strictly earlier nonzero lookup returns 66. Same-year and future rates do not qualify. |

### Keep input preparation and schema handling separate

Calendar preparation and decoding native headers such as `technology|region`
are input-boundary concerns. Once a named calendar exposes the required month,
year, and timestamp columns, monthly-to-hourly expansion can use ordinary joins.
Representative-period expansion can likewise join a supplied hour map. Neither
case needs an application-specific profile-expansion operation in core.

A physical `DataFile` may declare `columns` as records with native `name`,
`dtype`, optional `rename`, and optional strict boolean `required` (default
`true`). Supported dtypes are `bool`, `int64`, `float64`, `string`, and
`datetime`. When the physical file is present, a missing required column is an
error. A missing column declared with `required: false` is materialized as a
typed null column and preserves the input row count. A present optional column
is cast and renamed by the same strict rules as every other declared column.
Malformed present values remain errors. A missing optional file remains distinct
from a missing column in a present file. Other present columns remain available
with their reader-provided types. Names are exact, including punctuation. A
blank native header must be renamed to a nonempty output name. Renames must not
collide with another output column. CSV declarations also guide reader schema
inference so a late fractional value is not incorrectly inferred as an integer. Native
floating-point columns declared as int64 are rejected rather than silently
truncated, including values read from HDF5.

When an optional physical input is missing and declares `columns`, core exposes a
zero-row typed source using the declared output names and dtypes, marked absent.
`TabularSource.availability` distinguishes this from present-empty data, and
`TabularSource.absent_inputs` tracks missing names through assembly. Without a
declared schema, a missing optional input remains omitted and cannot be used by
table assembly. A schema-bearing absent source remains absent when used as a
base; when used as a join right side it behaves as a zero-match table and the
result records the missing input in its diagnostics. `concat` skips absent
sources and returns a present typed empty result if none contribute rows. Parser
instructions cannot consume absent sources. Do not infer schema from missing
data, fabricate rows, or add per-row content-validation models to table
assembly. Missing columns and malformed present inputs remain errors.

`file_mapping.json` owns native columns, types, input filters, and renames.

Application configuration owns technology categories, eligibility, cost-source
priority, and component naming policy. Parser rules own component construction
and attachments. A complete mapping must account for every parser-facing source
and its preparation.

## Availability and empty results

| Input state | Behavior |
| --- | --- |
| Present-empty table | Retain its declared schema through transformations. Row operations do not invent observations. |
| Absent optional physical input with declared `columns` | Expose a typed zero-row source marked absent. |
| Absent optional physical input without declared `columns` | Omit it; ordinary table references are errors, while selection constructors may skip only when the scheduler confirmed this exact input absent. |
| Absent optional base source | Remain absent through ordinary operations, with output schema still known. |
| Absent optional right-side source | Act as a zero-match source for the join and retain absence in diagnostics. |
| Absent optional source in `concat` | Skip the source. Return a typed empty result if no source contributes rows. |
| Malformed present source | Fail rather than reinterpret it as empty or absent. |
| Unknown source name | Configuration error, not optional availability. |

`assemble_tables` and `assemble_table_records` accept `absent_source_names` for
exact optional inputs confirmed absent without producing a decoded source. This
set must be disjoint from decoded sources, initial tables, and table outputs.
Only `first_present` and `first_nonempty` may skip these names. By contrast,
`declared_source_names` validates external references on seeded table outputs
that are reused without executing their records. It does not mark a source
absent or make an ordinary table dependency optional.

An empty cross-join input produces no combinations. A left join against an empty
right table preserves the left rows with null payloads. Grouping an empty table
produces no groups. These rules are distinct from `fill_null`, which changes
values only after rows exist.

## Types and errors

The examples use string labels, int64 years, float64 measurements, and datetime
timestamps. Keep key types consistent across sources and numeric units
consistent across contributions. Numeric overflow and non-finite source-value
policies are outside the contract documented here. Do not rely on them to supply
application defaults or business validation.

| Error | Corrective action |
| --- | --- |
| Unknown operation or field | Use the operation's documented tag and arguments. |
| Duplicate table name or JSON key | Keep a single definition rather than relying on replacement order. |
| Unknown or forward source | Declare the source before its consumer and check the exact name. |
| Missing column | Correct the upstream schema or explicit column reference. |
| Join payload collision | Prepare a right-side table with distinct payload names. |
| Incompatible keys or operands | Normalize types and units upstream. |
| Incompatible concat or unpivot values | Establish compatible source schemas before reshaping. |
| Unresolved configuration binding | Supply the binding with the required value type. |

## Authoring checks

Before handing a mapping to its consumer:

1. Check strict JSON structure, including duplicate member names. A parser that
   silently keeps the last duplicate value is not a conformance check.
2. Trace each named source and binding. Check column availability after each
   operation and before the final projection.
3. Compare the final table name and schema with the consumer's request. Do not
   substitute an example name or expose an intermediate table instead.
4. Check results with duplicate keys, null values, empty inputs, and changed
   configuration values. Do not hardcode one example's rows or years.
5. Run the mapping with a compatible backend and verify row counts, values,
   and required order, not just whether the mapping parses.

Table assembly does not construct Pydantic components or attachments. The final
table must satisfy its parser instruction's field names, types, owner identity,
metadata partitioning, and time-axis requirements. See
[Attach time series](/r2x-core/how-tos/attach-timeseries/) for the implemented
attachment contract.
