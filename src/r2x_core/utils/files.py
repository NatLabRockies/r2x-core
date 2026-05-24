"""File operations: path resolution, auditing, caching, and backup."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from rust_ok import Err, Ok, Result

if TYPE_CHECKING:
    from ..datafile import DataFile, FileInfo


# ── Cache paths ─────────────────────────────────────────────────────


def get_r2x_cache_path() -> Path:
    """Return the r2x cache directory path."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".config"
    return base / "r2x" / "cache"


# ── File validation ─────────────────────────────────────────────────


def audit_file(fpath: Path) -> Result[Path, ValueError | FileNotFoundError]:
    """Check if a path exists and return it, or return an error."""
    if fpath.exists():
        return Ok(fpath)
    return Err(FileNotFoundError(f"Missing required file: {fpath}"))


def resolve_path(
    raw_path: Path | str,
    *,
    base_folder: Path,
    must_exist: bool = True,
) -> Result[Path, ValueError | FileNotFoundError]:
    """Resolve raw path relative to the given folder, optionally checking existence.

    Parameters
    ----------
    raw_path : Path | str
        The path to resolve (relative or absolute).
    base_folder : Path
        The base folder to resolve relative paths against.
    must_exist : bool
        If True, check that the resolved path exists.
    """
    path = Path(raw_path)
    resolved = path if path.is_absolute() else base_folder / path

    if must_exist:
        return audit_file(resolved)
    return Ok(resolved)


def resolve_glob_pattern(pattern: str, *, search_dir: Path) -> Result[Path, ValueError | FileNotFoundError]:
    """Resolve a glob pattern to a single file path.

    Parameters
    ----------
    pattern : str
        The glob pattern to resolve.
    search_dir : Path
        The directory to search for matching files.
    """
    if not any(wildcard in pattern for wildcard in ["*", "?", "[", "]"]):
        msg = f"Pattern '{pattern}' does not contain glob wildcards (*, ?, [, ]). "
        msg += "Use 'fpath' or 'relative_fpath' for exact filenames."
        return Err(ValueError(msg))

    matches = [p for p in search_dir.glob(pattern) if p.is_file()]

    if not matches:
        msg = f"No files found matching pattern '{pattern}' in {search_dir}"
        return Err(FileNotFoundError(msg))

    if len(matches) > 1:
        file_list = "\n".join(f"  - {m.name}" for m in sorted(matches))
        msg = f"Multiple files matched pattern '{pattern}' in {search_dir}:\n{file_list}"
        return Err(ValueError(msg))

    logger.debug("Glob pattern {} resolved to: {}", pattern, matches[0])
    return Ok(matches[0])


def backup_folder(folder_path: Path | str) -> Result[None, str]:
    """Backup a folder by moving then copying back."""
    if isinstance(folder_path, str):
        folder_path = Path(folder_path)

    if not folder_path.exists():
        return Err(error="Folder does not exist")

    backup = folder_path.with_name(f"{folder_path.name}_backup")
    if backup.exists():
        logger.warning("Backup folder already exists, removing: {}", backup)
        shutil.rmtree(backup)

    shutil.move(str(folder_path), str(backup))
    logger.info("Created backup at: {}", backup)
    shutil.copytree(backup, folder_path)
    return Ok()


# ── DataFile path resolution ────────────────────────────────────────


def get_fpath(
    data_file: DataFile, *, folder_path: Path, info: FileInfo | None = None
) -> Result[Path, ValueError | FileNotFoundError]:
    """Get the resolved file path from a DataFile configuration.

    Parameters
    ----------
    data_file : DataFile
        The data file configuration.
    folder_path : Path
        The base folder path to resolve relative paths against.
    info : FileInfo | None
        Optional file metadata (unused; reserved for future extensions).
    """
    if not any((data_file.glob, data_file.relative_fpath, data_file.fpath)):
        raise ValueError("DataFile must have fpath, relative_fpath, or glob")

    if data_file.glob is not None:
        return resolve_glob_pattern(data_file.glob, search_dir=folder_path)
    if data_file.relative_fpath is not None:
        fpath = folder_path / Path(data_file.relative_fpath)
        logger.trace("Resolved relative_fpath={} for file={}", fpath, data_file.name)
        return audit_file(fpath)

    assert data_file.fpath
    fpath = Path(data_file.fpath)
    logger.trace("Resolved absolute fpath={} for file={}", fpath, data_file.name)
    return audit_file(fpath)
