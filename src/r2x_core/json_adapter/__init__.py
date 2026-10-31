"""JSON readers and processing adapters."""

from .processing import JSONProcessingBackend
from .readers import JSONFileReader

__all__ = [
    "JSONFileReader",
    "JSONProcessingBackend",
]
