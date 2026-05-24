"""Utility functions script."""

import os
import platform
import shutil
from pathlib import Path

from loguru import logger
from rust_ok import Err, Ok, Result


def backup_folder(folder_path: Path | str) -> Result[None, str]:
    """Backup a folder."""
    if isinstance(folder_path, str):
        folder_path = Path(folder_path)

    if not folder_path.exists():
        return Err(error="Folder does not exist")

    backup_folder = folder_path.with_name(f"{folder_path.name}_backup")
    if backup_folder.exists():
        logger.warning("Backup folder already exists, removing: {}", backup_folder)
        shutil.rmtree(backup_folder)

    # It turns out that moving all the files probably faster than one by one.
    shutil.move(str(folder_path), str(backup_folder))
    logger.info("Created backup at: {}", backup_folder)
    shutil.copytree(backup_folder, folder_path)
    return Ok()


def get_r2x_cache_path() -> Path:
    """Return the cache path."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".config"
    return base / "r2x" / "cache"


def audit_file(fpath: Path) -> Result[Path, ValueError | FileNotFoundError]:
    """Check if a path exists and return it, or return FileNotFoundError.

    Parameters
    ----------
    fpath : Path
        The file path to check.

    Returns
    -------
    Result[Path, ValueError | FileNotFoundError]
        Ok(Path) if the file exists.
        Err(FileNotFoundError) if the file does not exist.
    """
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
        The path to resolve (relative or absolute)
    base_folder : Path
        The base folder to resolve relative paths against
    must_exist : bool, optional
        If True, check that the resolved path exists, by default True

    Returns
    -------
    Result[Path, ValueError | FileNotFoundError]
        Ok with resolved path if successful, Err otherwise
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
        The glob pattern to resolve
    search_dir : Path
        The directory to search for matching files

    Returns
    -------
    Result[Path, ValueError | FileNotFoundError]
        Ok with the matched file path, Err if no matches or multiple matches
    """
    if not any(wildcard in pattern for wildcard in ["*", "?", "[", "]"]):
        msg = f"Pattern '{pattern}' does not contain glob wildcards (*, ?, [, ]). Use 'fpath' or 'relative_fpath' for exact filenames."
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
