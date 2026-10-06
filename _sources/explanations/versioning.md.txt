# Versioning and Upgrades: Design Philosophy

## The Problem We Solve

Data models and system schemas evolve. A parser built for v1.0 data won't work with v2.0. Traditional approaches to this problem fall into two categories:

1. **Monolithic Migrations**: One big transformation function that knows about all versions. Problem: unmaintainable, hard to test, risky to deploy.
2. **Database Migrations**: Complex tools like Alembic. Problem: overkill for static data files, hard to understand data transformations.

r2x-core uses **staged upgrades**: incremental transformations that compose together, each targeting a specific version range. This approach balances simplicity, testability, and maintainability.

## Staged Upgrades vs Monolithic Upgrades

### Monolithic Approach (Fragile)

```python
def upgrade_all(data, current_version: str):
    if current_version == "1.0.0":
        # Upgrade 1.0.0 → 1.1.0
        data = rename_columns_v1_1(data)
        # Upgrade 1.1.0 → 1.5.0
        data = add_field_v1_5(data)
        # ... 20 more transformations ...
    elif current_version == "1.5.0":
        # Duplicate logic for partial upgrades
        data = add_field_v1_5(data)
        # ... more duplicated code ...
    return data
```

Problems:

- Logic duplication across version branches
- Hard to test individual transformations
- Single point of failure: if one transformation breaks, entire upgrade fails
- Difficult to debug: which transformation failed?
- Risky to modify: changing one step might affect others unexpectedly

### Staged Approach (Maintainable)

```python
upgrades = [
    UpgradeStep(
        name="rename_columns",
        func=rename_columns_v1_1,
        target_version="1.1.0",
        priority=10
    ),
    UpgradeStep(
        name="add_field",
        func=add_field_v1_5,
        target_version="1.5.0",
        priority=20
    ),
    # ... more discrete steps ...
]

# Execute in order
for step in upgrades:
    result = run_upgrade_step(step, data, current_version=current_ver, strategy=strategy)
    if is_err(result):
        print(f"Failed at {step.name}")
        break
    data = result.ok()
```

Benefits:

- Each step is independent and testable
- Easy to identify exactly which step failed
- New versions add new steps without modifying old ones
- Individual transformations are simple and understandable
- Easier to rollback or skip problematic versions

## Version Comparison Strategies

Different projects need different versioning schemes. r2x-core provides a plugin architecture:

### Semantic Versioning (Most Common)

```python
strategy = SemanticVersioningStrategy()
assert strategy.compare_versions("1.0.0", target="2.0.0") == -1  # 1.0.0 < 2.0.0
assert strategy.compare_versions("2.0.0", target="2.0.0") == 0   # equal
assert strategy.compare_versions("3.0.0", target="2.0.0") == 1   # 3.0.0 > 2.0.0
```

Semantically versioned data follows major.minor.patch convention. Upgrades typically apply to a range (e.g., versions 1.5.0 to 1.9.9 need this upgrade to reach 2.0.0).

### Git-Based Versioning

```python
strategy = GitVersioningStrategy(repo_path=Path("."))
# Compares by commit order in git history
```

Useful for projects where commits are the source of truth. Typical in continuous integration/deployment scenarios.

### Custom Strategies

```python
class CustomVersionStrategy:
    def compare_versions(self, current: str, *, target: str) -> int:
        # Your comparison logic
        pass
```

Enables domain-specific versioning (e.g., "v2024-Q1" style versions).

## Version Ranges and Upgrade Applicability

An upgrade step specifies when it applies:

```python
upgrade = UpgradeStep(
    name="fix_bug_123",
    func=fix_bug_123,
    target_version="1.5.3",
    min_version="1.5.0",    # Don't apply if older than this
    max_version="1.5.2"     # Don't apply if newer than this
)
```

The logic: "If current version is in [min_version, max_version], and it's < target_version, run this upgrade."

This allows:

- **Targeted Fixes**: Apply patches only to affected versions
- **Conditional Upgrades**: Skip upgrades not needed for a particular version
- **Multi-Path Upgrades**: Different transformations for different starting versions

## FILE vs SYSTEM Upgrades

### FILE Upgrades (Most Common)

Transform raw data files before parsing. Typical operations:

- Rename columns in CSV
- Add missing columns with defaults
- Reformat dates
- Restructure JSON

```python
upgrade = UpgradeStep(
    name="rename_csv_columns",
    func=lambda data: data,  # Modify file representation
    target_version="1.1.0",
    upgrade_type=UpgradeType.FILE  # Raw data file operations
)
```

Applied in `parser.parse()` workflow before DataStore/System initialization.

### SYSTEM Upgrades (Less Common)

Modify System objects loaded from cache. Typical operations:

- Update component attributes
- Reorganize component hierarchy
- Recalculate derived values

```python
upgrade = UpgradeStep(
    name="fix_component_types",
    func=lambda system: system,  # Modify system object
    target_version="2.0.0",
    upgrade_type=UpgradeType.SYSTEM  # System object operations
)
```

Applied when loading cached systems via `System.from_json(upgrader=...)`.

## Priority and Execution Order

Upgrades execute in priority order (lower numbers first). This enables dependencies:

```python
# Priority 10: Must run first (prepares data)
step1 = UpgradeStep(name="prep", priority=10, ...)

# Priority 20: Depends on step1
step2 = UpgradeStep(name="transform", priority=20, ...)

# Priority 30: Depends on step2
step3 = UpgradeStep(name="validate", priority=30, ...)
```

## Design Trade-offs

### Why Not Just Update All Data Upfront?

You might wonder: why not upgrade all data once when the new version is released, rather than on-demand?

**Reasons**:

1. **Optionality**: Some users might not upgrade immediately. Supporting multiple versions reduces friction.
2. **Testing**: Upgrades can be tested on real data in production, then rolled back if issues arise.
3. **Gradual Migration**: Large datasets can be migrated incrementally rather than all-at-once.
4. **Reversibility**: You can theoretically downgrade by running inverse transformations.

### Why Priority Instead of Dependency Graphs?

Dependency graphs are more flexible but harder to understand and debug. Priority ordering is:

- Simple to reason about
- Easy to visualize (topological sort)
- Sufficient for most upgrade chains
- Easier for users to configure

## Real-World Example

Suppose you're transitioning from per-unit to SI units:

```python
upgrades = [
    # Version 1.5.0: Prepare for transition
    UpgradeStep(
        name="add_unit_field",
        func=add_unit_field_to_csv,
        target_version="1.5.0",
        min_version="1.0.0",
        priority=10
    ),
    # Version 1.8.0: Dual-mode reading (both per-unit and SI)
    UpgradeStep(
        name="enable_unit_detection",
        func=enable_unit_detection,
        target_version="1.8.0",
        min_version="1.5.0",
        priority=20
    ),
    # Version 2.0.0: Require SI units
    UpgradeStep(
        name="convert_to_si",
        func=convert_to_si_units,
        target_version="2.0.0",
        min_version="1.8.0",
        priority=30
    ),
]
```

A v1.0 user wanting to upgrade to v2.0 would run all three steps in order. A v1.5 user would run the last two. A v1.8 user would run only the last one.

## See Also

- {doc}`../how-tos/manage-versions` - How-to for version strategies
- {doc}`../how-tos/upgrade-systems` - How-to for staged upgrades
- {py:class}`~r2x_core.VersionStrategy` - Version comparison protocol
- {py:class}`~r2x_core.UpgradeStep` - Upgrade definition
- {py:class}`~r2x_core.UpgradeType` - FILE vs SYSTEM upgrades
