# Managing Versions

R2X Core provides flexible version management through {py:class}`~r2x_core.VersionStrategy` implementations. Choose a strategy based on your versioning scheme and how you track changes to data files and system models.

## Create a Semantic Versioning Strategy

Use semantic versioning (MAJOR.MINOR.PATCH) to manage versions based on the nature of changes:

```python doctest
>>> from r2x_core import SemanticVersioningStrategy
>>> strategy = SemanticVersioningStrategy()
>>> type(strategy).__name__
'SemanticVersioningStrategy'
```

## Create a Git-Based Versioning Strategy

Track versions using Git tags and commit hashes:

```python doctest
>>> from r2x_core import GitVersioningStrategy
>>> commits = ["abc123", "def456", "ghi789"]
>>> strategy = GitVersioningStrategy(commits)
>>> type(strategy).__name__
'GitVersioningStrategy'
```

## Work with Version Strategies

Both strategies implement the {py:class}`~r2x_core.VersionStrategy` interface for consistent version management across your project:

```python doctest
>>> from r2x_core import SemanticVersioningStrategy, GitVersioningStrategy, VersionStrategy
>>> semantic = SemanticVersioningStrategy()
>>> commits = ["abc123", "def456", "ghi789"]
>>> git = GitVersioningStrategy(commits)
>>>
>>> # Both implement the same interface
>>> isinstance(semantic, VersionStrategy)
True
>>> isinstance(git, VersionStrategy)
True
```

## See Also

- {doc}`upgrade-data-files` - Upgrade data files between versions
- {doc}`upgrade-systems` - Upgrade system models between versions
- {py:class}`~r2x_core.VersionStrategy` - Version strategy interface
- {py:class}`~r2x_core.SemanticVersioningStrategy` - Semantic version strategy
- {py:class}`~r2x_core.GitVersioningStrategy` - Git-based version strategy
