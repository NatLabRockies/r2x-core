# Version strategy contracts

`VersionStrategy.compare_versions(current, *, target)` compares the current
version with a target. The result is `-1` for older, `0` for equal and `1` for
newer. Comparison does not read a file, select an upgrade or mutate a system.

## Semantic versioning

`SemanticVersioningStrategy()` compares semantic-version strings.
It does not expose the former examples' `get_version`, `set_version`, or `compare`
methods and takes no `version_field` or `default_version` configuration.

```python doctest
>>> from r2x_core import SemanticVersioningStrategy
>>> strategy = SemanticVersioningStrategy()
>>> # Expected: ordering follows semantic versions, not lexical string order.
>>> strategy.compare_versions("1.9.0", target="1.10.0")
-1
>>> strategy.compare_versions("2.0.0", target="1.0.0")
1
>>> strategy.compare_versions("1.0.0", target="1.0.0")
0
```

## Git history order

`GitVersioningStrategy(commit_history)` accepts a nonempty list ordered oldest
to newest. Comparisons use positions in that supplied history, not timestamps
or lexical ordering. Unknown commits and a missing current version raise `ValueError`.
The labels below stand in for known identifiers in a supplied history; no Git
repository or network request is needed to test ordering.

```python doctest
>>> from r2x_core import GitVersioningStrategy
>>> strategy = GitVersioningStrategy(["older", "middle", "newer"])
>>> # Expected: the first supplied history entry precedes the last.
>>> strategy.compare_versions("older", target="newer")
-1
>>> strategy.compare_versions("newer", target="middle")
1
>>> try:
...     strategy.compare_versions("unknown", target="newer")
... except ValueError as error:
...     assert "not found in history" in str(error)
...     print(type(error).__name__)
ValueError
```

## Version readers

`VersionReader.read_version(folder_path: Path)` is a protocol returning a
version string or `None`. A model package implements its own file/layout convention.
This complete example reads an actual temporary `VERSION` file:

```python doctest
>>> from pathlib import Path
>>> from tempfile import TemporaryDirectory
>>> from r2x_core import VersionReader
>>> class TextVersionReader:
...     def read_version(self, folder_path: Path) -> str | None:
...         path = folder_path / "VERSION"
...         return path.read_text(encoding="utf-8").strip() if path.is_file() else None
>>> reader: VersionReader = TextVersionReader()
>>> with TemporaryDirectory() as directory:
...     root = Path(directory)
...     before = reader.read_version(root)
...     _ = (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")
...     after = reader.read_version(root)
>>> # Expected: absence is distinct from the version read from the created file.
>>> before, after
(None, '1.2.3')
```

Use [manage versions](/r2x-core/how-tos/manage-versions/) for selection guidance,
[upgrade steps](/r2x-core/references/upgrader/) for transformation/error contracts,
and the [generated API](/r2x-core/references/api/) for signatures and pinned source.

<span id="versioning-strategies"></span>

<span id="quick-reference"></span>

<span id="overview"></span>

<span id="protocol-versionreader"></span>

<span id="usage-examples"></span>

<span id="custom-version-field"></span>

<span id="git-based-versioning"></span>

<span id="version-comparison"></span>

<span id="working-with-objects"></span>

<span id="best-practices"></span>

<span id="choose-the-right-strategy"></span>

<span id="version-field-naming"></span>

<span id="handle-missing-versions"></span>

<span id="see-also"></span>
