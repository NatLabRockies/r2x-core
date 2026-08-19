"""Custom exceptions for r2x-core package."""


class R2XCoreError(Exception):
    """Base exception for all r2x-core errors."""


class ValidationError(R2XCoreError):
    """Exception raised for validation errors."""


class ComponentCreationError(R2XCoreError):
    """Exception raised when component creation fails."""


class UpgradeError(R2XCoreError):
    """Exception raised for upgrader-related errors."""


class ReaderError(R2XCoreError):
    """Exception raised for data reading related errors."""


class HDF5GroupNotFoundError(KeyError):
    """Exception raised when a configured HDF5 group is missing."""


class MultipleFileError(ValueError):
    """Exception raised when a glob pattern matches multiple files."""


class CLIError(R2XCoreError):
    """Error raised during CLI plugin execution."""


class PluginError(R2XCoreError):
    """Exception raised during plugin execution."""


class UnwrapError(Exception):
    """Exception raised when unwrapping an Err result."""


class IsNotError(Exception):
    """Exception raised when accessing .err if Ok()."""
