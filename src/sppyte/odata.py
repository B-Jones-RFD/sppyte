"""
sppyte.odata
~~~~~~~~~~~~

Helpers for building SharePoint REST / OData URLs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias
from urllib.parse import quote

ParamValue: TypeAlias = str | int
Params: TypeAlias = Mapping[str, ParamValue] | Sequence[tuple[str, ParamValue]] | None
"""OData query options such as ``{"$select": "Id,Title", "$top": 5}``."""


def build_path(*parts: str | None) -> str:
    """
    Join path segments as a normalized server-relative path.

    Example:
        build_path("sites/demo", "Shared Documents", "Reports")
        -> "/sites/demo/Shared Documents/Reports"
    """
    segments = [p.strip("/") for p in parts if p]
    path = "/".join(segment for segment in segments if segment)
    return f"/{path}" if path else "/"


def odata_literal(value: str) -> str:
    """
    Escape a value for use inside an OData string literal (`'...'`) in a URL path.

    Apostrophes are doubled per OData and the result is percent-encoded so that
    spaces, `#`, `%`, `?` and `&` cannot break the URL. The doubled apostrophes
    survive encoding because SharePoint expects them literally.

    Example:
        odata_literal("O'Brien's #1 Report")
        -> "O''Brien''s%20%231%20Report"
    """
    return quote(value.replace("'", "''"), safe="'")


def odata_path(path: str) -> str:
    """
    Escape a server-relative path for use inside an OData string literal.

    Each `/`-separated segment is passed through `odata_literal` so slashes
    are preserved while everything else is escaped.

    Example:
        odata_path("/sites/demo/Shared Documents/Q1 '25")
        -> "/sites/demo/Shared%20Documents/Q1%20''25"
    """
    return "/".join(odata_literal(segment) for segment in path.split("/"))
