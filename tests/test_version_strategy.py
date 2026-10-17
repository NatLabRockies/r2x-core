"""Tests for versioning strategies."""

import pytest


@pytest.mark.parametrize(
    "current,target,expected",
    [
        ("1.0.0", "2.0.0", -1),
        ("1.1.0", "1.0.0", 1),
        ("1.0.1", "1.0.0", 1),
        ("1.0.0", "1.0.0", 0),
        ("1.0", "1.1", -1),
        ("2", "1", 1),
        ("1.0.0", "1.0", 0),
        ("1.10.0", "1.9.0", 1),
        ("1.0.10", "1.0.9", 1),
        ("0.0.1", "0.1.0", -1),
        ("10.0.0", "9.9.9", 1),
        ("1.2.3", "1.2.4", -1),
        ("1.2.3", "1.3.0", -1),
        ("1.2.3", "2.0.0", -1),
    ],
    ids=[
        "major_upgrade",
        "minor_downgrade",
        "patch_upgrade",
        "equal_versions",
        "two_components",
        "single_component",
        "mixed_3v2_components",
        "double_digit_minor",
        "double_digit_patch",
        "pre_1_0_versions",
        "cross_decade_boundary",
        "patch_update",
        "minor_update",
        "major_update",
    ],
)
def test_semantic_versioning_compare(current, target, expected):
    """Test semantic version comparison across various cases."""

    from r2x_core.versioning import SemanticVersioningStrategy

    strategy = SemanticVersioningStrategy()
    assert strategy.compare_versions(current, target=target) == expected


def test_git_versioning_constructor_valid():
    """Test GitVersioningStrategy initialization with valid commits."""
    from r2x_core.versioning import GitVersioningStrategy

    commits = ["abc123", "def456", "ghi789"]
    strategy = GitVersioningStrategy(commits)
    assert strategy.commit_history == ("abc123", "def456", "ghi789")


def test_git_versioning_constructor_single_commit():
    """Test GitVersioningStrategy with single commit."""
    from r2x_core.versioning import GitVersioningStrategy

    commits = ["abc123"]
    strategy = GitVersioningStrategy(commits)
    assert len(strategy.commit_history) == 1
    assert strategy.commit_history[0] == "abc123"


def test_git_versioning_constructor_empty_raises():
    """Test that empty commit history raises ValueError."""
    from r2x_core.versioning import GitVersioningStrategy

    with pytest.raises(ValueError, match="commit_history cannot be empty"):
        GitVersioningStrategy([])


def test_git_versioning_constructor_non_string_raises():
    """Test that non-string commits raise ValueError."""
    from r2x_core.versioning import GitVersioningStrategy

    with pytest.raises(ValueError, match="All commits must be strings"):
        GitVersioningStrategy(["abc123", 456, "def456"])  # type: ignore


def test_git_versioning_constructor_none_raises():
    """Test that None values in commits raise ValueError."""
    from r2x_core.versioning import GitVersioningStrategy

    with pytest.raises(ValueError, match="All commits must be strings"):
        GitVersioningStrategy(["abc123", None, "def456"])  # type: ignore


def test_git_versioning_commit_history_is_tuple():
    """Test that commit_history is stored as immutable tuple."""
    from r2x_core.versioning import GitVersioningStrategy

    commits_list = ["abc123", "def456"]
    strategy = GitVersioningStrategy(commits_list)
    assert isinstance(strategy.commit_history, tuple)

    # Modifying original list shouldn't affect strategy
    commits_list.append("ghi789")
    assert len(strategy.commit_history) == 2


@pytest.mark.parametrize(
    "current,target,expected",
    [
        ("abc123", "def456", -1),
        ("def456", "abc123", 1),
        ("abc123", "abc123", 0),
        ("abc123", "ghi789", -1),
        ("ghi789", "abc123", 1),
        ("def456", "ghi789", -1),
        ("ghi789", "def456", 1),
    ],
    ids=[
        "first_to_second",
        "second_to_first",
        "same_commit",
        "first_to_last",
        "last_to_first",
        "middle_to_last",
        "last_to_middle",
    ],
)
def test_git_versioning_compare_valid(current, target, expected):
    """Test git version comparison with valid commits."""
    from r2x_core.versioning import GitVersioningStrategy

    strategy = GitVersioningStrategy(["abc123", "def456", "ghi789"])
    assert strategy.compare_versions(current, target=target) == expected


def test_git_versioning_compare_current_none():
    """Test that None current version raises ValueError."""
    from r2x_core.versioning import GitVersioningStrategy

    strategy = GitVersioningStrategy(["abc123", "def456"])
    with pytest.raises(ValueError, match="Current version cannot be None"):
        strategy.compare_versions(None, target="def456")


def test_git_versioning_compare_current_not_found():
    """Test that unknown current commit raises ValueError with helpful message."""
    from r2x_core.versioning import GitVersioningStrategy

    strategy = GitVersioningStrategy(["abc123", "def456", "ghi789"])
    with pytest.raises(ValueError, match="Current commit 'xyz999' not found"):
        strategy.compare_versions("xyz999", target="def456")


def test_git_versioning_compare_target_not_found():
    """Test that unknown target commit raises ValueError with helpful message."""
    from r2x_core.versioning import GitVersioningStrategy

    strategy = GitVersioningStrategy(["abc123", "def456", "ghi789"])
    with pytest.raises(ValueError, match="Target commit 'xyz999' not found"):
        strategy.compare_versions("abc123", target="xyz999")


def test_git_versioning_error_message_shows_available_commits():
    """Test that error messages include available commits."""
    from r2x_core.versioning import GitVersioningStrategy

    commits = ["aaa", "bbb", "ccc", "ddd", "eee"]
    strategy = GitVersioningStrategy(commits)

    with pytest.raises(ValueError, match=r"aaa.*eee"):
        strategy.compare_versions("xyz", target="bbb")


def test_git_versioning_commit_history_ordering():
    """Test that commits are properly ordered from oldest to newest."""
    from r2x_core.versioning import GitVersioningStrategy

    commits = ["commit1", "commit2", "commit3", "commit4", "commit5"]
    strategy = GitVersioningStrategy(commits)

    # Earlier commits should be "older"
    assert strategy.compare_versions("commit1", target="commit5") == -1
    assert strategy.compare_versions("commit2", target="commit4") == -1
    assert strategy.compare_versions("commit3", target="commit3") == 0


def test_git_versioning_adjacent_commits():
    """Test comparison of adjacent commits in history."""
    from r2x_core.versioning import GitVersioningStrategy

    strategy = GitVersioningStrategy(["a", "b", "c", "d"])

    # Adjacent pairs
    assert strategy.compare_versions("a", target="b") == -1
    assert strategy.compare_versions("b", target="c") == -1
    assert strategy.compare_versions("c", target="d") == -1

    # Reverse adjacent pairs
    assert strategy.compare_versions("b", target="a") == 1
    assert strategy.compare_versions("c", target="b") == 1
    assert strategy.compare_versions("d", target="c") == 1


def test_git_versioning_many_commits():
    """Test with many commits in history."""
    from r2x_core.versioning import GitVersioningStrategy

    commits = [f"commit{i:03d}" for i in range(100)]
    strategy = GitVersioningStrategy(commits)

    assert strategy.compare_versions(commits[0], target=commits[1]) == -1
    assert strategy.compare_versions(commits[-1], target=commits[-2]) == 1
    assert strategy.compare_versions(commits[50], target=commits[75]) == -1


@pytest.mark.parametrize("current,target,expected", [("a", "b", -1), ("b", "a", 1), ("a", "a", 0)])
def test_git_versioning_duplicate_commits_use_first_position(
    current: str, target: str, expected: int
) -> None:
    from r2x_core import GitVersioningStrategy

    commits = ["a", "b", "a"]
    strategy = GitVersioningStrategy(commits)
    commits.reverse()

    assert strategy.compare_versions(current, target=target) == expected
    assert strategy.commit_history == ("a", "b", "a")
