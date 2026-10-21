# Tabular Processing Roadmap

`TabularProcessing` is the current contract for `DataFile.proc_spec`. It is
transitional.

## Why it is transitional

`TabularProcessing` has 17 optional operation fields, but their execution order
is implicit. `polars_adapter.processing.process_tabular_data` contains two
hard-coded orderings, selected according to whether `unpivot_on` is set. Each
new transform requires a placement decision in both orderings.

## Intended replacement

An ordered list of `MappingStep` from `r2x_core.models` will be executed by
`tabular_backend.apply_mapping_steps`, which delegates each operation to
`MappingStepBackend.apply_mapping_operation`. The executor exists today and is
exercised by `tests/test_polars_adapter.py`. The step-list form is not yet a
supported `DataFile.proc_spec`.

`PolarsTabularBackend` implements both contracts. A backend that only processes
`DataFile` inputs needs just `TabularBackend.supports_data` and `process`.

## Parity checklist

The replacement is gated on all of the following:

1. A pivot step equivalent to `pivot_on` with `group_by` and `aggregate_on`.
2. A drop-columns step.
3. Sort direction on `SortStep`.
4. A replace-values expression or step.
5. Behavioral equivalence tests that run every existing `TabularProcessing` test
   fixture through an equivalent `MappingStep` list and compare collected frames.

When parity lands, remove `TabularProcessing` in the same change. The two models
must not ship as alternatives for the same `DataFile`.

## Configuration authors

Continue using `TabularProcessing` today. The step-list form is not a supported
`proc_spec` yet.
