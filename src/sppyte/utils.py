"""
sppyte.utils
~~~~~~~~~~~~~~~

This module provides utility functions that are used in sppyte.
"""

from typing import TypedDict
from urllib.parse import quote

from sppyte.errors import ResponseFormatError


# ----------------------------- Types -----------------------------------------
class FormDigestResponse(TypedDict):
    """Minimal shape of the contextinfo JSON response to get Form Digest value."""

    FormDigestValue: str


class ItemTypeResponse(TypedDict):
    """Response shape for list metadata to get the item entity type."""

    ListItemEntityTypeFullName: str


class AddItemResponse(TypedDict):
    """Response shape for adding a list item to return the new ID."""

    ID: int


class AddDocumentResponse(TypedDict):
    """Response shape for adding a document to return the UniqueId."""

    UniqueId: str


# ----------------------------- Methods ----------------------------------------
def build_path(*parts: str | None) -> str:
    """
    Join path segments as a normalized server-relative path.

    Example:
        build_path("sites/demo", "Shared Documents", "Reports")
        -> "/sites/demo/Shared Documents/Reports"
    """
    path = "/".join([p.strip("/") for p in parts if p is not None])
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


def parse_form_digest(r: FormDigestResponse) -> str:
    """
    Extract FormDigestValue or raise ResponseFormatError if missing.
    """
    val = "Form digest value"
    form_digest = r.get("FormDigestValue", val)
    if form_digest == val:
        raise ResponseFormatError(val)
    return form_digest


def parse_item_type(r: ItemTypeResponse) -> str:
    """
    Extract ListItemEntityTypeFullName or raise ResponseFormatError if missing.
    """
    val = "List item type"
    item_type = r.get("ListItemEntityTypeFullName", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type


def parse_add_item(r: AddItemResponse) -> int:
    """
    Extract 'ID' from an Add Item response or raise ResponseFormatError.
    """
    msg = "Item id"
    item_type = r.get("ID", -1)
    if item_type == -1:
        raise ResponseFormatError(msg)
    return item_type


def parse_add_document(r: AddDocumentResponse) -> str:
    """
    Extract 'UniqueId' from an Add Document response or raise ResponseFormatError.
    """
    val = "Document id"
    item_type = r.get("UniqueId", val)
    if item_type == val:
        raise ResponseFormatError(val)
    return item_type
