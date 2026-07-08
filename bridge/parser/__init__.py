"""Error parser: raw HIPIFY/ROCm/ctest output -> structured, ordered diagnostics.

Public surface:
    parse(text) -> ParseResult          module-level convenience
    ErrorParser                         the parser (stateless; reusable)
    Diagnostic, Cluster, ParseResult    value types
    ErrorClass, Category, Severity       taxonomy constants (the M3/dashboard contract)
"""

from __future__ import annotations

from .model import (
    Category,
    Cluster,
    Diagnostic,
    ErrorClass,
    HipifyStats,
    ParseResult,
    Severity,
)
from .parser import ErrorParser, parse

__all__ = [
    "parse",
    "ErrorParser",
    "Diagnostic",
    "Cluster",
    "ParseResult",
    "HipifyStats",
    "ErrorClass",
    "Category",
    "Severity",
]
