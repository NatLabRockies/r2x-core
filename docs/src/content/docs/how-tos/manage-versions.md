---
title: "Managing Versions"
---

<span id="managing-versions"></span>

r2x-core provides [`VersionStrategy`](/r2x-core/references/api/) implementations for semantic versions and Git history. Choose one based on how you label releases or track changes to data files and systems.

## Create a Semantic Versioning Strategy

Use semantic versioning (MAJOR.MINOR.PATCH) to manage versions based on the nature of changes:

```python doctest
>>> from r2x_core import SemanticVersioningStrategy
>>> strategy = SemanticVersioningStrategy()
>>> type(strategy).__name__
# 'SemanticVersioningStrategy'
```

## Track versions with Git

Track versions using Git tags and commit hashes:

```python doctest
>>> from r2x_core import GitVersioningStrategy
>>> commits = ["abc123", "def456", "ghi789"]
>>> strategy = GitVersioningStrategy(commits)
>>> type(strategy).__name__
# 'GitVersioningStrategy'
```

## Work with Version Strategies

Both strategies implement the [`VersionStrategy`](/r2x-core/references/api/) interface for consistent version management across your project:

```python doctest
>>> from r2x_core import SemanticVersioningStrategy, GitVersioningStrategy, VersionStrategy
>>> semantic = SemanticVersioningStrategy()
>>> commits = ["abc123", "def456", "ghi789"]
>>> git = GitVersioningStrategy(commits)
>>>
>>> # Both implement the same interface
>>> isinstance(semantic, VersionStrategy)
# True
>>> isinstance(git, VersionStrategy)
# True
```

## See Also

- [upgrade data files](/r2x-core/how-tos/upgrade-data-files/) - Upgrade data files between versions
- [upgrade systems](/r2x-core/how-tos/upgrade-systems/) - Upgrade system models between versions
- [`VersionStrategy`](/r2x-core/references/api/) - Version strategy interface
- [`SemanticVersioningStrategy`](/r2x-core/references/api/) - Semantic version strategy
- [`GitVersioningStrategy`](/r2x-core/references/api/) - Version strategy for Git history
